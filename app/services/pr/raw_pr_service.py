from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.raw_pr import RawPr
from app.repositories.incident_repository import IncidentRepository
from app.repositories.raw_pr_repository import RawPrRepository
from app.repositories.raw_ticket_repository import RawTicketRepository
from app.schemas.raw_pr import RawPrCreate, RawPrIngestResponse, RawPrRead
from app.services.embedding import EmbeddingService
from app.services.pr.enrich_service import LlmPrEnrichmentService
from app.services.pr.parse_service import RawPrParseService
from app.utils.strings import union_unique_strings


class RawPrService:
    def __init__(
        self,
        session: Session,
        parse_service: RawPrParseService,
        llm_enrichment_service: LlmPrEnrichmentService,
        embedding_service: EmbeddingService,
        raw_pr_repo: RawPrRepository,
        raw_ticket_repo: RawTicketRepository,
        incident_repo: IncidentRepository,
    ) -> None:
        self._session = session
        self._parse_service = parse_service
        self._llm_enrichment_service = llm_enrichment_service
        self._embedding_service = embedding_service
        self._raw_pr_repo = raw_pr_repo
        self._raw_ticket_repo = raw_ticket_repo
        self._incident_repo = incident_repo

    def ingest_raw_pr(self, payload: RawPrCreate) -> RawPrIngestResponse:
        project_name = payload.project_name.strip()
        repository_name = payload.repository_name.strip()
        pull_request = payload.pull_request
        parsed = self._parse_service.parse(payload)

        raw_pr = RawPr(
            id=uuid.uuid4(),
            pr_key=f"{repository_name}#{pull_request.number}",
            project_name=project_name,
            repository_name=repository_name,
            title=pull_request.title.strip(),
            description=pull_request.body,
            author=pull_request.user.login.strip(),
            status="merged" if pull_request.merged else pull_request.state.strip(),
            source_branch=pull_request.head.ref.strip(),
            target_branch=pull_request.base.ref.strip(),
            changed_files=parsed.changed_files,
            diff_summary=parsed.diff_summary,
            commit_messages=parsed.commit_messages,
            related_ticket_keys=parsed.related_ticket_keys,
            pr_created_at=pull_request.created_at,
            pr_updated_at=pull_request.updated_at,
            merged_at=pull_request.merged_at,
            incident_id=None,
            match_status=None,
        )

        incident = self._find_incident_from_related_tickets(
            project_name=project_name,
            related_ticket_keys=parsed.related_ticket_keys,
        )
        if incident is not None:
            raw_pr.incident_id = incident.id
            raw_pr.match_status = "matched"
            enriched = self._llm_enrichment_service.enrich(
                payload=payload,
                parsed=parsed,
                incident=incident,
            )
            if enriched is not None:
                raw_pr.normalized_summary = enriched.normalized_summary
                raw_pr.extracted_keywords = enriched.extracted_keywords
                raw_pr.domain_tags = enriched.domain_tags
                raw_pr.suspected_fix_for = enriched.suspected_fix_for
                raw_pr.resolution_note = enriched.resolution_note
                raw_pr.diff_summary = enriched.diff_summary or raw_pr.diff_summary
        else:
            raw_pr.match_status = "unmatched"

        self._raw_pr_repo.create(raw_pr)
        if incident is not None:
            self._merge_pr_into_incident(incident=incident, raw_pr=raw_pr)
            self._embedding_service.upsert_for_incident(incident)

        self._session.commit()
        self._session.refresh(raw_pr)
        if incident is not None:
            self._session.refresh(incident)

        return RawPrIngestResponse(
            raw_pr=RawPrRead.model_validate(raw_pr),
            incident_id=incident.id if incident else None,
            incident_action="linked" if incident else "unmatched",
        )

    def _find_incident_from_related_tickets(
        self,
        *,
        project_name: str,
        related_ticket_keys: list[str],
    ) -> Incident | None:
        tickets = self._raw_ticket_repo.find_by_ticket_keys(
            project_name=project_name,
            ticket_keys=related_ticket_keys,
        )
        for key in related_ticket_keys:
            for ticket in tickets:
                if ticket.ticket_key != key or ticket.incident_id is None:
                    continue
                incident = self._incident_repo.get_by_id(ticket.incident_id)
                if incident is not None:
                    return incident
        return None

    def _merge_pr_into_incident(
        self,
        *,
        incident: Incident,
        raw_pr: RawPr,
    ) -> Incident:
        related_pr_ids = list(incident.related_pr_ids or [])
        raw_pr_id = str(raw_pr.id)
        if raw_pr_id not in related_pr_ids:
            related_pr_ids.append(raw_pr_id)
        incident.related_pr_ids = related_pr_ids

        incident.error_keywords = union_unique_strings(
            incident.error_keywords,
            raw_pr.extracted_keywords,
        )
        incident.domain_tags = union_unique_strings(
            incident.domain_tags,
            raw_pr.domain_tags,
        )
        incident.resolution_summary = (
            raw_pr.resolution_note
            or raw_pr.diff_summary
            or raw_pr.description
            or raw_pr.title
        )
        if raw_pr.status == "merged":
            incident.status = "resolved"
            incident.resolved_at = raw_pr.merged_at
        incident.updated_at = datetime.now(timezone.utc)
        return self._incident_repo.update(incident)
