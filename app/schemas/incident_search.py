from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncidentSearchRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class IncidentBm25SearchRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class IncidentBm25SearchResult(BaseModel):
    incident_id: uuid.UUID
    bm25_score: float
    rank: int


class IncidentBm25SearchResponse(BaseModel):
    project_name: str
    query: str
    limit: int
    results: list[IncidentBm25SearchResult]


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
    score: float = Field(..., description="Final retrieval score. Higher is better.")
    distance: float | None = Field(
        default=None,
        description="pgvector cosine distance. Lower is better.",
    )
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rrf_rank: int | None = None
    vector_score: float | None = Field(
        default=None,
        description="Vector similarity score. Higher is better.",
    )
    bm25_score: float | None = None
    rrf_score: float
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
    project_name: str | None
    results: list[IncidentSearchResult]


class IncidentAgentRequest(BaseModel):
    conversation_id: uuid.UUID
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class IncidentDirectAnswerRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class IncidentAgentResponse(BaseModel):
    question: str
    project_name: str | None
    intent: Literal[
        "ROOT_CAUSE",
        "RESOLUTION",
        "SIMILAR_CASE",
        "SUMMARY",
        "OUT_OF_SCOPE",
    ]
    retrieval_required: bool
    rewritten_query: str | None
    analysis_reason: str
    answer: str
    search_results: list[IncidentSearchResult]


class ProjectListResponse(BaseModel):
    projects: list[str]
