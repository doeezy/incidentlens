import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.database import init_db


def _configure_logging() -> None:
    # uvicorn이 자체 로깅 설정을 적용하는 경우가 있어도,
    # 애플리케이션 로거(app.*) DEBUG가 콘솔에 보이도록 기본 설정을 보장한다.
    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("app").setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    init_db()
    yield


app = FastAPI(title="IncidentLens Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)
