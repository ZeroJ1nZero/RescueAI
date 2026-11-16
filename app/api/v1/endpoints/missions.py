from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_officer, require_clearance, require_role, verify_edge_device
from app.models.user import User, UserRole
from app.models.building import Building
from app.models.device import Device, DeviceStatus
from app.models.mission import Mission, MissionStatus
from app.models.sensor import SensorLog
from app.models.detection import DetectionEvent
from app.models.ai_assessment import AIAssessment, HazardLevel, POIType
from app.schemas.mission import (
    MissionCreate,
    MissionResponse,
    MissionDetailResponse,
    MissionReplayResponse,
    DetectionEventItem,
    SensorTrajectoryItem,
)
from app.schemas.telemetry import (
    TacticalTelemetryIngest,
    RawTelemetryIngest,
    Coordinate3D,
    AIAssessmentResponse,
    MapMissionStateResponse,
    MapAlertMarker,
)
from app.services.mission_manager import mission_manager

router = APIRouter(prefix="/missions", tags=["출동 작전 세션 및 실시간 데이터"])


@router.post(
    "",
    response_model=MissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="현장 출동 작전 발령 (작전 개시 - 지휘관 전용)",
    description="현장 지휘관(소방경/소방위 이상, Clearance 2 이상)이 대상 건물과 엣지 장치를 지정해 작전을 시작합니다."
)
def create_mission(
    req: MissionCreate,
    db: Session = Depends(get_db),
    officer: User = Depends(require_clearance(2))
):
    # 1. 건물 검증
    building = db.query(Building).filter(Building.building_id == req.building_id).first()
    if not building:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="지정된 건물이 존재하지 않습니다.")

    # 2. 엣지 장비 검증
    device = db.query(Device).filter(Device.device_id == req.device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="지정된 엣지 카메라 장비가 존재하지 않습니다.")

    # 3. 새 작전 생성
    mission = Mission(
        title=req.title,
        building_id=req.building_id,
        device_id=req.device_id,
        commander_id=officer.user_id,
        start_time=datetime.utcnow(),
        status=MissionStatus.ACTIVE
    )
    db.add(mission)
    device.status = DeviceStatus.ONLINE
    db.commit()
    db.refresh(mission)
    return mission


@router.get(
    "/active",
    response_model=List[MissionResponse],
    summary="현재 진행 중인(ACTIVE) 출동 작전 목록 조회"
)
def get_active_missions(
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    missions = db.query(Mission).filter(Mission.status == MissionStatus.ACTIVE).all()
    return missions


@router.get(
    "/{mission_id}",
    response_model=MissionDetailResponse,
    summary="출동 작전 상세 정보 조회 (건물 및 지휘관 정보 포함)"
)
def get_mission_detail(
    mission_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작전을 찾을 수 없습니다.")
    return mission


@router.put(
    "/{mission_id}/close",
    response_model=MissionResponse,
    summary="출동 작전 종료 (지휘관 전용)"
)
def close_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_clearance(2))
):
    mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작전을 찾을 수 없습니다.")

    mission.status = MissionStatus.COMPLETED
    mission.end_time = datetime.utcnow()

    # 디바이스 상태 업데이트
    if mission.device:
        mission.device.status = DeviceStatus.OFFLINE

    db.commit()
    db.refresh(mission)
    return mission


