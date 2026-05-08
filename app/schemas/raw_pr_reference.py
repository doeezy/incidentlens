"""raw_prs 테이블용 참조 스키마(향후 단계에서 API/서비스 연동 시 사용)."""

import uuid

from pydantic import BaseModel


class RawPrFieldsReference(BaseModel):
    title: str
    project_name: str


class RawPrReadReference(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    project_name: str
