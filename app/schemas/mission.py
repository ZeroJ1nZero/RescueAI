from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.models.mission import MissionStatus
from app.models.detection import EventType
from app.schemas.building import BuildingResponse
from app.schemas.auth import OfficerInfo


class MissionCreate(BaseModel):
    title: str = Field(..., description="작전명 (예: 종로구 모의건물 화재진압 및 인명구조 작전)")
    building_id: int = Field(..., description="작전 대상 건물 ID")
    device_id: str = Field(..., description="투입할 엣지 카메라 장치 ID (예: EDGE-CAM-01)")


class MissionResponse(BaseModel):
    mission_id: int
    title: str
    building_id: int
    device_id: str
    commander_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    status: MissionStatus

    class Config:
        from_attributes = True


class MissionDetailResponse(MissionResponse):
    building: BuildingResponse
    commander: OfficerInfo

    class Config:
        from_attributes = True


class DetectionEventItem(BaseModel):
    event_id: int
    timestamp: int
    event_type: EventType
    confidence: Optional[float]
    coord_x: float
    coord_y: float
    coord_z: float
    max_temperature: Optional[float]
    snapshot_path: Optional[str]

    class Config:
        from_attributes = True


class SensorTrajectoryItem(BaseModel):
    timestamp: int
    pos_x: float
    pos_y: float
    pos_z: float
    imu_yaw: Optional[float]
    ambient_temp: Optional[float]

    class Config:
        from_attributes = True


class MissionReplayResponse(BaseModel):
    """사후 분석 및 타임라인 재생용 전체 데이터 패킷"""
    mission: MissionResponse
    total_trajectory_points: int
    total_detection_events: int
    trajectory: List[SensorTrajectoryItem]
    events: List[DetectionEventItem]
