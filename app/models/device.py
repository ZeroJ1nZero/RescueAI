import enum
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission
    from app.models.detection import DetectionEvent
    from app.models.sensor import SensorLog
    from app.models.raw_telemetry import RawTelemetryLog
    from app.models.ai_assessment import AIAssessment


class DeviceStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus),
        default=DeviceStatus.OFFLINE,
        nullable=False
    )
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    missions: Mapped[List["Mission"]] = relationship("Mission", back_populates="device")
    detection_events: Mapped[List["DetectionEvent"]] = relationship("DetectionEvent", back_populates="device")
    sensor_logs: Mapped[List["SensorLog"]] = relationship("SensorLog", back_populates="device")
    raw_telemetry_logs: Mapped[List["RawTelemetryLog"]] = relationship("RawTelemetryLog", back_populates="device")
    ai_assessments: Mapped[List["AIAssessment"]] = relationship("AIAssessment", back_populates="device")

    def __repr__(self) -> str:
        return f"<Device(id='{self.device_id}', name='{self.device_name}', status='{self.status}')>"
