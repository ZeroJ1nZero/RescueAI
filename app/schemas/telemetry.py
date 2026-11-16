from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.models.detection import EventType
from app.models.ai_assessment import HazardLevel, POIType


class Coordinate3D(BaseModel):
    x: float = Field(..., description="x 좌표 (미터 단위, 동-서)")
    y: float = Field(..., description="y 좌표 (미터 단위, 남-북)")
    z: float = Field(default=0.0, description="z 좌표 (높이/층고, 미터 단위)")


class IMUData(BaseModel):
    pitch: Optional[float] = None
    roll: Optional[float] = None
    yaw: Optional[float] = Field(None, description="대원/카메라의 방위각 (0~360도)")


class HotspotInfo(BaseModel):
    x: float
    y: float
    temp: float


class TemperatureData(BaseModel):
    max: float = Field(..., description="열화상 카메라 최고 온도 (℃)")
    avg: Optional[float] = None
    hotspots: List[HotspotInfo] = []


class DetectionItem(BaseModel):
    class_name: EventType = Field(..., description="탐지된 객체 유형 (PERSON, FIRE, HAZARD)")
    confidence: Optional[float] = Field(None, description="AI 신뢰도 점수 (0.0 ~ 1.0)")
    bbox: Optional[List[int]] = Field(None, description="2D 이미지 내 바운딩 박스 [x1, y1, x2, y2]")
    estimated_coord: Coordinate3D = Field(..., description="3D 공간지도 상의 추정 위치")
    snapshot_base64: Optional[str] = Field(None, description="현장 캡처 스냅샷 이미지 (선택 사항)")


# ============================================================================
# 1. 발표자료 6~7페이지 규격: AI 보드/서버 추출 객체 및 프레임 데이터 스키마
# ============================================================================
class DetectedObjectItem(BaseModel):
    """
    발표자료 6페이지 DATA FORMAT SPECIFICATION 규격:
    {
      "class": "chair",
      "screen_box": [120, 240, 310, 450],
      "description": "복도 중앙을 가로막고 있는 장애물 의자"
    }
    """
    class_label: str = Field(..., alias="class", description="객체 분류 라벨 (예: chair, person, fire, obstacle)")
    screen_box: List[int] = Field(..., min_length=4, max_length=4, description="2D 화면 좌표계 바운딩 박스 [x1, y1, x2, y2]")
    description: str = Field(..., description="상황 서술 텍스트 (예: 복도 중앙을 가로막고 있는 장애물 의자)")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "class": "chair",
                "screen_box": [120, 240, 310, 450],
                "description": "복도 중앙을 가로막고 있는 장애물 의자"
            }
        }
    }


class RawTelemetryIngest(BaseModel):
    """
    [발표자료 6~7페이지 수집 계층(Ingestion) 통합 스키마]
    - STEP 01 프로토타입 규격: timestamp (ISO 8601 문자열 또는 Unix ms), frame_id, detected_objects
    - STEP 02 센서 확장 호환: location, imu, temperature, distance_sensor_m, gas_co_ppm
    (서버 수신 즉시 Save-First 원칙에 따라 raw_telemetry_logs 테이블에 원본 선저장됨)
    """
    timestamp: str | int = Field(
        ...,
        description="관측 절대시각 (예: '2026-10-12T05:20:00Z' 또는 Unix Epoch ms)"
    )
    frame_id: Optional[int] = Field(
        None,
        description="프레임 번호 (예: 1042)"
    )
    detected_objects: Optional[List[DetectedObjectItem]] = Field(
        default=None,
        description="탐지된 객체 목록 (class, screen_box, description)"
    )

    # 하위 호환 및 STEP 02 센서 확장용 선택 필드
    device_id: Optional[str] = Field(None, description="엣지 장비 고유 식별자 (헤더 미지정 시 사용)")
    location: Optional[Coordinate3D] = Field(None, description="추정 대원 3D/2D 위치 좌표 (m, 미지정 시 화면 좌표 기반 추정)")
    imu: Optional[IMUData] = Field(None, description="자이로/가속도 센서 방위각")
    temperature: Optional[TemperatureData] = Field(None, description="열화상 카메라 측정 온도")
    distance_sensor_m: Optional[float] = Field(None, description="전방 거리 센서 장애물 거리 (m)")
    gas_co_ppm: Optional[float] = Field(None, description="일산화탄소/유독가스 센서 계측치 (ppm)")
    snapshot_base64: Optional[str] = Field(None, description="저조도/열화상 카메라 캡처 스냅샷 (Base64 JPEG/PNG)")
    extra_sensors: Optional[Dict[str, Any]] = Field(default={}, description="추가 확장 센서 원시 데이터")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "timestamp": "2026-10-12T05:20:00Z",
                "frame_id": 1042,
                "detected_objects": [
                    {
                        "class": "chair",
                        "screen_box": [120, 240, 310, 450],
                        "description": "복도 중앙을 가로막고 있는 장애물 의자"
                    }
                ]
            }
        }
    }


