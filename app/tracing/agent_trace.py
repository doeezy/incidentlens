from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AgentTraceQuery(BaseModel):
    original_query: str
    rewritten_query: str | None
    intent: str | None
    retrieval_required: bool
    reason: str | None = None


class AgentTraceRetrievalCandidate(BaseModel):
    search_type: Literal["VECTOR", "BM25", "RRF"]
    incident_id: uuid.UUID
    rank: int
    raw_score: float | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    distance: float | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None


class AgentTraceRetrieval(BaseModel):
    vector_candidate_count: int = 0
    bm25_candidate_count: int = 0
    rrf_candidate_count: int = 0
    vector_candidates: list[AgentTraceRetrievalCandidate] = Field(default_factory=list)
    bm25_candidates: list[AgentTraceRetrievalCandidate] = Field(default_factory=list)
    rrf_candidates: list[AgentTraceRetrievalCandidate] = Field(default_factory=list)


class AgentTraceConfidenceEvaluation(BaseModel):
    incident_id: uuid.UUID
    confidence: Literal["high", "medium", "low"]
    confidence_score: float
    should_include: bool
    reason: str


class AgentTraceConfidence(BaseModel):
    batch_input_candidate_ids: list[uuid.UUID] = Field(default_factory=list)
    llm_evaluations: list[AgentTraceConfidenceEvaluation] = Field(default_factory=list)
    ranking: list[uuid.UUID] = Field(default_factory=list)
    selected_incident_id: uuid.UUID | None = None
    selected_incident_ids: list[uuid.UUID] = Field(default_factory=list)


class AgentTraceReference(BaseModel):
    source_type: Literal["incident", "log", "ticket", "pr"]
    source_id: uuid.UUID
    label: str | None = None
    summary: str | None = None


class AgentTraceAnswer(BaseModel):
    incident_id: uuid.UUID | None
    confidence: Literal["high", "medium", "low"] | None
    references: list[AgentTraceReference] = Field(default_factory=list)
    response: str


class AgentTraceTiming(BaseModel):
    query_analyzer_ms: float | None = None
    retrieval_ms: float | None = None
    confidence_ms: float | None = None
    answer_generation_ms: float | None = None
    total_ms: float | None = None


class AgentTrace(BaseModel):
    trace_id: uuid.UUID
    trace_version: str = "v1"
    request_id: str
    created_at: datetime
    query: AgentTraceQuery
    retrieval: AgentTraceRetrieval
    confidence: AgentTraceConfidence
    answer: AgentTraceAnswer
    timing: AgentTraceTiming
