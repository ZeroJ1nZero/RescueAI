from datetime import datetime
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AuthorizedTerminal(Base):
    """사전 승인된 현장 작전 전용 안드로이드 태블릿 단말기 (MDM 통제용)"""
    __tablename__ = "authorized_terminals"

    # 안드로이드 기기 고유 식별자 (Android UUID / 하드웨어 식별자)
    terminal_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    terminal_name: Mapped[str] = mapped_column(String(100), nullable=False)  # 예: 현장지휘 태블릿 1호
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # 분실/탈취 시 원격 차단
    registered_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuthorizedTerminal(id='{self.terminal_id}', name='{self.terminal_name}', active={self.is_active})>"
