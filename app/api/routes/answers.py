from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.routes.conversations import get_conversation_service
from app.schemas.incident_search import IncidentAgentRequest, IncidentAgentResponse
from app.services.conversations import ConversationService


router = APIRouter(prefix="/api/v1/answers", tags=["answers"])


@router.post("", response_model=IncidentAgentResponse)
def answer_question(
    request: Request,
    body: IncidentAgentRequest,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> IncidentAgentResponse:
    """Conversation history를 반영해 incident 답변을 생성하고 메시지를 저장한다."""
    try:
        return service.answer(
            conversation_id=body.conversation_id,
            question=body.question,
            top_k=body.top_k,
            request_id=request.headers.get("x-request-id"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="conversation not found") from None
