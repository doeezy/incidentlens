from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncidentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceLog(BaseModel):
    id: uuid.UUID
    log_level: str | None
    raw_message: str
    error_type: str | None
    error_message: str | None
    normalized_summary: str | None
    occurred_at: datetime


class EvidenceTicket(BaseModel):
    id: uuid.UUID
    ticket_key: str
    title: str
    description: str | None
    status: str | None
    priority: str | None
    reporter: str | None
    assignee: str | None
    normalized_summary: str | None
    suspected_cause: str | None
    resolution_note: str | None
    ticket_created_at: datetime


class EvidencePr(BaseModel):
    id: uuid.UUID
    pr_key: str | None
    title: str
    description: str | None
    author: str | None
    status: str | None
    source_branch: str | None
    target_branch: str | None
    changed_files: list[str] | None
    diff_summary: str | None
    normalized_summary: str | None
    suspected_fix_for: str | None
    resolution_note: str | None
    merged_at: datetime | None


class IncidentSearchResult(BaseModel):
    incident_id: uuid.UUID
    score: float = Field(..., description="Vector similarity score. Higher is better.")
    distance: float = Field(..., description="pgvector cosine distance. Lower is better.")
    confidence: Literal["high", "medium", "low"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_reason: str
    project_name: str
    status: str
    first_detected_at: datetime
    last_seen_at: datetime | None
    resolved_at: datetime | None
    summary: str | None
    error_type: str | None
    error_message: str
    root_cause: str | None
    suspected_cause: str | None
    resolution: str | None
    keywords: list[str] | None
    domain_tags: list[str] | None
    evidence_logs: list[EvidenceLog] = Field(default_factory=list)
    evidence_tickets: list[EvidenceTicket] = Field(default_factory=list)
    evidence_prs: list[EvidencePr] = Field(default_factory=list)


class IncidentSearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[IncidentSearchResult]


class IncidentAgentRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class IncidentAgentResponse(BaseModel):
    question: str
    answer: str
    search_results: list[IncidentSearchResult]
