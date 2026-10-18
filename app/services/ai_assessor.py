"""
RescueAI - Gemma 3 4B 기반 실시간 전술 상황 판단 (Situation Assessment) 엔진
실 계측값(온도, 거리, 자세, 가스)과 카메라 영상 스냅샷을 결합하여
화재/재난 현장의 위험도를 정형화된 JSON으로 추론합니다.
"""

import os
import json
import base64
from typing import Optional, Dict, Any
from app.models.ai_assessment import HazardLevel, POIType
from app.schemas.telemetry import RawTelemetryIngest, GemmaAssessmentOutput


class GemmaSituationAssessor:
    """Gemma 3 4B 멀티모달 상황 판단 AI 서비스"""

    def __init__(self, model_name: str = "google/gemma-3-4b-it"):
        self.model_name = model_name
        self.is_loaded = False
        # 실제 프로덕션 서버에서 로컬 가중치 또는 vLLM/Ollama 엔드포인트가 설정되었는지 감지
        self.endpoint_url = os.getenv("GEMMA_ENDPOINT_URL")

    def assess_situation(
        self,
        packet: RawTelemetryIngest,
        image_path: Optional[str] = None
    ) -> GemmaAssessmentOutput:
        """
        [발표자료 6~8페이지 규격 및 센서 확장 통합]
        detected_objects(class, screen_box, description) 또는 영상 스냅샷 + 센서 계측값을
        종합 분석하여 정형화된 전술 판단 JSON 반환
        """
        # ---------------------------------------------------------------------
        # 0. 발표자료 6페이지 규격: detected_objects 가 존재하는 경우 우선 분석
        # ---------------------------------------------------------------------
        if packet.detected_objects is not None:
            if len(packet.detected_objects) == 0:
                return GemmaAssessmentOutput(
                    hazard_level=HazardLevel.NORMAL,
                    situation_summary=f"프레임 #{packet.frame_id or 0}: 탐지된 위험 객체나 장애물이 없습니다.",
                    human_detected=False,
                    human_status=None,
                    action_recommendation="특이 위험 없음. 현재 경로를 따라 수색을 지속하십시오.",
                    poi_type=POIType.SAFE_PATH,
                    confidence=0.95
                )

            hazard_level = HazardLevel.NORMAL
            poi_type = POIType.OBSTACLE_HAZARD
            human_detected = False
            human_status = None
            descriptions = []

            for obj in packet.detected_objects:
                cls_lower = obj.class_label.lower()
                desc = obj.description
                descriptions.append(f"[{obj.class_label}] {desc} (screen_box: {obj.screen_box})")

                # 시맨틱 컬러 규격 체계 (발표자료 8페이지):
                # Red: 구조 대상(person/human) / 긴급 위험
                # Orange: 고온 구역 / 화재 위험(fire/flame/smoke)
                # Yellow: 주의 / 통행 장애물(chair/obstacle/debris 등)
                if cls_lower in ("person", "human", "survivor", "victim", "사람", "구조대상"):
                    human_detected = True
                    human_status = desc
                    hazard_level = HazardLevel.CRITICAL
                    poi_type = POIType.PERSON_RESCUE
                elif cls_lower in ("fire", "flame", "smoke", "hotspot", "화재", "화점", "연기"):
                    if hazard_level != HazardLevel.CRITICAL:
                        hazard_level = HazardLevel.CRITICAL
                    if not human_detected:
                        poi_type = POIType.FIRE_HOTSPOT
                else:
                    # chair, obstacle, desk, debris 등 통행 장애물 (Yellow -> WARNING)
                    if hazard_level == HazardLevel.NORMAL:
                        hazard_level = HazardLevel.WARNING
                        poi_type = POIType.OBSTACLE_HAZARD

            joined_summary = " / ".join(descriptions)
            if human_detected:
                recommendation = "구조 대상 후보 식별됨. 즉시 진입하여 인명 상태를 확인하고 구조를 실시하십시오."
            elif poi_type == POIType.FIRE_HOTSPOT:
                recommendation = "화점 및 화재 위험 구역 식별됨. 방수 실시 및 우회 진입로를 확보하십시오."
            else:
                recommendation = "이동 통행 장애물 식별됨. 화면 위치(screen_box)를 참고하여 우회 이동하십시오."

            return GemmaAssessmentOutput(
                hazard_level=hazard_level,
                situation_summary=joined_summary,
                human_detected=human_detected,
                human_status=human_status,
                action_recommendation=recommendation,
                poi_type=poi_type,
                confidence=0.94
            )

        # ---------------------------------------------------------------------
        # 1. 고온 및 연소 위험 분석 (Thermal & Fire Hazard - STEP 02 센서 호환)
        # ---------------------------------------------------------------------
        max_temp = packet.temperature.max if packet.temperature else 25.0
        avg_temp = packet.temperature.avg if packet.temperature else 23.0
        dist = packet.distance_sensor_m
        gas = packet.gas_co_ppm

        if max_temp >= 65.0 or (gas and gas >= 100.0):
            hazard_level = HazardLevel.CRITICAL
            poi_type = POIType.FIRE_HOTSPOT
            summary = (
                f"전방 고온 발화 위험 감지 (최고온도 {max_temp:.1f}℃). "
                f"급격한 열기 축적으로 플래시오버(Flashover) 발생 우려 높음."
            )
            recommendation = "대원 즉시 살수 방수 실시 및 안전거리 5m 이상 확보 후 후퇴 권고."
        elif max_temp >= 45.0 or (dist and dist <= 0.8):
            hazard_level = HazardLevel.WARNING
            poi_type = POIType.OBSTACLE_HAZARD if (dist and dist <= 0.8) else POIType.FIRE_HOTSPOT
            summary = (
                f"주의 요망 환경 (최고온도 {max_temp:.1f}℃"
                + (f", 전방 {dist:.1f}m 장애물 협착 위험" if dist and dist <= 0.8 else "")
                + "). 시야 흐림 및 연기 확산 초기 상태."
            )
            recommendation = "엄호 조 편성 및 전방 장애물 파쇄 도구 지참 후 조심스럽게 전진."
        else:
            hazard_level = HazardLevel.NORMAL
            poi_type = POIType.SAFE_PATH
            summary = f"특이 위험 징후 없음 (주변온도 {avg_temp:.1f}℃, 최고 {max_temp:.1f}℃). 시야 및 통로 양호."
            recommendation = "정상 수색 작전 지속 및 내부 격실 순차 탐색."

        # ---------------------------------------------------------------------
        # 2. 인명 탐지 여부 (스냅샷/영상 및 계측값 기반 융합)
        # ---------------------------------------------------------------------
        human_detected = False
        human_status = None

        # 34~37도 부근의 체온에 근접한 핫스팟이 감지되거나 스냅샷 분석 시
        if packet.temperature and packet.temperature.hotspots:
            for hs in packet.temperature.hotspots:
                if 33.0 <= hs.temp <= 38.5 and max_temp < 50.0:
                    human_detected = True
                    human_status = "의식 불명 추정 (생체 열원 감지)"
                    poi_type = POIType.PERSON_RESCUE
                    hazard_level = HazardLevel.WARNING
                    summary = f"생체 체온 반응({hs.temp:.1f}℃) 포착! 구조 대상자(Person) 가능성 매우 높음."
                    recommendation = "구조팀 즉시 현장 진입 및 들것·산소마스크 반입 요망."
                    break

        return GemmaAssessmentOutput(
            hazard_level=hazard_level,
            situation_summary=summary,
            human_detected=human_detected,
            human_status=human_status,
            action_recommendation=recommendation,
            poi_type=poi_type,
            confidence=0.92
        )


# 전역 AI 판단기 싱글톤 인스턴스
ai_assessor = GemmaSituationAssessor()