class SessionBatchIngest(BaseModel):
    """
    발표자료 6~7페이지: 외장 SSD 세션 단위 일괄 이동(JSON/JSONL 배열) 등록 스키마
    """
    frames: List[RawTelemetryIngest] = Field(..., description="세션 프레임 데이터 목록")


# 레거시 호환용
TacticalTelemetryIngest = RawTelemetryIngest



# ============================================================================
# 2. Gemma 3 4B AI 모델 상황 판단 출력 규격 (Structured JSON)
# ============================================================================
class GemmaAssessmentOutput(BaseModel):
    """
    실 계측값 + 영상 스냅샷을 결합하여 Gemma 3 4B 멀티모달 모델이 추론한 구조화된 JSON 결과
    """
    hazard_level: HazardLevel = Field(..., description="종합 위험 등급 (CRITICAL, WARNING, NORMAL, UNKNOWN)")
    situation_summary: str = Field(..., description="현장 종합 상황 요약 (화재·연기·붕괴 상태)")
    human_detected: bool = Field(default=False, description="인명 발견 여부")
    human_status: Optional[str] = Field(None, description="발견된 인명 상태 (예: '의식 불명 추정', '대피 가능')")
    action_recommendation: str = Field(..., description="대원 및 지휘관 전술 행동 권고 (예: '즉시 후퇴 및 방수')")
    poi_type: Optional[POIType] = Field(None, description="지도 마커 표시용 POI 유형 (FIRE_HOTSPOT, PERSON_RESCUE 등)")
    confidence: Optional[float] = Field(default=0.9, description="AI 신뢰도 점수 (0.0 ~ 1.0)")


class AIAssessmentResponse(BaseModel):
    """클라이언트 및 지도 앱에 전달되는 AI 상황 판단 이력 응답"""
    assessment_id: int
    mission_id: int
    device_id: str
    timestamp: int
    hazard_level: HazardLevel
    situation_summary: str
    human_detected: bool
    human_status: Optional[str] = None
    action_recommendation: Optional[str] = None
    poi_type: Optional[POIType] = None
    coord_x: Optional[float] = None
    coord_y: Optional[float] = None
    coord_z: Optional[float] = None
    snapshot_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# 3. 서버 -> 모바일 지도 앱 (Map App) 전용 인터페이스 규격
# ============================================================================
class MapLocationUpdate(BaseModel):
    """지도 앱 실시간 대원 위치 마커 갱신 패킷"""
    type: str = "LOCATION_UPDATE"
    mission_id: int
    device_id: str
    timestamp: int
    x: float = Field(..., description="지도 x좌표 (m)")
    y: float = Field(..., description="지도 y좌표 (m)")
    z: float = Field(default=0.0, description="지도 z좌표 (m)")
    yaw: Optional[float] = Field(None, description="대원 진행 방향각 (0~360도 화살표 렌더링용)")
    max_temperature: Optional[float] = None


class MapAlertMarker(BaseModel):
    """지도 앱 위험/인명/상황 POI 마커 및 브리핑 팝업 정보"""
    type: str = "AI_MARKER_ALERT"
    mission_id: int
    assessment_id: int
    timestamp: int
    hazard_level: HazardLevel
    poi_type: POIType
    title: str = Field(..., description="마커 타이틀 (예: '🔥 고온 발화 위험 감지')")
    summary: str = Field(..., description="Gemma 3 4B 현장 요약")
    action_recommendation: Optional[str] = Field(None, description="지휘관 권고사항")
    coord: Coordinate3D
    snapshot_url: Optional[str] = None


class MapMissionStateResponse(BaseModel):
    """지도 앱 접속 시 초기 전체 지도 레이어 데이터 (대원 위치, 이동 궤적, 활성 마커)"""
    mission_id: int
    title: str
    status: str
    building_id: int
    device_id: str
    current_location: Optional[Coordinate3D] = None
    current_yaw: Optional[float] = None
    trajectory: List[Coordinate3D] = Field(default=[], description="대원이 지나온 이동 궤적 (Polyline 그리기용)")
    active_markers: List[MapAlertMarker] = Field(default=[], description="지도 위에 표시할 활성 POI 마커 목록")
