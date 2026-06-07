from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.raw_ticket import RawTicket


class RawTicketRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, raw_ticket: RawTicket) -> RawTicket:
        self._session.add(raw_ticket)
        self._session.flush()
        return raw_ticket

    def update(self, raw_ticket: RawTicket) -> RawTicket:
        self._session.add(raw_ticket)
        self._session.flush()
        return raw_ticket

    def get_by_id(self, ticket_id: uuid.UUID) -> RawTicket | None:
        return self._session.get(RawTicket, ticket_id)

    def find_by_ticket_keys(
        self,
        *,
        project_name: str,
        ticket_keys: list[str],
    ) -> list[RawTicket]:
        if not ticket_keys:
            return []
        stmt = (
            select(RawTicket)
            .where(RawTicket.project_name == project_name)
            .where(RawTicket.ticket_key.in_(ticket_keys))
        )
        return list(self._session.scalars(stmt).all())
