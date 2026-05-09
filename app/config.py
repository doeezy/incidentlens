from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 앱 패키지(app/) 기준으로 프로젝트 루트의 .env 를 고정 로드 (실행 cwd 와 무관)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/incidentlens"
    )

    incident_match_threshold: float = 60.0
    ticket_match_threshold: float = 65.0
    incident_match_candidate_days: int = 2
    # 매칭 판단 시간 창(분). 현재는 "1시간 이내 + 핵심 필드 완전 동일" 기준으로만 사용한다.
    incident_time_window_minutes_full: int = 60
    # (호환성 유지용) 기존 partial 설정값. 현재 매칭 로직에서는 full과 동일하게 취급한다.
    incident_time_window_minutes_partial: int = 60

    embedding_dimension: int = 1536
    embedding_model_name: str = "text-embedding-3-small"
    embedding_rules_version: str = "v1"

    openai_api_key: str | None = None
    llm_model_name: str = "gpt-4.1-mini"

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _empty_openai_key_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
