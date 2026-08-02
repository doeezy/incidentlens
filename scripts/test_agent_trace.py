from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents import IncidentAnswerAgent
from app.schemas.incident_search import IncidentSearchResponse, IncidentSearchResult
from app.tracing import (
    AgentTraceConfidence,
    AgentTraceConfidenceEvaluation,
    AgentTraceRetrieval,
    AgentTraceRetrievalCandidate,
)


class StubRetrievalService:
    def __init__(self, incident_id: uuid.UUID) -> None:
        self.incident_id = incident_id
        self.last_retrieval_ms = 0.12
        self.last_confidence_ms = 0.34
        self.last_trace_retrieval = AgentTraceRetrieval(
            vector_candidate_count=1,
            bm25_candidate_count=1,
            rrf_candidate_count=1,
            vector_candidates=[
                AgentTraceRetrievalCandidate(
                    search_type="VECTOR",
                    incident_id=incident_id,
                    rank=1,
                    raw_score=0.9,
                    vector_score=0.9,
                    distance=0.1,
                )
            ],
            bm25_candidates=[
                AgentTraceRetrievalCandidate(
                    search_type="BM25",
                    incident_id=incident_id,
                    rank=1,
                    raw_score=7.0,
                    bm25_score=7.0,
                )
            ],
            rrf_candidates=[
                AgentTraceRetrievalCandidate(
                    search_type="RRF",
                    incident_id=incident_id,
                    rank=1,
                    raw_score=0.03,
                    rrf_score=0.03,
                    vector_rank=1,
                    bm25_rank=1,
                )
            ],
        )
        self.last_trace_confidence = AgentTraceConfidence(
            batch_input_candidate_ids=[incident_id],
            llm_evaluations=[
                AgentTraceConfidenceEvaluation(
                    incident_id=incident_id,
                    confidence="high",
                    confidence_score=0.9,
                    should_include=True,
                    reason="동일 장애",
                )
            ],
            ranking=[incident_id],
            selected_incident_id=incident_id,
            selected_incident_ids=[incident_id],
        )

    def search(self, **kwargs):
        return IncidentSearchResponse(
            query=kwargs["query"],
            top_k=kwargs["top_k"],
            project_name=kwargs.get("project_name"),
            results=[
                IncidentSearchResult(
                    incident_id=self.incident_id,
                    score=0.03,
                    distance=0.1,
                    vector_rank=1,
                    keyword_rank=1,
                    rrf_rank=1,
                    vector_score=0.9,
                    bm25_score=7.0,
                    rrf_score=0.03,
                    confidence="high",
                    confidence_score=0.9,
                    confidence_reason="동일 장애",
                    project_name="data-portal",
                    status="resolved",
                    first_detected_at=datetime.now(timezone.utc),
                    last_seen_at=None,
                    resolved_at=None,
                    summary="로그인 클래스 로딩 실패",
                    error_type="ClassNotFoundException",
                    error_message="JwtTokenProvider",
                    root_cause=None,
                    suspected_cause="classpath 누락",
                    resolution="빌드 의존성 추가",
                    keywords=["login"],
                    domain_tags=["auth"],
                    evidence_logs=[],
                    evidence_tickets=[],
                    evidence_prs=[],
                )
            ],
        )


class AgentTraceTest(unittest.TestCase):
    def test_answer_builds_json_serializable_trace_without_response_field(self) -> None:
        incident_id = uuid.uuid4()
        agent = IncidentAnswerAgent(
            settings=SimpleNamespace(openai_api_key=None, agent_trace_debug=False),
            retrieval_service=StubRetrievalService(incident_id),
        )

        response = agent.answer(
            question="로그인 장애 원인 알려줘",
            top_k=3,
            project_name="data-portal",
            request_id="req-test",
        )

        self.assertFalse(hasattr(response, "trace"))
        self.assertIsNotNone(agent.last_trace)
        assert agent.last_trace is not None
        self.assertEqual(agent.last_trace.request_id, "req-test")
        self.assertEqual(agent.last_trace.trace_version, "v1")
        self.assertEqual(agent.last_trace.query.reason, "LLM Query Analyzer를 사용할 수 없어 규칙 기반으로 분류했습니다.")
        self.assertEqual(agent.last_trace.retrieval.vector_candidate_count, 1)
        self.assertEqual(agent.last_trace.retrieval.bm25_candidate_count, 1)
        self.assertEqual(agent.last_trace.retrieval.rrf_candidate_count, 1)
        self.assertEqual(agent.last_trace.confidence.selected_incident_id, incident_id)
        self.assertEqual(agent.last_trace.answer.incident_id, incident_id)
        self.assertIn("trace_id", agent.last_trace.model_dump_json())


if __name__ == "__main__":
    unittest.main()