@router.get(
    "/{mission_id}/replay",
    response_model=MissionReplayResponse,
    summary="출동 사후 리플레이 데이터 조회 (궤적 시계열 및 탐지 이벤트 전체)",
    description="작전 종료 후 또는 분석 시 대원의 3D 이동 경로(sensor_logs)와 AI 탐지 사건(detection_events)을 시간순으로 정렬하여 반환합니다."
)
def get_mission_replay(
    mission_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작전을 찾을 수 없습니다.")

    # 복합 인덱스(idx_sensor_mission_time)를 활용한 빠른 시간순 정렬 조회
    trajectory = db.query(SensorLog).filter(
        SensorLog.mission_id == mission_id
    ).order_by(SensorLog.timestamp.asc()).all()

    # 복합 인덱스(idx_detection_mission_time) 활용
    events = db.query(DetectionEvent).filter(
        DetectionEvent.mission_id == mission_id
    ).order_by(DetectionEvent.timestamp.asc()).all()

    return MissionReplayResponse(
        mission=MissionResponse.model_validate(mission),
        total_trajectory_points=len(trajectory),
        total_detection_events=len(events),
        trajectory=[SensorTrajectoryItem.model_validate(t) for t in trajectory],
        events=[DetectionEventItem.model_validate(e) for e in events]
    )


@router.post(
    "/{mission_id}/telemetry",
    summary="[수집 계층] AI 보드 / 서버 프레임 분석 데이터 인입 API",
    description=(
        "프레임 분석 JSON(`timestamp`, `frame_id`, `detected_objects` [class, screen_box, description]) 및 "
        "센서 확장 데이터를 수신하여 Save-First 원칙에 따라 원본을 선저장하고, 관제 대시보드로 중계합니다. "
        "인증 헤더로 `X-Terminal-Id`(MDM 인가 단말) 또는 `X-Device-Id`/`X-Device-Key`를 사용합니다."
    )
)
async def ingest_telemetry(
    mission_id: int,
    packet: TacticalTelemetryIngest,
    device: Device = Depends(verify_edge_device),
    db: Session = Depends(get_db)
):
    mission = db.query(Mission).filter(
        Mission.mission_id == mission_id,
        Mission.status == MissionStatus.ACTIVE
    ).first()

    if not mission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 활성화된 작전 세션이 아닙니다."
        )

    assessment = await mission_manager.process_raw_telemetry(db=db, mission=mission, packet=packet)

    return {
        "status": "ACK",
        "mission_id": mission_id,
        "timestamp": packet.timestamp,
        "frame_id": packet.frame_id,
        "detected_objects_count": len(packet.detected_objects) if packet.detected_objects else 0,
        "assessment_id": assessment.assessment_id,
        "hazard_level": assessment.hazard_level.value
    }


@router.post(
    "/{mission_id}/telemetry/raw",
    summary="[수집 계층 - Save-First] 원시(Raw) 세션 프레임 JSON 및 센서 인입 API",
    description=(
        "현장 AI 보드/외장 SSD 세션에서 추출된 JSON(`timestamp`, `frame_id`, `detected_objects`) 또는 "
        "원시 센서 계측 데이터를 수신 즉시 `raw_telemetry_logs`에 최우선 선저장(Save-First)한 뒤, "
        "Gemma 3 4B 상황 판단 및 공간 좌표 정합을 수행합니다."
    )
)
async def ingest_raw_telemetry(
    mission_id: int,
    packet: RawTelemetryIngest,
    device: Device = Depends(verify_edge_device),
    db: Session = Depends(get_db)
):
    mission = db.query(Mission).filter(
        Mission.mission_id == mission_id,
        Mission.status == MissionStatus.ACTIVE
    ).first()

    if not mission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 활성화된 작전 세션이 아닙니다."
        )

    assessment = await mission_manager.process_raw_telemetry(db=db, mission=mission, packet=packet)

    return {
        "status": "SAVED_AND_ASSESSED",
        "mission_id": mission_id,
        "timestamp": packet.timestamp,
        "frame_id": packet.frame_id,
        "detected_objects_count": len(packet.detected_objects) if packet.detected_objects else 0,
        "assessment_id": assessment.assessment_id,
        "hazard_level": assessment.hazard_level.value
    }


@router.post(
    "/{mission_id}/telemetry/batch",
    summary="[수집 계층 - 외장 SSD 세션 일괄 이동] 다중 프레임(JSON/JSONL 배열) 일괄 등록 API",
    description=(
        "외장 SSD 세션 일괄 이동 규격에 따라, "
        "여러 프레임의 JSON 데이터 리스트를 한 번에 일괄 등록 및 Save-First 선저장합니다."
    )
)
async def ingest_batch_telemetry(
    mission_id: int,
    batch: List[RawTelemetryIngest],
    device: Device = Depends(verify_edge_device),
    db: Session = Depends(get_db)
):
    mission = db.query(Mission).filter(
        Mission.mission_id == mission_id,
        Mission.status == MissionStatus.ACTIVE
    ).first()

    if not mission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 활성화된 작전 세션이 아닙니다."
        )

    results = []
    for packet in batch:
        assessment = await mission_manager.process_raw_telemetry(db=db, mission=mission, packet=packet)
        results.append({
            "frame_id": packet.frame_id,
            "timestamp": packet.timestamp,
            "assessment_id": assessment.assessment_id,
            "hazard_level": assessment.hazard_level.value
        })

    return {
        "status": "BATCH_SAVED_AND_ASSESSED",
        "mission_id": mission_id,
        "total_ingested": len(results),
        "results": results
    }


