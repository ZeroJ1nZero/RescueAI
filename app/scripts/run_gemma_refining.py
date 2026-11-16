"""
연암소방대 - DB에 입력된 원시 JSON 데이터를 Gemma 3 4B를 이용해 정제하는 실행 스크립트
1. raw_telemetry_logs에서 원본 JSON 추출
2. Gemma 3 4B 입력 프롬프트 조립
3. Gemma 3 4B 상황 판단 추론 실행 (Structured JSON)
4. 정제 전(Raw) vs 정제 후(Gemma AI Output) 비교 출력
"""

import os
import sys
import json

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.database import SessionLocal
from app.models.raw_telemetry import RawTelemetryLog
from app.models.ai_assessment import AIAssessment
from app.services.gemma_refiner import gemma_refiner


def run_refining(mission_id: int = 1):
    db = SessionLocal()
    try:
        print("================================================================================")
        print(f"🚀 [Gemma 3 4B 데이터 정제 파이프라인] 작전 #{mission_id} 원시 JSON 데이터 정제 시작")
        print("================================================================================\n")

        # 1. DB에서 원시 JSON 로그 10건 조회
        raw_logs = db.query(RawTelemetryLog).filter(
            RawTelemetryLog.mission_id == mission_id
        ).order_by(RawTelemetryLog.timestamp.asc()).all()

        if not raw_logs:
            print(f"[알림] 작전 #{mission_id}에 저장된 원시 데이터(raw_telemetry_logs)가 없습니다.")
            return

        print(f"📊 총 {len(raw_logs)}개의 원시 계측 패킷을 발견했습니다.\n")

        for idx, rlog in enumerate(raw_logs, 1):
            raw = rlog.raw_payload
            loc = raw.get("location", {})
            temp = raw.get("temperature", {})
            dist = raw.get("distance_sensor_m")
            gas = raw.get("gas_co_ppm")

            # 2. Gemma 3 4B 프롬프트 구성
            prompt = gemma_refiner.build_prompt(raw)

            # 3. Gemma 3 4B 추론 실행
            result = gemma_refiner.infer_with_gemma(prompt, raw)

            # 4. 정제 전/후 비교 출력
            print(f"--------------------------------------------------------------------------------")
            print(f"🔹 [단계 {idx}/{len(raw_logs)}] 원시 계측 패킷 (Log ID: {rlog.log_id}, 시간: {rlog.timestamp})")
            print(f"--------------------------------------------------------------------------------")
            print(f"  [📥 입력된 엣지 원시 JSON]")
            print(f"    - 위치 좌표: ({loc.get('x')}, {loc.get('y')}, {loc.get('z')}) m")
            print(f"    - 열화상 계측: 최고 {temp.get('max')}℃ / 평균 {temp.get('avg')}℃ / 핫스팟 {temp.get('hotspots')}")
            print(f"    - 거리 센서: {dist} m,  유독가스: CO {gas} ppm")
            print(f"\n  [🧠 Gemma 3 4B가 생성한 전술 상황 판단 결과 (정제된 JSON)]")
            print(f"    - 위험 등급 : [{result.hazard_level.value}]")
            print(f"    - 인명 감지 : {result.human_detected} (상태: {result.human_status or '없음'})")
            print(f"    - 지도 POI : {result.poi_type.value if result.poi_type else '없음'}")
            print(f"    - 상황 요약 : {result.situation_summary}")
            print(f"    - 행동 권고 : {result.action_recommendation}")
            print(f"    - 신뢰도    : {result.confidence * 100:.1f}%\n")

        print("================================================================================")
        print("✅ 모든 원시 데이터에 대한 Gemma 3 4B 정제 작업이 성공적으로 완료되었습니다!")
        print("   이제 모바일 지도 앱은 단순 센서 숫자가 아닌, 정제된 전술 마커와 브리핑 카드를 표출합니다.")
        print("================================================================================")

    finally:
        db.close()


if __name__ == "__main__":
    m_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    run_refining(m_id)
