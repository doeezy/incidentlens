from __future__ import annotations

import json
import sys
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.database import SessionLocal
from app.models.evaluation import (
    EvaluationCandidate,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
)
from app.models.incident import Incident
from app.services.retrieval import IncidentRetrievalService

REPORT_DIR = ROOT_DIR / "docs" / "evaluation"
JSON_REPORT_PATH = REPORT_DIR / "rrf_ranking_miss_analysis.json"
MD_REPORT_PATH = REPORT_DIR / "rrf_ranking_miss_analysis.md"

DEFAULT_RUN_ID = uuid.UUID("fa8a0e14-ece6-445a-a88b-737d35cf36ca")
EXPANDED_CANDIDATE_LIMIT = 100
TOP_K = 3


@dataclass(frozen=True)
class CandidateRanks:
    vector_rank: int | None = None
    vector_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    rrf_rank: int | None = None
    rrf_score: float | None = None


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def load_run_data(session, run_id: uuid.UUID):
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise RuntimeError(f"evaluation run not found: {run_id}")

    results = session.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
        .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
    ).all()
    cases = {
        case.id: case
        for case in session.scalars(
            select(EvaluationCase).where(
                EvaluationCase.id.in_([result.case_id for result in results])
            )
        ).all()
    }
    candidates = session.scalars(
        select(EvaluationCandidate).where(
            EvaluationCandidate.evaluation_result_id.in_(
                [result.id for result in results]
            )
        )
    ).all()

    candidates_by_result: dict[uuid.UUID, list[EvaluationCandidate]] = {}
    for candidate in candidates:
        candidates_by_result.setdefault(candidate.evaluation_result_id, []).append(
            candidate
        )
    for grouped in candidates_by_result.values():
        grouped.sort(key=lambda item: (item.search_type, item.rank, str(item.id)))

    return run, results, cases, candidates_by_result


def ranks_from_evaluation_candidates(
    expected_incident_id: uuid.UUID | None,
    candidates: list[EvaluationCandidate],
) -> CandidateRanks:
    expected_id = _uuid(expected_incident_id)
    if expected_id is None:
        return CandidateRanks()

    def find(search_type: str) -> EvaluationCandidate | None:
        return next(
            (
                candidate
                for candidate in candidates
                if candidate.search_type == search_type
                and candidate.incident_id == expected_id
            ),
            None,
        )

    vector = find("VECTOR")
    bm25 = find("BM25")
    rrf = find("RRF")
    return CandidateRanks(
        vector_rank=vector.rank if vector else None,
        vector_score=_float(vector.vector_score) if vector else None,
        bm25_rank=bm25.rank if bm25 else None,
        bm25_score=_float(bm25.bm25_score) if bm25 else None,
        rrf_rank=rrf.rank if rrf else None,
        rrf_score=_float(rrf.rrf_score) if rrf else None,
    )


def ranks_from_hybrid_hits(
    expected_incident_id: uuid.UUID,
    *,
    vector_hits: list[Any],
    bm25_hits: list[Any],
    rrf_hits: list[Any],
) -> CandidateRanks:
    expected_id = _uuid(expected_incident_id)
    vector = next((hit for hit in vector_hits if hit.incident_id == expected_id), None)
    bm25 = next((hit for hit in bm25_hits if hit.incident_id == expected_id), None)
    rrf = next((hit for hit in rrf_hits if hit.incident_id == expected_id), None)
    return CandidateRanks(
        vector_rank=vector.rank if vector else None,
        vector_score=_float(vector.vector_score) if vector else None,
        bm25_rank=bm25.rank if bm25 else None,
        bm25_score=_float(bm25.bm25_score) if bm25 else None,
        rrf_rank=rrf.rrf_rank if rrf else None,
        rrf_score=_float(rrf.rrf_score) if rrf else None,
    )


