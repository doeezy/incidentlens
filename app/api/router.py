from fastapi import APIRouter

from app.api.routes import raw_logs, raw_tickets

api_router = APIRouter()
api_router.include_router(raw_logs.router)
api_router.include_router(raw_tickets.router)
