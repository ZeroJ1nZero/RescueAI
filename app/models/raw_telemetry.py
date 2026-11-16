from datetime import datetime
from typing import Optional, Any, Dict, TYPE_CHECKING
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission
    from app.models.device import Device
    from app.models.ai_assessment import AIAssessment


class RawTelemetryLog(Base):
    """
    현장 엣지 보드로부터 수신한 원시 계측 및 센서 JSON 데이터를 
    가공 전에 있는 그대로 먼저 영속화(Save First)하는 테이블
    """
    __tablename__ = "raw_telemetry_logs"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"),
        nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"),
        nullable=False
    )
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Unix Epoch ms (측정 시점)
    
    # 엣지에서 전송한 원본 JSON 페이로드 (센서값, IMU, 온도, 거리 등 계측값 일체)
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    
    # 영상 프레임/스냅샷 이미지 파일 저장 경로 (서버 정적 디렉토리에 저장된 경로)
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # 서버 가공 및 AI(Gemma 3 4B) 분석 완료 여부
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    mission: Mapped["Mission"] = relationship("Mission", back_populates="raw_telemetry_logs")
    device: Mapped["Device"] = relationship("Device", back_populates="raw_telemetry_logs")
    ai_assessment: Mapped[Optional["AIAssessment"]] = relationship(
        "AIAssessment",
        back_populates="raw_telemetry_log",
        uselist=False
    )

    __table_args__ = (
        Index("idx_raw_mission_time", "mission_id", "timestamp"),
        Index("idx_raw_processed", "is_processed"),
    )

    def __repr__(self) -> str:
        return f"<RawTelemetryLog(id={self.log_id}, mission_id={self.mission_id}, processed={self.is_processed})>"