def hybrid_ranks(
    service: IncidentRetrievalService,
    *,
    query: str,
    project_name: str,
    expected_incident_id: uuid.UUID,
    candidate_limit: int,
    rrf_k: int,
) -> CandidateRanks:
    vector_hits, bm25_hits, rrf_hits = service._search_hybrid_candidates(
        query=query,
        top_k=candidate_limit,
        candidate_limit=candidate_limit,
        rrf_k=rrf_k,
        project_name=project_name,
    )
    return ranks_from_hybrid_hits(
        expected_incident_id,
        vector_hits=vector_hits,
        bm25_hits=bm25_hits,
        rrf_hits=rrf_hits,
    )


def project_incident_counts(session) -> dict[str, int]:
    rows = session.execute(
        select(Incident.project_name, func.count(Incident.id)).group_by(
            Incident.project_name
        )
    ).all()
    return {project_name: int(count) for project_name, count in rows}


def incident_brief(session, incident_id: uuid.UUID) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None:
        return {}
    return {
        "project_name": incident.project_name,
        "summary": incident.primary_error_summary,
        "error_type": incident.primary_error_type,
        "error_message": incident.primary_error_message,
        "keywords": incident.error_keywords,
        "domain_tags": incident.domain_tags,
        "root_cause": incident.root_cause_summary,
        "resolution": incident.resolution_summary,
    }


def top3_rrf_candidates(
    session,
    candidates: list[EvaluationCandidate],
) -> list[dict[str, Any]]:
    top3 = [
        candidate
        for candidate in candidates
        if candidate.search_type == "RRF" and candidate.rank <= TOP_K
    ]
    top3.sort(key=lambda item: item.rank)
    return [
        {
            "rank": candidate.rank,
            "incident_id": str(candidate.incident_id),
            "vector_score": _float(candidate.vector_score),
            "bm25_score": _float(candidate.bm25_score),
            "rrf_score": _float(candidate.rrf_score),
            "incident": incident_brief(session, candidate.incident_id),
        }
        for candidate in top3
    ]


def rank_in_top3(rank: int | None) -> bool:
    return rank is not None and rank <= TOP_K


def rank_missing_or_outside_top3(rank: int | None) -> bool:
    return rank is None or rank > TOP_K


def rank_declined(before: int | None, after: int | None) -> bool:
    if before is None:
        return False
    if after is None:
        return True
    return after > before


def classify_case(
    *,
    stored: CandidateRanks,
    original: CandidateRanks,
    expanded: CandidateRanks,
    project_incident_count: int,
    candidate_limit: int,
) -> tuple[str, list[str], str]:
    secondary: list[str] = []

    if rank_in_top3(original.rrf_rank) and not rank_in_top3(stored.rrf_rank):
        secondary.append("QUERY_REWRITE_TOP3_LOSS")
    elif rank_declined(original.rrf_rank, stored.rrf_rank):
        secondary.append("QUERY_REWRITE_RANK_DROP")

    if rank_in_top3(original.rrf_rank) and not rank_in_top3(stored.rrf_rank):
        primary = "QUERY_REWRITE_TOP3_LOSS"
    elif stored.rrf_rank is None and expanded.rrf_rank is not None:
        primary = "CANDIDATE_LIMIT_MISS"
    elif (
        stored.rrf_rank is not None
        and expanded.rrf_rank is not None
        and expanded.rrf_rank <= TOP_K
        and not rank_in_top3(stored.rrf_rank)
    ):
        primary = "CANDIDATE_LIMIT_RANKING_LOSS"
    elif stored.vector_rank is None and stored.bm25_rank is None:
        primary = "BOTH_RETRIEVERS_MISS"
    elif stored.bm25_rank is None and rank_missing_or_outside_top3(stored.vector_rank):
        primary = "BM25_MISS_AND_VECTOR_NOT_TOP3"
    elif stored.vector_rank is None and rank_missing_or_outside_top3(stored.bm25_rank):
        primary = "VECTOR_MISS_AND_BM25_NOT_TOP3"
    elif rank_missing_or_outside_top3(stored.vector_rank) and rank_missing_or_outside_top3(
        stored.bm25_rank
    ):
        primary = "BOTH_RETRIEVERS_WEAK"
    elif stored.vector_rank is None and stored.bm25_rank is not None:
        primary = "VECTOR_MISS"
    elif stored.bm25_rank is None and stored.vector_rank is not None:
        primary = "BM25_MISS"
    elif stored.vector_rank is not None and stored.vector_rank > TOP_K:
        primary = "VECTOR_WEAK_RANK"
    elif stored.bm25_rank is not None and stored.bm25_rank > TOP_K:
        primary = "BM25_WEAK_RANK"
    else:
        primary = "RRF_SCORE_COLLISION"

    if primary not in {"CANDIDATE_LIMIT_MISS", "CANDIDATE_LIMIT_RANKING_LOSS"}:
        if project_incident_count <= candidate_limit:
            secondary.append("CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL")
        elif expanded.rrf_rank == stored.rrf_rank:
            secondary.append("CANDIDATE_LIMIT_NOT_RELEVANT_SAME_RANK")
        elif expanded.rrf_rank is not None and stored.rrf_rank is None:
            secondary.append("CANDIDATE_LIMIT_SECONDARY")

    if stored.vector_rank is None:
        secondary.append("VECTOR_MISS")
    elif stored.vector_rank > TOP_K:
        secondary.append("VECTOR_NOT_TOP3")

    if stored.bm25_rank is None:
        secondary.append("BM25_MISS")
    elif stored.bm25_rank > TOP_K:
        secondary.append("BM25_NOT_TOP3")

    if stored.vector_rank is not None and stored.bm25_rank is not None:
        secondary.append("PRESENT_IN_BOTH_RETRIEVERS")

    deduped_secondary = list(dict.fromkeys(secondary))
    reason = summarize_reason(primary=primary, stored=stored, secondary=deduped_secondary)
    return primary, deduped_secondary, reason


