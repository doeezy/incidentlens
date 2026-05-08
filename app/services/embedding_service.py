from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.models.incident import Incident
from app.models.incident_embedding import IncidentEmbedding
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository


class EmbeddingService:
    """incident 변경 시 임베딩 텍스트 생성 및 벡터 저장(mock)."""

    def __init__(
        self,
        settings: Settings,
        embedding_repo: IncidentEmbeddingRepository,
    ) -> None:
        self._settings = settings
        self._embedding_repo = embedding_repo

    def build_embedding_text(self, incident: Incident) -> str:
        """이벤트 임베딩 텍스트 생성.

        - 프로젝트 이름, 모듈 이름, 클래스 이름, 상태, 에러 타입, 요약 메시지, 에러 메시지를 포함한다.
        - 에러 키워드와 도메인 태그를 추가한다.
        """
        parts = [
            f"project={incident.project_name}",
            f"module={incident.module_name or ''}",
            f"class={incident.class_name or ''}",
            f"status={incident.status}",
            f"error_type={incident.primary_error_type or ''}",
            f"summary={incident.primary_error_summary or ''}",
            f"message={incident.primary_error_message}",
        ]
        kws = incident.error_keywords or []
        tags = incident.domain_tags or []
        parts.append("keywords=" + ",".join(str(x) for x in kws))
        parts.append("tags=" + ",".join(str(x) for x in tags))
        return "\n".join(parts)

    def mock_vector(self, text: str) -> list[float]:
        """이벤트 임베딩 벡터 생성.

        - 이벤트 임베딩 텍스트를 SHA-256 해시하고, 해시 값을 설정된 차원 벡터로 변환한다.
        """
        dim = self._settings.embedding_dimension
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        repeat = (digest * ((dim // len(digest)) + 1))[:dim]
        return [(b / 255.0) * 2.0 - 1.0 for b in repeat]

    def upsert_for_incident(self, incident: Incident) -> IncidentEmbedding:
        """이벤트 임베딩 텍스트와 벡터 저장.

        - 이벤트 임베딩 텍스트를 생성하고, 이벤트 임베딩 벡터를 생성한다.
        - 이벤트 임베딩 텍스트와 벡터를 저장한다.
        """
        text = self.build_embedding_text(incident)
        vector = self.mock_vector(text)
        now = datetime.now(timezone.utc)
        source_ts = incident.updated_at
        if source_ts.tzinfo is None:
            source_ts = source_ts.replace(tzinfo=timezone.utc)

        # 기존 이벤트 임베딩 삭제
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
