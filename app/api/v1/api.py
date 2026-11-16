from fastapi import APIRouter
from app.api.v1.endpoints import auth, buildings, missions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(buildings.router)
api_router.include_router(missions.router)
