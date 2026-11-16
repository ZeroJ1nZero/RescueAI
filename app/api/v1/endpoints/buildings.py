import os
import shutil
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_officer, require_clearance
from app.models.user import User, UserRole
from app.models.building import Building, SpatialMap
from app.schemas.building import (
    BuildingCreate,
    BuildingResponse,
    SpatialMapResponse,
)

router = APIRouter(prefix="/buildings", tags=["건물 및 3D 공간지도 관리"])


@router.get(
    "",
    response_model=List[BuildingResponse],
    summary="등록된 건물 및 3D 공간지도 메타데이터 목록 조회",
    description="통제실 안드로이드 앱에서 출동 대상 건물 선택을 위해 등록된 건물 및 층별 3D 공간지도(.glb) 정보를 조회합니다."
)
def get_buildings(
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    buildings = db.query(Building).all()
    return buildings


@router.get(
    "/{building_id}",
    response_model=BuildingResponse,
    summary="특정 건물 상세 및 3D 맵 정보 조회"
)
def get_building(
    building_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(get_current_officer)
):
    building = db.query(Building).filter(Building.building_id == building_id).first()
    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="요청한 건물을 찾을 수 없습니다."
        )
    return building


@router.post(
    "",
    response_model=BuildingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="신규 모의/실제 건물 등록 (보안 1급/관리관 전용)"
)
def create_building(
    req: BuildingCreate,
    db: Session = Depends(get_db),
    officer: User = Depends(require_clearance(1))
):
    building = Building(
        name=req.name,
        address=req.address,
        floors_count=req.floors_count,
        description=req.description
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


@router.post(
    "/{building_id}/maps/upload",
    response_model=SpatialMapResponse,
    status_code=status.HTTP_201_CREATED,
    summary="건물 층별 3D 공간지도(.glb) 파일 업로드 및 메타데이터 등록"
)
async def upload_3d_spatial_map(
    building_id: int,
    floor: int = Form(1),
    scale_factor: float = Form(1.0),
    origin_x: float = Form(0.0),
    origin_y: float = Form(0.0),
    origin_z: float = Form(0.0),
    file: UploadFile = File(..., description="포토그래메트리 구축 3D .glb 파일"),
    db: Session = Depends(get_db),
    officer: User = Depends(require_clearance(2))
):
    building = db.query(Building).filter(Building.building_id == building_id).first()
    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 건물이 존재하지 않습니다."
        )

    # 파일 확장자 검증
    if not file.filename.lower().endswith(".glb"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="3D 공간지도 파일은 .glb 포맷만 지원합니다."
        )

    save_dir = "static/maps"
    os.makedirs(save_dir, exist_ok=True)
    filename = f"building_{building_id}_floor_{floor}_{file.filename}"
    file_path = os.path.join(save_dir, filename).replace("\\", "/")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    spatial_map = SpatialMap(
        building_id=building_id,
        floor=floor,
        file_path=file_path,
        scale_factor=scale_factor,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_z=origin_z
    )
    db.add(spatial_map)
    db.commit()
    db.refresh(spatial_map)
    return spatial_map


@router.post(
    "/{building_id}/floorplans/upload",
    response_model=SpatialMapResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[모바일 지도 앱용] 층별 2D 평면도(PNG/JPG/SVG) 이미지 업로드 및 도면 규격 등록",
    description="모바일 지도 앱에서 건물 내부 진입 시 오버레이할 2D 층별 도면 이미지와 실제 가로/세로 길이(m)를 등록합니다."
)
async def upload_2d_floorplan(
    building_id: int,
    floor: int = Form(1),
    width_meter: float = Form(..., description="도면의 실제 가로 길이 (m)"),
    height_meter: float = Form(..., description="도면의 실제 세로 길이 (m)"),
    file: UploadFile = File(..., description="2D 평면도 도면 이미지 (PNG/JPG/SVG)"),
    db: Session = Depends(get_db),
    officer: User = Depends(require_clearance(2))
):
    building = db.query(Building).filter(Building.building_id == building_id).first()
    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 건물이 존재하지 않습니다."
        )

    save_dir = "static/maps/floorplans"
    os.makedirs(save_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1]
    filename = f"building_{building_id}_floor_{floor}_2d{ext}"
    file_path = os.path.join(save_dir, filename).replace("\\", "/")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 기존 해당 층의 맵이 있는지 확인
    existing_map = db.query(SpatialMap).filter(
        SpatialMap.building_id == building_id,
        SpatialMap.floor == floor
    ).first()

    if existing_map:
        existing_map.floor_plan_image = f"maps/floorplans/{filename}"
        existing_map.width_meter = width_meter
        existing_map.height_meter = height_meter
        db.commit()
        db.refresh(existing_map)
        return existing_map
    else:
        new_map = SpatialMap(
            building_id=building_id,
            floor=floor,
            file_path="",
            floor_plan_image=f"maps/floorplans/{filename}",
            width_meter=width_meter,
            height_meter=height_meter
        )
        db.add(new_map)
        db.commit()
        db.refresh(new_map)
        return new_map
