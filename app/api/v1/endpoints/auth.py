from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_pin, create_tactical_access_token
from app.models.user import User
from app.models.terminal import AuthorizedTerminal
from app.schemas.auth import (
    OfficerLoginRequest,
    OfficerInfo,
    TacticalTokenResponse,
    TerminalVerifyResponse,
)
from app.api.deps import verify_terminal, get_current_officer

router = APIRouter(prefix="/auth", tags=["소방/군 공무원 보안 인증"])


@router.post(
    "/login",
    response_model=TacticalTokenResponse,
    summary="소방/군 공무원 3중 보안 로그인",
    description="사전 인가된 태블릿 단말기(X-Terminal-Id 헤더)에서 공무원 식별번호와 보안 PIN을 입력하여 보안 JWT를 발급받습니다."
)
def login_officer(
    req: OfficerLoginRequest,
    terminal: AuthorizedTerminal = Depends(verify_terminal),
    db: Session = Depends(get_db)
):
    # 1. 공무원 계정 조회
    officer = db.query(User).filter(User.service_number == req.service_number).first()
    if not officer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 실패: 등록되지 않은 소방/군 공무원 식별번호입니다."
        )

    # 2. 계정 활성화 여부 확인
    if not officer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="접근 거부: 비활성화 또는 직무정지 처리된 공무원 계정입니다."
        )

    # 3. 공무원증 보안 PIN 검증
    if not verify_pin(req.pin, officer.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 실패: 공무원증 보안 PIN 번호가 일치하지 않습니다."
        )

    # 4. 공무원 클레임 구성 및 보안 JWT 발급
    expires_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    claims = {
        "sub": officer.service_number,
        "full_name": officer.full_name,
        "rank": officer.rank,
        "department": officer.department,
        "role": officer.role.value,
        "security_clearance": officer.security_clearance,
        "terminal_id": terminal.terminal_id,
    }

    access_token = create_tactical_access_token(
        claims=claims,
        expires_delta=timedelta(minutes=expires_minutes)
    )

    return TacticalTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_minutes * 60,
        officer=OfficerInfo.model_validate(officer),
        terminal_id=terminal.terminal_id
    )


@router.get(
    "/me",
    response_model=OfficerInfo,
    summary="현재 로그인된 공무원 신원 및 보안인가등급 확인",
    description="Bearer 보안 토큰을 통해 현재 접속 중인 공무원의 계급, 소속, 보안인가등급을 조회합니다."
)
def get_my_profile(
    current_officer: User = Depends(get_current_officer)
):
    return OfficerInfo.model_validate(current_officer)


@router.get(
    "/terminal/check",
    response_model=TerminalVerifyResponse,
    summary="안드로이드 태블릿 단말기 인가 상태 점검",
    description="단말기 부팅 시 X-Terminal-Id 헤더를 보내 현재 태블릿이 정상 인가된 작전 장비인지 점검합니다."
)
def check_terminal_status(
    terminal: AuthorizedTerminal = Depends(verify_terminal)
):
    return TerminalVerifyResponse(
        terminal_id=terminal.terminal_id,
        terminal_name=terminal.terminal_name,
        is_authorized=terminal.is_active
    )
