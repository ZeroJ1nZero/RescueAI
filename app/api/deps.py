from typing import Optional, Generator
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.models.terminal import AuthorizedTerminal
from app.models.device import Device, DeviceStatus

# Bearer 토큰 추출기
security_scheme = HTTPBearer(auto_error=False)


def verify_terminal(
    x_terminal_id: Optional[str] = Header(None, alias="X-Terminal-Id"),
    db: Session = Depends(get_db)
) -> AuthorizedTerminal:
    """
    [1단계 보안 - MDM 통제]
    사전 인가된 현장 전용 안드로이드 단말기인지 검증합니다.
    """
    if not x_terminal_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비인가 단말기 접근: 'X-Terminal-Id' 보안 헤더가 누락되었습니다."
        )

    terminal = db.query(AuthorizedTerminal).filter(
        AuthorizedTerminal.terminal_id == x_terminal_id
    ).first()

    if not terminal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"미등록 단말기 접근 차단: 식별자({x_terminal_id})가 인가 단말기 목록에 없습니다."
        )

    if not terminal.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="단말기 차단 상태: 분실 또는 보안 조치로 원격 비활성화된 단말기입니다."
        )

    return terminal


def get_current_officer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    [2/3단계 보안 - 공무원 신원 검증]
    JWT 보안 토큰을 검증하여 현재 로그인된 소방/군 공무원 객체를 반환합니다.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 실패: 보안 토큰(Bearer Token)이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 작전 보안 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    service_number: Optional[str] = payload.get("sub") or payload.get("service_number")
    if not service_number:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="보안 토큰 내 공무원 식별번호(service_number)가 누락되었습니다."
        )

    officer = db.query(User).filter(User.service_number == service_number).first()
    if not officer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="등록되지 않은 공무원 정보입니다."
        )

    if not officer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 공무원 계정은 현재 직무정지 또는 비활성화 상태입니다."
        )

    return officer


def require_clearance(min_clearance: int):
    """
    [보안 인가 등급 통제]
    지정된 보안 등급(숫자가 낮을수록 상위: 1급 > 2급 > 3급) 이상의 공무원만 통과시킵니다.
    """
    def clearance_checker(officer: User = Depends(get_current_officer)) -> User:
        if officer.security_clearance > min_clearance:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"보안 인가 등급 부족: 필요 등급({min_clearance}급 이상) 대비 현재 공무원 등급({officer.security_clearance}급)이 낮습니다."
            )
        return officer
    return clearance_checker


def require_role(*allowed_roles: UserRole):
    """
    [직책(Role) 기반 통제]
    지정된 직무 역할(ADMIN, COMMANDER, OPERATOR 등)에 해당하는지 검증합니다.
    """
    def role_checker(officer: User = Depends(get_current_officer)) -> User:
        if officer.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"작전 권한 없음: {officer.role.value} 직책은 본 기능에 대한 접근 권한이 없습니다."
            )
        return officer
    return role_checker


def verify_edge_device(
    x_terminal_id: Optional[str] = Header(None, alias="X-Terminal-Id"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    x_device_key: Optional[str] = Header(None, alias="X-Device-Key"),
    db: Session = Depends(get_db)
) -> Device:
    """
    [수집 계층 인가 검증 - 발표자료 7페이지]
    1. MDM 인가 단말 검증 (X-Terminal-Id): 사전에 등록된 합법적 장치 식별 정보 대조
    2. 엣지 보드 API Key 검증 (X-Device-Id / X-Device-Key): 기존 엣지 장비 호환 지원
    """
    # 1) X-Device-Id 및 X-Device-Key가 제공된 경우
    if x_device_id and x_device_key:
        device = db.query(Device).filter(Device.device_id == x_device_id).first()
        if not device or device.api_key != x_device_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="미등록 또는 비인가 엣지 디바이스입니다."
            )
        return device

    # 2) 발표자료 7페이지 규격: MDM 인가 단말 검증 (X-Terminal-Id)
    if x_terminal_id:
        terminal = db.query(AuthorizedTerminal).filter(
            AuthorizedTerminal.terminal_id == x_terminal_id
        ).first()
        # AuthorizedTerminal 또는 Device 테이블에서 식별자 대조
        if terminal:
            if not terminal.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="단말기 차단 상태: 분실 또는 보안 조치로 원격 비활성화된 단말기입니다."
                )
            # 연결된 기본 엣지 디바이스 반환 (없으면 첫 번째 등록 디바이스 또는 자동 매핑)
            device = db.query(Device).filter(Device.device_id == (x_device_id or "EDGE-CAM-01")).first()
            if not device:
                device = db.query(Device).first()
            if device:
                return device

        # 혹시 X-Terminal-Id에 EDGE-CAM-01 같은 device_id를 넣은 경우 허용
        device_by_tid = db.query(Device).filter(Device.device_id == x_terminal_id).first()
        if device_by_tid:
            return device_by_tid

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"미등록 단말기 접근 차단: 식별자({x_terminal_id})가 인가 단말기 목록에 없습니다."
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="수집 계층 인가 실패: 'X-Terminal-Id' (MDM 인가 단말) 또는 'X-Device-Id'/'X-Device-Key' 헤더가 필요합니다."
    )

