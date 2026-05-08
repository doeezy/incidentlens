from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.incident_embedding import IncidentEmbedding


class IncidentEmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def delete_by_incident_id(self, incident_id: uuid.UUID) -> None:
        stmt = delete(IncidentEmbedding).where(
            IncidentEmbedding.incident_id == incident_id
        )
        self._session.execute(stmt)

    def create(self, embedding: IncidentEmbedding) -> IncidentEmbedding:
        self._session.add(embedding)
        self._session.flush()
        return embedding

    def get_latest_for_incident(
        self, incident_id: uuid.UUID
    ) -> IncidentEmbedding | None:
        stmt = (
            select(IncidentEmbedding)
            .where(IncidentEmbedding.incident_id == incident_id)
            .order_by(IncidentEmbedding.updated_at.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()
