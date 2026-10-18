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
    title="연암소방대 (Yeonam Fire Brigade) 관제 백엔드 API",
    description="영상 객체 분석 기반 실내 공간지도 관제 시스템 백엔드 API",
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
        "system": "연암소방대 관제 백엔드 시스템",
        "status": "OPERATIONAL",
        "environment": settings.ENVIRONMENT,
        "security_level": "GOVERNMENT_TACTICAL"
    }


@app.get("/health", tags=["시스템 상태"])
def health_check():
    return {"status": "healthy"}
