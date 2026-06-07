from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GitHubIssueUser(BaseModel):
    login: str = Field(..., min_length=1)


class GitHubIssueLabel(BaseModel):
    name: str = Field(..., min_length=1)


class GitHubIssue(BaseModel):
    number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    body: str | None = None
    state: str
    user: GitHubIssueUser
    assignees: list[GitHubIssueUser] = Field(default_factory=list)
    labels: list[GitHubIssueLabel] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class RawTicketCreate(BaseModel):
    project_name: str = Field(..., min_length=1)
    repository_name: str = Field(..., min_length=1)
    issue: GitHubIssue


class RawTicketRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    ticket_key: str
    project_name: str
    repository_name: str | None
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
    ticket_updated_at: datetime | None
    ticket_closed_at: datetime | None
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
        description="선택된 후보의 규칙 기반 점수(최대 100).",
    )
    semantic_score: float | None = Field(
        None,
        description="선택된 후보의 LLM semantic 점수(0~1).",
    )
    final_score: float | None = Field(
        None,
        description="0.6*rule_score + 0.4*(semantic*100).",
    )