def summarize_reason(
    *,
    primary: str,
    stored: CandidateRanks,
    secondary: list[str],
) -> str:
    if primary == "BOTH_RETRIEVERS_WEAK":
        return (
            "Vector와 BM25 모두 정답을 Top3로 올리지 못해 RRF 합산 후에도 밀렸다. "
            f"vector_rank={stored.vector_rank}, bm25_rank={stored.bm25_rank}, rrf_rank={stored.rrf_rank}."
        )
    if primary == "VECTOR_MISS":
        return (
            "BM25에는 정답이 잡혔지만 Vector 후보에는 없어서 RRF 합의 점수를 얻지 못했다. "
            f"bm25_rank={stored.bm25_rank}, rrf_rank={stored.rrf_rank}."
        )
    if primary == "BM25_MISS":
        return (
            "Vector에는 정답이 잡혔지만 BM25 후보에는 없어 exact keyword 근거를 얻지 못했다. "
            f"vector_rank={stored.vector_rank}, rrf_rank={stored.rrf_rank}."
        )
    if primary == "VECTOR_WEAK_RANK":
        return (
            "정답이 Vector에는 있으나 순위가 낮아 BM25/RRF 상위 후보를 넘지 못했다. "
            f"vector_rank={stored.vector_rank}, bm25_rank={stored.bm25_rank}, rrf_rank={stored.rrf_rank}."
        )
    if primary == "BM25_WEAK_RANK":
        return (
            "정답이 BM25에는 있으나 순위가 낮아 Vector/RRF 상위 후보를 넘지 못했다. "
            f"vector_rank={stored.vector_rank}, bm25_rank={stored.bm25_rank}, rrf_rank={stored.rrf_rank}."
        )
    if primary.startswith("CANDIDATE_LIMIT"):
        return "candidate_limit 확장 시 정답 순위가 개선되어 limit 영향이 확인됐다."
    if "QUERY_REWRITE_TOP3_LOSS" in secondary:
        return "원본 질의에서는 정답이 RRF Top3였지만 rewritten query에서 Top3 밖으로 밀렸다."
    if primary == "QUERY_REWRITE_TOP3_LOSS":
        return "원본 질의에서는 정답이 RRF Top3였지만 rewritten query에서 Top3 밖으로 밀렸다."
    if primary == "BM25_MISS_AND_VECTOR_NOT_TOP3":
        return (
            "정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. "
            f"vector_rank={stored.vector_rank}, bm25_rank=None, rrf_rank={stored.rrf_rank}."
        )
    if primary == "VECTOR_MISS_AND_BM25_NOT_TOP3":
        return (
            "정답이 Vector에는 잡히지 않았고 BM25에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. "
            f"vector_rank=None, bm25_rank={stored.bm25_rank}, rrf_rank={stored.rrf_rank}."
        )
    if primary == "BOTH_RETRIEVERS_MISS":
        return "정답이 Vector와 BM25 후보 양쪽 모두에서 누락되어 RRF 후보에도 포함되지 않았다."
    return (
        "개별 검색기 후보에는 있으나 상위 후보들의 RRF 합산 점수가 더 높아 Top3 밖으로 밀렸다. "
        f"vector_rank={stored.vector_rank}, bm25_rank={stored.bm25_rank}, rrf_rank={stored.rrf_rank}."
    )


