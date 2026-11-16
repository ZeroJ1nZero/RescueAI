from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class SpatialMapBase(BaseModel):
    floor: int = Field(default=1, description="건물 층수")
    file_path: Optional[str] = Field(None, description="저장된 3D .glb 파일 상대경로")
    floor_plan_image: Optional[str] = Field(None, description="모바일 지도 앱용 2D 평면도 이미지 상대경로 (PNG/SVG)")
    width_meter: Optional[float] = Field(None, description="2D 도면 실제 가로 길이 (미터)")
    height_meter: Optional[float] = Field(None, description="2D 도면 실제 세로 길이 (미터)")
    scale_factor: float = Field(default=1.0, description="공간지도 스케일 배율")
    origin_x: float = Field(default=0.0, description="x축 원점 오프셋 (미터)")
    origin_y: float = Field(default=0.0, description="y축 원점 오프셋 (미터)")
    origin_z: float = Field(default=0.0, description="z축 원점 오프셋 (미터)")


class SpatialMapCreate(SpatialMapBase):
    pass


class SpatialMapResponse(SpatialMapBase):
    map_id: int
    building_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class BuildingBase(BaseModel):
    name: str = Field(..., description="건물 명칭 (예: 소방방재 테스트빌딩 A동)")
    address: str = Field(..., description="건물 도로명 주소")
    floors_count: int = Field(default=1, description="지상/지하 전체 층수")
    description: Optional[str] = Field(None, description="건물 부가 설명 및 화재 특이사항")
    latitude: Optional[float] = Field(None, description="건물 실외 GPS 위도 (모바일 지도 앱 표출용)")
    longitude: Optional[float] = Field(None, description="건물 실외 GPS 경도 (모바일 지도 앱 표출용)")


class BuildingCreate(BuildingBase):
    pass


class BuildingResponse(BuildingBase):
    building_id: int
    created_at: datetime
    spatial_maps: List[SpatialMapResponse] = []

    class Config:
        from_attributes = True
