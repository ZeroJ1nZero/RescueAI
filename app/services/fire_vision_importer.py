"""
연암소방대 - 임베디드(Fire Vision) SSD 세션 가져오기 서비스

임베디드 `edge/fire_vision`의 `extract-bag` 결과 폴더(format: fire-vision-normalized-v1)를 읽어
Save-First 원칙으로 서버 DB에 등록하고, 서버의 Gemma 3 4B로 프레임을 분석합니다.

  세션 폴더/
    manifest.json      format, extraction.complete, streams.rgb[{timestamp_ns, path, sha256, ...}], accel, gyro
    calibration.json   (참조만, 이번 단계에서는 사용하지 않음)
    rgb/000001_<ns>.npy  uint8 HxWx3 (rgb8)

[1단계: Save-First 저장]  Gemma와 무관하게 먼저 끝냄
  - rgb 프레임을 interval 간격으로 골라 JPEG로 저장(static/snapshots/)
  - 프레임 메타(시각, 원본 경로, 해시, 가장 가까운 IMU 원시값)를 raw_telemetry_logs에 커밋 (is_processed=False)
  - 같은 세션(manifest 해시)·같은 프레임은 다시 저장하지 않음 → 같은 SSD를 다시 넣어도 중복 없음

[2단계: 분석]  미처리 원시 로그만 대상
  - JPEG를 Gemma 3 4B(Ollama /api/generate 호환)에 보내 detected_objects(class, screen_box, description)를 받음
  - 위험도는 기존 규칙 엔진(ai_assessor)으로 판정 → 실시간 API와 같은 기준
  - Gemma가 연결되지 않았거나 응답이 잘못되면 가짜 결과를 만들지 않고 원시 로그를 미처리로 남김
    (나중에 다시 실행하면 분석만 이어서 수행)

※ 위치(pose)가 아직 없으므로 sensor_logs(이동 궤적)는 만들지 않습니다.
  ai_assessments/detection_events의 좌표는 기존 파이프라인과 같이 screen_box 중심 픽셀값입니다(실제 공간 좌표 아님).
"""

import base64
import bisect
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
from PIL import Image
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_assessment import AIAssessment
from app.models.detection import DetectionEvent, EventType
from app.models.mission import Mission
from app.models.raw_telemetry import RawTelemetryLog
from app.schemas.telemetry import DetectedObjectItem, RawTelemetryIngest
from app.services.ai_assessor import ai_assessor

SOURCE_FORMAT = "fire-vision-normalized-v1"
SNAPSHOT_DIR = Path("static/snapshots")
GEMMA_MAX_SIDE = 896          # Gemma 3 비전 입력 해상도
OBJECT_CLASSES = ("person", "fire", "smoke", "obstacle", "door", "stairs", "fire_extinguisher", "other")


# ----------------------------------------------------------------------------
# 세션 폴더 읽기
# ----------------------------------------------------------------------------
@dataclass
class FireVisionSession:
    root: Path
    session_key: str
    manifest: Dict[str, Any]
    rgb_rows: List[Dict[str, Any]]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_session(session_dir: str) -> FireVisionSession:
    root = Path(session_dir).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"manifest.json이 없습니다: {root} (임베디드 extract-bag 결과 폴더를 지정하세요)")
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("format") != SOURCE_FORMAT:
        raise ValueError(f"지원하지 않는 형식입니다: {manifest.get('format')} (필요: {SOURCE_FORMAT})")
    if not manifest.get("extraction", {}).get("complete"):
        raise ValueError("추출이 완료되지 않은 세션입니다 (manifest.extraction.complete=false)")
    rows = manifest.get("streams", {}).get("rgb") or []
    if not rows:
        raise ValueError("RGB 프레임이 없습니다 (manifest.streams.rgb 비어 있음)")
    for row in rows:
        if type(row.get("timestamp_ns")) is not int or row["timestamp_ns"] < 0:
            raise ValueError("timestamp_ns는 0 이상의 정수여야 합니다")
        p = (root / row.get("path", "")).resolve()
        if not p.is_relative_to(root):
            raise ValueError(f"세션 폴더 밖을 가리키는 경로입니다: {row.get('path')}")
    rows = sorted(rows, key=lambda r: r["timestamp_ns"])
    return FireVisionSession(root=root, session_key=hashlib.sha256(raw).hexdigest()[:16],
                             manifest=manifest, rgb_rows=rows)


