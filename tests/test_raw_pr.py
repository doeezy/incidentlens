from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from app.models.incident import Incident
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from app.schemas.raw_pr import RawPrCreate
from app.services.pr.enrich_service import LlmEnrichedPr
from app.services.pr.parse_service import RawPrParseService
from app.services.pr.raw_pr_service import RawPrService


def _payload() -> RawPrCreate:
    return RawPrCreate.model_validate(
        {
            "project_name": "data-portal",
            "repository_name": "auth-service",
            "pull_request": {
                "number": 45,
                "title": "fix: 로그인 ClassNotFoundException 수정",
                "body": "Fixes #101 and owner/payments#202",
                "state": "closed",
                "merged": True,
                "user": {"login": "kim"},
                "head": {"ref": "fix/auth-class-not-found-#404"},
                "base": {"ref": "main"},
                "created_at": "2026-05-07T11:00:00Z",
                "updated_at": "2026-05-07T11:20:00Z",
                "merged_at": "2026-05-07T11:20:00Z",
            },
            "files": [
                {
                    "filename": "src/main/java/com/example/auth/AuthService.java",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n-old\n+new",
                },
                {
                    "filename": "build.gradle",
                    "status": "modified",
                    "patch": "@@ -3,0 +4 @@\n+implementation 'jwt'",
                },
            ],
            "commits": [
                {"message": "fix: add jwt dependency for #101"},
                {"message": "follow-up repo-tools#303"},
            ],
        }
    )


class RawPrParseServiceTest(unittest.TestCase):
    def test_pr_fields_are_preprocessed(self) -> None:
        parsed = RawPrParseService().parse(_payload())

        self.assertEqual(
            parsed.changed_files,
            [
                "src/main/java/com/example/auth/AuthService.java",
                "build.gradle",
            ],
        )
        self.assertEqual(
            parsed.related_ticket_keys,
            [
                "auth-service#101",
                "payments#202",
                "auth-service#404",
                "repo-tools#303",
            ],
        )
        self.assertIn("AuthService.java (modified, +1/-1)", parsed.diff_summary or "")
        self.assertIn("build.gradle (modified, +1/-0)", parsed.diff_summary or "")


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, model: object) -> None:
        if isinstance(model, RawPr):
            now = datetime.now(timezone.utc)
            model.created_at = now
            model.updated_at = now


class _FakeRawPrRepository:
    def __init__(self) -> None:
        self.created: RawPr | None = None

    def create(self, raw_pr: RawPr) -> RawPr:
        self.created = raw_pr
        return raw_pr


class _FakeRawTicketRepository:
    def __init__(self, tickets: list[RawTicket]) -> None:
        self.tickets = tickets

    def find_by_ticket_keys(
        self,
        *,
        project_name: str,
        ticket_keys: list[str],
    ) -> list[RawTicket]:
        return [
            ticket
            for ticket in self.tickets
            if ticket.project_name == project_name and ticket.ticket_key in ticket_keys
        ]


class _FakeIncidentRepository:
    def __init__(self, incident: Incident) -> None:
        self.incident = incident

    def get_by_id(self, incident_id: uuid.UUID) -> Incident | None:
        return self.incident if self.incident.id == incident_id else None

    def update(self, incident: Incident) -> Incident:
        self.incident = incident
        return incident


class _FakeEmbeddingService:
    def __init__(self) -> None:
        self.incidents: list[Incident] = []

    def upsert_for_incident(self, incident: Incident) -> None:
        self.incidents.append(incident)


class _FakeLlmPrEnrichmentService:
    def __init__(self) -> None:
        self.incidents: list[Incident] = []

    def enrich(
        self,
        *,
        payload: RawPrCreate,
        parsed: object,
        incident: Incident,
    ) -> LlmEnrichedPr:
        self.incidents.append(incident)
        return LlmEnrichedPr(
            normalized_summary="JWT 의존성을 추가해 인증 오류를 해결했습니다.",
            extracted_keywords=["jwt", "dependency"],
            domain_tags=["auth"],
            suspected_fix_for="ClassNotFoundException",
            resolution_note="누락된 JWT 의존성을 추가했습니다.",
            diff_summary="build.gradle에 JWT 의존성을 추가했습니다.",
        )


