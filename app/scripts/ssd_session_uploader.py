"""
연암소방대 - 외장 SSD 세션 → 서버 일괄 등록 업로더 (MVP)

AI 보드가 외장 SSD에 남긴 세션 폴더의 프레임 분석 결과(JSON / JSONL)를 읽어
서버 수집 API `POST /api/v1/missions/{mission_id}/telemetry/batch`로 묶음 전송합니다.
서버는 Save-First 원칙에 따라 원본을 raw_telemetry_logs에 먼저 저장한 뒤 분석합니다.

[세션 폴더에서 읽는 파일]
  - *.jsonl : 한 줄에 프레임 1개
  - *.json  : 프레임 1개(객체) 또는 프레임 목록(배열)
  하위 폴더까지 모두 읽으며, 파일명 순서 → 파일 안의 순서대로 전송합니다.

[프레임 형식] (api_specification.md 3장)
  {"timestamp": "2026-10-12T05:20:00Z", "frame_id": 1042,
   "detected_objects": [{"class": "chair", "screen_box": [120,240,310,450], "description": "..."}]}
  선택: "snapshot_file": "frames/1042.jpg"  → 세션 폴더 기준 경로의 이미지를 snapshot_base64로 첨부

[이어 올리기]
  전송에 성공한 묶음마다 세션 폴더의 `.upload_state.json`에 진행 위치를 기록합니다.
  중간에 실패해도 다시 실행하면 이어서 올립니다. (서버에는 중복 제거 기능이 없으므로
  같은 세션을 처음부터 다시 올리려면 --restart 를 명시해야 합니다.)

사용 예:
  python app/scripts/ssd_session_uploader.py E:/session_20261012_01 --mission 1 --dry-run
  python app/scripts/ssd_session_uploader.py E:/session_20261012_01 --mission 1 --server http://192.168.0.10:8000
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

STATE_FILE = ".upload_state.json"

DEFAULT_SERVER = os.getenv("RESCUE_SERVER_URL", "http://127.0.0.1:8000")
DEFAULT_DEVICE_ID = os.getenv("RESCUE_DEVICE_ID", "EDGE-CAM-01")
DEFAULT_DEVICE_KEY = os.getenv("RESCUE_DEVICE_KEY", "rescue-edge-secret-key-01")


# ----------------------------------------------------------------------------
# 1. 세션 폴더 읽기
# ----------------------------------------------------------------------------
def find_session_files(session_dir: Path) -> List[Path]:
    files = [
        p for p in session_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".json", ".jsonl") and p.name != STATE_FILE
    ]
    return sorted(files, key=lambda p: str(p.relative_to(session_dir)).lower())


def read_frames(path: Path) -> Tuple[List[Tuple[str, Any]], List[str]]:
    """파일에서 (출처, 레코드) 목록과 읽기 오류 목록을 반환"""
    records: List[Tuple[str, Any]] = []
    errors: List[str] = []
    text = path.read_text(encoding="utf-8-sig")

    if path.suffix.lower() == ".jsonl":
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append((f"{path.name}:{line_no}", json.loads(line)))
            except json.JSONDecodeError as e:
                errors.append(f"{path.name}:{line_no} JSON 형식 오류 ({e.msg})")
        return records, errors

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"{path.name} JSON 형식 오류 ({e.msg}, {e.lineno}행)"]

    if isinstance(data, list):
        records = [(f"{path.name}[{i}]", item) for i, item in enumerate(data)]
    else:
        records = [(path.name, data)]
    return records, errors


# ----------------------------------------------------------------------------
# 2. 프레임 검증 (서버 스키마 RawTelemetryIngest 기준)
#    잘못된 프레임 하나 때문에 묶음 전체가 422로 거절되지 않도록 미리 걸러냅니다.
# ----------------------------------------------------------------------------
def validate_frame(rec: Any) -> Optional[str]:
    if not isinstance(rec, dict):
        return "프레임이 JSON 객체가 아님"
    ts = rec.get("timestamp")
    if ts is None:
        return "timestamp 누락"
    if not isinstance(ts, (str, int)) or isinstance(ts, bool):
        return "timestamp는 ISO 8601 문자열 또는 Unix ms 정수여야 함"
    if "frame_id" in rec and rec["frame_id"] is not None and not isinstance(rec["frame_id"], int):
        return "frame_id는 정수여야 함"

    objs = rec.get("detected_objects")
    if objs is not None:
        if not isinstance(objs, list):
            return "detected_objects는 배열이어야 함"
        for i, obj in enumerate(objs):
            if not isinstance(obj, dict):
                return f"detected_objects[{i}]가 객체가 아님"
            if not isinstance(obj.get("class"), str):
                return f"detected_objects[{i}].class 누락"
            box = obj.get("screen_box")
            if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
                return f"detected_objects[{i}].screen_box는 숫자 4개 [x1,y1,x2,y2]여야 함"
            if not isinstance(obj.get("description"), str):
                return f"detected_objects[{i}].description 누락"
    return None


def to_payload(rec: Dict[str, Any], session_dir: Path) -> Dict[str, Any]:
    """서버로 보낼 형태로 변환: screen_box 정수화, snapshot_file 첨부"""
    payload = dict(rec)
    if payload.get("detected_objects"):
        payload["detected_objects"] = [
            {**obj, "screen_box": [int(round(v)) for v in obj["screen_box"]]}
            for obj in payload["detected_objects"]
        ]

    snap = payload.pop("snapshot_file", None)
    if snap and not payload.get("snapshot_base64"):
        img_path = (session_dir / snap)
        if img_path.is_file():
            payload["snapshot_base64"] = base64.b64encode(img_path.read_bytes()).decode("ascii")
        else:
            print(f"  [경고] 스냅샷 파일 없음, 이미지 없이 전송: {snap}")
    return payload


# ----------------------------------------------------------------------------
# 3. 진행 상태 저장
# ----------------------------------------------------------------------------
def load_state(session_dir: Path) -> Dict[str, Any]:
    p = session_dir / STATE_FILE
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(session_dir: Path, state: Dict[str, Any]) -> None:
    (session_dir / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------
# 4. 실행
# ----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="외장 SSD 세션 → 서버 일괄 등록 업로더")
    ap.add_argument("session_dir", help="AI 보드 세션 폴더 경로 (예: E:/session_20261012_01)")
    ap.add_argument("--mission", type=int, required=True, help="등록할 작전 ID (ACTIVE 상태여야 함)")
    ap.add_argument("--server", default=DEFAULT_SERVER, help=f"서버 주소 (기본: {DEFAULT_SERVER})")
    ap.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    ap.add_argument("--device-key", default=DEFAULT_DEVICE_KEY)
    ap.add_argument("--chunk-size", type=int, default=20, help="한 번에 보낼 프레임 수 (기본 20)")
    ap.add_argument("--dry-run", action="store_true", help="전송하지 않고 파일 검증만 수행")
    ap.add_argument("--restart", action="store_true", help="이전 진행 기록을 무시하고 처음부터 전송 (중복 저장 주의)")
    args = ap.parse_args()

    session_dir = Path(args.session_dir).resolve()
    if not session_dir.is_dir():
        print(f"[오류] 세션 폴더가 없습니다: {session_dir}")
        return 2
    if args.chunk_size < 1:
        print("[오류] --chunk-size는 1 이상이어야 합니다.")
        return 2

    # 1) 읽기 + 검증
    files = find_session_files(session_dir)
    if not files:
        print(f"[오류] 세션 폴더에 .json / .jsonl 파일이 없습니다: {session_dir}")
        return 2

    valid: List[Tuple[str, Dict[str, Any]]] = []
    problems: List[str] = []
    for f in files:
        recs, errs = read_frames(f)
        problems.extend(errs)
        for src, rec in recs:
            err = validate_frame(rec)
            if err:
                problems.append(f"{src} {err}")
            else:
                valid.append((src, rec))

    print(f"[세션] {session_dir}")
    print(f"  파일 {len(files)}개 / 전송 가능 프레임 {len(valid)}개 / 제외 {len(problems)}건")
    for p in problems[:20]:
        print(f"  [제외] {p}")
    if len(problems) > 20:
        print(f"  ... 외 {len(problems) - 20}건")

    if args.dry_run:
        print("[dry-run] 검증만 수행했습니다. 전송하지 않았습니다.")
        return 0 if valid else 1
    if not valid:
        print("[오류] 전송할 프레임이 없습니다.")
        return 1

    # 2) 이어 올리기 위치 결정
    state = {} if args.restart else load_state(session_dir)
    start = 0
    if state:
        if state.get("mission_id") != args.mission:
            print(f"[오류] 이 세션은 작전 #{state.get('mission_id')}에 {state.get('uploaded', 0)}개까지 올린 기록이 있습니다.")
            print("       다른 작전으로 다시 올리려면 --restart 를 붙이세요.")
            return 2
        if state.get("total") != len(valid):
            print(f"[오류] 이전 전송 이후 세션 내용이 바뀌었습니다 (이전 {state.get('total')}개 → 현재 {len(valid)}개).")
            print("       확인 후 --restart 로 다시 올리세요. 서버에는 이전에 올린 프레임이 남아 있습니다.")
            return 2
        start = int(state.get("uploaded", 0))
        if start >= len(valid):
            print(f"[완료] 이미 작전 #{args.mission}에 모두 올린 세션입니다 ({start}개).")
            return 0
        print(f"[이어 올리기] {start}개 전송 기록이 있어 {start + 1}번째 프레임부터 전송합니다.")

    if args.restart:
        save_state(session_dir, {"mission_id": args.mission, "total": len(valid), "uploaded": 0})
    retry_hint = "같은 명령에서 --restart 를 빼고" if args.restart else "같은 명령으로"

    # 3) 전송
    url = f"{args.server.rstrip('/')}/api/v1/missions/{args.mission}/telemetry/batch"
    headers = {"X-Device-Id": args.device_id, "X-Device-Key": args.device_key}
    hazard_count: Dict[str, int] = {}
    sent = start

    while sent < len(valid):
        chunk = valid[sent:sent + args.chunk_size]
        body = [to_payload(rec, session_dir) for _, rec in chunk]
        label = f"{sent + 1}~{sent + len(chunk)}/{len(valid)}"
        try:
            res = requests.post(url, json=body, headers=headers, timeout=120)
        except requests.RequestException as e:
            print(f"[실패] {label} 서버 연결 오류: {e}")
            print(f"       서버 상태를 확인한 뒤 {retry_hint} 다시 실행하면 이어서 올립니다.")
            return 1

        if res.status_code != 200:
            print(f"[실패] {label} HTTP {res.status_code}: {res.text[:300]}")
            if res.status_code >= 500:
                print(f"       주의: 이 묶음({label}) 중 일부는 서버에 이미 저장됐을 수 있습니다.")
            print(f"       원인을 해결한 뒤 {retry_hint} 다시 실행하면 이 묶음부터 이어서 올립니다.")
            return 1

        for r in res.json().get("results", []):
            lvl = r.get("hazard_level", "UNKNOWN")
            hazard_count[lvl] = hazard_count.get(lvl, 0) + 1

        sent += len(chunk)
        save_state(session_dir, {"mission_id": args.mission, "total": len(valid), "uploaded": sent})
        print(f"[전송] {label} 완료")

    summary = ", ".join(f"{k} {v}" for k, v in sorted(hazard_count.items()))
    print(f"[완료] 작전 #{args.mission}에 {sent - start}개 프레임 등록 (위험도: {summary or '없음'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
