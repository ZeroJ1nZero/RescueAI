from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, BigInteger, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission
    from app.models.device import Device


class SensorLog(Base):
    __tablename__ = "sensor_logs"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"),
        nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"),
        nullable=False
    )
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Unix Epoch ms
    pos_x: Mapped[float] = mapped_column(Float, nullable=False)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False)
    pos_z: Mapped[float] = mapped_column(Float, nullable=False)
    imu_yaw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ambient_temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    mission: Mapped["Mission"] = relationship("Mission", back_populates="sensor_logs")
    device: Mapped["Device"] = relationship("Device", back_populates="sensor_logs")

    # 복합 인덱스 (이동 궤적 리플레이 조회 최적화)
    __table_args__ = (
        Index("idx_sensor_mission_time", "mission_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<SensorLog(id={self.log_id}, mission={self.mission_id}, pos=({self.pos_x}, {self.pos_y}, {self.pos_z}))>"
