import enum
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.device import Device
    from app.models.building import Building
    from app.models.detection import DetectionEvent
    from app.models.sensor import SensorLog
    from app.models.raw_telemetry import RawTelemetryLog
    from app.models.ai_assessment import AIAssessment


class MissionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Mission(Base):
    __tablename__ = "missions"

    mission_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[int] = mapped_column(
        ForeignKey("buildings.building_id"),
        nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"),
        nullable=False
    )
    commander_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus),
        default=MissionStatus.ACTIVE,
        nullable=False
    )

    # 연관 관계
    building: Mapped["Building"] = relationship("Building", back_populates="missions")
    device: Mapped["Device"] = relationship("Device", back_populates="missions")
    commander: Mapped["User"] = relationship("User", back_populates="commanded_missions")
    detection_events: Mapped[List["DetectionEvent"]] = relationship(
        "DetectionEvent",
        back_populates="mission",
        cascade="all, delete-orphan"
    )
    sensor_logs: Mapped[List["SensorLog"]] = relationship(
        "SensorLog",
        back_populates="mission",
        cascade="all, delete-orphan"
    )
    raw_telemetry_logs: Mapped[List["RawTelemetryLog"]] = relationship(
        "RawTelemetryLog",
        back_populates="mission",
        cascade="all, delete-orphan"
    )
    ai_assessments: Mapped[List["AIAssessment"]] = relationship(
        "AIAssessment",
        back_populates="mission",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Mission(id={self.mission_id}, title='{self.title}', status='{self.status}')>"
