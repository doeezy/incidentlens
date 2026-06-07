from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.incident import Incident
from app.models.raw_ticket import RawTicket
from app.schemas.raw_ticket import RawTicketCreate
from app.services.ticket.parse_service import TicketParseService
from app.services.ticket.raw_ticket_service import RawTicketService
from app.services.ticket.rule_match_service import TicketIncidentRuleMatchService


class RawTicketSchemaTest(unittest.TestCase):
    def test_github_issue_request_is_parsed(self) -> None:
        payload = RawTicketCreate.model_validate(
            {
                "project_name": "data-portal",
                "repository_name": "auth-service",
                "issue": {
                    "number": 101,
                    "title": "로그인 장애 발생",
                    "body": "배포 이후 인증 오류 발생",
                    "state": "open",
                    "user": {"login": "kim"},
                    "assignees": [{"login": "lee"}],
                    "labels": [{"name": "bug"}, {"name": "priority: high"}],
                    "created_at": "2026-05-07T10:30:00Z",
                    "updated_at": "2026-05-07T11:00:00Z",
                    "closed_at": None,
                },
            }
        )

        self.assertEqual(payload.issue.number, 101)
        self.assertEqual(payload.issue.user.login, "kim")
        self.assertEqual(payload.issue.assignees[0].login, "lee")

    def test_priority_is_extracted_from_priority_label(self) -> None:
        payload = RawTicketCreate.model_validate(
            {
                "project_name": "data-portal",
                "repository_name": "auth-service",
                "issue": {
                    "number": 101,
                    "title": "로그인 장애 발생",
                    "body": None,
                    "state": "open",
                    "user": {"login": "kim"},
                    "assignees": [],
                    "labels": [{"name": "bug"}, {"name": "priority/high"}],
                    "created_at": "2026-05-07T10:30:00Z",
                    "updated_at": "2026-05-07T11:00:00Z",
                    "closed_at": None,
                },
            }
        )

        service = object.__new__(RawTicketService)
        self.assertEqual(service._extract_priority(payload), "high")


class TicketParseServiceTest(unittest.TestCase):
    def test_only_explicit_exception_or_error_is_extracted(self) -> None:
        service = TicketParseService()

        explicit = service.parse("로그인 장애", "AuthTokenException 발생")
        ambiguous = service.parse("로그인 오류 발생", "인증 오류가 반복됩니다")

        self.assertEqual(explicit.error_type, "AuthTokenException")
        self.assertIsNone(ambiguous.error_type)
        self.assertFalse(hasattr(explicit, "module_name"))


class TicketRuleMatchServiceTest(unittest.TestCase):
    def test_full_rule_score_is_100(self) -> None:
        ticket_created_at = datetime(2026, 5, 7, 10, 30, tzinfo=timezone.utc)
        raw_ticket = RawTicket(
            ticket_created_at=ticket_created_at,
            error_type="AuthTokenException",
            domain_tags=["auth", "login"],
            extracted_keywords=["token", "expired"],
        )
        incident = Incident(
            last_seen_at=datetime(2026, 5, 7, 9, 30, tzinfo=timezone.utc),
            primary_error_type="AuthTokenException",
            domain_tags=["auth", "login"],
            error_keywords=["token", "expired"],
        )

        score = TicketIncidentRuleMatchService().score(
            raw_ticket=raw_ticket,
            incident=incident,
        )

        self.assertEqual(score, 100.0)

    def test_missing_error_types_do_not_score(self) -> None:
        raw_ticket = RawTicket(
            ticket_created_at=datetime(2026, 5, 7, 10, 30),
            error_type=None,
            domain_tags=[],
            extracted_keywords=[],
        )
        incident = Incident(
            last_seen_at=None,
            primary_error_type=None,
            domain_tags=[],
            error_keywords=[],
        )

        score = TicketIncidentRuleMatchService().score(
            raw_ticket=raw_ticket,
            incident=incident,
        )

        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
