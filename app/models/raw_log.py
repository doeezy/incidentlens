from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawLog(Base):
    __tablename__ = "raw_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    module_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    class_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    method_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    log_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    error_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_keywords: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    domain_tags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    incident_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    match_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
