from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models.incident import Incident
from app.repositories.incident_repository import IncidentBm25SearchHit
from app.services.retrieval.incident_retrieval_service import (
    _BatchConfidenceEval,
    _BatchConfidenceEvaluation,
    _ConfidenceEval,
    _HybridConfidenceInput,
    _RrfSearchHit,
    _VectorSearchHit,
    ConfidenceTelemetry,
    IncidentRetrievalService,
)


class FakeLlm:
    def __init__(self, response: str | None = None) -> None:
        self.response = response or json.dumps(
            {
                "confidence": "high",
                "confidence_score": 0.9,
                "reason": "테스트 응답",
            },
            ensure_ascii=False,
        )
        self.messages: list[dict[str, str]] | None = None

    def chat_json_schema_strict(self, messages, *, schema_model, schema_name):
        self.messages = messages
        return self.response

    def chat_json_object(self, messages):
        self.messages = messages
        return self.response


class ConfidencePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.incident = Incident(
            id=uuid.uuid4(),
            project_name="data-portal",
            module_name="auth",
            class_name="AuthService",
            method_name="login",
            status="resolved",
            occurred_at=datetime(2026, 5, 7, 10, 0, 0),
            first_detected_at=datetime(2026, 5, 7, 10, 0, 0),
            primary_error_type="ClassNotFoundException",
            primary_error_message="com.example.auth.JwtTokenProvider",
            primary_error_summary="로그인 인증 클래스 로딩 실패",
            error_keywords=["로그인", "JwtTokenProvider"],
            domain_tags=["auth"],
            suspected_cause="classpath 누락",
            resolution_summary="빌드 의존성 추가",
        )

    def service(self) -> IncidentRetrievalService:
        service = IncidentRetrievalService.__new__(IncidentRetrievalService)
        service._confidence_telemetry = ConfidenceTelemetry()
        service._settings = SimpleNamespace(openai_api_key="test")
        service._llm = FakeLlm()
        return service

    def confidence_input(
        self,
        *,
        vector_rank=None,
        vector_score=None,
        bm25_rank=None,
        bm25_score=None,
        rrf_rank=1,
        rrf_score=0.03,
        query_intent=None,
        query="로그인 ClassNotFoundException",
    ) -> _HybridConfidenceInput:
        return _HybridConfidenceInput(
            query=query,
            incident=self.incident,
            vector_rank=vector_rank,
            vector_score=vector_score,
            bm25_rank=bm25_rank,
            bm25_score=bm25_score,
            rrf_rank=rrf_rank,
            rrf_score=rrf_score,
            query_intent=query_intent,
        )

    def test_bm25_top1_rrf_top1_low_vector_calls_llm(self) -> None:
        service = self.service()
        calls = 0

        def fake_llm(confidence_input):
            nonlocal calls
            calls += 1
            return _ConfidenceEval(confidence="high", confidence_score=0.8, reason="ok")

        service._evaluate_confidence_with_llm = fake_llm
        result = service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=7,
                vector_score=0.01,
                bm25_rank=1,
                bm25_score=10.0,
                rrf_rank=1,
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(calls, 1)

    def test_both_vector_and_bm25_evidence_is_sent_to_llm(self) -> None:
        service = self.service()
        fake_llm = FakeLlm()
        service._llm = fake_llm

        service._evaluate_confidence_with_llm(
            confidence_input=self.confidence_input(
                vector_rank=2,
                vector_score=0.2,
                bm25_rank=1,
                bm25_score=8.0,
                rrf_rank=1,
            )
        )

        assert fake_llm.messages is not None
        payload = json.loads(fake_llm.messages[1]["content"])
        evidence = payload["retrieval_evidence"]
        self.assertTrue(evidence["included_in_vector"])
        self.assertTrue(evidence["included_in_bm25"])
        self.assertTrue(evidence["included_in_both_vector_and_bm25"])
        self.assertEqual(evidence["vector_rank"], 2)
        self.assertEqual(evidence["bm25_rank"], 1)
        self.assertEqual(evidence["rrf_rank"], 1)

    def test_vector_only_high_score_still_calls_llm(self) -> None:
        service = self.service()
        calls = 0

        def fake_llm(confidence_input):
            nonlocal calls
            calls += 1
            return _ConfidenceEval(confidence="high", confidence_score=0.9, reason="ok")

        service._evaluate_confidence_with_llm = fake_llm
        service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=1,
                vector_score=0.8,
                bm25_rank=None,
                rrf_rank=1,
            )
        )
        self.assertEqual(calls, 1)

    def test_vector_only_very_low_score_can_reject_before_llm(self) -> None:
        service = self.service()
        calls = 0

        def fake_llm(confidence_input):
            nonlocal calls
            calls += 1
            return _ConfidenceEval(confidence="high", confidence_score=0.9, reason="ok")

        service._evaluate_confidence_with_llm = fake_llm
        result = service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=8,
                vector_score=0.01,
                bm25_rank=None,
                rrf_rank=8,
            )
        )
        self.assertIsNone(result)
        self.assertEqual(calls, 0)

    def test_bm25_only_calls_llm(self) -> None:
        service = self.service()
        calls = 0

        def fake_llm(confidence_input):
            nonlocal calls
            calls += 1
            return _ConfidenceEval(confidence="medium", confidence_score=0.7, reason="ok")

        service._evaluate_confidence_with_llm = fake_llm
        result = service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=None,
                vector_score=None,
                bm25_rank=1,
                bm25_score=5.0,
                rrf_rank=1,
            )
        )
        self.assertIsNotNone(result)
        self.assertEqual(calls, 1)

    def test_bm25_only_llm_failure_rejects(self) -> None:
        service = self.service()
        service._evaluate_confidence_with_llm = lambda confidence_input: None
        result = service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=None,
                vector_score=None,
                bm25_rank=1,
                bm25_score=5.0,
                rrf_rank=1,
            )
        )
        self.assertIsNone(result)
        self.assertEqual(service._confidence_telemetry.llm_failures, 1)

    def test_rrf_top_with_low_llm_confidence_rejects(self) -> None:
        service = self.service()
        service._evaluate_confidence_with_llm = lambda confidence_input: _ConfidenceEval(
            confidence="low",
            confidence_score=0.2,
            reason="다른 문제",
        )
        result = service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=3,
                vector_score=0.1,
                bm25_rank=1,
                bm25_score=5.0,
                rrf_rank=1,
            )
        )
        self.assertIsNone(result)

    def test_high_rrf_score_is_not_used_as_probability(self) -> None:
        service = self.service()
        calls = 0

        def fake_llm(confidence_input):
            nonlocal calls
            calls += 1
            return _ConfidenceEval(confidence="high", confidence_score=0.9, reason="ok")

        service._evaluate_confidence_with_llm = fake_llm
        result = service._evaluate_confidence(
            confidence_input=self.confidence_input(
                vector_rank=10,
                vector_score=0.01,
                bm25_rank=None,
                rrf_rank=10,
                rrf_score=10.0,
            )
        )
        self.assertIsNone(result)
        self.assertEqual(calls, 0)

    def test_compact_batch_payload_removes_scores_empty_fields_and_limits_lists(
        self,
    ) -> None:
        service = self.service()
        self.incident.error_keywords = [
            "JwtTokenProvider",
            "ClassNotFoundException",
            "login",
            "classpath",
            "dependency",
            "extra-keyword",
        ]
        self.incident.domain_tags = [
            "auth",
            "login",
            "token",
            "java",
            "build",
            "extra-tag",
        ]
        confidence_input = self.confidence_input(
            vector_rank=1,
            vector_score=0.87,
            bm25_rank=None,
            bm25_score=None,
            rrf_rank=1,
            rrf_score=0.032,
        )

        payload = service._batch_confidence_candidate_payload(
            confidence_input,
            query_intent="SIMILAR_CASE",
        )

        self.assertNotIn("rrf_score", payload)
        self.assertNotIn("vector_score", payload)
        self.assertNotIn("bm25_score", payload)
        self.assertNotIn("bm25_rank", payload)
        self.assertNotIn("module_name", payload)
        self.assertNotIn("class_name", payload)
        self.assertEqual(payload["rrf"], 1)
        self.assertEqual(payload["vec"], 1)
        self.assertEqual(len(payload["keywords"]), 5)
        self.assertEqual(len(payload["tags"]), 5)

    def test_compact_batch_payload_uses_intent_specific_context(self) -> None:
        service = self.service()
        self.incident.suspected_cause = "원인" * 150
        self.incident.root_cause_summary = "루트원인" * 100
        self.incident.resolution_summary = "해결" * 200
        self.incident.error_keywords = ["k1", "k2", "k3", "k4", "k5", "k6"]
        self.incident.domain_tags = ["d1", "d2", "d3", "d4", "d5", "d6"]
        confidence_input = self.confidence_input(
            vector_rank=1,
            bm25_rank=1,
            query_intent="ROOT_CAUSE",
            query="data-portal 로그인 장애",
        )

        root_cause_payload = service._batch_confidence_candidate_payload(
            confidence_input,
            query_intent="ROOT_CAUSE",
        )
        resolution_payload = service._batch_confidence_candidate_payload(
            confidence_input,
            query_intent="RESOLUTION",
        )
        summary_payload = service._batch_confidence_candidate_payload(
            confidence_input,
            query_intent="SUMMARY",
        )

        self.assertIn("cause", root_cause_payload)
        self.assertIn("root", root_cause_payload)
        self.assertIn("keywords", root_cause_payload)
        self.assertIn("tags", root_cause_payload)
        self.assertNotIn("resolution", root_cause_payload)
        self.assertLessEqual(len(root_cause_payload["cause"]), 200)
        self.assertLessEqual(len(root_cause_payload["root"]), 200)
        self.assertIn("resolution", resolution_payload)
        self.assertNotIn("cause", resolution_payload)
        self.assertLessEqual(len(resolution_payload["resolution"]), 250)
        self.assertEqual(summary_payload["keywords"], ["k1", "k2", "k3", "k4", "k5"])
        self.assertEqual(summary_payload["tags"], ["d1", "d2", "d3", "d4", "d5"])
        self.assertIn("cause", summary_payload)
        self.assertIn("resolution", summary_payload)
        self.assertLessEqual(len(summary_payload["cause"]), 200)
        self.assertLessEqual(len(summary_payload["resolution"]), 250)


