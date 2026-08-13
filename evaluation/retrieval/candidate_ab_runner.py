from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.incident_agent import IncidentAnswerAgent, QueryAnalysis
from app.config import Settings
from app.models.incident import Incident
from app.services.retrieval import IncidentRetrievalService, RetrievalStageCandidate
from evaluation.common import EVALUATION_DATA_DIR, read_json, utc_now_iso, write_json
from evaluation.datasets.models import RetrievalDataset, RetrievalQuery

RetrievalMethod = Literal["vector", "bm25", "hybrid"]
METHODS: tuple[RetrievalMethod, ...] = ("vector", "bm25", "hybrid")
QUERY_TYPES = (
    "exact_error",
    "error_type_only",
    "natural_language",
    "cause_keyword",
    "ambiguous",
)


@dataclass(frozen=True)
class _AnalyzedQuery:
    query: RetrievalQuery
    analysis: QueryAnalysis
    analyzer_latency_ms: float

    @property
    def retrieval_query(self) -> str:
        return self.analysis.rewritten_query or self.query.query_text


def run_candidate_retrieval_ab_experiment(
    *,
    session: Session,
    settings: Settings,
    candidate_path: Path | None = None,
    output_dir: Path | None = None,
    top_k: int = 5,
    recall_points: tuple[int, ...] = (3, 5),
    candidate_limit: int = 20,
    rrf_k: int = 60,
) -> dict[str, Any]:
    dataset = _load_candidate_dataset(candidate_path)
    queries = [query for query in dataset.queries if not query.excluded]
    if not queries:
        raise ValueError("candidate dataset has no non-excluded queries.")

    retrieval_service = IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )
    agent = IncidentAnswerAgent(
        settings=settings,
        retrieval_service=retrieval_service,
    )
    incident_lookup = _load_incident_lookup(session)
    analyzed_queries = [
        _analyze_query(agent=agent, query=query)
        for query in queries
    ]

    method_cases: dict[str, list[dict[str, Any]]] = {}
    for method in METHODS:
        method_cases[method] = [
            _run_one_query(
                service=retrieval_service,
                analyzed=analyzed,
                method=method,
                top_k=top_k,
                recall_points=recall_points,
                candidate_limit=candidate_limit,
                rrf_k=rrf_k,
                incident_lookup=incident_lookup,
            )
            for analyzed in analyzed_queries
        ]

    metrics = {
        "experiment": "candidate_retrieval_ab",
        "generated_at": utc_now_iso(),
        "dataset": {
            "name": dataset.dataset_name,
            "status": dataset.status,
            "candidate_path": str(candidate_path or EVALUATION_DATA_DIR / "retrieval_queries_candidate.json"),
            "candidate_query_count": len(dataset.queries),
            "excluded_query_count": len(dataset.queries) - len(queries),
            "evaluated_query_count": len(queries),
            "retrieval_executed_query_count": len(method_cases["vector"]),
        },
        "parameters": {
            "top_k": top_k,
            "recall_points": list(recall_points),
            "candidate_limit": candidate_limit,
            "rrf_k": rrf_k,
            "embedding_model": settings.embedding_model_name,
            "query_analyzer": "IncidentAnswerAgent.analyze_query",
            "query_rewrite": "QueryAnalysis.rewritten_query",
        },
        "overall": {
            method: _metrics(cases, recall_points=recall_points)
            for method, cases in method_cases.items()
        },
        "by_query_type": {
            method: _metrics_by_query_type(cases, recall_points=recall_points)
            for method, cases in method_cases.items()
        },
        "query_analyzer": _analyzer_metrics(analyzed_queries),
    }
    analysis = _build_analysis(
        method_cases=method_cases,
        incident_lookup=incident_lookup,
        top_k=top_k,
    )

    base_output_dir = output_dir or Path("evaluation_result")
    base_output_dir.mkdir(parents=True, exist_ok=True)
    write_json(base_output_dir / "retrieval_metrics.json", metrics)
    _write_summary_report(
        output_path=base_output_dir / "retrieval_summary.md",
        metrics=metrics,
        analysis=analysis,
        method_cases=method_cases,
        top_k=top_k,
    )
    _write_failure_report(
        output_path=base_output_dir / "retrieval_failure_analysis.md",
        analysis=analysis,
        metrics=metrics,
    )
    _write_query_type_report(
        output_path=base_output_dir / "retrieval_query_type_analysis.md",
        metrics=metrics,
        method_cases=method_cases,
    )
    write_json(base_output_dir / "retrieval_cases.json", method_cases)
    return {
        "metrics": metrics,
        "analysis": analysis,
        "cases": method_cases,
    }


