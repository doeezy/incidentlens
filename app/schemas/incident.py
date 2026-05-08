from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class IncidentRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_name: str
    module_name: str | None
    class_name: str | None
    method_name: str | None
    status: str
    occurred_at: datetime
    first_detected_at: datetime
    last_seen_at: datetime | None
    resolved_at: datetime | None
    primary_error_type: str | None
    primary_error_message: str
    primary_error_summary: str | None
    error_keywords: list[str] | None
    domain_tags: list[str] | None
    related_log_ids: list[str] | None