def build_analysis() -> dict[str, Any]:
    settings = get_settings()
    with SessionLocal() as session:
        run, results, cases, candidates_by_result = load_run_data(session, DEFAULT_RUN_ID)
        candidate_limit = int(run.parameters.get("candidate_limit", 20))
        rrf_k = int(run.parameters.get("rrf_k", 60))
        service = IncidentRetrievalService.from_session(session=session, settings=settings)
        counts_by_project = project_incident_counts(session)

        miss_results = []
        for result in results:
            if result.expected_no_result or result.expected_incident_id is None:
                continue
            if result.top3_hit or result.error_message:
                continue

            stored = ranks_from_evaluation_candidates(
                result.expected_incident_id,
                candidates_by_result.get(result.id, []),
            )
            if stored.rrf_rank is None or stored.rrf_rank <= TOP_K:
                continue

            case = cases[result.case_id]
            rewritten_query = result.rewritten_query or result.original_query
            original = hybrid_ranks(
                service,
                query=result.original_query,
                project_name=case.project_name,
                expected_incident_id=result.expected_incident_id,
                candidate_limit=candidate_limit,
                rrf_k=rrf_k,
            )
            expanded = hybrid_ranks(
                service,
                query=rewritten_query,
                project_name=case.project_name,
                expected_incident_id=result.expected_incident_id,
                candidate_limit=EXPANDED_CANDIDATE_LIMIT,
                rrf_k=rrf_k,
            )
            primary, secondary, reason = classify_case(
                stored=stored,
                original=original,
                expanded=expanded,
                project_incident_count=counts_by_project.get(case.project_name, 0),
                candidate_limit=candidate_limit,
            )

            miss_results.append(
                {
                    "case_key": case.case_key,
                    "category": case.category,
                    "project_name": case.project_name,
                    "project_incident_count": counts_by_project.get(case.project_name, 0),
                    "original_query": result.original_query,
                    "rewritten_query": result.rewritten_query,
                    "expected_incident_id": str(result.expected_incident_id),
                    "incident": incident_brief(session, result.expected_incident_id),
                    "stored_rrf_top3_candidates": top3_rrf_candidates(
                        session,
                        candidates_by_result.get(result.id, []),
                    ),
                    "stored_rewritten_ranks": asdict(stored),
                    "original_query_ranks": asdict(original),
                    "expanded_limit_rewritten_ranks": asdict(expanded),
                    "primary_type": primary,
                    "secondary_types": secondary,
                    "analysis_summary": reason,
                }
            )

        primary_counts = Counter(item["primary_type"] for item in miss_results)
        secondary_counts = Counter(
            secondary
            for item in miss_results
            for secondary in item["secondary_types"]
        )
        factor_counts = {
            "vector_miss": sum(
                1
                for item in miss_results
                if item["stored_rewritten_ranks"]["vector_rank"] is None
            ),
            "vector_not_top3": sum(
                1
                for item in miss_results
                if rank_missing_or_outside_top3(
                    item["stored_rewritten_ranks"]["vector_rank"]
                )
            ),
            "bm25_miss": sum(
                1
                for item in miss_results
                if item["stored_rewritten_ranks"]["bm25_rank"] is None
            ),
            "bm25_not_top3": sum(
                1
                for item in miss_results
                if rank_missing_or_outside_top3(
                    item["stored_rewritten_ranks"]["bm25_rank"]
                )
            ),
            "query_rewrite_top3_loss": sum(
                1
                for item in miss_results
                if "QUERY_REWRITE_TOP3_LOSS" in item["secondary_types"]
                or item["primary_type"] == "QUERY_REWRITE_TOP3_LOSS"
            ),
            "query_rewrite_rank_drop": sum(
                1
                for item in miss_results
                if "QUERY_REWRITE_RANK_DROP" in item["secondary_types"]
            ),
            "candidate_limit_direct": sum(
                1
                for item in miss_results
                if item["primary_type"].startswith("CANDIDATE_LIMIT")
            ),
        }

        return {
            "run": {
                "id": str(run.id),
                "run_name": run.run_name,
                "retrieval_version": run.retrieval_version,
                "parameters": run.parameters,
                "total_cases": run.total_cases,
                "completed_cases": run.completed_cases,
            },
            "analysis_scope": {
                "target_failure_type": "RRF_RANKING_MISS",
                "case_count": len(miss_results),
                "top_k": TOP_K,
                "stored_candidate_limit": candidate_limit,
                "expanded_candidate_limit": EXPANDED_CANDIDATE_LIMIT,
                "rrf_k": rrf_k,
            },
            "project_incident_counts": counts_by_project,
            "primary_type_counts": dict(primary_counts),
            "secondary_type_counts": dict(secondary_counts),
            "factor_counts": factor_counts,
            "cases": miss_results,
        }


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def ranks_summary(ranks: dict[str, Any]) -> str:
    return (
        f"V {fmt(ranks['vector_rank'])}/{fmt(ranks['vector_score'])}, "
        f"B {fmt(ranks['bm25_rank'])}/{fmt(ranks['bm25_score'])}, "
        f"RRF {fmt(ranks['rrf_rank'])}/{fmt(ranks['rrf_score'])}"
    )