@router.get(
    "/{mission_id}/map-state",
    response_model=MapMissionStateResponse,
    summary="[모바일 지도 앱용] 지도 초기화용 전체 레이어 데이터 조회",
    description="모바일 지도 앱이 화면을 열었을 때 대원의 현재 위치, 지나온 이동 궤적(Polyline), 지도 위에 띄울 AI 위험/구조자 POI 마커를 한 번에 가져옵니다."
)
def get_mission_map_state(
    mission_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작전을 찾을 수 없습니다.")

    # 1. 이동 궤적 조회 (sensor_logs 시간순)
    trajectory_logs = db.query(SensorLog).filter(
        SensorLog.mission_id == mission_id
    ).order_by(SensorLog.timestamp.asc()).all()

    trajectory = [Coordinate3D(x=t.pos_x, y=t.pos_y, z=t.pos_z) for t in trajectory_logs]
    current_loc = trajectory[-1] if trajectory else None
    current_yaw = trajectory_logs[-1].imu_yaw if trajectory_logs else None

    # 2. 활성 AI POI 마커 조회 (CRITICAL, WARNING 또는 인명 발견)
    ai_logs = db.query(AIAssessment).filter(
        AIAssessment.mission_id == mission_id
    ).order_by(AIAssessment.timestamp.asc()).all()

    active_markers = []
    for item in ai_logs:
        if item.hazard_level in (HazardLevel.CRITICAL, HazardLevel.WARNING) or item.human_detected:
            title_prefix = "🔥 화재 위험" if item.poi_type == POIType.FIRE_HOTSPOT else (
                "🚨 구조 대상자 발견" if item.human_detected else "⚠️ 현장 위험 주의"
            )
            active_markers.append(MapAlertMarker(
                mission_id=mission_id,
                assessment_id=item.assessment_id,
                timestamp=item.timestamp,
                hazard_level=item.hazard_level,
                poi_type=item.poi_type or POIType.OBSTACLE_HAZARD,
                title=f"[{item.hazard_level.value}] {title_prefix}",
                summary=item.situation_summary,
                action_recommendation=item.action_recommendation,
                coord=Coordinate3D(x=item.coord_x or 0.0, y=item.coord_y or 0.0, z=item.coord_z or 0.0),
                snapshot_url=f"/static/{item.snapshot_path}" if item.snapshot_path else None
            ))

    return MapMissionStateResponse(
        mission_id=mission.mission_id,
        title=mission.title,
        status=mission.status.value,
        building_id=mission.building_id,
        device_id=mission.device_id,
        current_location=current_loc,
        current_yaw=current_yaw,
        trajectory=trajectory,
        active_markers=active_markers
    )


@router.get(
    "/{mission_id}/ai-assessments",
    response_model=List[AIAssessmentResponse],
    summary="[모바일 지도 앱/상황실용] Gemma 3 4B 상황 판단 이력 전체 조회",
    description="작전 중 발생한 모든 AI 전술 상황 판단 로그(타임라인)를 시간 역순으로 조회합니다."
)
def get_mission_ai_assessments(
    mission_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    mission = db.query(Mission).filter(Mission.mission_id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작전을 찾을 수 없습니다.")

    assessments = db.query(AIAssessment).filter(
        AIAssessment.mission_id == mission_id
    ).order_by(AIAssessment.timestamp.desc()).limit(limit).all()

    results = []
    for a in assessments:
        results.append(AIAssessmentResponse(
            assessment_id=a.assessment_id,
            mission_id=a.mission_id,
            device_id=a.device_id,
            timestamp=a.timestamp,
            hazard_level=a.hazard_level,
            situation_summary=a.situation_summary,
            human_detected=a.human_detected,
            human_status=a.human_status,
            action_recommendation=a.action_recommendation,
            poi_type=a.poi_type,
            coord_x=a.coord_x,
            coord_y=a.coord_y,
            coord_z=a.coord_z,
            snapshot_url=f"/static/{a.snapshot_path}" if a.snapshot_path else None,
            created_at=a.created_at
        ))

    return results
