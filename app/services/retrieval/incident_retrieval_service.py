from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm import OpenAiChatClient
from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository
from app.schemas.incident_search import (
    EvidenceLog,
    EvidencePr,
    EvidenceTicket,
    IncidentSearchResponse,
    IncidentSearchResult,
)
from app.services.embedding import EmbeddingService
from app.utils.json_text import extract_first_json_object
from app.utils.text_preview import preview_truncated

logger = logging.getLogger(__name__)

_HIGH_CONFIDENCE_SCORE = 0.65
_MIN_SCORE = 0.45
_MIN_LLM_CONFIDENCE_SCORE = 0.5


class _ConfidenceEval(BaseModel):
    confidence: Literal["high", "medium", "low"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reason: str


class IncidentRetrievalService:
    """Vector retrieval for incidents and their connected evidence.

    This service is intentionally independent from FastAPI routers so it can be
    reused by a LangGraph agent.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings,
        embedding_service: EmbeddingService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._embedding_service = embedding_service
        self._llm = OpenAiChatClient(settings)

    @classmethod
    def from_session(
        cls,
        *,
        session: Session,
        settings: Settings,
    ) -> "IncidentRetrievalService":
        embedding_repo = IncidentEmbeddingRepository(session)
        return cls(
            session=session,
            settings=settings,
            embedding_service=EmbeddingService(settings, embedding_repo),
        )

    # TODO: 파라미터로 project_name 추가 필요
    # _search_embeddings에서 project_name where 조건 추가 필요
    def search(self, *, query: str, top_k: int = 5) -> IncidentSearchResponse:
        logging.info(f"========== search query, top_k: {query}, {top_k}")
        clean_query = query.strip()
        # 사용자 질문 임베딩
        query_vector = self._embedding_service.embed_text(clean_query)
        # 임베딩 벡터 검색
        hits = self._search_embeddings(query_vector=query_vector, limit=top_k)
        logging.info(f"========== search_embeddings hits: {hits}")

        # TODO: 추후 고도화시 BM25 키워드 검색 추가하여 RRF 기반 Hybrid Search 적용 예정

        # 임베딩 벡터 거리 기준으로 정렬한 결과에서 incident_id 추출
        incident_ids = [incident_id for incident_id, _distance in hits]
        # incident_id 목록으로 incidents 조회
        incidents = self._load_incidents(incident_ids)
        # incident_id 목록으로 logs 조회
        evidence_logs = self._load_logs(incident_ids)
        # incident_id 목록으로 tickets 조회
        evidence_tickets = self._load_tickets(incident_ids)
        # incident_id 목록으로 prs 조회
        evidence_prs = self._load_prs(incident_ids)

        results: list[IncidentSearchResult] = []

        for incident_id, distance in hits:
            incident = incidents.get(incident_id)
            if incident is None:
                continue

            # 스코어링
            score = max(0.0, 1.0 - float(distance))

            # confidence 평가
            confidence_eval = self._evaluate_confidence(
                query=clean_query,
                score=score,
                incident=incident,
            )
            if confidence_eval is None:
                continue

            results.append(
                IncidentSearchResult(
                    incident_id=incident.id,
                    score=score,
                    distance=float(distance),
                    confidence=confidence_eval.confidence,
                    confidence_score=confidence_eval.confidence_score,
                    confidence_reason=confidence_eval.reason,
                    project_name=incident.project_name,
                    status=incident.status,
                    first_detected_at=incident.first_detected_at,
                    last_seen_at=incident.last_seen_at,
                    resolved_at=incident.resolved_at,
                    summary=incident.primary_error_summary,
                    error_type=incident.primary_error_type,
                    error_message=incident.primary_error_message,
                    root_cause=incident.root_cause_summary,
                    suspected_cause=incident.suspected_cause,
                    resolution=incident.resolution_summary,
                    keywords=list(incident.error_keywords or []),
                    domain_tags=list(incident.domain_tags or []),
                    evidence_logs=evidence_logs.get(incident.id, []),
                    evidence_tickets=evidence_tickets.get(incident.id, []),
                    evidence_prs=evidence_prs.get(incident.id, []),
                )
            )

        return IncidentSearchResponse(query=clean_query, top_k=top_k, results=results)

    def _evaluate_confidence(
        self,
        *,
        query: str,
        score: float,
        incident: Incident,
    ) -> _ConfidenceEval | None:
        # score가 high 기준 이상이면 LLM 평가 제외
        if score >= _HIGH_CONFIDENCE_SCORE:
            return _ConfidenceEval(
                confidence="high",
                confidence_score=score,
                reason="vector score가 high 기준 이상입니다.",
            )

        if score < _MIN_SCORE:
            return None

        # score가 medium 기준 이하면 LLM 평가
        llm_eval = self._evaluate_confidence_with_llm(
            query=query,
            incident=incident,
        )
        # LLM 평가 실패 시 medium 반환
        if llm_eval is None:
            return _ConfidenceEval(
                confidence="medium",
                confidence_score=score,
                reason=(
                    "LLM confidence 평가에 실패하여 vector score 기준으로 "
                    "애매한 구간 결과를 medium으로 반환합니다."
                ),
            )

        if llm_eval.confidence_score < _MIN_LLM_CONFIDENCE_SCORE:
            return None
        return llm_eval

    def _evaluate_confidence_with_llm(
        self,
        *,
        query: str,
        incident: Incident,
    ) -> _ConfidenceEval | None:
        if not self._settings.openai_api_key:
            return None

        prompt = {
            "task": "incident_confidence_eval",
            "instruction": (
                "사용자 query와 검색된 incident가 같은 문제를 가리킬 가능성만 평가한다. "
                "추측하거나 새로운 원인을 만들어 평가하지 않는다."
                "query에 없는 세부 정보가 incident에 있다는 이유만으로 낮게 평가하지 않는다."
            ),
            # confidence 평가 기준
            "confidence_criteria": {
                "high": "query에 incident의 error_type, class, keyword, symptom이 직접 겹침",
                "medium": "도메인/증상은 유사하지만 핵심 에러가 부족함",
                "low": "관련 근거 부족 또는 다른 문제",
            },
            "query": query,
            "incident": {
                "summary": incident.primary_error_summary,
                "error_type": incident.primary_error_type,
                "error_message": incident.primary_error_message,
                "keywords": incident.error_keywords,
                "domain_tags": incident.domain_tags,
                "resolution": incident.resolution_summary,
            },
            "output_contract": {
                "must_be_json_only": True,
                "format": {
                    "confidence": "high | medium | low",
                    "confidence_score": "0.0~1.0 float",
                    "reason": "한국어 한 문장",
                },
            },
        }
        messages = [
            {
                "role": "developer",
                "content": (
                    "Return JSON only. "
                    "Evaluate only whether the user query and retrieved incident "
                    "likely refer to the same problem. Do not infer missing causes, "
                    "fixes, or hidden context."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]

        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=_ConfidenceEval,
            schema_name="IncidentConfidenceEval",
        )
        parsed = self._parse_confidence_eval(text, allow_json_extraction=False)
        if parsed is not None:
            return parsed

        text = self._llm.chat_json_object(messages)
        return self._parse_confidence_eval(text, allow_json_extraction=True)

    def _parse_confidence_eval(
        self,
        text: str | None,
        *,
        allow_json_extraction: bool,
    ) -> _ConfidenceEval | None:
        if not text or not text.strip():
            return None
        try:
            json_text = (
                extract_first_json_object(text) if allow_json_extraction else text
            )
            return _ConfidenceEval.model_validate_json(json_text or text)
        except ValidationError as exc:
            logger.debug(
                "confidence eval parse failed: %s preview=%s",
                exc,
                preview_truncated(text, 800),
            )
            return None

    def _search_embeddings(
        self,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[tuple[uuid.UUID, float]]:
        if limit <= 0 or not query_vector:
            return []

        # 현재는 데이터가 적으므로 exact scan을 사용
        # TODO: incident_embeddings 데이터가 충분히 많아지면 HNSW 인덱스 적용 예정
        query_vector_str = "[" + ",".join(map(str, query_vector)) + "]"
        rows = self._session.execute(
            text("""
                SELECT incident_id, distance
                FROM (
                    SELECT
                        incident_id,
                        embedding_vector <=> CAST(:query_vector AS vector) AS distance
                    FROM incident_embeddings
                ) AS exact_search
                ORDER BY distance + 0
                LIMIT :limit
            """),
            {
                "query_vector": query_vector_str,
                "limit": limit,
            },
        ).all()

        return [(incident_id, float(distance)) for incident_id, distance in rows]

    def _load_incidents(
        self, incident_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Incident]:
        if not incident_ids:
            return {}
        stmt = select(Incident).where(Incident.id.in_(incident_ids))
        return {incident.id: incident for incident in self._session.scalars(stmt).all()}

    def _load_logs(
        self,
        incident_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[EvidenceLog]]:
        if not incident_ids:
            return {}
        stmt = (
            select(RawLog)
            .where(RawLog.incident_id.in_(incident_ids))
            .order_by(RawLog.occurred_at.asc())
        )
        grouped: dict[uuid.UUID, list[EvidenceLog]] = defaultdict(list)
        for log in self._session.scalars(stmt).all():
            if log.incident_id is None:
                continue
            grouped[log.incident_id].append(
                EvidenceLog(
                    id=log.id,
                    log_level=log.log_level,
                    raw_message=log.raw_message,
                    error_type=log.error_type,
                    error_message=log.error_message,
                    normalized_summary=log.normalized_summary,
                    occurred_at=log.occurred_at,
                )
            )
        return grouped

    def _load_tickets(
        self,
        incident_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[EvidenceTicket]]:
        if not incident_ids:
            return {}
        stmt = (
            select(RawTicket)
            .where(RawTicket.incident_id.in_(incident_ids))
            .order_by(RawTicket.ticket_created_at.asc())
        )
        grouped: dict[uuid.UUID, list[EvidenceTicket]] = defaultdict(list)
        for ticket in self._session.scalars(stmt).all():
            if ticket.incident_id is None:
                continue
            grouped[ticket.incident_id].append(
                EvidenceTicket(
                    id=ticket.id,
                    ticket_key=ticket.ticket_key,
                    title=ticket.title,
                    description=ticket.description,
                    status=ticket.status,
                    priority=ticket.priority,
                    reporter=ticket.reporter,
                    assignee=ticket.assignee,
                    normalized_summary=ticket.normalized_summary,
                    suspected_cause=ticket.suspected_cause,
                    resolution_note=ticket.resolution_note,
                    ticket_created_at=ticket.ticket_created_at,
                )
            )
        return grouped

    def _load_prs(
        self,
        incident_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[EvidencePr]]:
        if not incident_ids:
            return {}
        stmt = (
            select(RawPr)
            .where(RawPr.incident_id.in_(incident_ids))
            .order_by(RawPr.pr_created_at.asc())
        )
        grouped: dict[uuid.UUID, list[EvidencePr]] = defaultdict(list)
        for pr in self._session.scalars(stmt).all():
            if pr.incident_id is None:
                continue
            grouped[pr.incident_id].append(
                EvidencePr(
                    id=pr.id,
                    pr_key=pr.pr_key,
                    title=pr.title,
                    description=pr.description,
                    author=pr.author,
                    status=pr.status,
                    source_branch=pr.source_branch,
                    target_branch=pr.target_branch,
                    changed_files=list(pr.changed_files or []),
                    diff_summary=pr.diff_summary,
                    normalized_summary=pr.normalized_summary,
                    suspected_fix_for=pr.suspected_fix_for,
                    resolution_note=pr.resolution_note,
                    merged_at=pr.merged_at,
                )
            )
        return grouped