class SearchPathConsistencyTest(unittest.TestCase):
    def test_operating_search_and_evaluation_use_same_confidence_path(self) -> None:
        incident_id = uuid.uuid4()

        class StubService(IncidentRetrievalService):
            def __init__(self) -> None:
                self._confidence_telemetry = ConfidenceTelemetry()

            def _search_hybrid_candidates(self, **kwargs):
                vector_hits = [
                    _VectorSearchHit(
                        incident_id=incident_id,
                        distance=0.1,
                        vector_score=0.9,
                        rank=1,
                    )
                ]
                bm25_hits = [
                    IncidentBm25SearchHit(
                        incident_id=incident_id,
                        bm25_score=5.0,
                        rank=1,
                    )
                ]
                rrf_hits = self._merge_with_rrf(
                    vector_hits=vector_hits,
                    bm25_hits=bm25_hits,
                    top_k=kwargs["top_k"],
                    rrf_k=kwargs["rrf_k"],
                )
                return vector_hits, bm25_hits, rrf_hits

            def _load_incidents(self, incident_ids):
                incident = Incident(
                    id=incident_id,
                    project_name="data-portal",
                    status="resolved",
                    occurred_at=datetime(2026, 5, 7, 10, 0, 0),
                    first_detected_at=datetime(2026, 5, 7, 10, 0, 0),
                    primary_error_type="ClassNotFoundException",
                    primary_error_message="JwtTokenProvider",
                )
                return {incident_id: incident}

            def _load_logs(self, incident_ids):
                return {}

            def _load_tickets(self, incident_ids):
                return {}

            def _load_prs(self, incident_ids):
                return {}

            def _evaluate_batch_confidence_with_llm(self, *, confidence_inputs):
                return _BatchConfidenceEval(
                    evaluations=[
                        _BatchConfidenceEvaluation(
                            incident_id=incident_id,
                            confidence="high",
                            confidence_score=0.9,
                            should_include=True,
                            reason="동일",
                        )
                    ],
                    ranking=[incident_id],
                    no_relevant_candidate=False,
                )

        service = StubService()
        operating = service.search(query="로그인", top_k=3, project_name="data-portal")
        evaluation = service.search_for_evaluation(
            query="로그인",
            top_k=3,
            candidate_limit=20,
            rrf_k=60,
            project_name="data-portal",
        ).search_response

        self.assertEqual(
            [result.incident_id for result in operating.results],
            [result.incident_id for result in evaluation.results],
        )