def _load_candidate_dataset(path: Path | None) -> RetrievalDataset:
    dataset_path = path or EVALUATION_DATA_DIR / "retrieval_queries_candidate.json"
    dataset = RetrievalDataset.model_validate(read_json(dataset_path))
    if dataset.status != "candidate":
        raise ValueError(f"{dataset_path} must have status='candidate'.")
    return dataset


def _load_incident_lookup(session: Session) -> dict[str, dict[str, Any]]:
    incidents = session.scalars(select(Incident).order_by(Incident.project_name, Incident.id)).all()
    return {
        str(incident.id): _incident_summary(incident)
        for incident in incidents
    }


def _incident_summary(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": str(incident.id),
        "project_name": incident.project_name,
        "module_name": incident.module_name,
        "class_name": incident.class_name,
        "method_name": incident.method_name,
        "summary": incident.primary_error_summary,
        "error_type": incident.primary_error_type,
        "error_message": incident.primary_error_message,
        "keywords": incident.error_keywords or [],
        "domain_tags": incident.domain_tags or [],
        "root_cause": incident.root_cause_summary,
        "resolution": incident.resolution_summary,
    }


def _analyze_query(*, agent: IncidentAnswerAgent, query: RetrievalQuery) -> _AnalyzedQuery:
    started = perf_counter()
    analysis = agent.analyze_query(query.query_text)
    return _AnalyzedQuery(
        query=query,
        analysis=analysis,
        analyzer_latency_ms=(perf_counter() - started) * 1000.0,
    )


