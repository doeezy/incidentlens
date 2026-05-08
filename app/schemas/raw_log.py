from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RawLogCreate(BaseModel):
    id: uuid.UUID | None = Field(
        default=None,
        description="클라이언트가 지정하면 해당 UUID로 raw_log id를 저장합니다.",
    )
    project_name: str = Field(..., min_length=1)
    raw_message: str = Field(..., min_length=1)
    occurred_at: datetime


class RawLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_name: str
    module_name: str | None
    class_name: str | None
    method_name: str | None
    log_level: str | None
    raw_message: str
    stack_trace: str | None
    error_type: str | None
    error_message: str | None
    normalized_summary: str | None
    extracted_keywords: list[str] | None
    domain_tags: list[str] | None
    occurred_at: datetime
    ingested_at: datetime
    incident_id: uuid.UUID | None
    match_status: str | None


class IncidentSummaryRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_name: str
    status: str
    primary_error_type: str | None
    primary_error_summary: str | None


class RawLogIngestResponse(BaseModel):
    raw_log: RawLogRead
    incident_id: uuid.UUID
    incident_action: str = Field(
        ...,
        description="'created' 또는 'linked'",
    )
    match_score: float | None = Field(
        None,
        description="기존 incident 연결 시 부여된 규칙 기반 점수",
    )
