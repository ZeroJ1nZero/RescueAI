"""
연암소방대 - Gemma 3 4B LLM 원시 데이터 정제(Refining) 및 배치 추론 엔진
DB의 raw_telemetry_logs에 선저장된 원본 계측 JSON(`is_processed=False` 등)을 읽어와
Gemma 3 4B 멀티모달/LLM 엔드포인트(Ollama/vLLM)를 호출하여 정제 데이터(ai_assessments, sensor_logs)로 변환합니다.

※ 실시간 인입 API의 무지연 규칙/시맨틱 판정은 `app/services/ai_assessor.py` (`TacticalRuleAssessor`)가 담당하며,
본 모듈은 외부 LLM 엔드포인트 연동 및 배치/비동기 재정제(Re-refining) 파이프라인을 전담합니다.
(LLM 엔드포인트 미연결 시에는 `ai_assessor`의 표준 규칙 엔진을 폴백으로 위임 호출하여 판단 기준의 일관성을 유지합니다.)
"""

import os
import json
import requests
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.raw_telemetry import RawTelemetryLog
from app.models.ai_assessment import AIAssessment
from app.models.sensor import SensorLog
from app.schemas.telemetry import RawTelemetryIngest, GemmaAssessmentOutput
from app.services.ai_assessor import ai_assessor


