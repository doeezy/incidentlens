from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.incident import Incident
from app.models.log_processing import LlmEnrichedTicket
from app.models.raw_ticket import RawTicket
from app.repositories.incident_repository import IncidentRepository
from app.repositories.raw_ticket_repository import RawTicketRepository
from app.schemas.raw_ticket import (
    RawTicketCreate,
    RawTicketIngestResponse,
    RawTicketRead,
)
from app.services.embedding import EmbeddingService
from app.services.ticket.enrich_service import LlmTicketEnrichmentService
from app.services.ticket.parse_service import TicketParseService
from app.services.ticket.rule_match_service import TicketIncidentRuleMatchService
from app.utils.strings import union_unique_strings

logger = logging.getLogger(__name__)

_PRIORITY_LABEL = re.compile(
    r"^priority\s*(?::|/|=|-)\s*(?P<value>.+)$",
    re.IGNORECASE,
)


class RawTicketService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        parse_service: TicketParseService,
        llm_ticket_service: LlmTicketEnrichmentService,
        rule_match_service: TicketIncidentRuleMatchService,
        embedding_service: EmbeddingService,
        raw_ticket_repo: RawTicketRepository,
        incident_repo: IncidentRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._parse_service = parse_service
        self._llm_ticket_service = llm_ticket_service
        self._rule_match_service = rule_match_service
        self._embedding_service = embedding_service
        self._raw_ticket_repo = raw_ticket_repo
        self._incident_repo = incident_repo

    def ingest_raw_ticket(self, payload: RawTicketCreate) -> RawTicketIngestResponse:
        project_name = payload.project_name.strip()
        repository_name = payload.repository_name.strip()
        issue = payload.issue
        title = issue.title.strip()
        # 규칙 기반 error_type 파싱
        parsed = self._parse_service.parse(title, issue.body)
        # LLM 추론/생성/검증
        enriched = self._llm_ticket_service.enrich(
            project_name=project_name,
            title=title,
            description=issue.body,
            parsed=parsed,
        )
        if enriched is None:
            enriched = LlmEnrichedTicket(
                normalized_summary=title,
                extracted_keywords=[],
                domain_tags=[],
                suspected_cause=None,
                resolution_note=None,
            )

        ticket_id = uuid.uuid4()

        raw_ticket = RawTicket(
            id=ticket_id,
            ticket_key=f"{repository_name}#{issue.number}",
            project_name=project_name,
            repository_name=repository_name,
            error_type=parsed.error_type or enriched.error_type,
            title=title,
            description=issue.body,
            status=self._strip_opt(issue.state),
            priority=self._extract_priority(payload),
            assignee=(
                self._strip_opt(issue.assignees[0].login)
                if issue.assignees
                else None
            ),
            reporter=self._strip_opt(issue.user.login),
            normalized_summary=enriched.normalized_summary,
            extracted_keywords=list(enriched.extracted_keywords or []),
            domain_tags=list(enriched.domain_tags or []),
            suspected_cause=enriched.suspected_cause,
            resolution_note=enriched.resolution_note,
            ticket_created_at=issue.created_at,
            ticket_updated_at=issue.updated_at,
            ticket_closed_at=issue.closed_at,
            incident_id=None,
            match_status=None,
        )

        # project_name이 같으면서 상태가 open, investigating인 incident +
        # 최초 에러 발생 시간이 티켓 생성일시보다 이전인 incident만 조회
        candidates = self._incident_repo.find_ticket_match_candidates(
            project_name, issue.created_at
        )
        logger.debug(
            "ticket_match candidates project=%s count=%s ticket_key=%s raw_ticket_id=%s",
            project_name,
            len(candidates),
            raw_ticket.ticket_key,
            raw_ticket.id,
        )

        # 규칙 기반 매칭 순위 계산
        ranked = self._rule_match_service.rank(
            raw_ticket=raw_ticket,
            incidents=candidates,
        )

        # top5 후보만 추출
        top5 = ranked[:5]
        # LLM 추론/생성/검증
        ticket_payload = self._ticket_payload_for_llm(
            raw_ticket=raw_ticket,
        )
        # 티켓 title/description이 각 incident의 normalized_summary와 동일한 장애를 설명하는지 평가
        semantic_map = self._llm_ticket_service.evaluate_top_candidates(
            ticket_payload=ticket_payload,
            candidates=top5,
        )
        logger.debug(
            "ticket_match semantic_map ticket_key=%s top5_ids=%s evaluated_ids=%s",
            raw_ticket.ticket_key,
            [str(r.incident.id) for r in top5],
            [str(u) for u in semantic_map.keys()],
        )

        # 최적 매칭 후보 선택
        top5_ids = {r.incident.id for r in top5}
        threshold = float(self._settings.ticket_match_threshold)

        best_incident: Incident | None = None
        best_final: float | None = None
        best_rule: float | None = None
        best_semantic: float | None = None

        for rs in ranked:
            ev = (
                semantic_map.get(rs.incident.id) if rs.incident.id in top5_ids else None
            )
            sem_ok = float(ev.semantic_score) if ev is not None else 0.0

            # 최종 점수 계산
            final = 0.6 * float(rs.rule_score) + 0.4 * (sem_ok * 100)

            logger.debug("===== final icident_id: %s, score: %s", rs.incident.id, final)
            # 최종 점수가 임계값 이상이고 현재 최적 점수보다 높으면 업데이트
            if final >= threshold and (best_final is None or final > best_final):
                best_final = final
                best_incident = rs.incident
                best_rule = float(rs.rule_score)
                best_semantic = sem_ok

        if best_incident is not None:
            raw_ticket.incident_id = best_incident.id
            raw_ticket.match_status = "matched"
            # 티켓 정보를 incident에 병합
            self._merge_ticket_into_incident(best_incident, raw_ticket)
        else:
            raw_ticket.match_status = "unmatched"

        # 티켓 저장
        self._raw_ticket_repo.create(raw_ticket)
        # incident embedding 업데이트
        if best_incident is not None:
            self._embedding_service.upsert_for_incident(best_incident)

        self._session.commit()
        self._session.refresh(raw_ticket)
        if best_incident is not None:
            self._session.refresh(best_incident)

        return RawTicketIngestResponse(
            raw_ticket=RawTicketRead.model_validate(raw_ticket),
            incident_id=best_incident.id if best_incident else None,
            incident_action="linked" if best_incident else "unmatched",
            rule_score=best_rule,
            semantic_score=best_semantic,
            final_score=best_final,
        )

    def _strip_opt(self, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    def _extract_priority(self, payload: RawTicketCreate) -> str | None:
        for label in payload.issue.labels:
            name = label.name.strip()
            match = _PRIORITY_LABEL.fullmatch(name)
            if match:
                return match.group("value").strip() or None
            if "priority" in name.lower():
                return name
        return None

    def _ticket_payload_for_llm(
        self,
        *,
        raw_ticket: RawTicket,
    ) -> dict:
        return {
            "project_name": raw_ticket.project_name,
            "repository_name": raw_ticket.repository_name,
            "ticket_key": raw_ticket.ticket_key,
            "title": raw_ticket.title,
            "description": raw_ticket.description,
            "status": raw_ticket.status,
            "priority": raw_ticket.priority,
            "assignee": raw_ticket.assignee,
            "reporter": raw_ticket.reporter,
            "ticket_created_at": (
                raw_ticket.ticket_created_at.isoformat()
                if raw_ticket.ticket_created_at is not None
                else None
            ),
            "error_type": raw_ticket.error_type,
            "normalized_summary": raw_ticket.normalized_summary,
            "extracted_keywords": raw_ticket.extracted_keywords,
            "domain_tags": raw_ticket.domain_tags,
            "suspected_cause": raw_ticket.suspected_cause,
            "resolution_note": raw_ticket.resolution_note,
        }

    def _merge_ticket_into_incident(
        self,
        incident: Incident,
        ticket: RawTicket,
    ) -> Incident:
        ids = list(incident.related_ticket_ids or [])
        sid = str(ticket.id)
        if sid not in ids:
            ids.append(sid)
        incident.related_ticket_ids = ids

        if ticket.suspected_cause:
            incident.suspected_cause = ticket.suspected_cause
        if ticket.resolution_note:
            incident.resolution_summary = ticket.resolution_note

        incident.error_keywords = union_unique_strings(
            incident.error_keywords,
            ticket.extracted_keywords,
        )
        incident.domain_tags = union_unique_strings(
            incident.domain_tags,
            ticket.domain_tags,
        )
        incident.status = "investigating"
        incident.updated_at = datetime.now(timezone.utc)
        return self._incident_repo.update(incident)
