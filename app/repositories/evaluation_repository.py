from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation import (
    EvaluationCandidate,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
)


class EvaluationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_active_cases(self) -> list[EvaluationCase]:
        stmt = (
            select(EvaluationCase)
            .where(EvaluationCase.is_active.is_(True))
            .order_by(EvaluationCase.case_key.asc())
        )
        return list(self._session.scalars(stmt).all())

    def create_run(self, run: EvaluationRun) -> EvaluationRun:
        self._session.add(run)
        self._session.flush()
        return run

    def update_run(self, run: EvaluationRun) -> EvaluationRun:
        self._session.add(run)
        self._session.flush()
        return run

    def create_result(self, result: EvaluationResult) -> EvaluationResult:
        self._session.add(result)
        self._session.flush()
        return result

    def create_candidates(
        self, candidates: list[EvaluationCandidate]
    ) -> list[EvaluationCandidate]:
        self._session.add_all(candidates)
        self._session.flush()
        return candidates

    def list_results_for_run(self, run_id: uuid.UUID) -> list[EvaluationResult]:
        stmt = (
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run_id)
            .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
        )
        return list(self._session.scalars(stmt).all())

    def list_candidates_for_results(
        self, result_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[EvaluationCandidate]]:
        if not result_ids:
            return {}
        stmt = (
            select(EvaluationCandidate)
            .where(EvaluationCandidate.evaluation_result_id.in_(result_ids))
            .order_by(
                EvaluationCandidate.evaluation_result_id.asc(),
                EvaluationCandidate.search_type.asc(),
                EvaluationCandidate.rank.asc(),
            )
        )
        grouped: dict[uuid.UUID, list[EvaluationCandidate]] = {}
        for candidate in self._session.scalars(stmt).all():
            grouped.setdefault(candidate.evaluation_result_id, []).append(candidate)
        return grouped

    def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return self._session.get(EvaluationRun, run_id)

    def get_case_map(self, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, EvaluationCase]:
        if not case_ids:
            return {}
        stmt = select(EvaluationCase).where(EvaluationCase.id.in_(case_ids))
        return {case.id: case for case in self._session.scalars(stmt).all()}

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
