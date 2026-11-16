import enum
from datetime import datetime
from typing import Optional, Any, Dict, TYPE_CHECKING
from sqlalchemy import String, Integer, BigInteger, Float, Boolean, Text, DateTime, Enum, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission
    from app.models.device import Device
    from app.models.raw_telemetry import RawTelemetryLog


class HazardLevel(str, enum.Enum):
    CRITICAL = "CRITICAL"  # 극도로 위험 (화재 최성기, 즉각 후퇴/방수 필요)
    WARNING = "WARNING"    # 위험 (고온 감지, 농연 발생, 인명 발견 등 주의)
    NORMAL = "NORMAL"      # 정상 (특이 위험 없음, 탐색 지속 가능)
    UNKNOWN = "UNKNOWN"    # 판단 불가


class POIType(str, enum.Enum):
    FIRE_HOTSPOT = "FIRE_HOTSPOT"        # 고온/발화 지점
    PERSON_RESCUE = "PERSON_RESCUE"      # 구조 대상자 발견 지점
    OBSTACLE_HAZARD = "OBSTACLE_HAZARD"  # 붕괴/장애물 위험 지점
    SAFE_PATH = "SAFE_PATH"              # 안전 탈출로


class AIAssessment(Base):
    """
    서버 AI(Gemma 3 4B 멀티모달 모델)가 실 계측값 + 영상 스냅샷을 종합 분석하여 
    판단한 전술 상황 평가 결과 및 모바일 지도 앱용 POI 마커 테이블
    """
    __tablename__ = "ai_assessments"

    assessment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"),
        nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"),
        nullable=False
    )
    raw_log_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_telemetry_logs.log_id", ondelete="SET NULL"),
        nullable=True
    )
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 판단 시점 (ms)
    
    # AI 상황 판단 핵심 결과
    hazard_level: Mapped[HazardLevel] = mapped_column(
        Enum(HazardLevel),
        default=HazardLevel.NORMAL,
        nullable=False
    )
    situation_summary: Mapped[str] = mapped_column(Text, nullable=False)  # 현장 상황 종합 요약
    human_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    human_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # "의식 불명 추정", "움직임 감지" 등
    action_recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 대원 전술 행동 권고
    
    # 지도 앱 표출용 POI 마커 메타데이터
    poi_type: Mapped[Optional[POIType]] = mapped_column(Enum(POIType), nullable=True)
    coord_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 2D/3D 지도 좌표 (m)
    coord_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coord_z: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Gemma 3 4B가 생성한 구조화된 원본 JSON 페이로드 전체
    assessment_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    
    # 분석에 사용된 영상 스냅샷 경로
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 연관 관계
    mission: Mapped["Mission"] = relationship("Mission", back_populates="ai_assessments")
    device: Mapped["Device"] = relationship("Device", back_populates="ai_assessments")
    raw_telemetry_log: Mapped[Optional["RawTelemetryLog"]] = relationship(
        "RawTelemetryLog",
        back_populates="ai_assessment"
    )

    __table_args__ = (
        Index("idx_ai_mission_time", "mission_id", "timestamp"),
        Index("idx_ai_hazard_level", "hazard_level"),
    )

    def __repr__(self) -> str:
        return f"<AIAssessment(id={self.assessment_id}, hazard={self.hazard_level}, summary='{self.situation_summary[:20]}...')>"
