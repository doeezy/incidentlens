from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    module_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    class_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    method_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    primary_error_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    primary_error_message: Mapped[str] = mapped_column(Text, nullable=False)
    primary_error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    error_keywords: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    domain_tags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    suspected_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    related_log_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    related_ticket_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    related_pr_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
