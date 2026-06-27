from __future__ import annotations

import json
from typing import Any, TypedDict

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.llm import OpenAiChatClient
from app.schemas.incident_search import IncidentAgentResponse, IncidentSearchResponse
from app.services.retrieval import IncidentRetrievalService


class IncidentAgentState(TypedDict, total=False):
    question: str
    top_k: int
    search_response: IncidentSearchResponse
    answer: str


class _AgentAnswerSchema(BaseModel):
    answer: str = Field(..., description="검색 결과를 근거로 한 한국어 답변.")


class IncidentAnswerAgent:
    """

    Nodes:
    - retrieve_incidents
    - generate_answer

    TODO: add tracing, evaluation, confidence scoring, and prompt/version metadata.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        retrieval_service: IncidentRetrievalService,
    ) -> None:
        self._settings = settings
        self._retrieval_service = retrieval_service
        self._llm = OpenAiChatClient(settings)
        self._graph = self._build_graph()

    # TODO: 사용자에게 project name 입력 받아서 해당 프로젝트 내에서 장애사례 검색할 수 있도록 수정 필요
    # 다른 프로젝트로 변경하는 로직도 필요함
    def answer(self, *, question: str, top_k: int = 5) -> IncidentAgentResponse:
        state = self._graph.invoke({"question": question.strip(), "top_k": top_k})
        search_response = state["search_response"]
        return IncidentAgentResponse(
            question=question.strip(),
            answer=state["answer"],
            search_results=search_response.results,
        )

    def _build_graph(self) -> Any:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "langgraph is required for IncidentAnswerAgent. "
                "Install dependencies from requirements.txt."
            ) from exc

        # LangGraph 상태 그래프 생성
        graph = StateGraph(IncidentAgentState)
        # 노드 추가
        graph.add_node("retrieve_incidents", self._retrieve_incidents)
        graph.add_node("generate_answer", self._generate_answer)
        # 시작 노드 설정
        graph.set_entry_point("retrieve_incidents")
        # 엣지 추가
        graph.add_edge("retrieve_incidents", "generate_answer")
        # 종료 노드 설정
        graph.add_edge("generate_answer", END)
        return graph.compile()

    def _retrieve_incidents(self, state: IncidentAgentState) -> IncidentAgentState:
        response = self._retrieval_service.search(
            query=state["question"],
            top_k=state.get("top_k", 5),
        )
        return {"search_response": response}

    def _generate_answer(self, state: IncidentAgentState) -> IncidentAgentState:
        search_response = state["search_response"]
        # 검색 결과를 기반으로 LLM 답변 생성
        answer = self._generate_llm_answer(
            question=state["question"],
            search_response=search_response,
        )
        if answer is None:
            answer = self._fallback_answer(search_response)
        return {"answer": answer}

    def _generate_llm_answer(
        self,
        *,
        question: str,
        search_response: IncidentSearchResponse,
    ) -> str | None:
        if not self._settings.openai_api_key:
            return None

        retrieved_json = json.dumps(
            [result.model_dump(mode="json") for result in search_response.results],
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""
        사용자의 장애 관련 질문에 답변한다.

        [답변 원칙]
        - 반드시 검색된 incident 결과만 근거로 답변한다.
        - 검색 결과에 없는 원인, 해결책, 파일명, 코드 변경 내용은 새로 만들어내지 않는다.
        - 관련 incident가 없거나 근거가 부족하면, 근거가 부족하다고 한다.
        - 한국어로 답변한다.
        - 너무 길게 늘이지 말고, 원인/근거/해결 방향 중심으로 정리한다.

        [답변에 포함하면 좋은 내용]
        1. 어떤 장애 사례와 유사한지
        2. 관찰된 에러 타입과 메시지
        3. 추정 가능한 원인 또는 근거
        4. 실제 해결 이력이 있다면 해결 방법
        5. 관련 로그, 티켓, PR 근거

        [사용자 질문]
        {question}

        [검색된 incident 결과]
        ```json
        {retrieved_json}
        ```

        [반환 형식]
        반드시 JSON만 반환한다.
        아래 필드만 포함한다.

        * answer

        """.strip()
        messages = [
            {
                "role": "developer",
                "content": (
                    "You are an incident response assistant. "
                    "Answer in Korean using only the retrieved incident evidence. "
                    "Do not invent facts. "
                    "If the evidence is insufficient, clearly say so. "
                    "Return only valid JSON matching the schema."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=_AgentAnswerSchema,
            schema_name="IncidentAgentAnswer",
        )

        parsed = self._parse_answer(text)
        if parsed:
            return parsed

        return self._llm_plain_text(messages)

    def _parse_answer(self, text: str | None) -> str | None:
        if not text or not text.strip():
            return None
        try:
            return _AgentAnswerSchema.model_validate_json(text).answer.strip() or None
        except ValidationError:
            return None

    def _llm_plain_text(self, messages: list[dict[str, str]]) -> str | None:
        """OpenAI 플레인 텍스트 응답 생성. 실패 시 None."""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._settings.openai_api_key)
            response = client.chat.completions.create(
                model=self._settings.llm_model_name,
                messages=messages,
            )
            out = (response.choices[0].message.content or "").strip()
            return out or None
        except Exception:
            return None

    def _fallback_answer(self, search_response: IncidentSearchResponse) -> str:
        if not search_response.results:
            return "검색된 장애 사례가 없습니다."

        lines = ["검색된 장애 사례를 기준으로 정리했습니다."]
        for index, result in enumerate(search_response.results, start=1):
            lines.extend(
                [
                    f"{index}. {result.summary or result.error_message}",
                    f"- 상태: {result.status}",
                    f"- 원인: {result.root_cause or result.suspected_cause or '확인된 원인 정보가 없습니다.'}",
                    f"- 해결: {result.resolution or '확인된 해결 정보가 없습니다.'}",
                    (
                        "- 근거: "
                        f"logs {len(result.evidence_logs)}건, "
                        f"tickets {len(result.evidence_tickets)}건, "
                        f"prs {len(result.evidence_prs)}건"
                    ),
                ]
            )
        return "\n".join(lines)
