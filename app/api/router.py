from fastapi import APIRouter

from app.api.routes import raw_logs

api_router = APIRouter()
api_router.include_router(raw_logs.router)