class BatchMultiCandidateConfidenceResponseTest(unittest.TestCase):
    def incidents(self, count: int = 3) -> list[Incident]:
        return [
            Incident(
                id=uuid.uuid4(),
                project_name="data-portal",
                status="resolved",
                occurred_at=datetime(2026, 5, 7, 10, 0, 0),
                first_detected_at=datetime(2026, 5, 7, 10, 0, 0),
                primary_error_type="ClassNotFoundException",
                primary_error_message=f"error-{index}",
                primary_error_summary=f"summary-{index}",
            )
            for index in range(1, count + 1)
        ]

    def service(
        self,
        incidents: list[Incident],
        batch_eval: _BatchConfidenceEval | None,
    ):
        class StubService(IncidentRetrievalService):
            def __init__(self) -> None:
                self._confidence_telemetry = ConfidenceTelemetry()
                self.batch_calls = 0
                self.individual_calls: list[uuid.UUID] = []
                self._settings = SimpleNamespace(openai_api_key="test")

            def _load_incidents(self, incident_ids):
                return {incident.id: incident for incident in incidents}

            def _load_logs(self, incident_ids):
                return {}

            def _load_tickets(self, incident_ids):
                return {}

            def _load_prs(self, incident_ids):
                return {}

            def _evaluate_batch_confidence_with_llm(self, *, confidence_inputs):
                self.batch_calls += 1
                return batch_eval

            def _evaluate_confidence_with_llm(self, *, confidence_input):
                self.individual_calls.append(confidence_input.incident.id)
                return _ConfidenceEval(
                    confidence="high",
                    confidence_score=0.9,
                    reason="fallback 통과",
                )

        return StubService()

    def batch_eval(
        self,
        incidents: list[Incident],
        *,
        included_indexes: list[int],
        ranking_indexes: list[int],
        high_indexes: list[int] | None = None,
    ) -> _BatchConfidenceEval:
        included_ids = {incidents[index - 1].id for index in included_indexes}
        high_ids = {incidents[index - 1].id for index in (high_indexes or included_indexes)}
        evaluations = []
        for incident in incidents:
            should_include = incident.id in included_ids
            confidence = "high" if incident.id in high_ids else "medium"
            evaluations.append(
                _BatchConfidenceEvaluation(
                    incident_id=incident.id,
                    confidence=confidence if should_include else "low",
                    confidence_score=0.9 if should_include else 0.2,
                    should_include=should_include,
                    reason="관련 있음" if should_include else "무관",
                )
            )
        return _BatchConfidenceEval(
            evaluations=evaluations,
            ranking=[incidents[index - 1].id for index in ranking_indexes],
            no_relevant_candidate=not ranking_indexes,
        )

    def hits(self, incidents: list[Incident]) -> list[_RrfSearchHit]:
        return [
            _RrfSearchHit(
                incident_id=incident.id,
                rrf_rank=index,
                vector_rank=index,
                keyword_rank=index,
                vector_score=0.8 - (index * 0.1),
                bm25_score=10.0 - index,
                distance=0.2 + (index * 0.1),
                rrf_score=1.0 / (60 + index),
            )
            for index, incident in enumerate(incidents, start=1)
        ]

    def test_rrf_first_can_be_reordered_below_second_candidate(self) -> None:
        incidents = self.incidents()
        service = self.service(
            incidents,
            self.batch_eval(incidents, included_indexes=[1, 2], ranking_indexes=[2, 1]),
        )

        response = service._build_search_response(
            query="로그인",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual(
            [result.incident_id for result in response.results],
            [incidents[1].id, incidents[0].id],
        )
        self.assertEqual(service.batch_calls, 1)
        self.assertEqual(service.individual_calls, [])
        self.assertEqual(service._confidence_telemetry.llm_calls, 1)

    def test_rrf_third_candidate_is_preserved(self) -> None:
        incidents = self.incidents()
        service = self.service(
            incidents,
            self.batch_eval(incidents, included_indexes=[3], ranking_indexes=[3]),
        )

        response = service._build_search_response(
            query="로그인",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual([result.incident_id for result in response.results], [incidents[2].id])
        self.assertEqual(service.batch_calls, 1)
        self.assertEqual(service._confidence_telemetry.llm_calls, 1)

    def test_one_related_candidate_returns_only_that_candidate(self) -> None:
        incidents = self.incidents()
        service = self.service(
            incidents,
            self.batch_eval(incidents, included_indexes=[2], ranking_indexes=[2]),
        )

        response = service._build_search_response(
            query="로그인",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual([result.incident_id for result in response.results], [incidents[1].id])
        self.assertEqual(service._confidence_telemetry.passed_candidates, 1)

    def test_two_related_candidates_return_in_llm_ranking_order(self) -> None:
        incidents = self.incidents()
        service = self.service(
            incidents,
            self.batch_eval(incidents, included_indexes=[1, 3], ranking_indexes=[3, 1]),
        )

        response = service._build_search_response(
            query="로그인",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual(
            [result.incident_id for result in response.results],
            [incidents[2].id, incidents[0].id],
        )
        self.assertEqual(service._confidence_telemetry.passed_candidates, 2)

    def test_all_unrelated_candidates_return_empty_results(self) -> None:
        incidents = self.incidents()
        service = self.service(
            incidents,
            self.batch_eval(incidents, included_indexes=[], ranking_indexes=[]),
        )

        response = service._build_search_response(
            query="로그인",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual(response.results, [])
        self.assertEqual(service.batch_calls, 1)
        self.assertEqual(service.individual_calls, [])
        self.assertEqual(service._confidence_telemetry.passed_candidates, 0)

    def test_exact_keyword_candidate_can_rank_above_generic_candidate(self) -> None:
        incidents = self.incidents()
        incidents[0].primary_error_message = "일반 로그인 오류"
        incidents[1].primary_error_message = "JwtTokenProvider ClassNotFoundException"
        service = self.service(
            incidents,
            self.batch_eval(incidents, included_indexes=[1, 2], ranking_indexes=[2, 1]),
        )

        response = service._build_search_response(
            query="JwtTokenProvider ClassNotFoundException",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual(response.results[0].incident_id, incidents[1].id)

    def test_batch_parse_failure_falls_back_to_individual_confidence(self) -> None:
        incidents = self.incidents()
        service = self.service(incidents, batch_eval=None)

        response = service._build_search_response(
            query="로그인",
            top_k=3,
            project_name="data-portal",
            hits=self.hits(incidents),
        )

        self.assertEqual([result.incident_id for result in response.results], [incident.id for incident in incidents])
        self.assertEqual(service.batch_calls, 1)
        self.assertEqual(service.individual_calls, [incident.id for incident in incidents])
        self.assertEqual(service._confidence_telemetry.fallback_executions, 1)
        self.assertEqual(service._confidence_telemetry.llm_failures, 1)


if __name__ == "__main__":
    unittest.main()
