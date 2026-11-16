import enum
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.mission import Mission


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"          # 시스템 및 보안 관리관
    COMMANDER = "COMMANDER"  # 현장 지휘관 (출동 지휘, 작전 통제)
    OPERATOR = "OPERATOR"    # 현장 구조대원 (모니터링)


class User(Base):
    """소방/군 공무원 사용자 모델"""
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 소방공무원 식별번호 / 군번 (예: FIRE-2024-0102)
    service_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(50), nullable=False)
    rank: Mapped[str] = mapped_column(String(30), nullable=False)           # 계급: 소방령, 소방경, 소방위 등
    department: Mapped[str] = mapped_column(String(100), nullable=False)    # 소속: 서울종로소방서 현장대응단
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        default=UserRole.OPERATOR,
        nullable=False
    )
    security_clearance: Mapped[int] = mapped_column(Integer, default=2, nullable=False)  # 1: 최고, 2: 일반작전, 3: 기본
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)       # 공무원증 보안 PIN 해시 (bcrypt)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # 지휘관으로서 관제한 출동 작전 관계
    commanded_missions: Mapped[List["Mission"]] = relationship(
        "Mission",
        back_populates="commander"
    )

    def __repr__(self) -> str:
        return f"<User({self.service_number} {self.rank} {self.full_name}, role='{self.role}', clearance={self.security_clearance})>"
