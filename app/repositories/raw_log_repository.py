from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.raw_log import RawLog


class RawLogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, raw_log: RawLog) -> RawLog:
        self._session.add(raw_log)
        self._session.flush()
        return raw_log

    def update(self, raw_log: RawLog) -> RawLog:
        self._session.add(raw_log)
        self._session.flush()
        return raw_log

    def get_by_id(self, log_id: uuid.UUID) -> RawLog | None:
        return self._session.get(RawLog, log_id)
