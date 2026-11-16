"""
연암소방대 - 임베디드(Fire Vision) SSD 세션 → 서버 가져오기

SSD를 노트북에 연결한 뒤, 임베디드 `extract-bag` 결과 폴더(manifest.json + rgb/*.npy)를 지정해 실행합니다.
  1) Save-First: 프레임 JPEG 저장 + raw_telemetry_logs 선저장 (Gemma 연결 여부와 무관)
  2) 분석: 서버 Gemma 3 4B로 미처리 프레임 분석 → ai_assessments / detection_events
Gemma가 꺼져 있으면 1)만 수행되며, 나중에 같은 명령을 다시 실행하면 2)만 이어서 수행합니다.
같은 세션을 다시 실행해도 이미 저장된 프레임은 중복 저장하지 않습니다.

사용 예 (프로젝트 루트에서):
  python app/scripts/import_fire_vision_session.py E:/fire_vision/office1-1-e0 --mission 1
  python app/scripts/import_fire_vision_session.py E:/fire_vision/office1-1-e0 --mission 1 --interval 2 --save-only

Gemma(Ollama) 준비:
  ollama pull gemma3:4b
  .env 에 GEMMA_API_URL=http://127.0.0.1:11434/api/generate  (모델명 변경 시 GEMMA_MODEL_NAME)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))  # static/ 경로 기준

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.core.database import SessionLocal, engine  # noqa: E402

engine.echo = False  # 개발용 SQL 로그가 진행 메시지에 섞이지 않도록
from app.models.mission import Mission  # noqa: E402
from app.services import fire_vision_importer as fvi  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="임베디드 SSD 세션 → 서버 가져오기 (Save-First + Gemma 분석)")
    ap.add_argument("session_dir", help="extract-bag 결과 폴더 (manifest.json이 있는 폴더)")
    ap.add_argument("--mission", type=int, required=True, help="연결할 작전 ID")
    ap.add_argument("--interval", type=float, default=1.0, help="프레임 샘플링 간격(초, 기본 1.0)")
    ap.add_argument("--max-frames", type=int, default=None, help="최대 프레임 수 (시험용)")
    ap.add_argument("--save-only", action="store_true", help="Save-First 저장만 하고 분석은 하지 않음")
    ap.add_argument("--gemma-url", default=None, help="Gemma 엔드포인트 (기본: 환경변수 GEMMA_API_URL)")
    ap.add_argument("--model", default=None, help="모델명 (기본: 환경변수 GEMMA_MODEL_NAME 또는 gemma3:4b)")
    ap.add_argument("--server", default=os.getenv("RESCUE_SERVER_URL", "http://127.0.0.1:8000"),
                    help="결과를 앱에 실시간 푸시할 서버 주소 (기본: RESCUE_SERVER_URL 또는 http://127.0.0.1:8000)")
    ap.add_argument("--device-id", default=os.getenv("RESCUE_DEVICE_ID", "EDGE-CAM-01"))
    ap.add_argument("--device-key", default=os.getenv("RESCUE_DEVICE_KEY", "rescue-edge-secret-key-01"))
    ap.add_argument("--no-notify", action="store_true", help="서버 알림(앱 실시간 푸시)을 하지 않음")
    args = ap.parse_args()

    if args.interval <= 0:
        print("[오류] --interval은 0보다 커야 합니다.")
        return 2

    try:
        session = fvi.load_session(args.session_dir)
    except Exception as e:
        print(f"[오류] 세션을 읽을 수 없습니다: {e}")
        return 2

    db = SessionLocal()
    try:
        mission = db.query(Mission).filter(Mission.mission_id == args.mission).first()
        if not mission:
            print(f"[오류] 작전 #{args.mission}이 없습니다.")
            return 2

        print(f"[세션] {session.root}")
        print(f"  세션 키 {session.session_key} / RGB 프레임 {len(session.rgb_rows)}개 / 작전 #{mission.mission_id} ({mission.status.value})")

        # 1) Save-First
        s = fvi.save_first(db, mission, session, args.interval, args.max_frames)
        print(f"[1/2 Save-First] 샘플 {s.sampled}개 → 새로 저장 {s.saved}개, 이미 저장됨 {s.skipped_existing}개, 실패 {len(s.errors)}개")
        for err in s.errors[:10]:
            print(f"  [실패] {err}")

        if args.save_only:
            print("[2/2 분석] --save-only: 건너뜀. 나중에 같은 명령(옵션 없이)으로 분석할 수 있습니다.")
            return 0 if not s.errors else 1

        # 2) 분석
        endpoint = args.gemma_url or fvi.default_endpoint()
        model = args.model or fvi.default_model()
        notifier = None if args.no_notify else fvi.ServerNotifier(
            args.server, mission.mission_id, {"X-Device-Id": args.device_id, "X-Device-Key": args.device_key})
        a = fvi.analyze_pending(db, mission, session.session_key, endpoint, model, notify=notifier)
        if a.pending == 0:
            print("[2/2 분석] 분석할 미처리 프레임이 없습니다.")
        else:
            summary = ", ".join(f"{k} {v}" for k, v in sorted(a.hazard_counts.items())) or "없음"
            print(f"[2/2 분석] 대상 {a.pending}개 → 완료 {a.analyzed}개, 실패 {a.failed}개 (위험도: {summary})")
            for err in a.errors[:10]:
                print(f"  [실패] {err}")
            remaining = a.pending - a.analyzed
            if a.gemma_unavailable:
                print(f"  [중단] {a.gemma_unavailable}")
            if remaining:
                print(f"  미처리 {remaining}개는 원본이 저장되어 있습니다. Gemma를 확인한 뒤 같은 명령으로 다시 실행하세요.")
            if notifier and a.analyzed:
                if notifier.disabled_reason:
                    print(f"  [앱 푸시] {notifier.sent}건 전송 후 중단: {notifier.disabled_reason}")
                else:
                    print(f"  [앱 푸시] {notifier.sent}건 방송 (경보 {notifier.alerts}건, 접속 중인 앱 {notifier.clients}대)")
        ok = not s.errors and a.failed == 0 and not a.gemma_unavailable
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
