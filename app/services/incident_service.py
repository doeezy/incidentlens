from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.repositories.incident_repository import IncidentRepository
from app.repositories.raw_log_repository import RawLogRepository
from app.schemas.raw_log import RawLogCreate, RawLogIngestResponse, RawLogRead
from app.services.embedding_service import EmbeddingService
from app.services.incident_match_service import IncidentMatchService
from app.models.log_processing import LlmEnrichedLog, PatternParsedLog
from app.services.llm_log_enrichment_service import LlmLogEnrichmentService
from app.services.log_parse_service import LogParseService


class IncidentService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        parse_service: LogParseService,
        llm_enrichment_service: LlmLogEnrichmentService,
        match_service: IncidentMatchService,
        embedding_service: EmbeddingService,
        raw_log_repo: RawLogRepository,
        incident_repo: IncidentRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._parse_service = parse_service
        self._llm_enrichment_service = llm_enrichment_service
        self._match_service = match_service
        self._embedding_service = embedding_service
        self._raw_log_repo = raw_log_repo
        self._incident_repo = incident_repo

    def ingest_raw_log(self, payload: RawLogCreate) -> RawLogIngestResponse:
        project_name = payload.project_name.strip()
        # 규칙 기반 파싱
        parsed = self._parse_service.parse(payload.raw_message)
        # LLM 보정/생성
        enriched = self._llm_enrichment_service.enrich(
            project_name=project_name,
            raw_message=payload.raw_message,
            parsed=parsed,
        )

        # 이벤트 발생 시간
        occurred_at = payload.occurred_at

        # 규칙 기반 파싱 결과와 LLM 보정/생성 결과를 병합
        merged = self._merge_pattern_and_llm(parsed, enriched)
        raw_log = RawLog(
            id=payload.id or uuid.uuid4(),
            project_name=project_name,
            module_name=merged["module_name"],
            class_name=merged["class_name"],
            method_name=merged["method_name"],
            log_level=merged["log_level"],
            raw_message=payload.raw_message,
            stack_trace=merged["stack_trace"],
            error_type=merged["error_type"],
            error_message=merged["error_message"],
            normalized_summary=merged["normalized_summary"],
            extracted_keywords=merged["extracted_keywords"],
            domain_tags=merged["domain_tags"],
            occurred_at=occurred_at,
            incident_id=None,
            match_status=None,
        )

        # 이벤트 매칭 후보 탐색
        candidates = self._incident_repo.find_match_candidates(
            project_name=raw_log.project_name,
            occurred_at=occurred_at,
            candidate_days=self._settings.incident_match_candidate_days,
        )

        # 이벤트 매칭 후보 중 가장 점수가 높은 이벤트 선택
        best = self._match_service.pick_best(raw_log, candidates)
        # 이벤트 매칭 임계점
        threshold = self._settings.incident_match_threshold

        # 이벤트 매칭 여부 판단
        linked = best is not None and best.score >= threshold
        match_score = best.score if linked else None

        if linked:
            incident = self._merge_into_incident(incident=best.incident, log=raw_log)
            action = "linked"
        else:
            incident = self._create_incident_from_log(raw_log)
            action = "created"

        raw_log.incident_id = incident.id
        raw_log.match_status = "matched" if linked else "created"
        self._raw_log_repo.create(raw_log)

        self._embedding_service.upsert_for_incident(incident)
        self._session.commit()
        self._session.refresh(raw_log)
        self._session.refresh(incident)

        return RawLogIngestResponse(
            raw_log=RawLogRead.model_validate(raw_log),
            incident_id=incident.id,
            incident_action=action,
            match_score=match_score,
        )

    def _merge_pattern_and_llm(
        self,
        parsed: PatternParsedLog,
        enriched: LlmEnrichedLog | None,
    ) -> dict[str, object | None]:
        p = parsed
        # LLM 실패 시: rule-based 값만 사용
        if enriched is None:
            return {
                "module_name": p.module_name,
                "class_name": p.class_name,
                "method_name": p.method_name,
                "log_level": p.log_level,
                "stack_trace": p.stack_trace,
                "error_type": p.error_type,
                "error_message": p.error_message,
                "normalized_summary": None,
                "extracted_keywords": [],
                "domain_tags": [],
            }

        # 구조 필드는 parser_confidence가 high/medium일 때만 LLM 값을 사용
        # 단 모듈명, 클래스명, 함수명은 규칙 기반 파싱 값 우선 사용
        allow_struct_override = enriched.parser_confidence in {"high", "medium"}

        def pick_struct(field: str) -> object | None:
            llm_val = getattr(enriched, field)
            if llm_val is not None and allow_struct_override:
                return llm_val
            return getattr(p, field)

        return {
            "module_name": parsed.module_name or enriched.module_name,
            "class_name": parsed.class_name or enriched.class_name,
            "method_name": parsed.method_name or enriched.method_name,
            "log_level": pick_struct("log_level"),
            "stack_trace": pick_struct("stack_trace"),
            "error_type": pick_struct("error_type"),
            "error_message": pick_struct("error_message"),
            # normalized_summary/keywords/tags는 LLM 값 우선
            "normalized_summary": enriched.normalized_summary,
            "extracted_keywords": enriched.extracted_keywords or [],
            "domain_tags": enriched.domain_tags or [],
        }

    def _create_incident_from_log(self, log: RawLog) -> Incident:
        msg = log.error_message or log.raw_message
        summary = log.normalized_summary
        now = datetime.now(timezone.utc)
        incident = Incident(
            id=uuid.uuid4(),
            project_name=log.project_name,
            module_name=log.module_name,
            class_name=log.class_name,
            method_name=log.method_name,
            status="open",
            occurred_at=log.occurred_at,
            first_detected_at=log.occurred_at,
            last_seen_at=log.occurred_at,
            resolved_at=None,
            primary_error_type=log.error_type,
            primary_error_message=msg,
            primary_error_summary=summary,
            error_keywords=list(log.extracted_keywords or []),
            domain_tags=list(log.domain_tags or []),
            suspected_cause=None,
            root_cause_summary=None,
            resolution_summary=None,
            related_log_ids=[str(log.id)],
            related_ticket_ids=[],
            related_pr_ids=[],
            created_at=now,
            updated_at=now,
        )
        return self._incident_repo.create(incident)

    def _merge_into_incident(self, incident: Incident, log: RawLog) -> Incident:
        ids = list(incident.related_log_ids or [])
        sid = str(log.id)
        if sid not in ids:
            ids.append(sid)

        incident.related_log_ids = ids
        if incident.method_name is None and log.method_name is not None:
            incident.method_name = log.method_name
        prev_seen = incident.last_seen_at or incident.first_detected_at
        occurred_at = log.occurred_at
        incident.last_seen_at = max(prev_seen, occurred_at)
        incident.error_keywords = self._union_strings(
            incident.error_keywords,
            log.extracted_keywords,
        )
        incident.domain_tags = self._union_strings(
            incident.domain_tags, log.domain_tags
        )
        incident.updated_at = datetime.now(timezone.utc)
        return self._incident_repo.update(incident)

    def _union_strings(
        self,
        base: list[str] | None,
        extra: list[str] | None,
    ) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in list(base or []) + list(extra or []):
            key = str(item).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out
