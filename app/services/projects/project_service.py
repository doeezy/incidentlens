from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incident import Incident


class ProjectService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_projects(self) -> list[str]:
        stmt = (
            select(Incident.project_name)
            .where(Incident.project_name.is_not(None))
            .distinct()
            .order_by(Incident.project_name.asc())
        )
        return [
            str(project_name)
            for project_name in self._session.scalars(stmt).all()
            if str(project_name).strip()
        ]