def sample_frames(rows: List[Dict[str, Any]], interval_s: float, max_frames: Optional[int]) -> List[Tuple[int, Dict[str, Any]]]:
    """첫 프레임 기준 0, interval, 2*interval ... 목표 시각에 가장 가까운 프레임을 (manifest 순번, row)로 선택.
    (단순히 '직전 선택 + interval 이상'으로 고르면 정수 ns 반올림·시각 흔들림 때문에 간격이 한 프레임씩 밀림)"""
    interval_ns = int(interval_s * 1e9)
    stamps = [r["timestamp_ns"] for r in rows]
    picked: List[Tuple[int, Dict[str, Any]]] = []
    seen = set()
    target = stamps[0]
    while target <= stamps[-1] + interval_ns // 2:
        i = bisect.bisect_left(stamps, target)
        cands = [j for j in (i - 1, i) if 0 <= j < len(stamps)]
        j = min(cands, key=lambda k: abs(stamps[k] - target))
        if j not in seen and abs(stamps[j] - target) <= interval_ns // 2:
            seen.add(j)
            picked.append((j, rows[j]))
            if max_frames and len(picked) >= max_frames:
                break
        target += interval_ns
    return picked


def _nearest_value(stream: List[Dict[str, Any]], stamps: List[int], t: int) -> Optional[Dict[str, Any]]:
    if not stream:
        return None
    i = bisect.bisect_left(stamps, t)
    cands = [j for j in (i - 1, i) if 0 <= j < len(stream)]
    j = min(cands, key=lambda k: abs(stamps[k] - t))
    return {"value": stream[j].get("value"), "timestamp_ns": stamps[j], "dt_ms": round((stamps[j] - t) / 1e6, 3)}


# ----------------------------------------------------------------------------
# 1단계: Save-First
# ----------------------------------------------------------------------------
@dataclass
class SaveResult:
    sampled: int = 0
    saved: int = 0
    skipped_existing: int = 0
    errors: List[str] = field(default_factory=list)


def _session_logs_query(db: Session, mission_id: int, session_key: str):
    key_expr = func.json_unquote(func.json_extract(RawTelemetryLog.raw_payload, "$.session_key"))
    return db.query(RawTelemetryLog).filter(RawTelemetryLog.mission_id == mission_id, key_expr == session_key)


