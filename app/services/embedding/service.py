from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.models.incident import Incident
from app.models.incident_embedding import IncidentEmbedding
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository

logger = logging.getLogger(__name__)

_MAX_EMBED_INPUT_CHARS = 24000


class EmbeddingService:
    """incident 변경 시 임베딩 텍스트 생성 및 벡터 저장."""

    def __init__(
        self,
        settings: Settings,
        embedding_repo: IncidentEmbeddingRepository,
    ) -> None:
        self._settings = settings
        self._embedding_repo = embedding_repo

    def build_embedding_text(self, incident: Incident) -> str:
        parts = [
            f"project={incident.project_name}",
            f"module={incident.module_name or ''}",
            f"class={incident.class_name or ''}",
            f"status={incident.status}",
            f"error_type={incident.primary_error_type or ''}",
            f"summary={incident.primary_error_summary or ''}",
            f"message={incident.primary_error_message}",
            f"cause={incident.suspected_cause or ''}",
            f"root_cause={incident.root_cause_summary or ''}",
            f"resolution={incident.resolution_summary or ''}",
        ]
        kws = incident.error_keywords or []
        tags = incident.domain_tags or []
        parts.append("keywords=" + ",".join(str(x) for x in kws))
        parts.append("tags=" + ",".join(str(x) for x in tags))
        return "\n".join(parts)

    def _truncate_for_embed(self, text: str) -> str:
        if len(text) <= _MAX_EMBED_INPUT_CHARS:
            return text
        return text[:_MAX_EMBED_INPUT_CHARS]

    def _mock_vector(self, text: str) -> list[float]:
        dim = self._settings.embedding_dimension
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        repeat = (digest * ((dim // len(digest)) + 1))[:dim]
        return [(b / 255.0) * 2.0 - 1.0 for b in repeat]

    def embed_text(self, text: str) -> list[float]:
        text = self._truncate_for_embed(text)
        dim = self._settings.embedding_dimension
        model = self._settings.embedding_model_name

        if not self._settings.openai_api_key:
            logger.warning("OPENAI_API_KEY 없음: 임베딩은 mock 벡터로 저장됩니다.")
            return self._mock_vector(text)

        try:
            from openai import OpenAI
        except Exception as e:
            logger.warning("OpenAI 임포트 실패, mock 임베딩 사용: %s", e)
            return self._mock_vector(text)

        client = OpenAI(api_key=self._settings.openai_api_key)
        try:
            kwargs: dict = {
                "model": model,
                "input": text,
            }
            if model.startswith("text-embedding-3"):
                kwargs["dimensions"] = dim

            response = client.embeddings.create(**kwargs)
            vec = list(response.data[0].embedding)
        except Exception as e:
            logger.warning(
                "OpenAI 임베딩 호출 실패, mock 사용: %s",
                e,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            return self._mock_vector(text)

        if len(vec) != dim:
            logger.warning(
                "임베딩 차원 불일치: 기대 %s, 실제 %s — mock으로 대체",
                dim,
                len(vec),
            )
            return self._mock_vector(text)

        return vec

    def upsert_for_incident(self, incident: Incident) -> IncidentEmbedding:
        text = self.build_embedding_text(incident)
        vector = self.embed_text(text)
        now = datetime.now(timezone.utc)
        source_ts = incident.updated_at
        if source_ts.tzinfo is None:
            source_ts = source_ts.replace(tzinfo=timezone.utc)

        self._embedding_repo.delete_by_incident_id(incident.id)

        row = IncidentEmbedding(
            id=uuid.uuid4(),
            incident_id=incident.id,
            embedding_text=text,
            embedding_vector=vector,
            embedding_model=self._settings.embedding_model_name,
            embedding_version=self._settings.embedding_rules_version,
            source_updated_at=source_ts,
            created_at=now,
            updated_at=now,
        )
        return self._embedding_repo.create(row)
