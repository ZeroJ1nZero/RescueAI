import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, BigInteger, Float, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission
    from app.models.device import Device


class EventType(str, enum.Enum):
    PERSON = "PERSON"
    FIRE = "FIRE"
    HAZARD = "HAZARD"


class DetectionEvent(Base):
    __tablename__ = "detection_events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"),
        nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"),
        nullable=False
    )
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Unix Epoch ms
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType),
        nullable=False
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coord_x: Mapped[float] = mapped_column(Float, nullable=False)
    coord_y: Mapped[float] = mapped_column(Float, nullable=False)
    coord_z: Mapped[float] = mapped_column(Float, nullable=False)
    max_temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    mission: Mapped["Mission"] = relationship("Mission", back_populates="detection_events")
    device: Mapped["Device"] = relationship("Device", back_populates="detection_events")

    # 복합 인덱스 (작전별 타임라인 조회 최적화)
    __table_args__ = (
        Index("idx_detection_mission_time", "mission_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<DetectionEvent(id={self.event_id}, type='{self.event_type}', pos=({self.coord_x}, {self.coord_y}, {self.coord_z}))>"
