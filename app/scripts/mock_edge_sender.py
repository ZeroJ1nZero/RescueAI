"""
연암소방대 - 현장 AI 보드 / 외장 SSD 세션 데이터 전송 시뮬레이터
프레임 분석 JSON 스키마(timestamp, frame_id, detected_objects [class, screen_box, description]) 및
MDM 인가 단말 헤더(X-Terminal-Id)를 사용하여 수집 계층 API를 테스트합니다.
"""

import time
from datetime import datetime, timezone
import requests

SERVER_URL = "http://127.0.0.1:8000"
TERMINAL_ID = "TAB-HQ-001"
DEVICE_ID = "EDGE-CAM-01"
DEVICE_KEY = "rescue-edge-secret-key-01"


def simulate_telemetry(mission_id: int):
    # MDM 인가 단말 검증 (X-Terminal-Id) 및 엣지 호환 헤더
    headers = {
        "X-Terminal-Id": TERMINAL_ID,
        "X-Device-Id": DEVICE_ID,
        "X-Device-Key": DEVICE_KEY,
        "Content-Type": "application/json"
    }

    url = f"{SERVER_URL}/api/v1/missions/{mission_id}/telemetry/raw"
    print(f"[AI 보드 / 세션 수집 테스트] 작전 #{mission_id}으로 JSON 프레임 데이터 전송 시작...")

    sample_frames = [
        {
            "timestamp": "2026-10-12T05:20:00Z",
            "frame_id": 1042,
            "detected_objects": [
                {
                    "class": "chair",
                    "screen_box": [120, 240, 310, 450],
                    "description": "복도 중앙을 가로막고 있는 장애물 의자"
                }
            ]
        },
        {
            "timestamp": "2026-10-12T05:20:05Z",
            "frame_id": 1192,
            "detected_objects": [
                {
                    "class": "person",
                    "screen_box": [200, 150, 380, 520],
                    "description": "ROOM A 내부 바닥에 쓰러져 있는 구조 대상 후보 1명"
                }
            ]
        },
        {
            "timestamp": "2026-10-12T05:20:10Z",
            "frame_id": 1342,
            "detected_objects": [
                {
                    "class": "fire",
                    "screen_box": [410, 100, 590, 390],
                    "description": "ROOM B 입구 부근 고온 화점 및 화염 확산 위험 구역"
                }
            ]
        }
    ]

    for idx, packet in enumerate(sample_frames, start=1):
        try:
            res = requests.post(url, json=packet, headers=headers)
            if res.status_code == 200:
                data = res.json()
                print(
                    f"[{idx}/{len(sample_frames)}] 전송 성공 (frame_id={packet['frame_id']}) "
                    f"-> hazard_level: {data.get('hazard_level')}, assessment_id: {data.get('assessment_id')}"
                )
            else:
                print(f"[{idx}/{len(sample_frames)}] 전송 실패: {res.status_code} {res.text}")
        except Exception as e:
            print(f"[{idx}/{len(sample_frames)}] 서버 연결 오류: {e}")

        time.sleep(1.0)

    print("\n[AI 보드 / 세션 수집 테스트] 데이터 전송 시뮬레이션 완료.")


if __name__ == "__main__":
    import sys
    target_mission = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    simulate_telemetry(target_mission)

