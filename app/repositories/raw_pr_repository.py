from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.raw_pr import RawPr


class RawPrRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, raw_pr: RawPr) -> RawPr:
        self._session.add(raw_pr)
        self._session.flush()
        return raw_pr

    def update(self, raw_pr: RawPr) -> RawPr:
        self._session.add(raw_pr)
        self._session.flush()
        return raw_pr

    def get_by_id(self, pr_id: uuid.UUID) -> RawPr | None:
        return self._session.get(RawPr, pr_id)
