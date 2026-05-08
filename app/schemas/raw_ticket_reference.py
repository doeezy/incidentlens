"""raw_tickets 테이블용 참조 스키마(향후 단계에서 API/서비스 연동 시 사용)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RawTicketFieldsReference(BaseModel):
    """저장 가능한 필드 형태 참조."""

    ticket_key: str
    project_name: str
    repository_name: str | None = None
    title: str
    ticket_created_at: datetime


class RawTicketReadReference(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    ticket_key: str
    project_name: str
