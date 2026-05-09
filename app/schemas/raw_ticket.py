from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RawTicketCreate(BaseModel):
    project_name: str = Field(..., min_length=1)
    repository_name: str | None = None
    ticket_key: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    reporter: str | None = None
    ticket_created_at: datetime


class RawTicketRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    ticket_key: str
    project_name: str
    repository_name: str | None
    module_name: str | None
    class_name: str | None
    method_name: str | None
    error_type: str | None
    title: str
    description: str | None
    status: str | None
    priority: str | None
    assignee: str | None
    reporter: str | None
    normalized_summary: str | None
    extracted_keywords: list[str] | None
    domain_tags: list[str] | None
    suspected_cause: str | None
    resolution_note: str | None
    ticket_created_at: datetime
    incident_id: uuid.UUID | None
    match_status: str | None
    created_at: datetime
    updated_at: datetime


class RawTicketIngestResponse(BaseModel):
    raw_ticket: RawTicketRead
    incident_id: uuid.UUID | None = Field(
        None,
        description="매칭된 incident id. 없으면 null.",
    )
    incident_action: str = Field(
        ...,
        description="'linked' 또는 'unmatched'",
    )
    rule_score: float | None = Field(
        None,
        description="선택된 후보의 규칙 기반 점수(최대 95).",
    )
    semantic_score: float | None = Field(
        None,
        description="선택된 후보의 LLM semantic 점수(0~1).",
    )
    final_score: float | None = Field(
        None,
        description="0.6*rule_score + 0.4*(semantic*100).",
    )
