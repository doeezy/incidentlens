from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.llm import OpenAiChatClient
from app.schemas.incident_search import IncidentAgentResponse, IncidentSearchResponse
from app.services.retrieval import IncidentRetrievalService
from app.tracing import (
    AgentTrace,
    AgentTraceAnswer,
    AgentTraceConfidence,
    AgentTraceQuery,
    AgentTraceReference,
    AgentTraceRetrieval,
    AgentTraceTiming,
)
from app.utils.json_text import extract_first_json_object

logger = logging.getLogger(__name__)


class IncidentAgentState(TypedDict, total=False):
    question: str
    top_k: int
    project_name: str | None
    request_id: str
    trace_id: uuid.UUID
    trace_created_at: datetime
    history_messages: list["ConversationHistoryMessage"]
    query_analysis: "QueryAnalysis"
    search_response: IncidentSearchResponse
    answer: str
    query_analyzer_ms: float
    retrieval_ms: float
    confidence_ms: float
    answer_generation_ms: float
    trace_retrieval: AgentTraceRetrieval
    trace_confidence: AgentTraceConfidence


class QueryAnalysis(BaseModel):
    intent: Literal[
        "ROOT_CAUSE",
        "RESOLUTION",
        "SIMILAR_CASE",
        "SUMMARY",
        "OUT_OF_SCOPE",
    ]
    retrieval_required: bool
    rewritten_query: str | None = None
    reason: str
    query_sufficient: bool = True
    missing_information: list[
        Literal[
            "symptom_or_error",
            "error_message",
            "affected_feature",
            "project",
        ]
    ] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_question: str | None = None


class ConversationHistoryMessage(BaseModel):
    role: Literal["USER", "ASSISTANT"]
    content: str


class _AgentAnswerSchema(BaseModel):
    answer: str = Field(..., description="검색 결과를 근거로 한 한국어 답변.")


