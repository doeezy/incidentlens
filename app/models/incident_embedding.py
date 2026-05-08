from __future__ import annotations

import uuid
from datetime import datetime
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IncidentEmbedding(Base):
    __tablename__ = "incident_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_vector: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String, nullable=False)

    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
