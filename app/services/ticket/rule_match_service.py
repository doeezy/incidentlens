from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import logging

from app.models.incident import Incident
from app.models.raw_ticket import RawTicket
from app.utils.strings import equal_normalized

logger = logging.getLogger(__name__)


def _as_naive_wall(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.replace(tzinfo=None)


def _hours_delta(a: datetime, b: datetime) -> float:
    aa = _as_naive_wall(a)
    bb = _as_naive_wall(b)
    logger.debug(f"hours_delta: {aa} - {bb} = {abs((aa - bb).total_seconds())}")
    return abs((aa - bb).total_seconds()) / 3600.0


def _norm_tokens(items: list[str] | None) -> set[str]:
    return {str(x).strip().lower() for x in (items or []) if str(x).strip()}


def _overlap_points(
    ticket_vals: list[str] | None,
    incident_vals: list[str] | None,
    max_points: float,
) -> float:
    t = _norm_tokens(ticket_vals)
    i = _norm_tokens(incident_vals)
    if not t or not i:
        return 0.0
    inter = t & i
    if not inter:
        return 0.0
    ratio = len(inter) / max(len(t), len(i))
    return min(max_points, max_points * ratio)


@dataclass(frozen=True)
class RuleScoredIncident:
    incident: Incident
    rule_score: float


class TicketIncidentRuleMatchService:
    """티켓 ↔ incident 1단계 규칙 기반 스코어링 (최대 95점)."""

    def score(
        self,
        *,
        raw_ticket: RawTicket,
        incident: Incident,
    ) -> float:
        s = 0.0

        # 마지막 관찰 시간이 티켓 생성 시간 24시간 이내인 경우 20점 추가
        if incident.last_seen_at is not None:
            if (
                _hours_delta(raw_ticket.ticket_created_at, incident.last_seen_at)
                <= 24.0
            ):
                logger.debug("====== [score] last_seen_at_matched + 20.0 =======")
                s += 20.0

        # 에러 타입 매칭 25점
        if equal_normalized(raw_ticket.error_type, incident.primary_error_type):
            logger.debug("====== [score] error_type_matched + 25.0 =======")
            s += 25.0
        # 모듈 매칭 15점
        if equal_normalized(raw_ticket.module_name, incident.module_name):
            logger.debug("====== [score] module_matched + 15.0 =======")
            s += 15.0
        # 클래스 매칭 10점
        if equal_normalized(raw_ticket.class_name, incident.class_name):
            logger.debug("====== [score] class_matched + 10.0 =======")
            s += 10.0
        # 메서드 매칭 5점
        if equal_normalized(raw_ticket.method_name, incident.method_name):
            logger.debug("====== [score] method_matched + 5.0 =======")
            s += 5.0

        # 도메인 태그 매칭 10점
        s += _overlap_points(raw_ticket.domain_tags, incident.domain_tags, 10.0)
        # 에러 키워드 매칭 10점
        s += _overlap_points(
            raw_ticket.extracted_keywords, incident.error_keywords, 10.0
        )
        return s

    def rank(
        self,
        *,
        raw_ticket: RawTicket,
        incidents: list[Incident],
    ) -> list[RuleScoredIncident]:
        scored: list[RuleScoredIncident] = []
        for inc in incidents:
            rs = self.score(
                raw_ticket=raw_ticket,
                incident=inc,
            )
            scored.append(RuleScoredIncident(incident=inc, rule_score=rs))
        scored.sort(key=lambda x: x.rule_score, reverse=True)
        return scored