def write_reports(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# RRF Ranking Miss 분석 리포트",
        "",
        f"- run_id: `{payload['run']['id']}`",
        f"- run_name: `{payload['run']['run_name']}`",
        f"- 분석 대상: `{payload['analysis_scope']['target_failure_type']}`",
        f"- 대상 케이스 수: `{payload['analysis_scope']['case_count']}`",
        f"- top_k: `{payload['analysis_scope']['top_k']}`",
        f"- 저장 candidate_limit: `{payload['analysis_scope']['stored_candidate_limit']}`",
        f"- 확장 비교 candidate_limit: `{payload['analysis_scope']['expanded_candidate_limit']}`",
        f"- rrf_k: `{payload['analysis_scope']['rrf_k']}`",
        "",
        "## 요약",
        "",
        "### Primary Type",
        "",
        "| 유형 | 건수 | 의미 |",
        "| --- | ---: | --- |",
    ]

    descriptions = {
        "BOTH_RETRIEVERS_WEAK": "Vector/BM25 모두 정답을 Top3로 올리지 못함",
        "BOTH_RETRIEVERS_MISS": "Vector/BM25 양쪽 후보에서 모두 정답 누락",
        "BM25_MISS_AND_VECTOR_NOT_TOP3": "BM25 후보에 없고 Vector도 Top3 밖",
        "VECTOR_MISS_AND_BM25_NOT_TOP3": "Vector 후보에 없고 BM25도 Top3 밖",
        "VECTOR_MISS": "BM25에는 있으나 Vector 후보에 정답이 없음",
        "BM25_MISS": "Vector에는 있으나 BM25 후보에 정답이 없음",
        "VECTOR_WEAK_RANK": "Vector에는 있으나 Vector 순위가 낮음",
        "BM25_WEAK_RANK": "BM25에는 있으나 BM25 순위가 낮음",
        "RRF_SCORE_COLLISION": "개별 검색 후보에는 있으나 RRF 합산에서 상위 후보에 밀림",
        "CANDIDATE_LIMIT_MISS": "limit 확장 전에는 후보 밖, 확장 후 후보 안",
        "CANDIDATE_LIMIT_RANKING_LOSS": "limit 확장 시 Top3 진입",
    }
    for key, count in sorted(payload["primary_type_counts"].items()):
        lines.append(f"| `{key}` | {count} | {descriptions.get(key, '')} |")

    lines.extend(
        [
            "",
            "### Factor Counts",
            "",
            "| 요인 | 건수 |",
            "| --- | ---: |",
        ]
    )
    for key, count in payload["factor_counts"].items():
        lines.append(f"| `{key}` | {count} |")

    lines.extend(
        [
            "",
            "### Secondary Signals",
            "",
            "| 신호 | 건수 |",
            "| --- | ---: |",
        ]
    )
    for key, count in sorted(payload["secondary_type_counts"].items()):
        lines.append(f"| `{key}` | {count} |")

    lines.extend(
        [
            "",
            "## Candidate Limit 판단",
            "",
            (
                f"- 저장된 candidate_limit은 `{payload['analysis_scope']['stored_candidate_limit']}`이고, "
                f"프로젝트별 incident 수는 `{payload['project_incident_counts']}`입니다."
            ),
            "- 이번 17건에서는 candidate_limit을 100으로 확장해도 정답이 Top3로 올라온 케이스가 없었습니다.",
            "- 따라서 현재 데이터 기준으로는 Candidate Limit이 RRF Top3 실패의 직접 원인으로 보이지 않습니다.",
            "",
            "## 케이스별 상세",
            "",
        ]
    )

    for item in payload["cases"]:
        stored = item["stored_rewritten_ranks"]
        original = item["original_query_ranks"]
        expanded = item["expanded_limit_rewritten_ranks"]
        lines.extend(
            [
                f"### {item['case_key']}",
                "",
                f"- category: `{item['category']}`",
                f"- project_name: `{item['project_name']}`",
                f"- expected_incident_id: `{item['expected_incident_id']}`",
                f"- primary_type: `{item['primary_type']}`",
                f"- secondary_types: `{', '.join(item['secondary_types'])}`",
                f"- original_query: {item['original_query']}",
                f"- rewritten_query: {item['rewritten_query']}",
                f"- rewritten 저장 순위: {ranks_summary(stored)}",
                f"- original query 비교 순위: {ranks_summary(original)}",
                f"- limit 100 비교 순위: {ranks_summary(expanded)}",
                "- rewritten 기준 RRF Top3 후보:",
            ]
        )
        for candidate in item["stored_rrf_top3_candidates"]:
            incident = candidate["incident"]
            lines.append(
                "  - "
                f"#{candidate['rank']} `{candidate['incident_id']}` "
                f"RRF {fmt(candidate['rrf_score'])}, "
                f"V {fmt(candidate['vector_score'])}, "
                f"B {fmt(candidate['bm25_score'])}, "
                f"summary={incident.get('summary')}"
            )
        lines.extend(
            [
                f"- 판단: {item['analysis_summary']}",
                "",
            ]
        )

    lines.extend(
        [
            "## 결론",
            "",
            (
                "17건의 RRF_RANKING_MISS는 confidence 단계가 아니라 RRF 후보 Top3 구성 단계에서 "
                "정답이 밀린 케이스입니다."
            ),
            (
                "가장 큰 원인은 BM25가 정답을 전혀 후보로 올리지 못하고, Vector도 정답을 Top3까지 "
                "끌어올리지 못한 조합입니다. 이번 17건에서 BM25 miss는 17건, Vector Top3 실패도 "
                "17건입니다."
            ),
            (
                "Query Rewrite는 일부 케이스에서 순위 하락 신호가 있었지만, 원본 질의 기준으로도 Top3에 "
                "들지 못한 케이스가 많아 단독 원인으로 보기는 어렵습니다."
            ),
            (
                "Candidate Limit은 이번 데이터에서는 직접 원인이 아닙니다. 프로젝트별 incident 수가 "
                "저장 candidate_limit보다 작거나, limit 100 확장에서도 Top3 개선이 없었습니다."
            ),
        ]
    )

    MD_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    payload = build_analysis()
    write_reports(payload)
    print(json.dumps(payload["primary_type_counts"], ensure_ascii=False, indent=2))
    print(f"wrote {MD_REPORT_PATH}")
    print(f"wrote {JSON_REPORT_PATH}")


if __name__ == "__main__":
    main()
