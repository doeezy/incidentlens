from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import db_session_dep
from app.schemas.incident_search import ProjectListResponse
from app.services.projects import ProjectService


def get_project_service(
    session: Annotated[Session, Depends(db_session_dep)],
) -> ProjectService:
    return ProjectService(session)


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectListResponse:
    """incidents.project_name 기준 DISTINCT 프로젝트 목록 조회."""
    return ProjectListResponse(projects=service.list_projects())
