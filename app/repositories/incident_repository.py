from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, nulls_last, select, text
from sqlalchemy.orm import Session

from app.models.incident import Incident


@dataclass(frozen=True)
class IncidentBm25SearchHit:
    incident_id: uuid.UUID
    bm25_score: float
    rank: int


class IncidentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, incident: Incident) -> Incident:
        self._session.add(incident)
        self._session.flush()
        return incident

    def update(self, incident: Incident) -> Incident:
        self._session.add(incident)
        self._session.flush()
        return incident

    def get_by_id(self, incident_id: uuid.UUID) -> Incident | None:
        return self._session.get(Incident, incident_id)

    def find_match_candidates(
        self,
        project_name: str,
        occurred_at: datetime,
        candidate_days: int,
        limit: int = 100,
    ) -> list[Incident]:
        """이벤트 매칭 후보 탐색.

        - 프로젝트 이름, 마지막 관찰 시간이 조건을 만족하는 이벤트 중,
        - 마지막 관찰 시간이 이벤트 발생 시간 기준 candidate_days 이내인 이벤트를 최근 순으로 limit 개수만큼 조회한다.
        """
        cutoff = occurred_at - timedelta(days=candidate_days)
        stmt = (
            select(Incident)
            .where(Incident.project_name == project_name)
            .where(Incident.last_seen_at.is_not(None))
            .where(Incident.last_seen_at >= cutoff)
            .order_by(Incident.last_seen_at.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def find_ticket_match_candidates(
        self,
        project_name: str,
        ticket_created_at: datetime,
        limit: int = 500,
    ) -> list[Incident]:
        """티켓-incident 매칭 후보: 동일 프로젝트이고 상태가 open 또는 investigating."""
        stmt = (
            select(Incident)
            .where(Incident.project_name == project_name)
            .where(Incident.status.in_(("open", "investigating")))
            .where(Incident.first_detected_at <= ticket_created_at)
            .order_by(nulls_last(desc(Incident.last_seen_at)))
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def search_bm25(
        self,
        *,
        project_name: str,
        query: str,
        limit: int = 10,
    ) -> list[IncidentBm25SearchHit]:
        """pg_search BM25 기반 incident 단독 검색."""
        clean_project_name = project_name.strip()
        clean_query = query.strip()
        if not clean_project_name or not clean_query or limit <= 0:
            return []

        rows = self._session.execute(
            text("""
                WITH bm25_hits AS (
                    SELECT
                        id AS incident_id,
                        pdb.score(id) AS bm25_score
                    FROM incidents
                    WHERE project_name = :project_name
                      AND public.incident_searchable_text(
                            primary_error_summary,
                            primary_error_type,
                            primary_error_message,
                            error_keywords,
                            domain_tags,
                            suspected_cause,
                            root_cause_summary,
                            resolution_summary
                          ) ||| :query
                    ORDER BY pdb.score(id) DESC, id ASC
                    LIMIT :limit
                )
                SELECT
                    incident_id,
                    bm25_score,
                    rank() OVER (
                        ORDER BY bm25_score DESC, incident_id ASC
                    ) AS rank
                FROM bm25_hits
                ORDER BY rank ASC;
            """),
            {
                "project_name": clean_project_name,
                "query": clean_query,
                "limit": limit,
            },
        ).all()

        return [
            IncidentBm25SearchHit(
                incident_id=incident_id,
                bm25_score=float(bm25_score),
                rank=int(rank),
            )
            for incident_id, bm25_score, rank in rows
        ]