class IncidentAnswerAgent:
    """

    Nodes:
    - query_analyzer
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
        self._last_trace: AgentTrace | None = None

    # TODO: 사용자에게 project name 입력 받아서 해당 프로젝트 내에서 장애사례 검색할 수 있도록 수정 필요
    # 다른 프로젝트로 변경하는 로직도 필요함
    def answer(
        self,
        *,
        question: str,
        top_k: int = 5,
        project_name: str | None = None,
        request_id: str | None = None,
        history_messages: list[ConversationHistoryMessage] | None = None,
    ) -> IncidentAgentResponse:
        clean_project_name = project_name.strip() if project_name else None
        trace_id = uuid.uuid4()
        resolved_request_id = request_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        total_start = perf_counter()
        state = self._graph.invoke(
            {
                "question": question.strip(),
                "top_k": top_k,
                "project_name": clean_project_name,
                "request_id": resolved_request_id,
                "trace_id": trace_id,
                "trace_created_at": created_at,
                "history_messages": history_messages or [],
            }
        )
        search_response = state["search_response"]
        query_analysis = state["query_analysis"]
        response = IncidentAgentResponse(
            question=question.strip(),
            project_name=clean_project_name,
            intent=query_analysis.intent,
            retrieval_required=query_analysis.retrieval_required,
            rewritten_query=query_analysis.rewritten_query,
            analysis_reason=query_analysis.reason,
            query_sufficient=query_analysis.query_sufficient,
            missing_information=query_analysis.missing_information,
            clarification_required=query_analysis.clarification_required,
            clarification_question=query_analysis.clarification_question,
            answer=state["answer"],
            search_results=search_response.results,
        )
        self._last_trace = self._build_trace(
            state=state,
            response=response,
            total_ms=self._elapsed_ms(total_start),
        )
        if getattr(self._settings, "agent_trace_debug", False):
            logger.info(
                "agent_trace=%s",
                self._last_trace.model_dump_json(),
            )
        return response

    @property
    def last_trace(self) -> AgentTrace | None:
        return self._last_trace

    def analyze_query(
        self,
        question: str,
        history_messages: list[ConversationHistoryMessage] | None = None,
    ) -> QueryAnalysis:
        """운영 답변 경로와 동일한 Query Analyzer를 실행한다."""
        return self._analyze_query(
            question.strip(),
            history_messages=history_messages,
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
        graph.add_node("query_analyzer", self._query_analyzer)
        graph.add_node("retrieve_incidents", self._retrieve_incidents)
        graph.add_node("generate_answer", self._generate_answer)
        # 시작 노드 설정
        graph.set_entry_point("query_analyzer")
        # 엣지 추가
        graph.add_conditional_edges(
            "query_analyzer",
            self._route_after_query_analysis,
            {
                "retrieve": "retrieve_incidents",
                "end": END,
            },
        )
        graph.add_edge("retrieve_incidents", "generate_answer")
        # 종료 노드 설정
        graph.add_edge("generate_answer", END)
        return graph.compile()

    def _query_analyzer(self, state: IncidentAgentState) -> IncidentAgentState:
        start = perf_counter()
        analysis = self._analyze_query(
            state["question"],
            history_messages=state.get("history_messages", []),
        )
        elapsed_ms = self._elapsed_ms(start)
        if not analysis.retrieval_required:
            empty_response = IncidentSearchResponse(
                query=state["question"],
                top_k=state.get("top_k", 5),
                project_name=state.get("project_name"),
                results=[],
            )
            return {
                "query_analysis": analysis,
                "search_response": empty_response,
                "answer": "장애 검색과 관련 없는 질문입니다.",
                "query_analyzer_ms": elapsed_ms,
                "retrieval_ms": 0.0,
                "confidence_ms": 0.0,
                "answer_generation_ms": 0.0,
                "trace_retrieval": AgentTraceRetrieval(),
                "trace_confidence": AgentTraceConfidence(),
            }
        if not analysis.query_sufficient:
            empty_response = IncidentSearchResponse(
                query=state["question"],
                top_k=state.get("top_k", 5),
                project_name=state.get("project_name"),
                results=[],
            )
            return {
                "query_analysis": analysis,
                "search_response": empty_response,
                "answer": (
                    analysis.clarification_question
                    or "검색을 위해 장애 증상이나 오류 정보를 조금 더 알려주세요."
                ),
                "query_analyzer_ms": elapsed_ms,
                "retrieval_ms": 0.0,
                "confidence_ms": 0.0,
                "answer_generation_ms": 0.0,
                "trace_retrieval": AgentTraceRetrieval(),
                "trace_confidence": AgentTraceConfidence(),
            }
        return {"query_analysis": analysis, "query_analyzer_ms": elapsed_ms}

    def _route_after_query_analysis(self, state: IncidentAgentState) -> str:
        analysis = state["query_analysis"]
        return "retrieve" if analysis.retrieval_required and analysis.query_sufficient else "end"

    def _retrieve_incidents(self, state: IncidentAgentState) -> IncidentAgentState:
        analysis = state["query_analysis"]
        response = self._retrieval_service.search(
            query=analysis.rewritten_query or state["question"],
            top_k=state.get("top_k", 5),
            project_name=state.get("project_name"),
            query_intent=analysis.intent,
        )
        return {
            "search_response": response,
            "retrieval_ms": self._retrieval_service.last_retrieval_ms,
            "confidence_ms": self._retrieval_service.last_confidence_ms,
            "trace_retrieval": self._retrieval_service.last_trace_retrieval,
            "trace_confidence": self._retrieval_service.last_trace_confidence,
        }

    def _generate_answer(self, state: IncidentAgentState) -> IncidentAgentState:
        search_response = state["search_response"]
        # 검색 결과를 기반으로 LLM 답변 생성
        start = perf_counter()
        answer = self._generate_llm_answer(
            question=state["question"],
            search_response=search_response,
            history_messages=state.get("history_messages", []),
        )
        if answer is None:
            answer = self._fallback_answer(search_response)
        return {
            "answer": answer,
            "answer_generation_ms": self._elapsed_ms(start),
        }

    def _build_trace(
        self,
        *,
        state: IncidentAgentState,
        response: IncidentAgentResponse,
        total_ms: float,
    ) -> AgentTrace:
        query_analysis = state["query_analysis"]
        return AgentTrace(
            trace_id=state["trace_id"],
            request_id=state["request_id"],
            created_at=state["trace_created_at"],
            query=AgentTraceQuery(
                original_query=state["question"],
                rewritten_query=query_analysis.rewritten_query,
                intent=query_analysis.intent,
                retrieval_required=query_analysis.retrieval_required,
                reason=query_analysis.reason,
                query_sufficient=query_analysis.query_sufficient,
                missing_information=query_analysis.missing_information,
                clarification_required=query_analysis.clarification_required,
                clarification_question=query_analysis.clarification_question,
            ),
            retrieval=state.get("trace_retrieval") or AgentTraceRetrieval(),
            confidence=state.get("trace_confidence") or AgentTraceConfidence(),
            answer=self._build_answer_trace(response),
            timing=AgentTraceTiming(
                query_analyzer_ms=state.get("query_analyzer_ms"),
                retrieval_ms=state.get("retrieval_ms"),
                confidence_ms=state.get("confidence_ms"),
                answer_generation_ms=state.get("answer_generation_ms"),
                total_ms=total_ms,
            ),
        )

    def _build_answer_trace(
        self,
        response: IncidentAgentResponse,
    ) -> AgentTraceAnswer:
        if not response.search_results:
            return AgentTraceAnswer(
                incident_id=None,
                confidence=None,
                references=[],
                response=response.answer,
            )

        selected = response.search_results[0]
        references = [
            AgentTraceReference(
                source_type="incident",
                source_id=selected.incident_id,
                label=selected.error_type,
                summary=selected.summary or selected.error_message,
            )
        ]
        references.extend(
            AgentTraceReference(
                source_type="log",
                source_id=log.id,
                label=log.error_type,
                summary=log.normalized_summary or log.error_message,
            )
            for log in selected.evidence_logs
        )
        references.extend(
            AgentTraceReference(
                source_type="ticket",
                source_id=ticket.id,
                label=ticket.ticket_key,
                summary=ticket.normalized_summary or ticket.title,
            )
            for ticket in selected.evidence_tickets
        )
        references.extend(
            AgentTraceReference(
                source_type="pr",
                source_id=pr.id,
                label=pr.pr_key,
                summary=pr.normalized_summary or pr.title,
            )
            for pr in selected.evidence_prs
        )
        return AgentTraceAnswer(
            incident_id=selected.incident_id,
            confidence=selected.confidence,
            references=references,
            response=response.answer,
        )

    def _elapsed_ms(self, start: float) -> float:
        return (perf_counter() - start) * 1000.0

    def _analyze_query(
        self,
        question: str,
        *,
        history_messages: list[ConversationHistoryMessage] | None = None,
    ) -> QueryAnalysis:
        if not self._settings.openai_api_key:
            return self._fallback_query_analysis(
                question,
                history_messages=history_messages or [],
            )

        messages = [
            {
                "role": "developer",
                "content": self._query_analyzer_prompt(),
            },
            {
                "role": "user",
                "content": self._query_analyzer_user_content(
                    question=question,
                    history_messages=history_messages or [],
                ),
            },
        ]

        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=QueryAnalysis,
            schema_name="QueryAnalysis",
        )
        parsed = self._parse_query_analysis(text, allow_json_extraction=False)
        if parsed is not None:
            return self._normalize_query_analysis(parsed, question)

        text = self._llm.chat_json_object(messages)
        parsed = self._parse_query_analysis(text, allow_json_extraction=True)
        if parsed is not None:
            return self._normalize_query_analysis(parsed, question)

        return self._fallback_query_analysis(
            question,
            history_messages=history_messages or [],
        )

    def _query_analyzer_user_content(
        self,
        *,
        question: str,
        history_messages: list[ConversationHistoryMessage],
    ) -> str:
        if not history_messages:
            return question
        return json.dumps(
            {
                "history": [
                    message.model_dump(mode="json") for message in history_messages
                ],
                "current_question": question,
            },
            ensure_ascii=False,
        )

    def _query_analyzer_prompt(self) -> str:
        return (
            "당신은 장애 검색 에이전트의 Query Analyzer입니다.\n\n"
            "사용자의 질문을 분석하여 검색 의도를 판단하고, 검색이 필요한 경우 "
            "검색에 적합한 query를 생성하세요.\n\n"
            "## 역할\n\n"
            "당신은 장애 검색을 수행하지 않습니다.\n"
            "오직 사용자의 질문을 이해하고, 이후 Retrieval 단계가 사용할 정보를 "
            "생성하는 역할만 수행합니다.\n\n"
            "## 입력\n\n"
            "입력은 단일 질문 문자열이거나, 다음 JSON 형태일 수 있습니다.\n\n"
            "{\n"
            "  \"history\": [\n"
            "    {\"role\": \"USER\", \"content\": \"...\"},\n"
            "    {\"role\": \"ASSISTANT\", \"content\": \"...\"}\n"
            "  ],\n"
            "  \"current_question\": \"...\"\n"
            "}\n\n"
            "history는 현재 질문을 이해하기 위한 참고 정보입니다.\n"
            "current_question이 독립적인 질문이면 history를 무시하세요.\n"
            "current_question이 이전 대화를 참조하는 꼬리 질문이면 history를 이용하세요.\n"
            "history에 없는 내용을 추론하지 마세요.\n"
            "history에서 이미 확인된 정보를 current_question에서 다시 말하지 않았다는 "
            "이유만으로 부족하다고 판단하지 마세요.\n"
            "current_question이 history와 충돌하면 current_question을 우선하세요.\n"
            "rewritten_query는 항상 독립적인 검색어가 되도록 생성하세요.\n\n"
            "예:\n"
            "history: USER \"로그인 장애 원인이 뭐야?\", ASSISTANT \"JwtTokenProvider를 찾지 못해 발생한 장애입니다.\"\n"
            "current_question: \"어떻게 해결했어?\"\n"
            "rewrite: \"로그인 JwtTokenProvider 해결 방법\"\n\n"
            "## Intent 정의\n\n"
            "다음 다섯 가지 중 하나만 선택하세요.\n\n"
            "- ROOT_CAUSE\n"
            "  장애가 발생한 원인이나 이유를 묻는 질문\n\n"
            "- RESOLUTION\n"
            "  장애를 어떻게 해결했는지 또는 해결 방법을 묻는 질문\n\n"
            "- SIMILAR_CASE\n"
            "  비슷한 장애 사례나 과거 사례를 찾는 질문\n\n"
            "- SUMMARY\n"
            "  장애 내용을 요약하거나 설명해 달라는 질문\n\n"
            "- OUT_OF_SCOPE\n"
            "  장애 검색과 관련 없는 일반 질문\n\n"
            "## Retrieval 여부\n\n"
            "OUT_OF_SCOPE인 경우만\n\n"
            "retrieval_required = false\n\n"
            "그 외에는 모두\n\n"
            "retrieval_required = true\n\n"
            "입니다.\n\n"
            "## Query Sufficiency\n\n"
            "query_sufficient는 retrieval_required와 다른 판단입니다.\n"
            "- retrieval_required: 이 요청이 과거 Incident 검색을 필요로 하는가\n"
            "- query_sufficient: 현재 정보와 history만으로 검색을 시도할 만한 "
            "실질적인 단서가 있는가\n\n"
            "query_sufficient=false는 검색에 사용할 실질적인 단서가 거의 없는 "
            "경우에만 사용하세요.\n"
            "정보가 적거나 query가 모호하다는 이유만으로 clarification을 실행하지 "
            "마세요.\n"
            "고정된 필수 필드 체크리스트를 만들지 마세요. project_name, module_name, "
            "class_name, error_type이 모두 있어야 검색 가능하다고 판단하면 안 됩니다.\n"
            "핵심은 현재 정보와 history만으로 과거 Incident 검색을 시도할 만한 "
            "단서가 있는가입니다.\n\n"
            "다음처럼 최소한의 검색 단서가 있으면 query_sufficient=true입니다.\n"
            "- 캐시 서버 접속 실패\n"
            "- 로그인 오류\n"
            "- paymentMethod is null\n"
            "- ClassNotFoundException AuthService login\n"
            "- 배치 컨테이너 종료 오류\n\n"
            "다음처럼 검색 가능한 기술적/증상적 단서가 거의 없으면 "
            "query_sufficient=false일 수 있습니다.\n"
            "- 안돼요\n"
            "- 오류났어\n"
            "- 왜 이러지?\n"
            "- 이거 문제 있어\n\n"
            "history에서 이미 project, 서비스, 기능, 증상, 에러가 확인되었다면 "
            "그 정보를 함께 사용하세요. 이미 받은 정보를 다시 질문하지 마세요.\n\n"
            "missing_information은 비어 있는 모든 필드를 나열하는 용도가 아닙니다.\n"
            "검색 가능성을 확보하기 위해 사용자에게 추가로 받아야 하는 최소 정보만 "
            "반환하세요.\n"
            "가능한 값은 다음 중에서만 선택하세요.\n"
            "- symptom_or_error\n"
            "- error_message\n"
            "- affected_feature\n"
            "- project\n\n"
            "clarification은 한 번에 최소한의 정보만 요청하세요.\n"
            "나쁜 예: \"프로젝트명, 서비스명, 모듈명, 클래스명, 메서드명, 에러 타입, "
            "에러 메시지, 발생 시각을 알려주세요.\"\n"
            "좋은 예: \"어떤 기능에서 어떤 오류나 증상이 발생했는지 알려주세요.\"\n"
            "좋은 예: \"확인된 에러 메시지나 예외명이 있다면 알려주세요.\"\n\n"
            "query_sufficient=false이면 clarification_required=true, "
            "clarification_question은 한국어 질문 문자열, rewritten_query=null로 "
            "반환하세요.\n"
            "query_sufficient=true이면 clarification_required=false, "
            "missing_information=[], clarification_question=null로 반환하세요.\n"
            "OUT_OF_SCOPE이면 retrieval_required=false이고 clarification_required=false입니다.\n\n"
            "## Query Rewrite\n\n"
            "retrieval_required가 true인 경우에는 검색에 적합한 query를 작성하세요.\n"
            "단, query_sufficient=false이면 rewritten_query를 작성하지 말고 null로 "
            "반환하세요.\n"
            "rewrite는 새로운 의미를 만들거나 원문을 축약하는 작업이 아닙니다.\n"
            "원문의 핵심 검색 단서를 보존한 채 불필요한 표현만 제거하는 작업입니다.\n\n"
            "### 핵심 원칙\n\n"
            "1. 원문의 핵심 검색 단서를 반드시 보존합니다.\n\n"
            "다음 정보가 원문에 있으면 rewritten_query에도 유지하세요.\n\n"
            "- Exception 또는 Error 이름\n"
            "- 클래스명\n"
            "- 메서드명\n"
            "- 서비스명\n"
            "- 모듈명\n"
            "- 라이브러리명\n"
            "- 에러 코드\n"
            "- 파일명\n"
            "- 컬럼명\n"
            "- 설정 키\n"
            "- HTTP 상태 코드\n"
            "- 종료 코드\n"
            "- 데이터베이스 오류 코드\n"
            "- 장애 증상\n"
            "- 장애가 발생한 동작\n"
            "- 사용자가 명시한 원인 후보\n"
            "- 제품명 또는 기술명\n\n"
            "예: JwtTokenProvider, ClassNotFoundException, paymentMethod, "
            "report_status_cd, code 137, Docker container, memory limit, "
            "PKIX, truststore\n\n"
            "2. 원문의 구체적인 표현을 더 일반적인 표현으로 바꾸지 않습니다.\n\n"
            "나쁜 예:\n"
            "- \"Docker 컨테이너가 메모리 제한 때문에 code 137로 종료됨\"\n"
            "  -> \"컨테이너 종료 오류\"\n"
            "- \"JwtTokenProvider ClassNotFoundException\"\n"
            "  -> \"로그인 인증 오류\"\n"
            "- \"report_status_cd 컬럼이 없음\"\n"
            "  -> \"DB 조회 오류\"\n\n"
            "좋은 예:\n"
            "- \"Docker 컨테이너 메모리 제한 code 137 비정상 종료\"\n"
            "- \"JwtTokenProvider ClassNotFoundException 로그인 실패\"\n"
            "- \"report_status_cd 컬럼 없음 SQLGrammarException\"\n\n"
            "3. 원문에 없는 정보를 추론하여 추가하지 않습니다.\n\n"
            "- 원문에 OOMKilled가 없으면 OOMKilled를 추가하지 않습니다.\n"
            "- 원문에 OutOfMemoryError가 없으면 추가하지 않습니다.\n"
            "- 원문에 Docker가 없으면 Docker를 추가하지 않습니다.\n"
            "- 원문에 특정 원인이 없으면 일반적인 원인을 추측하지 않습니다.\n\n"
            "단, 원문의 명확한 동의어를 기계적으로 정규화하는 것은 가능합니다.\n"
            "예: \"널 포인터\" -> \"NullPointerException\"은 원문에서 해당 예외가 "
            "명확히 지칭된 경우만 가능합니다.\n"
            "\"코드 137\"을 임의로 \"OOMKilled\"로 바꾸지는 않습니다.\n\n"
            "4. intent 관련 표현은 rewritten_query에 기본적으로 포함하지 않습니다.\n\n"
            "intent는 별도 필드인 intent에 이미 분류됩니다. rewritten_query는 검색 "
            "대상이 되는 장애 핵심 단서만 포함해야 합니다.\n\n"
            "rewritten_query에서 제거할 표현:\n"
            "- \"원인\"\n"
            "- \"해결 방법\"\n"
            "- \"요약\"\n"
            "- \"유사 장애 사례\"\n"
            "- \"장애 설명\"\n"
            "- \"찾아줘\"\n"
            "- \"알려줘\"\n\n"
            "단, \"장애\"라는 단어가 제품명, 서비스명, 장애 동작 또는 핵심 증상의 "
            "일부로 실제 검색 단서라면 무리하게 제거하지 않습니다.\n\n"
            "5. 불필요한 표현만 제거합니다.\n\n"
            "제거 가능한 표현: \"혹시\", \"좀\", \"알려줘\", \"뭐야\", "
            "\"왜 이래\", \"찾아줄 수 있어?\", \"사례\", \"설명\", "
            "\"요약\", 과도한 조사나 감탄 표현\n\n"
            "제거하면 안 되는 표현: 장애 대상, 동작, 에러 타입, 클래스명, 기술명, "
            "원인 후보, 코드, 파일명, 컬럼명\n\n"
            "6. rewritten_query는 가능한 한 짧게 만들되, 핵심 단서를 잃지 않습니다.\n\n"
            "권장 형태:\n"
            "[프로젝트/서비스/모듈] + [대상/동작] + [에러/증상] + [구체 키워드]\n\n"
            "예:\n"
            "원문: \"batch-platform 이벤트 발행 실패와 비슷한 사례 찾아줘\"\n"
            "intent: SIMILAR_CASE\n"
            "좋은 rewrite: \"batch-platform 이벤트 발행 실패\"\n\n"
            "원문: \"로그인 인증 토큰 클래스 로딩 실패 원인이 뭐야?\"\n"
            "intent: ROOT_CAUSE\n"
            "좋은 rewrite: \"로그인 인증 토큰 클래스 로딩 실패\"\n\n"
            "원문: \"배치 컨테이너가 메모리 제한 때문에 비정상 종료된 장애 요약해줘\"\n"
            "intent: SUMMARY\n"
            "좋은 rewrite: \"배치 컨테이너 메모리 제한 비정상 종료\"\n"
            "나쁜 rewrite: \"컨테이너 종료 장애\"\n\n"
            "원문: \"report_status_cd 컬럼이 없다고 나오면서 리포트 화면에서 500이 떠\"\n"
            "좋은 rewrite: \"리포트 조회 report_status_cd 컬럼 없음 500 오류\"\n\n"
            "7. 이미 검색에 적합한 질문은 거의 그대로 유지합니다.\n\n"
            "예:\n"
            "- \"JwtTokenProvider ClassNotFoundException DataAuthService login\"\n"
            "- \"PKIX SSLHandshakeException truststore\"\n"
            "- \"paymentMethod NullPointerException\"\n\n"
            "이런 질문은 단어 순서나 조사만 최소 정리하고 핵심 표현을 삭제하지 않습니다.\n\n"
            "## 출력\n\n"
            "반드시 JSON만 반환하세요.\n"
            "기존 JSON Schema를 유지하세요.\n\n"
            "{\n"
            "  \"intent\": \"ROOT_CAUSE\",\n"
            "  \"retrieval_required\": true,\n"
            "  \"rewritten_query\": \"로그인 인증 토큰 클래스 로딩 실패\",\n"
            "  \"reason\": \"사용자가 로그인 과정의 클래스 로딩 실패 원인을 묻고 있음\",\n"
            "  \"query_sufficient\": true,\n"
            "  \"missing_information\": [],\n"
            "  \"clarification_required\": false,\n"
            "  \"clarification_question\": null\n"
            "}"
        )

    def _parse_query_analysis(
        self,
        text: str | None,
        *,
        allow_json_extraction: bool,
    ) -> QueryAnalysis | None:
        if not text or not text.strip():
            return None
        try:
            json_text = extract_first_json_object(text) if allow_json_extraction else text
            return QueryAnalysis.model_validate_json(json_text or text)
        except ValidationError:
            return None

    def _normalize_query_analysis(
        self,
        analysis: QueryAnalysis,
        question: str,
    ) -> QueryAnalysis:
        if analysis.intent == "OUT_OF_SCOPE":
            return QueryAnalysis(
                intent="OUT_OF_SCOPE",
                retrieval_required=False,
                rewritten_query=None,
                reason=analysis.reason,
                query_sufficient=True,
                missing_information=[],
                clarification_required=False,
                clarification_question=None,
            )
        if not analysis.query_sufficient:
            missing_information = (
                analysis.missing_information
                if analysis.missing_information
                else ["symptom_or_error"]
            )
            return QueryAnalysis(
                intent=analysis.intent,
                retrieval_required=True,
                rewritten_query=None,
                reason=analysis.reason,
                query_sufficient=False,
                missing_information=missing_information,
                clarification_required=True,
                clarification_question=(
                    analysis.clarification_question
                    or "어떤 기능에서 어떤 오류나 증상이 발생했는지 알려주세요."
                ),
            )
        rewritten_query = (analysis.rewritten_query or question).strip()
        return QueryAnalysis(
            intent=analysis.intent,
            retrieval_required=True,
            rewritten_query=rewritten_query or question.strip(),
            reason=analysis.reason,
            query_sufficient=True,
            missing_information=[],
            clarification_required=False,
            clarification_question=None,
        )

    def _fallback_query_analysis(
        self,
        question: str,
        *,
        history_messages: list[ConversationHistoryMessage] | None = None,
    ) -> QueryAnalysis:
        history_text = " ".join(message.content for message in (history_messages or []))
        combined = f"{history_text} {question}".strip()
        lowered = combined.lower()
        if self._is_vague_incident_question(question) and not history_text.strip():
            return QueryAnalysis(
                intent="SUMMARY",
                retrieval_required=True,
                rewritten_query=None,
                reason="검색에 사용할 구체적인 장애 증상이나 오류 단서가 부족합니다.",
                query_sufficient=False,
                missing_information=["symptom_or_error"],
                clarification_required=True,
                clarification_question="어떤 기능에서 어떤 오류나 증상이 발생했는지 알려주세요.",
            )
        incident_terms = [
            "장애",
            "에러",
            "오류",
            "exception",
            "error",
            "null",
            "로그",
            "로그인",
            "결제",
            "api",
            "timeout",
            "실패",
            "접속",
            "캐시",
            "서버",
            "종료",
            "컨테이너",
        ]
        if not any(term in lowered for term in incident_terms):
            return QueryAnalysis(
                intent="OUT_OF_SCOPE",
                retrieval_required=False,
                rewritten_query=None,
                reason="장애 검색과 관련된 키워드가 확인되지 않았습니다.",
                query_sufficient=True,
                missing_information=[],
                clarification_required=False,
                clarification_question=None,
            )
        if not self._has_searchable_incident_clue(question, history_text):
            return QueryAnalysis(
                intent="SUMMARY",
                retrieval_required=True,
                rewritten_query=None,
                reason="검색에 사용할 구체적인 장애 증상이나 오류 단서가 부족합니다.",
                query_sufficient=False,
                missing_information=["symptom_or_error"],
                clarification_required=True,
                clarification_question="어떤 기능에서 어떤 오류나 증상이 발생했는지 알려주세요.",
            )
        if any(term in question for term in ("원인", "왜", "이유")):
            intent = "ROOT_CAUSE"
        elif any(term in question for term in ("해결", "조치", "수정")):
            intent = "RESOLUTION"
        elif any(term in question for term in ("비슷", "유사", "사례", "과거")):
            intent = "SIMILAR_CASE"
        else:
            intent = "SUMMARY"
        rewritten_source = (
            combined
            if history_text.strip()
            and not self._has_searchable_incident_clue(question, "")
            else question
        )
        return QueryAnalysis(
            intent=intent,
            retrieval_required=True,
            rewritten_query=" ".join(rewritten_source.split()),
            reason="LLM Query Analyzer를 사용할 수 없어 규칙 기반으로 분류했습니다.",
            query_sufficient=True,
            missing_information=[],
            clarification_required=False,
            clarification_question=None,
        )

    def _has_searchable_incident_clue(self, question: str, history_text: str) -> bool:
        text = f"{history_text} {question}".strip().lower()
        if self._is_vague_incident_question(question) and not history_text.strip():
            return False

        technical_markers = [
            "exception",
            "error",
            "timeout",
            "null",
            "failed",
            "failure",
            "http",
            "500",
            "404",
            "sql",
            "redis",
            "docker",
            "container",
        ]
        korean_markers = [
            "로그인",
            "결제",
            "캐시",
            "서버",
            "접속",
            "실패",
            "종료",
            "배치",
            "컨테이너",
            "메모리",
            "컬럼",
            "인증",
            "조회",
            "요청",
            "응답",
        ]
        if any(marker in text for marker in technical_markers + korean_markers):
            return True

        compact_words = [word for word in text.replace("?", " ").split() if word]
        return len(compact_words) >= 3

    def _is_vague_incident_question(self, question: str) -> bool:
        return question.strip().lower() in {
            "안돼요",
            "안돼",
            "오류났어",
            "오류 났어",
            "왜 이러지?",
            "왜 이러지",
            "이거 문제 있어",
            "문제 있어",
        }

    def _generate_llm_answer(
        self,
        *,
        question: str,
        search_response: IncidentSearchResponse,
        history_messages: list[ConversationHistoryMessage] | None = None,
    ) -> str | None:
        if not self._settings.openai_api_key:
            return None

        retrieved_json = json.dumps(
            [result.model_dump(mode="json") for result in search_response.results],
            ensure_ascii=False,
            indent=2,
        )
        history_text = self._format_history_for_prompt(history_messages or [])

        prompt = f"""
        사용자의 장애 관련 질문에 답변한다.

        [답변 원칙]
        - 반드시 검색된 incident 결과만 근거로 답변한다.
        - 검색 결과에 없는 원인, 해결책, 파일명, 코드 변경 내용은 새로 만들어내지 않는다.
        - 관련 incident가 없거나 근거가 부족하면, 근거가 부족하다고 한다.
        - 한국어로 답변한다.
        - 너무 길게 늘이지 말고, 원인/근거/해결 방향 중심으로 정리한다.
        - 대화 history는 맥락 이해를 위한 참고 정보이며 현재 질문보다 우선하지 않는다.
        - history에 있더라도 검색 결과로 뒷받침되지 않는 내용은 사실처럼 답하지 않는다.

        [답변에 포함하면 좋은 내용]
        1. 어떤 장애 사례와 유사한지
        2. 관찰된 에러 타입과 메시지
        3. 추정 가능한 원인 또는 근거
        4. 실제 해결 이력이 있다면 해결 방법
        5. 관련 로그, 티켓, PR 근거

        [최근 대화 history]
        {history_text}

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

    def _format_history_for_prompt(
        self,
        history_messages: list[ConversationHistoryMessage],
    ) -> str:
        if not history_messages:
            return "없음"
        return "\n".join(
            f"{message.role}: {message.content}" for message in history_messages
        )

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
