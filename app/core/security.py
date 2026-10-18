from datetime import datetime, timedelta
from typing import Optional, Any, Dict
import bcrypt
from jose import jwt, JWTError
from app.core.config import settings


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """공무원증 보안 PIN 일치 여부 검증 (bcrypt 기반)"""
    try:
        return bcrypt.checkpw(plain_pin.encode("utf-8"), hashed_pin.encode("utf-8"))
    except Exception:
        return False


def get_pin_hash(pin: str) -> str:
    """공무원증 보안 PIN bcrypt 해싱 생성"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pin.encode("utf-8"), salt).decode("utf-8")


# 일반 호환용 함수
verify_password = verify_pin
get_password_hash = get_pin_hash


def create_tactical_access_token(claims: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    공무원/작전용 보안 JWT 발급
    Claims: service_number, full_name, rank, department, role, security_clearance, terminal_id
    """
    to_encode = claims.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """JWT 토큰 디코딩 및 유효성 검증"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None
