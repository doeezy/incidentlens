from fastapi import APIRouter

from app.api.routes import incidents, raw_logs, raw_prs, raw_tickets

api_router = APIRouter()
api_router.include_router(incidents.router)
api_router.include_router(raw_logs.router)
api_router.include_router(raw_prs.router)
api_router.include_router(raw_tickets.router)
# TODO: 프로젝트 목록 조회 API 필요