class RawPrServiceTest(unittest.TestCase):
    def test_merged_pr_links_incident_through_related_ticket(self) -> None:
        incident_id = uuid.uuid4()
        incident = Incident(
            id=incident_id,
            status="investigating",
            related_pr_ids=[],
            resolution_summary=None,
            resolved_at=None,
            error_keywords=["ClassNotFoundException"],
            domain_tags=["login"],
        )
        ticket = RawTicket(
            ticket_key="auth-service#101",
            project_name="data-portal",
            incident_id=incident_id,
        )
        raw_pr_repo = _FakeRawPrRepository()
        embedding_service = _FakeEmbeddingService()
        llm_enrichment_service = _FakeLlmPrEnrichmentService()
        service = RawPrService(
            session=_FakeSession(),
            parse_service=RawPrParseService(),
            llm_enrichment_service=llm_enrichment_service,
            embedding_service=embedding_service,
            raw_pr_repo=raw_pr_repo,
            raw_ticket_repo=_FakeRawTicketRepository([ticket]),
            incident_repo=_FakeIncidentRepository(incident),
        )

        response = service.ingest_raw_pr(_payload())

        self.assertEqual(response.incident_action, "linked")
        self.assertEqual(response.raw_pr.pr_key, "auth-service#45")
        self.assertEqual(response.raw_pr.status, "merged")
        self.assertEqual(response.raw_pr.match_status, "matched")
        self.assertEqual(
            response.raw_pr.normalized_summary,
            "JWT 의존성을 추가해 인증 오류를 해결했습니다.",
        )
        self.assertEqual(response.raw_pr.extracted_keywords, ["jwt", "dependency"])
        self.assertEqual(response.raw_pr.domain_tags, ["auth"])
        self.assertEqual(response.raw_pr.suspected_fix_for, "ClassNotFoundException")
        self.assertEqual(
            response.raw_pr.resolution_note,
            "누락된 JWT 의존성을 추가했습니다.",
        )
        self.assertEqual(
            response.raw_pr.diff_summary,
            "build.gradle에 JWT 의존성을 추가했습니다.",
        )
        self.assertEqual(incident.status, "resolved")
        self.assertEqual(incident.resolved_at, _payload().pull_request.merged_at)
        self.assertIn(str(response.raw_pr.id), incident.related_pr_ids)
        self.assertEqual(
            incident.resolution_summary,
            "누락된 JWT 의존성을 추가했습니다.",
        )
        self.assertEqual(
            incident.error_keywords,
            ["ClassNotFoundException", "jwt", "dependency"],
        )
        self.assertEqual(incident.domain_tags, ["login", "auth"])
        self.assertEqual(llm_enrichment_service.incidents, [incident])
        self.assertEqual(embedding_service.incidents, [incident])

    def test_unmatched_pr_skips_llm_and_is_still_saved(self) -> None:
        incident = Incident(id=uuid.uuid4())
        raw_pr_repo = _FakeRawPrRepository()
        embedding_service = _FakeEmbeddingService()
        llm_enrichment_service = _FakeLlmPrEnrichmentService()
        service = RawPrService(
            session=_FakeSession(),
            parse_service=RawPrParseService(),
            llm_enrichment_service=llm_enrichment_service,
            embedding_service=embedding_service,
            raw_pr_repo=raw_pr_repo,
            raw_ticket_repo=_FakeRawTicketRepository([]),
            incident_repo=_FakeIncidentRepository(incident),
        )

        response = service.ingest_raw_pr(_payload())

        self.assertEqual(response.incident_action, "unmatched")
        self.assertEqual(response.raw_pr.match_status, "unmatched")
        self.assertIsNotNone(raw_pr_repo.created)
        self.assertEqual(llm_enrichment_service.incidents, [])
        self.assertEqual(embedding_service.incidents, [])


if __name__ == "__main__":
    unittest.main()
