from pydantic import BaseModel, Field
from typing import Optional
from app.models.user import UserRole


class OfficerLoginRequest(BaseModel):
    """소방/군 공무원 로그인 요청 DTO"""
    service_number: str = Field(..., description="소방공무원 식별번호/군번 (예: FIRE-CMD-101)", examples=["FIRE-CMD-101"])
    pin: str = Field(..., min_length=4, max_length=20, description="공무원증 보안 PIN", examples=["123456"])


class OfficerInfo(BaseModel):
    """소방공무원 프로필 정보 DTO"""
    user_id: int
    service_number: str
    full_name: str
    rank: str
    department: str
    role: UserRole
    security_clearance: int

    class Config:
        from_attributes = True


class TacticalTokenResponse(BaseModel):
    """보안 인가 JWT 토큰 발급 응답 DTO"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="토큰 유효 시간(초)")
    officer: OfficerInfo
    terminal_id: str


class TerminalVerifyResponse(BaseModel):
    """단말기 인가 상태 확인 응답 DTO"""
    terminal_id: str
    terminal_name: Optional[str] = None
    is_authorized: bool