class GemmaDataRefiner:
    """
    [LLM 정제 및 배치 워커 전용]
    Gemma 3 4B 프롬프트 조립, 외부 LLM API(Ollama/vLLM) 추론, 미처리 원시 로그 정제 서비스
    """

    def __init__(self):
        # Ollama, vLLM 또는 Google API 엔드포인트 지원 (환경 변수)
        self.endpoint_url = os.getenv("GEMMA_API_URL") or os.getenv("GEMMA_ENDPOINT_URL")
        self.model_name = os.getenv("GEMMA_MODEL_NAME", "gemma3:4b")

    def build_prompt(self, raw_payload: Dict[str, Any]) -> str:
        """
        원시 계측 JSON을 Gemma 3 4B가 이해하기 쉬운 전술 프롬프트로 변환
        """
        loc = raw_payload.get("location") or {}
        temp = raw_payload.get("temperature") or {}
        imu = raw_payload.get("imu") or {}
        dist = raw_payload.get("distance_sensor_m")
        gas = raw_payload.get("gas_co_ppm")
        hotspots = temp.get("hotspots", [])
        detected_objects = raw_payload.get("detected_objects")

        prompt = f"""[소방 전술 현장 실시간 계측 데이터]
- 프레임 번호: {raw_payload.get('frame_id')}
- 탐지된 영상 객체(detected_objects): {json.dumps(detected_objects, ensure_ascii=False) if detected_objects is not None else '없음'}
- 대원 추정 좌표: x={loc.get('x')}m, y={loc.get('y')}m, z={loc.get('z', 0.0)}m
- 대원 진행 방향(Yaw): {imu.get('yaw')}°
- 열화상 카메라 계측: 최고온도={temp.get('max')}℃, 평균온도={temp.get('avg')}℃
- 집중 핫스팟 목록: {json.dumps(hotspots, ensure_ascii=False)}
- 전방 장애물 거리: {dist}m
- 유독가스(CO) 농도: {gas}ppm

[지시사항]
너는 대한민국 소방청 통제실 전술 AI 참모(Gemma 3 4B)다.
위 객체 탐지 및 센서 계측 수치를 바탕으로 현장의 복합적인 화재 위험도, 인명 생존 여부, 장애물 협착 위험을 종합 판단하여
반드시 아래 JSON 스키마 규격으로만 응답하라. 설명이나 인사말 없이 오직 JSON만 출력할 것.

출력 JSON 스키마:
{{
  "hazard_level": "CRITICAL" | "WARNING" | "NORMAL",
  "situation_summary": "현장 상황을 지휘관에게 브리핑하는 간결하고 명확한 요약 1~2문장",
  "human_detected": true | false,
  "human_status": "의식 저하 및 호흡 미약" | "활동 가능" | null,
  "action_recommendation": "현장 대원 및 통제실에 내릴 구체적 전술 행동 권고",
  "poi_type": "FIRE_HOTSPOT" | "PERSON_RESCUE" | "OBSTACLE_HAZARD" | "SAFE_PATH",
  "confidence": 0.0 ~ 1.0 사이의 실수
}}
"""
        return prompt

    def infer_with_gemma(self, prompt: str, raw_payload: Dict[str, Any]) -> GemmaAssessmentOutput:
        """
        Gemma 3 4B 모델을 호출하여 구조화된 전술 판단 JSON 생성
        1) 로컬/원격 Ollama·vLLM 엔드포인트가 설정된 경우 실제 LLM HTTP 추론 수행
        2) 미설정 또는 타임아웃 시 `ai_assessor` (TacticalRuleAssessor)로 위임하여 동일한 기준으로 폴백 처리
        """
        if self.endpoint_url:
            try:
                payload = {
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                res = requests.post(self.endpoint_url, json=payload, timeout=10)
                if res.status_code == 200:
                    res_json = res.json()
                    response_text = res_json.get("response", "{}")
                    parsed = json.loads(response_text)
                    return GemmaAssessmentOutput(**parsed)
            except Exception as e:
                print(f"[Gemma Endpoint Warning] {e} -> 실시간 규칙 엔진(TacticalRuleAssessor)으로 폴백 전환")

        # 폴백: 중복 규칙 로직을 두지 않고 TacticalRuleAssessor에 위임하여 판단 기준 일원화
        packet = RawTelemetryIngest.model_validate(raw_payload)
        return ai_assessor.assess_situation(packet=packet)

    def refine_raw_log(self, db: Session, raw_log: RawTelemetryLog) -> AIAssessment:
        """
        단일 원시 JSON 로그(raw_telemetry_logs)를 Gemma 3 4B로 정제하여 ai_assessments 및 sensor_logs에 반영
        """
        payload = raw_log.raw_payload
        loc = payload.get("location") or {}
        imu = payload.get("imu") or {}
        temp = payload.get("temperature") or {}

        # Step 1. 프롬프트 구성
        prompt = self.build_prompt(payload)

        # Step 2. Gemma 3 4B 추론
        assessment_output = self.infer_with_gemma(prompt, payload)

        # Step 3. 지도 궤적용 sensor_logs 저장
        sensor_log = SensorLog(
            mission_id=raw_log.mission_id,
            device_id=raw_log.device_id,
            timestamp=raw_log.timestamp,
            pos_x=loc.get("x", 0.0),
            pos_y=loc.get("y", 0.0),
            pos_z=loc.get("z", 0.0),
            imu_yaw=imu.get("yaw") if imu else None,
            ambient_temp=temp.get("avg") if temp else None
        )
        db.add(sensor_log)

        # Step 4. 정제된 상황 판단 ai_assessments 저장
        assessment = AIAssessment(
            mission_id=raw_log.mission_id,
            device_id=raw_log.device_id,
            raw_log_id=raw_log.log_id,
            timestamp=raw_log.timestamp,
            hazard_level=assessment_output.hazard_level,
            situation_summary=assessment_output.situation_summary,
            human_detected=assessment_output.human_detected,
            human_status=assessment_output.human_status,
            action_recommendation=assessment_output.action_recommendation,
            poi_type=assessment_output.poi_type,
            coord_x=loc.get("x", 0.0),
            coord_y=loc.get("y", 0.0),
            coord_z=loc.get("z", 0.0),
            assessment_json=assessment_output.model_dump(),
            snapshot_path=raw_log.snapshot_path
        )
        db.add(assessment)

        # Step 5. 원시 로그 정제 완료 플래그 갱신
        raw_log.is_processed = True
        raw_log.processed_at = datetime.utcnow()

        db.commit()
        db.refresh(assessment)
        return assessment


gemma_refiner = GemmaDataRefiner()
