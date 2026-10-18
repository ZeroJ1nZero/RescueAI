import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.v1.api import api_router

# 3D 맵 파일 및 스냅샷 저장 디렉토리 자동 생성
os.makedirs("static/maps", exist_ok=True)
os.makedirs("static/snapshots", exist_ok=True)

app = FastAPI(
    title="RescueAI Tactical Backend System",
    description="저조도·열화상 센서 융합 및 실시간 3D 소방 공간지도 관제 백엔드 API (소방/군 공무원 보안 규격 적용)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 설정 (현장 안드로이드 태블릿 및 로컬 통제망 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 (.glb 3D 맵 파일, 현장 스냅샷)
app.mount("/static", StaticFiles(directory="static"), name="static")

# API v1 라우터 등록
app.include_router(api_router)


@app.get("/", tags=["시스템 상태"])
def root():
    return {
        "system": "RescueAI Tactical Backend",
        "status": "OPERATIONAL",
        "environment": settings.ENVIRONMENT,
        "security_level": "GOVERNMENT_TACTICAL"
    }


@app.get("/health", tags=["시스템 상태"])
def health_check():
    return {"status": "healthy"}
