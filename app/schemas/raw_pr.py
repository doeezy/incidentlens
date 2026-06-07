from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GitHubPrUser(BaseModel):
    login: str = Field(..., min_length=1)


class GitHubPrBranch(BaseModel):
    ref: str = Field(..., min_length=1)


class GitHubPullRequest(BaseModel):
    number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    body: str | None = None
    state: str
    merged: bool
    user: GitHubPrUser
    head: GitHubPrBranch
    base: GitHubPrBranch
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None = None


class GitHubPrFile(BaseModel):
    filename: str = Field(..., min_length=1)
    status: str
    patch: str | None = None


class GitHubPrCommit(BaseModel):
    message: str = Field(..., min_length=1)


class RawPrCreate(BaseModel):
    project_name: str = Field(..., min_length=1)
    repository_name: str = Field(..., min_length=1)
    pull_request: GitHubPullRequest
    files: list[GitHubPrFile] = Field(default_factory=list)
    commits: list[GitHubPrCommit] = Field(default_factory=list)


class RawPrRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    pr_key: str | None
    project_name: str
    repository_name: str | None
    title: str
    description: str | None
    author: str | None
    status: str | None
    source_branch: str | None
    target_branch: str | None
    changed_files: list[str] | None
    diff_summary: str | None
    commit_messages: list[str] | None
    normalized_summary: str | None
    extracted_keywords: list[str] | None
    domain_tags: list[str] | None
    suspected_fix_for: str | None
    resolution_note: str | None
    related_ticket_keys: list[str] | None
    pr_created_at: datetime
    pr_updated_at: datetime | None
    merged_at: datetime | None
    incident_id: uuid.UUID | None
    match_status: str | None
    created_at: datetime
    updated_at: datetime


class RawPrIngestResponse(BaseModel):
    raw_pr: RawPrRead
    incident_id: uuid.UUID | None = Field(
        None,
        description="관련 ticket을 통해 매칭된 incident id. 없으면 null.",
    )
    incident_action: str = Field(
        ...,
        description="'linked' 또는 'unmatched'",
    )
