from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawPr(Base):
    """PR/MR 수집용 테이블 스키마(현 단계에서는 참조 전용)."""

    __tablename__ = "raw_prs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pr_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    repository_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    module_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    class_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    method_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_branch: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_branch: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    changed_files: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    commit_messages: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    normalized_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_keywords: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    domain_tags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    suspected_fix_for: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    pr_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    pr_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    merged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    incident_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    related_ticket_keys: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    match_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
