from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

QueryType = Literal[
    "exact_error",
    "error_type_only",
    "natural_language",
    "cause_keyword",
    "ambiguous",
]


class RetrievalQuery(BaseModel):
    query_id: str = Field(..., min_length=1)
    query_text: str = Field(..., min_length=1)
    query_type: QueryType
    expected_incident_id: str = Field(..., min_length=1)
    project_name: str = Field(..., min_length=1)
    note: str | None = None
    generated_by_llm: bool = True
    reviewed_by_human: bool = False
    review_note: str | None = None
    excluded: bool = False
    exclude_reason: str | None = None


class RetrievalDataset(BaseModel):
    dataset_name: str = "retrieval_queries"
    status: Literal["candidate", "frozen"]
    generated_at: str | None = None
    frozen_at: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    review_policy: list[str] = Field(default_factory=list)
    queries: list[RetrievalQuery] = Field(default_factory=list)


class LlmGroundTruthItem(BaseModel):
    query_id: str
    expected_incident_id: str
    expected_root_cause: str | None = None
    expected_fix: str | None = None
    required_evidence: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    reviewed_by_human: bool = False
    review_note: str | None = None


class LlmGroundTruth(BaseModel):
    dataset_name: str = "llm_ground_truth"
    items: list[LlmGroundTruthItem] = Field(default_factory=list)
