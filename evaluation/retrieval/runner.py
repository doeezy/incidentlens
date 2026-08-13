from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.config import Settings
from app.services.retrieval import IncidentRetrievalService, RetrievalStageCandidate
from evaluation.common import EVALUATION_RESULTS_DIR, REPORTS_DIR, utc_now_iso, write_json
from evaluation.datasets.models import RetrievalDataset, RetrievalQuery
from evaluation.retrieval.metrics import rank_of, retrieval_metrics, retrieval_metrics_by_query_type
from evaluation.reports.retrieval_report import write_retrieval_report

RetrievalMethod = Literal["vector", "bm25", "hybrid"]


def run_retrieval_experiment(
    *,
    session: Session,
    settings: Settings,
    dataset: RetrievalDataset,
    output_dir: Path | None = None,
    top_k: int = 5,
    candidate_limit: int = 20,
    rrf_k: int = 60,
) -> dict[str, Any]:
    if dataset.status != "frozen":
        raise ValueError("Retrieval experiments must use retrieval_queries_frozen.json.")

    service = IncidentRetrievalService.from_session(session=session, settings=settings)
    base_output_dir = output_dir or EVALUATION_RESULTS_DIR / "retrieval"
    method_payloads: dict[str, dict[str, Any]] = {}
    for method in ("vector", "bm25", "hybrid"):
        cases = [
            _run_one_query(
                service=service,
                query=query,
                method=method,
                top_k=top_k,
                candidate_limit=candidate_limit,
                rrf_k=rrf_k,
            )
            for query in dataset.queries
        ]
        payload = {
            "experiment": "retrieval",
            "method": method,
            "generated_at": utc_now_iso(),
            "dataset": {
                "name": dataset.dataset_name,
                "status": dataset.status,
                "query_count": len(dataset.queries),
            },
            "parameters": {
                "top_k": top_k,
                "candidate_limit": candidate_limit,
                "rrf_k": rrf_k,
                "embedding_model": settings.embedding_model_name,
            },
            "metrics": {
                "overall": retrieval_metrics(cases, recall_k=top_k),
                "by_query_type": retrieval_metrics_by_query_type(cases, recall_k=top_k),
            },
            "cases": cases,
        }
        method_payloads[method] = payload
        write_json(base_output_dir / f"{method}.json", payload)

    failure_payload = {
        "generated_at": utc_now_iso(),
        "top_k": top_k,
        "cases": analyze_retrieval_failures(method_payloads, top_k=top_k),
    }
    write_json(base_output_dir / "failure_analysis.json", failure_payload)
    write_retrieval_report(
        method_payloads=method_payloads,
        failure_payload=failure_payload,
        output_path=REPORTS_DIR / "retrieval_experiment.md",
        top_k=top_k,
    )
    return {"methods": method_payloads, "failure_analysis": failure_payload}


def analyze_retrieval_failures(
    method_payloads: dict[str, dict[str, Any]],
    *,
    top_k: int,
) -> dict[str, list[dict[str, Any]]]:
    by_method = {
        method: {case["query_id"]: case for case in payload["cases"]}
        for method, payload in method_payloads.items()
    }
    output: dict[str, list[dict[str, Any]]] = {
        "bm25_success_vector_failure": [],
        "vector_success_bm25_failure": [],
        "vector_bm25_failure_hybrid_success": [],
        "hybrid_rank_drop": [],
        "all_methods_failure": [],
    }
    for query_id in by_method["hybrid"]:
        vector = by_method["vector"][query_id]
        bm25 = by_method["bm25"][query_id]
        hybrid = by_method["hybrid"][query_id]
        vector_hit = _success(vector, top_k)
        bm25_hit = _success(bm25, top_k)
        hybrid_hit = _success(hybrid, top_k)
        detail = _failure_detail(vector=vector, bm25=bm25, hybrid=hybrid)
        if bm25_hit and not vector_hit:
            output["bm25_success_vector_failure"].append(detail)
        if vector_hit and not bm25_hit:
            output["vector_success_bm25_failure"].append(detail)
        if not vector_hit and not bm25_hit and hybrid_hit:
            output["vector_bm25_failure_hybrid_success"].append(detail)
        if _rank_drop(vector, hybrid) or _rank_drop(bm25, hybrid):
            output["hybrid_rank_drop"].append(detail)
        if not vector_hit and not bm25_hit and not hybrid_hit:
            output["all_methods_failure"].append(detail)
    return output


def _run_one_query(
    *,
    service: IncidentRetrievalService,
    query: RetrievalQuery,
    method: RetrievalMethod,
    top_k: int,
    candidate_limit: int,
    rrf_k: int,
) -> dict[str, Any]:
    started = perf_counter()
    if method == "vector":
        candidates = service.search_vector_candidates_for_evaluation(
            query=query.query_text,
            limit=candidate_limit,
            project_name=query.project_name,
        )
    elif method == "bm25":
        candidates = service.search_bm25_candidates_for_evaluation(
            query=query.query_text,
            limit=candidate_limit,
            project_name=query.project_name,
        )
    else:
        candidates = service.search_hybrid_candidates_for_evaluation(
            query=query.query_text,
            limit=candidate_limit,
            candidate_limit=candidate_limit,
            rrf_k=rrf_k,
            project_name=query.project_name,
        )
    latency_ms = (perf_counter() - started) * 1000.0
    result_rows = [_candidate_payload(item) for item in candidates]
    expected_rank = rank_of(query.expected_incident_id, result_rows)
    return {
        "query_id": query.query_id,
        "query_text": query.query_text,
        "query_type": query.query_type,
        "project_name": query.project_name,
        "expected_incident_id": query.expected_incident_id,
        "expected_rank": expected_rank,
        "top1_hit": expected_rank == 1,
        f"recall_at_{top_k}": expected_rank is not None and expected_rank <= top_k,
        "reciprocal_rank": (1.0 / expected_rank) if expected_rank else 0.0,
        "latency_ms": latency_ms,
        "results": result_rows,
    }


def _candidate_payload(item: RetrievalStageCandidate) -> dict[str, Any]:
    return {
        "incident_id": str(item.incident_id),
        "rank": item.rank,
        "raw_score": item.raw_score,
        "vector_score": item.vector_score,
        "bm25_score": item.bm25_score,
        "rrf_score": item.rrf_score,
    }


def _success(case: dict[str, Any], top_k: int) -> bool:
    rank = case.get("expected_rank")
    return rank is not None and int(rank) <= top_k


def _rank_drop(single: dict[str, Any], hybrid: dict[str, Any]) -> bool:
    single_rank = single.get("expected_rank")
    hybrid_rank = hybrid.get("expected_rank")
    if single_rank is None:
        return False
    if hybrid_rank is None:
        return True
    return int(hybrid_rank) > int(single_rank)


def _failure_detail(
    *,
    vector: dict[str, Any],
    bm25: dict[str, Any],
    hybrid: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query_id": hybrid["query_id"],
        "query": hybrid["query_text"],
        "query_type": hybrid["query_type"],
        "expected_incident_id": hybrid["expected_incident_id"],
        "methods": {
            "vector": _method_detail(vector),
            "bm25": _method_detail(bm25),
            "hybrid": _method_detail(hybrid),
        },
    }


def _method_detail(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_rank": case.get("expected_rank"),
        "latency_ms": case.get("latency_ms"),
        "top_k": case.get("results", []),
    }

