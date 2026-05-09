from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.config import Settings
from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.utils.strings import equal_normalized

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchResult:
    incident: Incident
    score: float


class IncidentMatchService:
    """인시던트 매칭 점수화.

    현재 기준:
    - 필수 조건: project 동일 + time window 이내
    - 점수(가산): module(+20) / class(+20) / method(+10) / error_type(+30)
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def score(self, log: RawLog, incident: Incident) -> float:
        if not equal_normalized(log.project_name, incident.project_name):
            return 0.0

        if incident.last_seen_at is None:
            return 0.0
        delta = self._delta_minutes(log.occurred_at, incident.last_seen_at)
        window = float(self._settings.incident_time_window_minutes_full)
        if delta > window:
            return 0.0

        score = 0.0
        if equal_normalized(log.module_name, incident.module_name):
            score += 20.0
        if equal_normalized(log.class_name, incident.class_name):
            score += 20.0
        if equal_normalized(log.method_name, getattr(incident, "method_name", None)):
            score += 10.0
        if equal_normalized(log.error_type, incident.primary_error_type):
            score += 30.0
        return score

    def _delta_minutes(self, a: datetime, b: datetime) -> float:
        if a.tzinfo is not None:
            a = a.replace(tzinfo=None)
        if b.tzinfo is not None:
            b = b.replace(tzinfo=None)
        return abs((a - b).total_seconds()) / 60.0

    def pick_best(
        self,
        log: RawLog,
        candidates: list[Incident],
    ) -> MatchResult | None:
        best: MatchResult | None = None
        for inc in candidates:
            s = self.score(log, inc)
            if best is None or s > best.score:
                best = MatchResult(incident=inc, score=s)
        return best