def save_first(db: Session, mission: Mission, session: FireVisionSession,
               interval_s: float = 1.0, max_frames: Optional[int] = None) -> SaveResult:
    result = SaveResult()
    picked = sample_frames(session.rgb_rows, interval_s, max_frames)
    result.sampled = len(picked)

    existing = {
        (log.raw_payload or {}).get("timestamp_ns")
        for log in _session_logs_query(db, mission.mission_id, session.session_key).all()
    }

    streams = session.manifest.get("streams", {})
    imu = {k: (streams.get(k) or []) for k in ("accel", "gyro")}
    imu_stamps = {k: [r["timestamp_ns"] for r in v] for k, v in imu.items()}

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for idx, row in picked:
        t = row["timestamp_ns"]
        if t in existing:
            result.skipped_existing += 1
            continue
        src = (session.root / row["path"]).resolve()
        try:
            if not src.is_file():
                raise FileNotFoundError(f"프레임 파일 없음: {row['path']}")
            if row.get("sha256") and _sha256_file(src) != row["sha256"]:
                raise ValueError(f"해시 불일치(파일 손상 의심): {row['path']}")
            arr = np.load(src, allow_pickle=False)
            if arr.dtype != np.uint8 or arr.ndim != 3 or arr.shape[2] != 3:
                raise ValueError(f"rgb8(uint8 HxWx3)이 아닙니다: dtype={arr.dtype}, shape={arr.shape}")
            ts_ms = t // 1_000_000
            filename = f"snapshot_m{mission.mission_id}_{ts_ms}_{session.session_key[:8]}.jpg"
            Image.fromarray(arr, "RGB").save(SNAPSHOT_DIR / filename, "JPEG", quality=90)
        except Exception as e:
            result.errors.append(f"frame {idx} ({row.get('path')}): {e}")
            continue

        payload = {
            "source_format": SOURCE_FORMAT,
            "session_key": session.session_key,
            "session_dir": str(session.root),
            "frame_index": idx,
            "frame_id": idx,
            "timestamp": ts_ms,
            "timestamp_ns": t,
            "rgb_path": row["path"],
            "rgb_sha256": row.get("sha256"),
            "width": int(arr.shape[1]),
            "height": int(arr.shape[0]),
            "camera_frame_id": row.get("frame_id"),
            "imu_raw": {k: _nearest_value(imu[k], imu_stamps[k], t) for k in imu},
        }
        db.add(RawTelemetryLog(
            mission_id=mission.mission_id,
            device_id=mission.device_id,
            timestamp=ts_ms,
            raw_payload=payload,
            snapshot_path=f"snapshots/{filename}",
            is_processed=False,
        ))
        db.commit()  # Save-First: 프레임마다 즉시 확정
        result.saved += 1
    return result


# ----------------------------------------------------------------------------
# 2단계: Gemma 분석
# ----------------------------------------------------------------------------
class GemmaUnavailable(Exception):
    pass


def _build_prompt(width: int, height: int) -> str:
    return f"""너는 소방 현장 영상을 분석하는 보조 AI다. 이 이미지는 {width}x{height} 픽셀이다.
이미지에 실제로 보이는 물체 중 소방 활동에 중요한 것만 찾아라.

규칙:
- class는 다음 중 하나: {", ".join(OBJECT_CLASSES)}
- screen_box는 그 물체를 감싸는 이 이미지의 픽셀 좌표 [x1, y1, x2, y2] 정수 (0<=x1<x2<={width}, 0<=y1<y2<={height})
- description은 한국어 한 문장. 보이는 것만 쓰고 온도·거리·인원 상태를 추측하지 마라.
- 확실히 보이지 않는 물체는 넣지 마라. 사람·불·연기가 보이지 않으면 절대 그 class를 쓰지 마라.
- 해당 물체가 하나도 없으면 detected_objects는 빈 배열 []로 둔다. 빈 배열도 정상적인 답이다.

출력 형식 (오직 JSON만):
- detected_objects: 물체 목록. 각 항목은 class, screen_box, description 키를 가진 객체
- scene_summary: 장면 전체를 한국어 한 문장으로 요약한 문자열"""


