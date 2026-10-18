"""
RescueAI - Gemma 3 4B 상황 판단 모델 시험 및 지도 앱 연동 검증용 더미 데이터 주입 스크립트
다양한 재난 상황(정상 수색, 인명 발견, 급격한 고온 화재, 장애물 붕괴, 비상 탈출로)을 시뮬레이션합니다.
"""

import os
import sys
import time
from datetime import datetime, timedelta

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.database import SessionLocal
from app.models.mission import Mission, MissionStatus
from app.models.raw_telemetry import RawTelemetryLog
from app.models.ai_assessment import AIAssessment, HazardLevel, POIType
from app.models.sensor import SensorLog
from app.models.device import Device
from app.models.building import Building


def seed_gemma_dummy_data(target_mission_id: int = 1):
    db = SessionLocal()
    try:
        print("==================================================")
        print(f"[더미 데이터 주입] 작전 #{target_mission_id} Gemma 3 4B 시나리오 데이터 생성 시작...")

        mission = db.query(Mission).filter(Mission.mission_id == target_mission_id).first()
        if not mission:
            print(f"[오류] 작전 #{target_mission_id}이 존재하지 않습니다.")
            return

        device_id = mission.device_id or "EDGE-CAM-01"

        # 기존 작전의 기존 테스트 로그 정리 (중복 방지 및 깔끔한 테스트)
        db.query(AIAssessment).filter(AIAssessment.mission_id == target_mission_id).delete()
        db.query(SensorLog).filter(SensorLog.mission_id == target_mission_id).delete()
        db.query(RawTelemetryLog).filter(RawTelemetryLog.mission_id == target_mission_id).delete()
        db.commit()
        print("   -> 기존 해당 작전의 이전 테스트 데이터 초기화 완료.")

        base_time_ms = int(time.time() * 1000) - (30 * 1000)  # 30초 전부터 시작

        # 10단계 현실적 화재/구조 전술 시나리오 정의
        scenarios = [
            {
                "step": 1,
                "offset_sec": 0,
                "x": 2.0, "y": 1.0, "z": 0.0, "yaw": 45.0,
                "temp_max": 24.5, "temp_avg": 22.0, "hotspots": [],
                "dist_m": 4.5, "gas_co": 5.0,
                "hazard": HazardLevel.NORMAL,
                "poi": POIType.SAFE_PATH,
                "human": False, "human_status": None,
                "summary": "1층 주출입구 로비 진입 완료. 시야 양호하며 특이 위험 징후 없음 (주변온도 22.0℃).",
                "recommendation": "1층 중앙 복도 및 좌측 격실 순차 수색 지속."
            },
            {
                "step": 2,
                "offset_sec": 3,
                "x": 4.5, "y": 2.0, "z": 0.0, "yaw": 50.0,
                "temp_max": 26.0, "temp_avg": 23.5, "hotspots": [],
                "dist_m": 3.8, "gas_co": 10.0,
                "hazard": HazardLevel.NORMAL,
                "poi": POIType.SAFE_PATH,
                "summary": "중앙 복도 15m 지점 통과 중. 연기 미발생 상태이며 대원 이동성 양호.",
                "recommendation": "전방 101호실 방향으로 접근 수색."
            },
            {
                "step": 3,
                "offset_sec": 6,
                "x": 6.8, "y": 3.2, "z": 0.0, "yaw": 60.0,
                "temp_max": 38.5, "temp_avg": 27.0, "hotspots": [{"x": 140, "y": 90, "temp": 38.5}],
                "dist_m": 1.8, "gas_co": 35.0,
                "hazard": HazardLevel.WARNING,
                "poi": POIType.OBSTACLE_HAZARD,
                "summary": "101호실 입구 옅은 백색 연기 유입 포착. CO 35ppm 검출 및 최고온도 38.5℃ 상승.",
                "recommendation": "공기호흡기 착용 밀착 점검 및 엄호 조 편성 후 실내 진입."
            },
            {
                "step": 4,
                "offset_sec": 9,
                "x": 8.5, "y": 4.0, "z": 0.0, "yaw": 75.0,
                "temp_max": 37.0, "temp_avg": 28.5, "hotspots": [{"x": 160, "y": 110, "temp": 36.8}],
                "dist_m": 1.1, "gas_co": 45.0,
                "hazard": HazardLevel.WARNING,
                "poi": POIType.PERSON_RESCUE,
                "human": True, "human_status": "의식 저하 및 호흡 미약 (연기 흡입 의심)",
                "summary": "🚨 침실 모퉁이 부근 36.8℃ 생체 체온 핫스팟 감지! 의식 저하된 요구조자(성인 1명) 발견.",
                "recommendation": "구조팀 즉시 들것 및 보조 호흡마스크 휴대 진입 요망. 후송 경로 확보."
            },
            {
                "step": 5,
                "offset_sec": 12,
                "x": 10.5, "y": 4.8, "z": 0.0, "yaw": 90.0,
                "temp_max": 48.0, "temp_avg": 32.0, "hotspots": [{"x": 110, "y": 70, "temp": 48.0}],
                "dist_m": 2.2, "gas_co": 75.0,
                "hazard": HazardLevel.WARNING,
                "poi": POIType.FIRE_HOTSPOT,
                "human": False, "human_status": None,
                "summary": "주방 연결 통로 진입 중. 천장부 열기 축적(최고 48.0℃, CO 75ppm) 및 회색 연기 밀도 증가.",
                "recommendation": "방수 호스 연장 준비 및 주방 개구부 열기 분출 주의."
            },
            {
                "step": 6,
                "offset_sec": 15,
                "x": 12.8, "y": 6.2, "z": 0.0, "yaw": 110.0,
                "temp_max": 84.5, "temp_avg": 45.0, "hotspots": [{"x": 180, "y": 85, "temp": 84.5}],
                "dist_m": 1.5, "gas_co": 185.0,
                "hazard": HazardLevel.CRITICAL,
                "poi": POIType.FIRE_HOTSPOT,
                "human": False, "human_status": None,
                "summary": "🔥 주방 싱크대 상단부 고온 발화점(최고 84.5℃, CO 185ppm) 포착! 플래시오버(Flashover) 발생 위험 극대화.",
                "recommendation": "현장 대원 즉시 주수 방수 실시 및 안전거리 5m 이상 확보 후 일시 후퇴 권고."
            },
            {
                "step": 7,
                "offset_sec": 18,
                "x": 11.5, "y": 5.5, "z": 0.0, "yaw": 240.0,
                "temp_max": 68.0, "temp_avg": 38.0, "hotspots": [{"x": 150, "y": 95, "temp": 68.0}],
                "dist_m": 1.8, "gas_co": 130.0,
                "hazard": HazardLevel.CRITICAL,
                "poi": POIType.FIRE_HOTSPOT,
                "human": False, "human_status": None,
                "summary": "집중 주수로 최고온도 68.0℃로 억제 중이나 흑색 농연 및 수증기 시야 차단 심각.",
                "recommendation": "배연 장비 가동 요청 및 잔화 정리 전까지 방수 엄호 유지."
            },
            {
                "step": 8,
                "offset_sec": 21,
                "x": 9.2, "y": 4.2, "z": 0.0, "yaw": 220.0,
                "temp_max": 42.0, "temp_avg": 30.0, "hotspots": [],
                "dist_m": 0.5, "gas_co": 60.0,
                "hazard": HazardLevel.WARNING,
                "poi": POIType.OBSTACLE_HAZARD,
                "human": False, "human_status": None,
                "summary": "복도 후퇴 경로 0.5m 전방 천장 석고보드 및 덕트 낙하로 통로 일부 폐쇄. 협착 주의.",
                "recommendation": "복도 중앙 통행 불가, 우측 벽면 지지대 밀착하여 조심스럽게 우회 통과."
            },
            {
                "step": 9,
                "offset_sec": 24,
                "x": 5.5, "y": 2.2, "z": 0.0, "yaw": 200.0,
                "temp_max": 28.0, "temp_avg": 24.0, "hotspots": [],
                "dist_m": 3.2, "gas_co": 20.0,
                "hazard": HazardLevel.NORMAL,
                "poi": POIType.SAFE_PATH,
                "human": False, "human_status": None,
                "summary": "1층 동측 비상구 통로 안전 확보. 외부 신선 외기 유입으로 시야 대폭 개선.",
                "recommendation": "동측 비상구를 요구조자 및 대원 주 탈출로(Primary Egress)로 지정 확정."
            },
            {
                "step": 10,
                "offset_sec": 27,
                "x": 2.5, "y": 1.2, "z": 0.0, "yaw": 180.0,
                "temp_max": 25.0, "temp_avg": 22.5, "hotspots": [],
                "dist_m": 4.0, "gas_co": 8.0,
                "hazard": HazardLevel.NORMAL,
                "poi": POIType.SAFE_PATH,
                "human": False, "human_status": None,
                "summary": "1층 전 구역 1차 수색 및 인명구조 인계 완료. 발화점 진압 안정화 단계 진입.",
                "recommendation": "2차 정밀 수색조 교대 및 잔류 연기 완전 환기 조치."
            }
        ]

        for s in scenarios:
            cur_timestamp = base_time_ms + (s["offset_sec"] * 1000)

            # 1. 원시 계측 JSON 패킷 생성 (엣지가 전송한 원본)
            raw_payload = {
                "timestamp": cur_timestamp,
                "device_id": device_id,
                "location": {"x": s["x"], "y": s["y"], "z": s["z"]},
                "imu": {"pitch": 0.5, "roll": -0.2, "yaw": s["yaw"]},
                "temperature": {
                    "max": s["temp_max"],
                    "avg": s["temp_avg"],
                    "hotspots": s["hotspots"]
                },
                "distance_sensor_m": s["dist_m"],
                "gas_co_ppm": s["gas_co"],
                "snapshot_base64": None,
                "extra_sensors": {"battery_pct": 95 - s["step"]}
            }

            # 2. Gemma 3 4B 구조화된 출력 JSON 생성
            human_val = s.get("human", False)
            human_stat = s.get("human_status", None)
            gemma_output_json = {
                "hazard_level": s["hazard"].value,
                "situation_summary": s["summary"],
                "human_detected": human_val,
                "human_status": human_stat,
                "action_recommendation": s["recommendation"],
                "poi_type": s["poi"].value if s["poi"] else None,
                "confidence": 0.94 if s["hazard"] != HazardLevel.NORMAL else 0.88
            }

            snap_file = s.get("snapshot_file")

            # 3. raw_telemetry_logs 저장 (JSON 선저장)
            raw_log = RawTelemetryLog(
                mission_id=target_mission_id,
                device_id=device_id,
                timestamp=cur_timestamp,
                raw_payload=raw_payload,
                snapshot_path=snap_file,
                is_processed=True,
                processed_at=datetime.utcnow()
            )
            db.add(raw_log)
            db.flush()

            # 4. sensor_logs 저장 (지도 궤적용 1Hz 다운샘플링)
            sensor_log = SensorLog(
                mission_id=target_mission_id,
                device_id=device_id,
                timestamp=cur_timestamp,
                pos_x=s["x"],
                pos_y=s["y"],
                pos_z=s["z"],
                imu_yaw=s["yaw"],
                ambient_temp=s["temp_avg"]
            )
            db.add(sensor_log)

            # 5. ai_assessments 저장 (Gemma 3 4B 상황 판단)
            assessment = AIAssessment(
                mission_id=target_mission_id,
                device_id=device_id,
                raw_log_id=raw_log.log_id,
                timestamp=cur_timestamp,
                hazard_level=s["hazard"],
                situation_summary=s["summary"],
                human_detected=human_val,
                human_status=human_stat,
                action_recommendation=s["recommendation"],
                poi_type=s["poi"],
                coord_x=s["x"],
                coord_y=s["y"],
                coord_z=s["z"],
                assessment_json=gemma_output_json,
                snapshot_path=snap_file
            )
            db.add(assessment)

            print(f"   [{s['step']}/10] {s['hazard'].value:8s} | 위치: ({s['x']:.1f}, {s['y']:.1f}) | POI: {s['poi'].value:15s}")

        db.commit()
        print("\n==================================================")
        print(f"🎉 작전 #{target_mission_id}에 총 {len(scenarios)}개의 Gemma 3 4B 시험용 더미 데이터 주입이 성공적으로 완료되었습니다!")
        print("   - raw_telemetry_logs: 10건 (원시 JSON 선저장)")
        print("   - sensor_logs:        10건 (지도 Polyline 이동 궤적)")
        print("   - ai_assessments:     10건 (Gemma 3 4B 상황 판단 & POI 마커)")
        print("==================================================")

    except Exception as e:
        db.rollback()
        print(f"[오류 발생] 더미 데이터 주입 실패: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    target_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    seed_gemma_dummy_data(target_id)
