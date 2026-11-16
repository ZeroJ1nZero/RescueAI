from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission


class Building(Base):
    __tablename__ = "buildings"

    building_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    floors_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 모바일 지도 앱용 건물 실외 GPS 좌표
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    spatial_maps: Mapped[List["SpatialMap"]] = relationship(
        "SpatialMap",
        back_populates="building",
        cascade="all, delete-orphan"
    )
    missions: Mapped[List["Mission"]] = relationship(
        "Mission",
        back_populates="building"
    )

    def __repr__(self) -> str:
        return f"<Building(id={self.building_id}, name='{self.name}')>"


class SpatialMap(Base):
    __tablename__ = "spatial_maps"

    map_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[int] = mapped_column(
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False
    )
    floor: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 저장된 .glb 파일 상대경로 (선택)
    
    # 모바일 지도 앱용 2D 평면도(Floor Plan) 이미지 및 메타데이터
    floor_plan_image: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 2D 도면 이미지 (PNG/SVG) 상대경로
    width_meter: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 도면의 실제 가로 길이 (미터)
    height_meter: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 도면의 실제 세로 길이 (미터)
    
    scale_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    origin_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    origin_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    origin_z: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    building: Mapped["Building"] = relationship("Building", back_populates="spatial_maps")

    def __repr__(self) -> str:
        return f"<SpatialMap(id={self.map_id}, building_id={self.building_id}, floor={self.floor}, file='{self.file_path}')>"
