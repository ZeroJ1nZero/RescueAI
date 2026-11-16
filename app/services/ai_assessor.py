"""
연암소방대 - 실시간 전술 상황 판단 (Real-time Tactical Rule Engine) 서비스
SSD 세션 가져오기(`app/services/fire_vision_importer.py`)에서 Gemma 3 4B가 찾은 프레임 객체(detected_objects)를
확정적 규칙으로 위험도·POI 마커로 판정합니다. Gemma는 '무엇이 보이는가'만 답하고, 위험도는 이 규칙으로 일관되게 정합니다.
(센서 계측값 분기는 RGB-D·열화상 센서 확장 시 사용 — 현재 입력 없음)
"""

from typing import Optional
from app.models.ai_assessment import HazardLevel, POIType
from app.schemas.telemetry import RawTelemetryIngest, GemmaAssessmentOutput


class TacticalRuleAssessor:
    """
    [실시간 파이프라인 전용]
    외부 LLM 네트워크 호출 없이 확정적(Deterministic) 규칙 및 시맨틱 컬러 규격으로
    수 밀리초 이내에 현장 위험도를 즉시 판정하는 엔진
    """

    # 센서 위험 판정 임계치 상수 (센서 확장 시 사용)
    CRITICAL_TEMP_C: float = 65.0
    WARNING_TEMP_C: float = 40.0
    CRITICAL_GAS_PPM: float = 100.0
    WARNING_GAS_PPM: float = 30.0
    OBSTACLE_DIST_M: float = 0.8
    HUMAN_TEMP_MIN_C: float = 33.0
    HUMAN_TEMP_MAX_C: float = 38.5

    def assess_situation(
        self,
        packet: RawTelemetryIngest,
        image_path: Optional[str] = None
    ) -> GemmaAssessmentOutput:
        """
        [발표자료 6~8페이지 규격 및 센서 확장 통합]
        detected_objects(class, screen_box, description) 또는 센서 계측값을
        즉시 분석하여 정형화된 전술 판단 JSON(GemmaAssessmentOutput) 반환
        """
        # ---------------------------------------------------------------------
        # 1. 발표자료 6페이지 규격: detected_objects 가 존재하는 경우 시맨틱 매핑 우선 수행
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
        # 2. 센서 수치 기반 실시간 위험 분석 (STEP 02 센서 호환)
        # ---------------------------------------------------------------------
        max_temp = packet.temperature.max if packet.temperature else 25.0
        avg_temp = packet.temperature.avg if packet.temperature else 23.0
        dist = packet.distance_sensor_m
        gas = packet.gas_co_ppm or 0.0

        # 생체 체온 열원(33.0~38.5℃) 우선 확인
        human_detected = False
        human_status = None
        if packet.temperature and packet.temperature.hotspots:
            for hs in packet.temperature.hotspots:
                if self.HUMAN_TEMP_MIN_C <= hs.temp <= self.HUMAN_TEMP_MAX_C and max_temp < 50.0:
                    human_detected = True
                    human_status = "의식 저하 추정 (생체 체온 열원 감지)"
                    break

        if max_temp >= self.CRITICAL_TEMP_C or gas >= self.CRITICAL_GAS_PPM:
            hazard_level = HazardLevel.CRITICAL
            poi_type = POIType.FIRE_HOTSPOT
            summary = (
                f"전방 고온 발화 위험 감지 (최고온도 {max_temp:.1f}℃, CO {gas:.0f}ppm). "
                f"급격한 열기 축적으로 플래시오버(Flashover) 발생 우려 높음."
            )
            recommendation = "대원 즉시 살수 방수 실시 및 안전거리 5m 이상 확보 후 후퇴 권고."
            confidence = 0.96
        elif human_detected:
            hazard_level = HazardLevel.WARNING
            poi_type = POIType.PERSON_RESCUE
            summary = f"생체 체온 반응 포착! 구조 대상자(Person) 가능성 매우 높음 (주변온도 {avg_temp:.1f}℃)."
            recommendation = "구조팀 즉시 현장 진입 및 들것·산소마스크 반입 요망."
            confidence = 0.93
        elif (dist is not None and dist <= self.OBSTACLE_DIST_M) or max_temp >= self.WARNING_TEMP_C or gas >= self.WARNING_GAS_PPM:
            hazard_level = HazardLevel.WARNING
            poi_type = POIType.OBSTACLE_HAZARD if (dist is not None and dist <= self.OBSTACLE_DIST_M) else POIType.FIRE_HOTSPOT
            summary = (
                f"주의 요망 환경 (최고온도 {max_temp:.1f}℃, CO {gas:.0f}ppm"
                + (f", 전방 {dist:.1f}m 장애물 협착 위험" if dist is not None and dist <= self.OBSTACLE_DIST_M else "")
                + "). 시야 흐림 및 연기 확산 초기 상태."
            )
            recommendation = "엄호 조 편성 및 복도 벽면 밀착하여 조심스럽게 우회 전진."
            confidence = 0.91
        else:
            hazard_level = HazardLevel.NORMAL
            poi_type = POIType.SAFE_PATH
            summary = f"특이 위험 징후 없음 (주변온도 {avg_temp:.1f}℃, 최고 {max_temp:.1f}℃). 시야 및 통로 양호."
            recommendation = "정상 수색 작전 지속 및 내부 격실 순차 탐색."
            confidence = 0.90

        return GemmaAssessmentOutput(
            hazard_level=hazard_level,
            situation_summary=summary,
            human_detected=human_detected,
            human_status=human_status,
            action_recommendation=recommendation,
            poi_type=poi_type,
            confidence=confidence
        )


# 하위 호환 별칭 및 전역 실시간 판단기 싱글톤 인스턴스
GemmaSituationAssessor = TacticalRuleAssessor
ai_assessor = TacticalRuleAssessor()