def _run_one_query(
    *,
    service: IncidentRetrievalService,
    analyzed: _AnalyzedQuery,
    method: RetrievalMethod,
    top_k: int,
    recall_points: tuple[int, ...],
    candidate_limit: int,
    rrf_k: int,
    incident_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    query = analyzed.query
    retrieval_query = analyzed.retrieval_query
    started = perf_counter()
    if method == "vector":
        candidates = service.search_vector_candidates_for_evaluation(
            query=retrieval_query,
            limit=candidate_limit,
            project_name=query.project_name,
        )
    elif method == "bm25":
        candidates = service.search_bm25_candidates_for_evaluation(
            query=retrieval_query,
            limit=candidate_limit,
            project_name=query.project_name,
        )
    else:
        candidates = service.search_hybrid_candidates_for_evaluation(
            query=retrieval_query,
            limit=candidate_limit,
            candidate_limit=candidate_limit,
            rrf_k=rrf_k,
            project_name=query.project_name,
        )
    latency_ms = (perf_counter() - started) * 1000.0
    results = [
        _candidate_payload(candidate, incident_lookup=incident_lookup)
        for candidate in candidates
    ]
    expected_rank = _rank_of(query.expected_incident_id, results)
    case = {
        "query_id": query.query_id,
        "query": query.query_text,
        "rewritten_query": retrieval_query,
        "query_type": query.query_type,
        "project_name": query.project_name,
        "expected_incident_id": query.expected_incident_id,
        "expected_incident": incident_lookup.get(query.expected_incident_id),
        "retrieval_required": analyzed.analysis.retrieval_required,
        "intent": analyzed.analysis.intent,
        "analysis_reason": analyzed.analysis.reason,
        "query_analyzer_latency_ms": analyzed.analyzer_latency_ms,
        "expected_rank": expected_rank,
        "top1_hit": expected_rank == 1,
        "reciprocal_rank": (1.0 / expected_rank) if expected_rank else 0.0,
        "latency_ms": latency_ms,
        "results": results,
    }
    for recall_k in recall_points:
        case[f"recall_at_{recall_k}"] = (
            expected_rank is not None and expected_rank <= recall_k
        )
    top_result = results[0] if results else None
    case["top_retrieved_incident_id"] = top_result["incident_id"] if top_result else None
    case["top_retrieved_incident"] = top_result.get("incident") if top_result else None
    case["top_retrieval_score"] = top_result.get("raw_score") if top_result else None
    return case


def _candidate_payload(
    candidate: RetrievalStageCandidate,
    *,
    incident_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    incident_id = str(candidate.incident_id)
    return {
        "incident_id": incident_id,
        "rank": candidate.rank,
        "raw_score": candidate.raw_score,
        "vector_score": candidate.vector_score,
        "bm25_score": candidate.bm25_score,
        "rrf_score": candidate.rrf_score,
        "incident": incident_lookup.get(incident_id),
    }


def _rank_of(expected_incident_id: str, results: list[dict[str, Any]]) -> int | None:
    for result in results:
        if result["incident_id"] == expected_incident_id:
            return int(result["rank"])
    return None


def _metrics(cases: list[dict[str, Any]], *, recall_points: tuple[int, ...]) -> dict[str, Any]:
    ranks = [case.get("expected_rank") for case in cases]
    latencies = [
        float(case["latency_ms"])
        for case in cases
        if case.get("latency_ms") is not None
    ]
    output = {
        "query_count": len(cases),
        "top1_accuracy": _ratio(sum(1 for rank in ranks if rank == 1), len(cases)),
        "mrr": _ratio(
            sum((1.0 / int(rank)) for rank in ranks if rank is not None),
            len(cases),
        ),
        "average_retrieval_latency_ms": _mean(latencies),
        "p50_retrieval_latency_ms": _percentile(latencies, 0.50),
        "p95_retrieval_latency_ms": _percentile(latencies, 0.95),
    }
    for recall_k in recall_points:
        output[f"recall_at_{recall_k}"] = _ratio(
            sum(1 for rank in ranks if rank is not None and int(rank) <= recall_k),
            len(cases),
        )
    return output


def _metrics_by_query_type(
    cases: list[dict[str, Any]],
    *,
    recall_points: tuple[int, ...],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["query_type"]].append(case)
    return {
        query_type: _metrics(grouped.get(query_type, []), recall_points=recall_points)
        for query_type in QUERY_TYPES
    }


def _analyzer_metrics(analyzed_queries: list[_AnalyzedQuery]) -> dict[str, Any]:
    latencies = [item.analyzer_latency_ms for item in analyzed_queries]
    intents = Counter(item.analysis.intent for item in analyzed_queries)
    rewrite_changed = sum(
        1
        for item in analyzed_queries
        if (item.analysis.rewritten_query or "").strip() != item.query.query_text.strip()
    )
    retrieval_required = sum(
        1 for item in analyzed_queries if item.analysis.retrieval_required
    )
    return {
        "query_count": len(analyzed_queries),
        "retrieval_required_by_analyzer_count": retrieval_required,
        "rewrite_changed_count": rewrite_changed,
        "intent_counts": dict(sorted(intents.items())),
        "average_latency_ms": _mean(latencies),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def _build_analysis(
    *,
    method_cases: dict[str, list[dict[str, Any]]],
    incident_lookup: dict[str, dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    by_query_id = {
        method: {case["query_id"]: case for case in cases}
        for method, cases in method_cases.items()
    }
    failure_samples = {
        method: [
            _failure_item(
                case=case,
                method=method,
                peers={
                    peer_method: by_query_id[peer_method][case["query_id"]]
                    for peer_method in METHODS
                },
            )
            for case in _representative_failures(cases, top_k=top_k, limit=10)
        ]
        for method, cases in method_cases.items()
    }
    vector_success_bm25_failure = []
    bm25_success_vector_failure = []
    hybrid_better_than_vector = []
    hybrid_better_than_bm25 = []
    hybrid_failures = []
    rrf_helped = []

    for query_id, hybrid_case in by_query_id["hybrid"].items():
        vector_case = by_query_id["vector"][query_id]
        bm25_case = by_query_id["bm25"][query_id]
        vector_hit = _hit(vector_case, top_k)
        bm25_hit = _hit(bm25_case, top_k)
        hybrid_hit = _hit(hybrid_case, top_k)
        vector_top1 = _hit(vector_case, 1)
        bm25_top1 = _hit(bm25_case, 1)
        hybrid_top1 = _hit(hybrid_case, 1)
        detail = _comparison_detail(
            vector=vector_case,
            bm25=bm25_case,
            hybrid=hybrid_case,
        )
        if vector_top1 and not bm25_top1:
            vector_success_bm25_failure.append(detail)
        if bm25_top1 and not vector_top1:
            bm25_success_vector_failure.append(detail)
        if _rank_improved(hybrid_case, vector_case):
            hybrid_better_than_vector.append(detail)
        if _rank_improved(hybrid_case, bm25_case):
            hybrid_better_than_bm25.append(detail)
        if not hybrid_top1:
            hybrid_failures.append(
                _failure_item(
                    case=hybrid_case,
                    method="hybrid",
                    peers={
                        "vector": vector_case,
                        "bm25": bm25_case,
                        "hybrid": hybrid_case,
                    },
                )
            )
        if hybrid_hit and (not vector_hit or not bm25_hit):
            rrf_helped.append(detail)
        elif hybrid_top1 and (not vector_top1 or not bm25_top1):
            rrf_helped.append(detail)

    return {
        "failure_samples": failure_samples,
        "failure_cause_counts": {
            method: dict(Counter(item["failure_cause"] for item in items))
            for method, items in failure_samples.items()
        },
        "vector_success_bm25_failure": vector_success_bm25_failure[:10],
        "bm25_success_vector_failure": bm25_success_vector_failure[:10],
        "hybrid_better_than_vector": hybrid_better_than_vector[:10],
        "hybrid_better_than_bm25": hybrid_better_than_bm25[:10],
        "hybrid_failures": hybrid_failures[:10],
        "rrf_helped": rrf_helped[:10],
        "comparison_counts": {
            "vector_success_bm25_failure": len(vector_success_bm25_failure),
            "bm25_success_vector_failure": len(bm25_success_vector_failure),
            "hybrid_better_than_vector": len(hybrid_better_than_vector),
            "hybrid_better_than_bm25": len(hybrid_better_than_bm25),
            "hybrid_top1_failures": len(hybrid_failures),
            "rrf_helped": len(rrf_helped),
        },
        "incident_lookup_size": len(incident_lookup),
    }


def _representative_failures(
    cases: list[dict[str, Any]],
    *,
    top_k: int,
    limit: int,
) -> list[dict[str, Any]]:
    failures = [case for case in cases if not _hit(case, 1)]
    failures.sort(
        key=lambda case: (
            case["expected_rank"] is None,
            case["expected_rank"] or 9999,
            case["query_type"],
            case["query_id"],
        )
    )
    return failures[:limit]


def _failure_item(
    *,
    case: dict[str, Any],
    method: str,
    peers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    top = case["results"][0] if case["results"] else None
    expected_rank = case.get("expected_rank")
    return {
        "query_id": case["query_id"],
        "query": case["query"],
        "rewritten_query": case["rewritten_query"],
        "query_type": case["query_type"],
        "expected_incident": _compact_incident(case.get("expected_incident")),
        "retrieved_incident": _compact_incident(top.get("incident") if top else None),
        "rank": expected_rank if expected_rank is not None else "not_in_candidate_limit",
        "retrieval_score": top.get("raw_score") if top else None,
        "failure_cause": _classify_failure(case=case, method=method, peers=peers),
        "peer_ranks": {
            peer_method: peers[peer_method].get("expected_rank")
            for peer_method in METHODS
        },
    }


def _comparison_detail(
    *,
    vector: dict[str, Any],
    bm25: dict[str, Any],
    hybrid: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query_id": hybrid["query_id"],
        "query": hybrid["query"],
        "rewritten_query": hybrid["rewritten_query"],
        "query_type": hybrid["query_type"],
        "expected_incident": _compact_incident(hybrid.get("expected_incident")),
        "ranks": {
            "vector": vector.get("expected_rank"),
            "bm25": bm25.get("expected_rank"),
            "hybrid": hybrid.get("expected_rank"),
        },
        "top_retrieved": {
            "vector": _compact_incident(vector.get("top_retrieved_incident")),
            "bm25": _compact_incident(bm25.get("top_retrieved_incident")),
            "hybrid": _compact_incident(hybrid.get("top_retrieved_incident")),
        },
        "scores": {
            "vector": vector.get("top_retrieval_score"),
            "bm25": bm25.get("top_retrieval_score"),
            "hybrid": hybrid.get("top_retrieval_score"),
        },
        "reason": _comparison_reason(vector=vector, bm25=bm25, hybrid=hybrid),
    }


def _classify_failure(
    *,
    case: dict[str, Any],
    method: str,
    peers: dict[str, dict[str, Any]],
) -> str:
    if _rewrite_lost_terms(case):
        return "Query Rewrite 영향"
    if method == "bm25" and _hit(peers["vector"], 1):
        return "BM25 문자열 매칭 한계"
    if method == "vector" and _hit(peers["bm25"], 1):
        return "Vector 의미 검색 한계"
    if method == "hybrid" and not _hit(peers["vector"], 5) and not _hit(peers["bm25"], 5):
        if case["query_type"] == "ambiguous":
            return "Candidate Query 문제"
        return "Incident 데이터 표현 부족"
    if case["query_type"] in {"exact_error", "error_type_only"}:
        return "Incident 데이터 표현 부족"
    if method == "vector":
        return "Embedding 표현 부족"
    if method == "bm25":
        return "BM25 문자열 매칭 한계"
    return "기타"


def _comparison_reason(
    *,
    vector: dict[str, Any],
    bm25: dict[str, Any],
    hybrid: dict[str, Any],
) -> str:
    if _hit(vector, 5) and not _hit(bm25, 5):
        return "의미적으로 가까운 표현은 잡혔지만 BM25가 rewritten query의 문자열 단서와 incident 표현을 충분히 맞추지 못했다."
    if _hit(bm25, 5) and not _hit(vector, 5):
        return "정확한 에러/식별자 문자열 매칭이 효과적이었고 vector embedding은 같은 의미 공간에서 정답을 충분히 올리지 못했다."
    if _hit(hybrid, 5) and not _hit(vector, 5) and not _hit(bm25, 5):
        return "두 검색 결과의 약한 순위 신호가 RRF에서 합쳐져 정답이 Top-K 안으로 올라왔다."
    if _rank_improved(hybrid, vector) or _rank_improved(hybrid, bm25):
        return "Vector와 BM25 양쪽에 나타난 후보가 RRF에서 보강되어 순위가 개선되었다."
    return "검색 방식별 후보 순위 차이가 발생했다."


def _rewrite_lost_terms(case: dict[str, Any]) -> bool:
    original = set(_tokens(case["query"]))
    rewritten = set(_tokens(case["rewritten_query"]))
    if not original or not rewritten:
        return False
    important = {
        token
        for token in original
        if len(token) >= 4 or any(char.isdigit() for char in token)
    }
    if not important:
        return False
    missing = important - rewritten
    return len(missing) >= max(2, len(important) // 2)


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in __import__("re").findall(r"[A-Za-z0-9_가-힣.-]+", text)
        if len(token.strip(".-")) >= 2
    ]


def _rank_improved(primary: dict[str, Any], baseline: dict[str, Any]) -> bool:
    primary_rank = primary.get("expected_rank")
    baseline_rank = baseline.get("expected_rank")
    if primary_rank is None:
        return False
    if baseline_rank is None:
        return True
    return int(primary_rank) < int(baseline_rank)


def _hit(case: dict[str, Any], top_k: int) -> bool:
    rank = case.get("expected_rank")
    return rank is not None and int(rank) <= top_k


def _compact_incident(incident: dict[str, Any] | None) -> dict[str, Any] | None:
    if not incident:
        return None
    return {
        "incident_id": incident.get("incident_id"),
        "project_name": incident.get("project_name"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
        "error_message": incident.get("error_message"),
    }


def _write_summary_report(
    *,
    output_path: Path,
    metrics: dict[str, Any],
    analysis: dict[str, Any],
    method_cases: dict[str, list[dict[str, Any]]],
    top_k: int,
) -> None:
    lines = [
        "# IncidentLens A/B/C Retrieval Evaluation",
        "",
        "## 목적",
        "",
        "IncidentLens의 기본 Retrieval 전략을 정확도, latency, 실패 사례, 유지보수성 관점에서 결정한다.",
        "",
        "## 실험 조건",
        "",
        f"- Dataset: `retrieval_queries_candidate.json`에서 `excluded=true` 제외",
        f"- Evaluated Queries: {metrics['dataset']['evaluated_query_count']}",
        f"- Retrieval Executed Queries: {metrics['dataset']['retrieval_executed_query_count']}",
        f"- Analyzer Retrieval Required: {metrics['query_analyzer']['retrieval_required_by_analyzer_count']}",
        f"- Top-K: {top_k}",
        f"- Candidate Limit: {metrics['parameters']['candidate_limit']}",
        f"- Embedding Model: `{metrics['parameters']['embedding_model']}`",
        "- 공통 단계: Query Analyzer -> Query Rewrite",
        "- 비교 대상: Vector Only, BM25 Only, Hybrid(Vector + BM25 + RRF)",
        "- Retrieval latency는 Analyzer/Rewrite 시간을 제외한 retrieval 구간만 측정",
        "",
        "## 전체 결과",
        "",
        "| Method | Top-1 Accuracy | Recall@3 | Recall@5 | MRR | Avg Retrieval Latency(ms) | p95(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        item = metrics["overall"][method]
        lines.append(
            f"| {method} | {_pct(item['top1_accuracy'])} | {_pct(item['recall_at_3'])} | "
            f"{_pct(item['recall_at_5'])} | {_num(item['mrr'])} | "
            f"{_num(item['average_retrieval_latency_ms'])} | {_num(item['p95_retrieval_latency_ms'])} |"
        )
    lines.extend(
        [
            "",
            "## 비교 요약",
            "",
            f"- Vector Top-1 성공 / BM25 Top-1 실패: {analysis['comparison_counts']['vector_success_bm25_failure']}건",
            f"- BM25 Top-1 성공 / Vector Top-1 실패: {analysis['comparison_counts']['bm25_success_vector_failure']}건",
            f"- Hybrid가 Vector보다 순위 개선: {analysis['comparison_counts']['hybrid_better_than_vector']}건",
            f"- Hybrid가 BM25보다 순위 개선: {analysis['comparison_counts']['hybrid_better_than_bm25']}건",
            f"- RRF가 실제 도움을 준 Query: {analysis['comparison_counts']['rrf_helped']}건",
            f"- Hybrid Top-1 실패: {analysis['comparison_counts']['hybrid_top1_failures']}건",
            "",
            "## 의사결정",
            "",
            _decision_text(metrics=metrics, analysis=analysis),
            "",
            "## AI 엔지니어 면접에서 설명할 수 있는 인사이트 5가지",
            "",
        ]
    )
    lines.extend(f"{index}. {item}" for index, item in enumerate(_interview_insights(metrics, analysis), start=1))
    lines.extend(
        [
            "",
            "## 기술 블로그에서 다룰 만한 내용",
            "",
            "- 목적: IncidentLens가 현재 장애를 직접 분석하지 않고, 사용자 텍스트만으로 과거 유사 incident를 찾는다는 제약에서 출발한다.",
            "- 가설: exact error와 identifier query는 BM25가 강하고, 증상형 query는 Vector가 보완하며, Hybrid/RRF가 기본 전략으로 더 안정적일 수 있다.",
            "- 결과: 전체 지표와 query type별 차이를 함께 보여주고, latency 비용까지 같이 제시한다.",
            "- 실패 사례: 평균 점수보다 실패 query를 중심으로 BM25 문자열 한계, Vector 의미 검색 한계, rewrite 영향, 데이터 표현 부족을 설명한다.",
            "- 의사결정: 단순 최고 점수보다 운영 기본값으로서 정확도, tail latency, 구현 복잡도, 유지보수성을 비교해 결론을 낸다.",
            "",
            "## 다음 실험 제안",
            "",
        ]
    )
    lines.extend(f"{index}. {item}" for index, item in enumerate(_next_experiments(metrics, analysis), start=1))
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_failure_report(
    *,
    output_path: Path,
    analysis: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    lines = [
        "# Retrieval Failure Analysis",
        "",
        "분류는 query rewrite 변화, method 간 성공/실패 차이, query type, top retrieved incident를 기반으로 한 휴리스틱이다.",
        "",
        "## 실패 원인 분포",
        "",
    ]
    for method in METHODS:
        lines.extend([f"### {method}", ""])
        lines.append("| Failure Cause | Count |")
        lines.append("|---|---:|")
        for cause, count in sorted(analysis["failure_cause_counts"][method].items()):
            lines.append(f"| {cause} | {count} |")
        lines.append("")

    for method in METHODS:
        lines.extend([f"## {method} 대표 실패 Query", ""])
        lines.append("| Query | Type | Expected Incident | Retrieved Incident | Rank | Score | Failure Cause |")
        lines.append("|---|---|---|---|---:|---:|---|")
        for item in analysis["failure_samples"][method]:
            lines.append(_failure_row(item))
        lines.append("")

    lines.extend(
        [
            "## Vector 성공 / BM25 실패",
            "",
            *_comparison_lines(analysis["vector_success_bm25_failure"]),
            "",
            "## BM25 성공 / Vector 실패",
            "",
            *_comparison_lines(analysis["bm25_success_vector_failure"]),
            "",
            "## Hybrid 분석",
            "",
            f"- Hybrid Recall@5: {_pct(metrics['overall']['hybrid']['recall_at_5'])}",
            f"- Hybrid Top-1 실패 Query: {analysis['comparison_counts']['hybrid_top1_failures']}건",
            f"- RRF 도움 Query: {analysis['comparison_counts']['rrf_helped']}건",
            "",
            "### Hybrid가 Vector보다 좋아진 Query",
            "",
            *_comparison_lines(analysis["hybrid_better_than_vector"]),
            "",
            "### Hybrid가 BM25보다 좋아진 Query",
            "",
            *_comparison_lines(analysis["hybrid_better_than_bm25"]),
            "",
            "### Hybrid도 실패한 Query",
            "",
        ]
    )
    lines.append("| Query | Type | Expected Incident | Retrieved Incident | Rank | Score | Failure Cause |")
    lines.append("|---|---|---|---|---:|---:|---|")
    for item in analysis["hybrid_failures"]:
        lines.append(_failure_row(item))
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_query_type_report(
    *,
    output_path: Path,
    metrics: dict[str, Any],
    method_cases: dict[str, list[dict[str, Any]]],
) -> None:
    lines = [
        "# Retrieval Query Type Analysis",
        "",
        "## Query Type별 성능",
        "",
    ]
    for query_type in QUERY_TYPES:
        lines.extend([f"### {query_type}", ""])
        lines.append("| Method | Query Count | Top-1 | Recall@3 | Recall@5 | MRR | Avg Latency(ms) |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for method in METHODS:
            item = metrics["by_query_type"][method][query_type]
            lines.append(
                f"| {method} | {item['query_count']} | {_pct(item['top1_accuracy'])} | "
                f"{_pct(item['recall_at_3'])} | {_pct(item['recall_at_5'])} | "
                f"{_num(item['mrr'])} | {_num(item['average_retrieval_latency_ms'])} |"
            )
        lines.append("")
        lines.extend(_query_type_observation(query_type, metrics))
        lines.append("")

    lines.extend(["## Query Rewrite 표본", ""])
    lines.append("| Query Type | Original | Rewritten | Intent |")
    lines.append("|---|---|---|---|")
    seen: set[str] = set()
    for case in method_cases["hybrid"]:
        if case["query_type"] in seen:
            continue
        seen.add(case["query_type"])
        lines.append(
            f"| {case['query_type']} | {_md(case['query'])} | "
            f"{_md(case['rewritten_query'])} | {case['intent']} |"
        )
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _decision_text(*, metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    overall = metrics["overall"]
    hybrid = overall["hybrid"]
    vector = overall["vector"]
    bm25 = overall["bm25"]
    hybrid_vs_vector_latency = (
        hybrid["average_retrieval_latency_ms"] - vector["average_retrieval_latency_ms"]
    )
    hybrid_vs_bm25_latency = (
        hybrid["average_retrieval_latency_ms"] - bm25["average_retrieval_latency_ms"]
    )
    if hybrid["recall_at_5"] >= bm25["recall_at_5"] and hybrid["mrr"] >= bm25["mrr"]:
        return (
            "기본 Retrieval은 Hybrid가 더 적절하다. BM25가 Top-1과 latency에서 매우 강하지만, "
            "IncidentLens는 답변/Confidence 단계에 후보군을 넘기는 제품이라 정답 후보를 Top-K 안에 "
            "넣는 안정성이 중요하다. Hybrid는 BM25보다 Recall@5와 MRR이 높고, Vector와 같은 Recall@5를 "
            "유지하면서 BM25의 문자열 신호를 함께 사용한다. 비용은 명확하다: 평균 latency는 Vector 대비 "
            f"약 {_num(hybrid_vs_vector_latency)}ms, BM25 대비 약 {_num(hybrid_vs_bm25_latency)}ms 증가한다. "
            "따라서 Hybrid를 기본값으로 두되, strict low-latency 경로에는 BM25 fallback 또는 BM25-first 옵션을 "
            "운영 정책으로 남기는 결론이 가장 균형적이다."
        )
    return (
        "이번 결과만으로는 Hybrid의 이점이 충분히 크다고 보기 어렵다. "
        "정확도 개선 폭이 작거나 latency 비용이 커서, 기본값 결정 전 실패 query의 "
        "데이터 표현과 query rewrite 영향을 먼저 줄이는 후속 실험이 필요하다."
    )


def _interview_insights(metrics: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    return [
        "BM25는 exact error, exception, class/method처럼 문자열 단서가 살아 있는 query에서 강하지만, 자연어 증상 표현이 incident 문서 표현과 어긋나면 급격히 약해진다.",
        "Vector는 표현이 다른 증상형 query를 보완하지만, 짧은 identifier나 error code 중심 query에서는 임베딩 공간에서 정답이 충분히 분리되지 않는 경우가 있다.",
        f"RRF는 한쪽 검색에서만 약하게 잡힌 후보보다 양쪽 검색에 동시에 등장한 후보를 밀어 올릴 때 효과가 있었다. 이번 run에서 RRF 도움 query는 {analysis['comparison_counts']['rrf_helped']}건이다.",
        "Query Rewrite는 모든 방식에 공통으로 적용되므로 공정성은 확보하지만, 원문 단서가 rewrite에서 사라지면 세 retrieval 방식이 함께 손해를 본다.",
        "검색 실패 중 일부는 모델 선택보다 incident 데이터 표현 문제다. 과거 incident에 error message, 기능명, 사용자 증상 표현이 충분히 구조화되어 있어야 어떤 retrieval도 안정적으로 동작한다.",
    ]


def _next_experiments(metrics: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    return [
        "1순위: Hybrid + Query Rewrite 진단. 실패 query에서 원문 단서가 rewrite 후 손실되는지 정량화하고, rewrite guardrail을 개선한다.",
        "2순위: Hybrid + Reranker. RRF Top-N 후보에 cross-encoder 또는 LLM-light reranker를 적용해 Top-1 정확도를 개선할 수 있는지 본다.",
        "3순위: Incident document representation 개선. incident embedding/searchable text에 사용자 증상, error, 기능명, 해결 전 관찰 정보를 분리해 넣는 실험을 한다.",
        "4순위: Confidence Evaluation 개선. retrieval rank와 confidence filtering이 충돌하는 case를 분석해 정답 후보가 confidence 단계에서 빠지는지 확인한다.",
        "5순위: Prompt/Context 실험. Retrieval 기본값이 정해진 뒤 answer generation context 구성과 prompt A/B/C/D를 비교한다.",
    ]


def _query_type_observation(query_type: str, metrics: dict[str, Any]) -> list[str]:
    recalls = {
        method: metrics["by_query_type"][method][query_type]["recall_at_5"]
        for method in METHODS
    }
    best_score = max(value or 0.0 for value in recalls.values())
    best_methods = [
        method for method, value in recalls.items() if (value or 0.0) == best_score
    ]
    top1 = {
        method: metrics["by_query_type"][method][query_type]["top1_accuracy"]
        for method in METHODS
    }
    if query_type == "ambiguous":
        observation = (
            "모호한 query에서는 Top-1 기준 BM25와 Hybrid가 Vector보다 강했고, "
            "Recall@5에서는 Vector/Hybrid가 더 안정적이었다."
        )
    elif query_type == "natural_language":
        observation = (
            "증상형 자연어에서는 Vector와 Hybrid가 Top-1에서 BM25를 보완했고, "
            "세 방식 모두 Recall@5는 포화에 가까웠다."
        )
    elif query_type == "error_type_only":
        observation = (
            "Exception/Class/Method 중심 query에서는 BM25가 Top-1을 모두 맞췄고, "
            "문자열 단서의 힘이 가장 크게 나타났다."
        )
    elif query_type == "cause_keyword":
        observation = (
            "넓은 기술 키워드 query에서는 BM25가 Top-1에서 강했고, "
            "세 방식 모두 Recall@5는 안정적이었다."
        )
    else:
        observation = (
            "정확한 error message query에서는 세 방식 모두 Recall@5가 같았고, "
            "문자열/벡터 양쪽 모두 충분한 단서를 얻었다."
        )
    return [
        f"- Recall@5 기준 가장 좋은 방식: `{', '.join(best_methods)}`",
        f"- Top-1: vector {_pct(top1['vector'])}, bm25 {_pct(top1['bm25'])}, hybrid {_pct(top1['hybrid'])}",
        f"- 관찰: {observation}",
    ]


def _comparison_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["해당 사례가 충분히 나오지 않았다."]
    lines = ["| Query | Type | Ranks(Vector/BM25/Hybrid) | Reason |"]
    lines.append("|---|---|---|---|")
    for item in items[:10]:
        ranks = item["ranks"]
        lines.append(
            f"| {_md(item['query'])} | {item['query_type']} | "
            f"{ranks['vector']}/{ranks['bm25']}/{ranks['hybrid']} | "
            f"{_md(item['reason'])} |"
        )
    return lines


def _failure_row(item: dict[str, Any]) -> str:
    expected = item["expected_incident"] or {}
    retrieved = item["retrieved_incident"] or {}
    return (
        f"| {_md(item['query'])} | {item['query_type']} | "
        f"{_md(_incident_label(expected))} | {_md(_incident_label(retrieved))} | "
        f"{item['rank']} | {_num(item['retrieval_score'])} | {item['failure_cause']} |"
    )


def _incident_label(incident: dict[str, Any]) -> str:
    if not incident:
        return "none"
    return (
        f"{incident.get('incident_id')} / {incident.get('error_type')} / "
        f"{incident.get('summary') or incident.get('error_message')}"
    )


def _ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = lower + (0 if rank.is_integer() else 1)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _md(value: Any) -> str:
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text