def call_gemma(image_path: Path, endpoint: str, model: str, timeout_s: float = 120.0) -> Tuple[Dict[str, Any], Tuple[int, int], Tuple[int, int]]:
    """Gemma 호출. (응답 JSON, 원본 크기, 전송 크기) 반환"""
    img = Image.open(image_path).convert("RGB")
    orig = img.size
    scale = min(1.0, GEMMA_MAX_SIDE / max(orig))
    if scale < 1.0:
        img = img.resize((round(orig[0] * scale), round(orig[1] * scale)))
    sent = img.size
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    body = {
        "model": model,
        "prompt": _build_prompt(*sent),
        "images": [base64.b64encode(buf.getvalue()).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    try:
        res = requests.post(endpoint, json=body, timeout=timeout_s)
    except requests.RequestException as e:
        raise GemmaUnavailable(f"Gemma 엔드포인트 연결 실패: {e}") from e
    if res.status_code != 200:
        raise GemmaUnavailable(f"Gemma 엔드포인트 HTTP {res.status_code}: {res.text[:200]}")
    text = res.json().get("response", "")
    return json.loads(text), orig, sent


def parse_objects(resp: Dict[str, Any], orig: Tuple[int, int], sent: Tuple[int, int]) -> List[DetectedObjectItem]:
    """Gemma 응답 검증 → 원본 해상도 기준 DetectedObjectItem 목록 (잘못된 항목은 버림)"""
    objs = resp.get("detected_objects")
    if not isinstance(objs, list):
        raise ValueError("응답에 detected_objects 배열이 없습니다")
    sx, sy = orig[0] / sent[0], orig[1] / sent[1]
    out: List[DetectedObjectItem] = []
    for o in objs:
        if not isinstance(o, dict):
            continue
        cls = str(o.get("class", "")).strip().lower()
        box = o.get("screen_box")
        desc = o.get("description")
        if cls not in OBJECT_CLASSES or not isinstance(desc, str) or not desc.strip():
            continue
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            continue
        x1, y1, x2, y2 = box
        x1, x2 = sorted((max(0, min(sent[0], x1)), max(0, min(sent[0], x2))))
        y1, y2 = sorted((max(0, min(sent[1], y1)), max(0, min(sent[1], y2))))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        out.append(DetectedObjectItem(**{
            "class": cls,
            "screen_box": [round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy)],
            "description": desc.strip(),
        }))
    return out


_EVENT_TYPE = {"person": EventType.PERSON, "fire": EventType.FIRE, "smoke": EventType.FIRE}


@dataclass
class AnalyzeResult:
    pending: int = 0
    analyzed: int = 0
    failed: int = 0
    hazard_counts: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    gemma_unavailable: Optional[str] = None


class ServerNotifier:
    """분석 결과가 저장될 때마다 서버(/notify/assessments)에 알려 관제 앱으로 실시간 푸시되게 함.
    서버가 꺼져 있거나 거부하면 경고를 한 번 남기고 알림만 멈춤 (분석·저장은 계속)."""

    def __init__(self, server_url: str, mission_id: int, headers: Dict[str, str], timeout_s: float = 3.0):
        self.url = f"{server_url.rstrip('/')}/api/v1/missions/{mission_id}/notify/assessments"
        self.headers = headers
        self.timeout_s = timeout_s
        self.sent = 0
        self.alerts = 0
        self.clients: Optional[int] = None
        self.disabled_reason: Optional[str] = None

    def __call__(self, assessment_ids: List[int]) -> None:
        if self.disabled_reason or not assessment_ids:
            return
        try:
            res = requests.post(self.url, json={"assessment_ids": assessment_ids, "source": "fire_vision_import"},
                                headers=self.headers, timeout=self.timeout_s)
        except requests.RequestException as e:
            self.disabled_reason = f"서버 연결 실패 ({type(e).__name__}) — 서버가 꺼져 있으면 앱은 /map-state 새로고침으로 확인"
            return
        if res.status_code != 200:
            self.disabled_reason = f"서버 알림 거부 HTTP {res.status_code}: {res.text[:150]}"
            return
        try:
            body = res.json()
            self.sent += int(body.get("broadcast_assessments", 0))
            self.alerts += int(body.get("alerts_sent", 0))
            self.clients = body.get("connected_clients")
        except Exception as e:  # 알림 응답 문제로 이미 저장된 분석 결과가 실패 처리되지 않도록
            self.disabled_reason = f"서버 알림 응답 해석 실패 ({e})"


def analyze_pending(db: Session, mission: Mission, session_key: str,
                    endpoint: Optional[str], model: str, notify=None) -> AnalyzeResult:
    result = AnalyzeResult()
    pending = _session_logs_query(db, mission.mission_id, session_key).filter(
        RawTelemetryLog.is_processed.is_(False)
    ).order_by(RawTelemetryLog.timestamp.asc()).all()
    result.pending = len(pending)
    if not pending:
        return result
    if not endpoint:
        result.gemma_unavailable = "GEMMA_API_URL이 설정되지 않았습니다"
        return result

    for log in pending:
        payload = log.raw_payload or {}
        image_path = Path("static") / (log.snapshot_path or "")
        try:
            resp, orig, sent = call_gemma(image_path, endpoint, model)
            objects = parse_objects(resp, orig, sent)
        except GemmaUnavailable as e:
            result.gemma_unavailable = str(e)
            break  # 엔드포인트 문제는 이후 프레임도 실패하므로 중단 (원시 로그는 미처리로 남음)
        except Exception as e:
            result.failed += 1
            result.errors.append(f"log {log.log_id}: Gemma 응답 처리 실패 ({e})")
            continue

        packet = RawTelemetryIngest(timestamp=log.timestamp, frame_id=payload.get("frame_id"),
                                    detected_objects=objects)
        decision = ai_assessor.assess_situation(packet=packet, image_path=log.snapshot_path)

        if objects:
            b = objects[0].screen_box
            cx, cy = round((b[0] + b[2]) / 2.0, 2), round((b[1] + b[3]) / 2.0, 2)
        else:
            cx = cy = 0.0
        try:
            for obj in objects:
                b = obj.screen_box
                db.add(DetectionEvent(
                    mission_id=log.mission_id, device_id=log.device_id, timestamp=log.timestamp,
                    event_type=_EVENT_TYPE.get(obj.class_label, EventType.HAZARD), confidence=None,
                    coord_x=round((b[0] + b[2]) / 2.0, 2), coord_y=round((b[1] + b[3]) / 2.0, 2), coord_z=0.0,
                    max_temperature=None, snapshot_path=log.snapshot_path,
                ))
            assessment = AIAssessment(
                mission_id=log.mission_id, device_id=log.device_id, raw_log_id=log.log_id,
                timestamp=log.timestamp,
                hazard_level=decision.hazard_level,
                situation_summary=resp.get("scene_summary") if isinstance(resp.get("scene_summary"), str) and resp.get("scene_summary").strip() else decision.situation_summary,
                human_detected=decision.human_detected, human_status=decision.human_status,
                action_recommendation=decision.action_recommendation, poi_type=decision.poi_type,
                coord_x=cx, coord_y=cy, coord_z=0.0,
                assessment_json={
                    "analyzer": "gemma_server", "model": model,
                    "frame_id": payload.get("frame_id"), "session_key": session_key,
                    "detected_objects": [o.model_dump(by_alias=True) for o in objects],
                    "rule_decision": decision.model_dump(mode="json"),
                    "gemma_response": resp,
                    "coord_meaning": "screen_box 중심 픽셀 (실제 공간 좌표 아님)",
                },
                snapshot_path=log.snapshot_path,
            )
            db.add(assessment)
            log.is_processed = True
            log.processed_at = datetime.utcnow()
            db.commit()
            if notify:
                notify([assessment.assessment_id])  # 저장이 확정된 뒤에만 알림
        except Exception as e:
            db.rollback()  # 이 프레임의 분석 결과만 취소, 원시 로그는 그대로
            result.failed += 1
            result.errors.append(f"log {log.log_id}: DB 저장 실패 ({e})")
            continue
        result.analyzed += 1
        lvl = decision.hazard_level.value
        result.hazard_counts[lvl] = result.hazard_counts.get(lvl, 0) + 1
    return result


def default_endpoint() -> Optional[str]:
    return os.getenv("GEMMA_API_URL") or os.getenv("GEMMA_ENDPOINT_URL")


def default_model() -> str:
    return os.getenv("GEMMA_MODEL_NAME", "gemma3:4b")
