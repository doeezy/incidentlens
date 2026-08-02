from __future__ import annotations

import json
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents.incident_agent import IncidentAnswerAgent
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models.evaluation import (
    EvaluationCandidate,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
)
from app.models.incident import Incident
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.evaluation import EvaluationRunCreate
from app.services.evaluation import EvaluationService
from app.services.retrieval import IncidentRetrievalService


SEED_MARKER = "seed=hybrid-search-v1"
CASE_PREFIX = "enriched_seed_v1"
RUN_NAME = "enriched_seed_baseline_v1"
TOP_K = 3
CANDIDATE_LIMIT = 20
RRF_K = 60

REPORT_DIR = ROOT_DIR / "docs" / "evaluation"
CANDIDATE_JSON_PATH = ROOT_DIR / "seed_data" / "enriched_seed_evaluation_candidates_v1.json"
REPORT_JSON_PATH = REPORT_DIR / "enriched_seed_baseline_v1.json"
REPORT_MD_PATH = REPORT_DIR / "enriched_seed_baseline_v1.md"

EXPECTED_DISTRIBUTION = {
    "exact_keyword": 8,
    "semantic_paraphrase": 10,
    "same_error_different_cause": 10,
    "cross_project_conflict": 6,
    "ambiguous_query": 6,
    "no_relevant_result": 6,
}


@dataclass(frozen=True)
class CaseSpec:
    suffix: str
    category: str
    project_name: str
    question: str
    expected_intent: str
    difficulty: str
    expected_no_result: bool = False
    module_name: str | None = None
    class_name: str | None = None
    error_type: str | None = None

    @property
    def case_key(self) -> str:
        return f"{CASE_PREFIX}_{self.category}_{self.suffix}"


def build_case_specs() -> list[CaseSpec]:
    return [
        CaseSpec("001", "exact_keyword", "data-portal", "JwtTokenProvider ClassNotFoundException DataAuthService login", "ROOT_CAUSE", "easy", module_name="auth", class_name="DataAuthService", error_type="ClassNotFoundException"),
        CaseSpec("002", "exact_keyword", "data-portal", "paymentMethod NullPointerException PAY-4021 DataPaymentService", "ROOT_CAUSE", "easy", module_name="payment", class_name="DataPaymentService", error_type="NullPointerException"),
        CaseSpec("003", "exact_keyword", "data-portal", "report_status_cd SQLGrammarException DataReportQueryRepository", "ROOT_CAUSE", "easy", module_name="report", class_name="DataReportQueryRepository", error_type="SQLGrammarException"),
        CaseSpec("004", "exact_keyword", "admin-portal", "REPORT_ADMIN AccessDeniedException AdminPermissionEvaluator", "ROOT_CAUSE", "easy", module_name="security", class_name="AdminPermissionEvaluator", error_type="AccessDeniedException"),
        CaseSpec("005", "exact_keyword", "admin-portal", "PKIX SSLHandshakeException AdminSecureHttpClient truststore", "ROOT_CAUSE", "easy", module_name="client", class_name="AdminSecureHttpClient", error_type="SSLHandshakeException"),
        CaseSpec("006", "exact_keyword", "batch-platform", "KafkaSerializationException schema version v3 BatchKafkaEventPublisher", "ROOT_CAUSE", "easy", module_name="stream", class_name="BatchKafkaEventPublisher", error_type="KafkaSerializationException"),
        CaseSpec("007", "exact_keyword", "batch-platform", "Docker container exited code 137 BatchContainerSupervisor", "ROOT_CAUSE", "easy", module_name="runtime", class_name="BatchContainerSupervisor", error_type="ContainerExitError"),
        CaseSpec("008", "exact_keyword", "data-portal", "feature-flags.yml FileNotFoundException DataFeatureFlagLoader", "ROOT_CAUSE", "easy", module_name="config", class_name="DataFeatureFlagLoader", error_type="FileNotFoundException"),
        CaseSpec("001", "semantic_paraphrase", "data-portal", "로그인 직후 인증 토큰 클래스를 못 찾아서 실패한 원인이 뭐야?", "ROOT_CAUSE", "medium", module_name="auth", class_name="DataAuthService", error_type="ClassNotFoundException"),
        CaseSpec("002", "semantic_paraphrase", "data-portal", "결제 승인에서 결제수단 값이 비어 터진 장애는 어떻게 해결했어?", "RESOLUTION", "medium", module_name="payment", class_name="DataPaymentService", error_type="NullPointerException"),
        CaseSpec("003", "semantic_paraphrase", "data-portal", "리포트 화면에서 없는 상태 컬럼을 조회해서 500이 난 사례 찾아줘", "SIMILAR_CASE", "medium", module_name="report", class_name="DataReportQueryRepository", error_type="SQLGrammarException"),
        CaseSpec("004", "semantic_paraphrase", "admin-portal", "관리자 리포트 접근이 권한 role 때문에 막힌 장애 원인이 뭐야?", "ROOT_CAUSE", "medium", module_name="security", class_name="AdminPermissionEvaluator", error_type="AccessDeniedException"),
        CaseSpec("005", "semantic_paraphrase", "admin-portal", "외부 HTTPS 호출에서 인증서 체인을 신뢰하지 못한 문제는 어떻게 처리했어?", "RESOLUTION", "medium", module_name="client", class_name="AdminSecureHttpClient", error_type="SSLHandshakeException"),
        CaseSpec("006", "semantic_paraphrase", "batch-platform", "배치 이벤트 발행 중 스키마 버전이 맞지 않아 직렬화가 실패한 사례", "SIMILAR_CASE", "medium", module_name="stream", class_name="BatchKafkaEventPublisher", error_type="KafkaSerializationException"),
        CaseSpec("007", "semantic_paraphrase", "batch-platform", "배치 컨테이너가 메모리 제한 때문에 비정상 종료된 장애 요약해줘", "SUMMARY", "medium", module_name="runtime", class_name="BatchContainerSupervisor", error_type="ContainerExitError"),
        CaseSpec("008", "semantic_paraphrase", "data-portal", "기능 토글 설정 파일이 배포 이미지에 없어 로딩 실패한 케이스", "SIMILAR_CASE", "medium", module_name="config", class_name="DataFeatureFlagLoader", error_type="FileNotFoundException"),
        CaseSpec("009", "semantic_paraphrase", "data-portal", "캐시 서버 연결 수가 꽉 차서 Redis 조회가 실패한 장애 해결 내용", "RESOLUTION", "medium", module_name="cache", class_name="DataRedisCacheClient", error_type="RedisConnectionException"),
        CaseSpec("010", "semantic_paraphrase", "data-portal", "파트너 프로필 API가 3초 안에 응답하지 않아 지연된 장애 있었어?", "SIMILAR_CASE", "medium", module_name="integration", class_name="DataPartnerApiClient", error_type="TimeoutException"),
        CaseSpec("001", "same_error_different_cause", "data-portal", "data-portal 로그인에서 JwtTokenProvider classpath 문제로 난 클래스 로딩 실패", "ROOT_CAUSE", "hard", module_name="auth", class_name="DataAuthService", error_type="ClassNotFoundException"),
        CaseSpec("002", "same_error_different_cause", "admin-portal", "admin-portal 로그인 인증에서 JwtTokenProvider 패키지 경로가 맞지 않았던 장애", "ROOT_CAUSE", "hard", module_name="auth", class_name="AdminAuthService", error_type="ClassNotFoundException"),
        CaseSpec("003", "same_error_different_cause", "data-portal", "데이터 포털 결제 승인 전에 paymentMethod를 참조해서 난 null 문제", "ROOT_CAUSE", "hard", module_name="payment", class_name="DataPaymentService", error_type="NullPointerException"),
        CaseSpec("004", "same_error_different_cause", "admin-portal", "관리자 포털 결제 승인 흐름에서 결제수단 검증 전에 터진 null 장애", "SIMILAR_CASE", "hard", module_name="payment", class_name="AdminPaymentService", error_type="NullPointerException"),
        CaseSpec("005", "same_error_different_cause", "admin-portal", "관리자 리포트 권한 role 매핑 누락으로 접근 거부된 장애", "ROOT_CAUSE", "hard", module_name="security", class_name="AdminPermissionEvaluator", error_type="AccessDeniedException"),
        CaseSpec("006", "same_error_different_cause", "batch-platform", "배치 권한 검사에서 REPORT_ADMIN role 때문에 막힌 케이스", "SIMILAR_CASE", "hard", module_name="security", class_name="BatchPermissionEvaluator", error_type="AccessDeniedException"),
        CaseSpec("007", "same_error_different_cause", "data-portal", "데이터 포털 webhook EventStatus enum 역직렬화 실패 장애", "ROOT_CAUSE", "hard", module_name="api", class_name="DataWebhookController", error_type="JsonMappingException"),
        CaseSpec("008", "same_error_different_cause", "admin-portal", "관리자 webhook에서 새 status enum 값 때문에 JSON 매핑 실패한 사례", "SIMILAR_CASE", "hard", module_name="api", class_name="AdminWebhookController", error_type="JsonMappingException"),
        CaseSpec("009", "same_error_different_cause", "data-portal", "주문 confirm 중 중복 요청이 같은 row를 동시에 갱신한 optimistic lock 장애", "ROOT_CAUSE", "hard", module_name="order", class_name="DataOrderCommandService", error_type="OptimisticLockException"),
        CaseSpec("010", "same_error_different_cause", "batch-platform", "배치 주문 confirm 중 같은 row 동시 갱신으로 충돌난 케이스", "SIMILAR_CASE", "hard", module_name="order", class_name="BatchOrderCommandService", error_type="OptimisticLockException"),
        CaseSpec("001", "cross_project_conflict", "data-portal", "data-portal 로그인 클래스 로딩 실패 사례", "SIMILAR_CASE", "hard", module_name="auth", class_name="DataAuthService", error_type="ClassNotFoundException"),
        CaseSpec("002", "cross_project_conflict", "admin-portal", "admin-portal 로그인 클래스 로딩 실패 사례", "SIMILAR_CASE", "hard", module_name="auth", class_name="AdminAuthService", error_type="ClassNotFoundException"),
        CaseSpec("003", "cross_project_conflict", "batch-platform", "batch-platform Redis 접속 수 초과 캐시 장애", "SIMILAR_CASE", "hard", module_name="cache", class_name="BatchRedisCacheClient", error_type="RedisConnectionException"),
        CaseSpec("004", "cross_project_conflict", "admin-portal", "admin-portal Redis 연결 풀 고갈로 캐시 조회가 실패한 사례", "SIMILAR_CASE", "hard", module_name="cache", class_name="AdminRedisCacheClient", error_type="RedisConnectionException"),
        CaseSpec("005", "cross_project_conflict", "data-portal", "data-portal 파트너 프로필 조회 3000ms timeout 장애", "SIMILAR_CASE", "hard", module_name="integration", class_name="DataPartnerApiClient", error_type="TimeoutException"),
        CaseSpec("006", "cross_project_conflict", "batch-platform", "batch-platform 파트너 프로필 API 응답 지연 timeout 장애", "SIMILAR_CASE", "hard", module_name="integration", class_name="BatchPartnerApiClient", error_type="TimeoutException"),
        CaseSpec("001", "ambiguous_query", "data-portal", "data-portal 로그인 장애 원인 알려줘", "ROOT_CAUSE", "medium", module_name="auth", class_name="DataAuthService", error_type="ClassNotFoundException"),
        CaseSpec("002", "ambiguous_query", "data-portal", "data-portal 결제 장애 해결 내용 요약해줘", "SUMMARY", "medium", module_name="payment", class_name="DataPaymentService", error_type="NullPointerException"),
        CaseSpec("003", "ambiguous_query", "admin-portal", "admin-portal 권한 문제로 막힌 장애 찾아줘", "SIMILAR_CASE", "medium", module_name="security", class_name="AdminPermissionEvaluator", error_type="AccessDeniedException"),
        CaseSpec("004", "ambiguous_query", "batch-platform", "batch-platform 이벤트 발행 실패 사례", "SIMILAR_CASE", "medium", module_name="stream", class_name="BatchKafkaEventPublisher", error_type="KafkaSerializationException"),
        CaseSpec("005", "ambiguous_query", "data-portal", "data-portal 캐시 쪽 장애 원인이 뭐였어?", "ROOT_CAUSE", "medium", module_name="cache", class_name="DataRedisCacheClient", error_type="RedisConnectionException"),
        CaseSpec("006", "ambiguous_query", "admin-portal", "admin-portal 외부 연동 호출 실패한 장애 설명해줘", "SUMMARY", "medium", module_name="integration", class_name="AdminPartnerApiClient", error_type="TimeoutException"),
        CaseSpec("001", "no_relevant_result", "data-portal", "이미지 업로드 썸네일 생성 실패 장애 원인", "ROOT_CAUSE", "medium", expected_no_result=True),
        CaseSpec("002", "no_relevant_result", "data-portal", "메일 발송 SMTP 인증 실패 해결 방법", "RESOLUTION", "medium", expected_no_result=True),
        CaseSpec("003", "no_relevant_result", "admin-portal", "관리자 화면 CSS 깨짐과 정적 리소스 캐시 문제", "SUMMARY", "easy", expected_no_result=True),
        CaseSpec("004", "no_relevant_result", "batch-platform", "S3 백업 파일 압축 해제 실패 사례", "SIMILAR_CASE", "medium", expected_no_result=True),
        CaseSpec("005", "no_relevant_result", "batch-platform", "Elasticsearch 색인 shard allocation 실패", "ROOT_CAUSE", "medium", expected_no_result=True),
        CaseSpec("006", "no_relevant_result", "data-portal", "사용자 프로필 이미지 크롭 기능 오류", "SUMMARY", "easy", expected_no_result=True),
    ]


def seed_incident_ids(session) -> set[uuid.UUID]:
    rows = session.execute(
        text(
            """
            SELECT DISTINCT i.id
            FROM incidents i
            JOIN raw_logs rl ON rl.incident_id = i.id
            WHERE rl.raw_message LIKE :marker
            """
        ),
        {"marker": f"%{SEED_MARKER}%"},
    ).scalars()
    return set(rows)


def load_seed_incidents(session) -> dict[tuple[str, str | None, str | None, str | None], Incident]:
    ids = seed_incident_ids(session)
    incidents = session.scalars(select(Incident).where(Incident.id.in_(ids))).all()
    return {
        (
            incident.project_name,
            incident.module_name,
            incident.class_name,
            incident.primary_error_type,
        ): incident
        for incident in incidents
    }


def load_evidence(session, incident_ids: set[uuid.UUID]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {
        str(incident_id): {"logs": [], "tickets": [], "prs": []}
        for incident_id in incident_ids
    }
    for row in session.execute(
        text(
            """
            SELECT incident_id::text, normalized_summary, error_type, error_message,
                   extracted_keywords, domain_tags
            FROM raw_logs
            WHERE incident_id = ANY(:incident_ids) AND raw_message LIKE :marker
            ORDER BY occurred_at
            """
        ),
        {"incident_ids": list(incident_ids), "marker": f"%{SEED_MARKER}%"},
    ).mappings():
        payload[row["incident_id"]]["logs"].append(dict(row))

    for row in session.execute(
        text(
            """
            SELECT incident_id::text, ticket_key, title, normalized_summary,
                   suspected_cause, resolution_note, extracted_keywords, domain_tags
            FROM raw_tickets
            WHERE incident_id = ANY(:incident_ids) AND description LIKE :marker
            ORDER BY ticket_key
            """
        ),
        {"incident_ids": list(incident_ids), "marker": f"%{SEED_MARKER}%"},
    ).mappings():
        payload[row["incident_id"]]["tickets"].append(dict(row))

    for row in session.execute(
        text(
            """
            SELECT incident_id::text, pr_key, title, status, normalized_summary,
                   suspected_fix_for, resolution_note, diff_summary, changed_files
            FROM raw_prs
            WHERE incident_id = ANY(:incident_ids) AND description LIKE :marker
            ORDER BY pr_key
            """
        ),
        {"incident_ids": list(incident_ids), "marker": f"%{SEED_MARKER}%"},
    ).mappings():
        payload[row["incident_id"]]["prs"].append(dict(row))
    return payload


def materialize_cases(session) -> list[dict[str, Any]]:
    incident_ids = seed_incident_ids(session)
    if len(incident_ids) != 36:
        raise RuntimeError(f"seed incident count must be 36, got {len(incident_ids)}")

    incident_map = load_seed_incidents(session)
    evidence_by_incident = load_evidence(session, incident_ids)
    cases: list[dict[str, Any]] = []
    for spec in build_case_specs():
        expected_incident_id = None
        expected_summary = None
        basis = "현재 seed 36건의 raw log/ticket/PR 어느 근거와도 직접 일치하지 않는 질문이다."
        evidence = None
        if not spec.expected_no_result:
            incident = incident_map.get(
                (spec.project_name, spec.module_name, spec.class_name, spec.error_type)
            )
            if incident is None:
                raise RuntimeError(f"missing incident for {spec}")
            expected_incident_id = str(incident.id)
            expected_summary = incident.primary_error_summary
            evidence = evidence_by_incident[str(incident.id)]
            basis_parts = [
                f"Incident error_type={incident.primary_error_type}, module={incident.module_name}, class={incident.class_name}",
                f"primary_error_message={incident.primary_error_message}",
            ]
            if evidence["logs"]:
                basis_parts.append(
                    "raw_log 근거: "
                    + "; ".join(
                        item["normalized_summary"] or item["error_message"] or ""
                        for item in evidence["logs"][:2]
                    )
                )
            if evidence["tickets"]:
                ticket = evidence["tickets"][0]
                basis_parts.append(
                    f"raw_ticket 근거: {ticket['ticket_key']} / "
                    f"{ticket['normalized_summary']} / cause={ticket['suspected_cause']}"
                )
            if evidence["prs"]:
                pr = evidence["prs"][0]
                basis_parts.append(
                    f"raw_pr 근거: {pr['pr_key']} / "
                    f"{pr['normalized_summary']} / resolution={pr['resolution_note']}"
                )
            basis = " | ".join(part for part in basis_parts if part)

        cases.append(
            {
                "case_key": spec.case_key,
                "category": spec.category,
                "project_name": spec.project_name,
                "question": spec.question,
                "expected_incident_id": expected_incident_id,
                "expected_incident_summary": expected_summary,
                "answer_basis": basis,
                "expected_no_result": spec.expected_no_result,
                "expected_intent": spec.expected_intent,
                "difficulty": spec.difficulty,
                "evidence": evidence,
            }
        )
    return cases


def validate_cases(session, cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_keys = [case["case_key"] for case in cases]
    questions = [case["question"] for case in cases]
    distribution = Counter(case["category"] for case in cases)
    incident_ids = seed_incident_ids(session)
    expected_ids = [
        uuid.UUID(case["expected_incident_id"])
        for case in cases
        if case["expected_incident_id"] is not None
    ]
    errors: list[str] = []
    if len(cases) != 46:
        errors.append(f"총 케이스 수 불일치: {len(cases)}")
    if len(set(case_keys)) != len(case_keys):
        errors.append("case_key 중복 존재")
    if len(set(questions)) != len(questions):
        errors.append("question 중복 존재")
    if dict(distribution) != EXPECTED_DISTRIBUTION:
        errors.append(f"카테고리 분포 불일치: {dict(distribution)}")
    missing_ids = sorted(str(item) for item in set(expected_ids) - incident_ids)
    if missing_ids:
        errors.append(f"현재 seed incidents에 없는 expected_incident_id: {missing_ids}")
    bad_no_result = [
        case["case_key"]
        for case in cases
        if case["expected_no_result"] and case["expected_incident_id"] is not None
    ]
    if bad_no_result:
        errors.append(f"expected_no_result=true인데 expected_incident_id가 있음: {bad_no_result}")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "case_count": len(cases),
        "distribution": dict(distribution),
        "duplicate_case_key": False,
        "duplicate_question": False,
        "answerable_expected_ids_exist": True,
        "no_result_expected_id_null": True,
    }


def save_candidate_json(cases: list[dict[str, Any]], validation: dict[str, Any]) -> None:
    CANDIDATE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed_marker": SEED_MARKER,
        "validation": validation,
        "cases": cases,
    }
    CANDIDATE_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def reset_and_insert_cases(session, cases: list[dict[str, Any]]) -> None:
    session.execute(delete(EvaluationRun))
    session.execute(delete(EvaluationCase))
    session.flush()
    for case in cases:
        session.add(
            EvaluationCase(
                case_key=case["case_key"],
                project_name=case["project_name"],
                question=case["question"],
                expected_incident_id=(
                    uuid.UUID(case["expected_incident_id"])
                    if case["expected_incident_id"]
                    else None
                ),
                expected_no_result=case["expected_no_result"],
                expected_intent=case["expected_intent"],
                category=case["category"],
                difficulty=case["difficulty"],
                is_active=True,
            )
        )
    session.commit()


@dataclass(frozen=True)
class CandidateRanks:
    vector_rank: int | None
    vector_score: float | None
    bm25_rank: int | None
    bm25_score: float | None
    rrf_rank: int | None
    rrf_score: float | None


def run_baseline(session):
    settings = get_settings()
    retrieval_service = IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )
    query_agent = IncidentAnswerAgent(
        settings=settings,
        retrieval_service=retrieval_service,
    )
    service = EvaluationService(
        settings=settings,
        repository=EvaluationRepository(session),
        query_agent=query_agent,
        retrieval_service=retrieval_service,
    )
    return service.run(
        EvaluationRunCreate(
            run_name=RUN_NAME,
            top_k=TOP_K,
            candidate_limit=CANDIDATE_LIMIT,
            rrf_k=RRF_K,
        )
    )


def load_run_data(session, run_id: uuid.UUID):
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
    by_result: dict[uuid.UUID, list[EvaluationCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_result[candidate.evaluation_result_id].append(candidate)
    return results, cases, by_result


def ranks_for(result: EvaluationResult, candidates: list[EvaluationCandidate]) -> CandidateRanks:
    expected_id = result.expected_incident_id
    if expected_id is None:
        return CandidateRanks(None, None, None, None, None, None)

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
        vector_score=vector.vector_score if vector else None,
        bm25_rank=bm25.rank if bm25 else None,
        bm25_score=bm25.bm25_score if bm25 else None,
        rrf_rank=rrf.rank if rrf else None,
        rrf_score=rrf.rrf_score if rrf else None,
    )


def ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def reciprocal_rank(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def compute_retrieval_metrics(results, candidates_by_result) -> dict[str, float | None]:
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    ranks = [
        ranks_for(result, candidates_by_result.get(result.id, [])).rrf_rank
        for result in answerable
    ]
    return {
        "retrieval_top1_accuracy": ratio(sum(1 for rank in ranks if rank == 1), len(answerable)),
        "retrieval_top3_accuracy": ratio(sum(1 for rank in ranks if rank is not None and rank <= 3), len(answerable)),
        "retrieval_mrr": ratio(sum(reciprocal_rank(rank) for rank in ranks), len(answerable)),
    }


def compute_final_metrics(results) -> dict[str, float | None]:
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    no_result = [result for result in results if result.expected_no_result]
    return {
        "final_top1_accuracy": ratio(sum(1 for result in answerable if result.top1_hit), len(answerable)),
        "final_top3_accuracy": ratio(sum(1 for result in answerable if result.top3_hit), len(answerable)),
        "final_mrr": ratio(sum(result.reciprocal_rank for result in answerable), len(answerable)),
        "no_result_accuracy": ratio(sum(1 for result in no_result if result.no_result_correct), len(no_result)),
        "abstain_ratio": ratio(sum(1 for result in results if result.abstained), len(results)),
    }


def compute_original_query_ranks(session, run: EvaluationRun, results, cases) -> dict[uuid.UUID, CandidateRanks]:
    settings = get_settings()
    retrieval_service = IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )
    ranks: dict[uuid.UUID, CandidateRanks] = {}
    for result in results:
        if result.expected_no_result or result.expected_incident_id is None:
            continue
        case = cases[result.case_id]
        trace = retrieval_service.search_for_evaluation(
            query=result.original_query,
            top_k=TOP_K,
            candidate_limit=CANDIDATE_LIMIT,
            rrf_k=RRF_K,
            project_name=case.project_name,
        )
        pseudo_candidates = [
            EvaluationCandidate(
                evaluation_result_id=result.id,
                search_type=item.search_type,
                incident_id=item.incident_id,
                rank=item.rank,
                raw_score=item.raw_score,
                vector_score=item.vector_score,
                bm25_score=item.bm25_score,
                rrf_score=item.rrf_score,
            )
            for item in trace.vector_candidates + trace.bm25_candidates + trace.rrf_candidates
        ]
        ranks[result.id] = ranks_for(result, pseudo_candidates)
    return ranks


def rank_declined(before: int | None, after: int | None) -> bool:
    if before is None:
        return False
    if after is None:
        return True
    return after > before


def classify_failure(result: EvaluationResult, ranks: CandidateRanks, original_ranks: CandidateRanks | None) -> str | None:
    if result.error_message:
        return "EXECUTION_ERROR"
    if result.expected_no_result:
        return None if result.no_result_correct else "RETRIEVAL_MISS"
    if result.top3_hit:
        return None
    if original_ranks is not None and rank_declined(original_ranks.rrf_rank, ranks.rrf_rank):
        return "QUERY_REWRITE_ISSUE"
    if ranks.vector_rank is None and ranks.bm25_rank is None:
        return "RETRIEVAL_MISS"
    if ranks.rrf_rank is None or ranks.rrf_rank > 3:
        return "RRF_RANKING_MISS"
    return "CONFIDENCE_REJECT"


def build_report_payload(session, run_detail) -> dict[str, Any]:
    run = session.get(EvaluationRun, run_detail.id)
    if run is None:
        raise RuntimeError("run not found")
    results, cases, candidates_by_result = load_run_data(session, run.id)
    original_query_ranks = compute_original_query_ranks(session, run, results, cases)
    failures = []
    failure_counts: Counter[str] = Counter()
    for result in results:
        case = cases[result.case_id]
        ranks = ranks_for(result, candidates_by_result.get(result.id, []))
        original_ranks = original_query_ranks.get(result.id)
        failure_type = classify_failure(result, ranks, original_ranks)
        if failure_type is not None:
            failure_counts[failure_type] += 1
            failures.append(
                {
                    "case_key": case.case_key,
                    "category": case.category,
                    "project_name": case.project_name,
                    "original_query": result.original_query,
                    "rewritten_query": result.rewritten_query,
                    "expected_incident_id": str(result.expected_incident_id) if result.expected_incident_id else None,
                    "expected_no_result": result.expected_no_result,
                    "vector_rank": ranks.vector_rank,
                    "vector_score": ranks.vector_score,
                    "bm25_rank": ranks.bm25_rank,
                    "bm25_score": ranks.bm25_score,
                    "rrf_rank": ranks.rrf_rank,
                    "rrf_score": ranks.rrf_score,
                    "original_query_rrf_rank": original_ranks.rrf_rank if original_ranks else None,
                    "confidence": result.confidence,
                    "abstained": result.abstained,
                    "error_message": result.error_message,
                    "failure_type": failure_type,
                }
            )

    candidate_count = sum(len(items) for items in candidates_by_result.values())
    telemetry = (run.parameters or {}).get("confidence_telemetry", {})
    final_metrics = compute_final_metrics(results)
    retrieval_metrics = compute_retrieval_metrics(results, candidates_by_result)
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    no_result = [result for result in results if result.expected_no_result]
    return {
        "run": {
            "id": str(run.id),
            "run_name": run.run_name,
            "retrieval_version": run.retrieval_version,
            "embedding_model": run.embedding_model,
            "query_analyzer_version": run.query_analyzer_version,
            "parameters": run.parameters,
            "total_cases": run.total_cases,
            "completed_cases": run.completed_cases,
            "mean_latency_ms": run.mean_latency_ms,
        },
        "case_counts": {
            "answerable": len(answerable),
            "no_result": len(no_result),
        },
        "metrics": {
            **retrieval_metrics,
            **final_metrics,
            "mean_latency_ms": run.mean_latency_ms,
        },
        "candidate_count": candidate_count,
        "confidence": {
            "evaluated_candidates": telemetry.get("evaluated_candidates"),
            "llm_calls": telemetry.get("llm_calls"),
            "avg_llm_calls_per_case": telemetry.get("avg_llm_calls_per_case"),
            "llm_failures": telemetry.get("llm_failures"),
            "passed_candidates": telemetry.get("passed_candidates"),
            "rejected_candidates": (
                telemetry.get("evaluated_candidates", 0)
                - telemetry.get("passed_candidates", 0)
                if telemetry
                else None
            ),
            "rejected_by": telemetry.get("rejected_by", {}),
            "pre_llm_rejections": telemetry.get("pre_llm_rejections"),
            "llm_low_confidence_rejections": telemetry.get("llm_low_confidence_rejections"),
        },
        "failure_counts": dict(failure_counts),
        "failures": failures,
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_report(payload: dict[str, Any], validation: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps({"validation": validation, **payload}, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    metrics = payload["metrics"]
    confidence = payload["confidence"]
    lines = [
        "# Enriched Seed Retrieval Baseline v1",
        "",
        "이번 Run은 LLM enrichment가 정상 적용된 seed 데이터 기준 최초의 유효 baseline이다. 이전 데이터 품질 문제가 있던 결과와 섞지 않는다.",
        "",
        "## Dataset 검증",
        "",
        f"- 총 케이스 수: `{validation['case_count']}`",
        f"- 카테고리 분포: `{validation['distribution']}`",
        f"- case_key 중복: `{validation['duplicate_case_key']}`",
        f"- 질문 중복: `{validation['duplicate_question']}`",
        f"- 정답 Incident UUID 현재 seed incidents 존재: `{validation['answerable_expected_ids_exist']}`",
        f"- no-result case expected_incident_id null: `{validation['no_result_expected_id_null']}`",
        f"- 후보 JSON: `{CANDIDATE_JSON_PATH.relative_to(ROOT_DIR)}`",
        "",
        "## Run 설정",
        "",
        f"- run_id: `{payload['run']['id']}`",
        f"- run_name: `{payload['run']['run_name']}`",
        f"- top_k: `{TOP_K}`",
        f"- candidate_limit: `{CANDIDATE_LIMIT}`",
        f"- rrf_k: `{RRF_K}`",
        f"- retrieval_version: `{payload['run']['retrieval_version']}`",
        f"- query_analyzer_version: `{payload['run']['query_analyzer_version']}`",
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| retrieval_top1_accuracy | {fmt(metrics['retrieval_top1_accuracy'])} |",
        f"| retrieval_top3_accuracy | {fmt(metrics['retrieval_top3_accuracy'])} |",
        f"| retrieval_mrr | {fmt(metrics['retrieval_mrr'])} |",
        f"| final_top1_accuracy | {fmt(metrics['final_top1_accuracy'])} |",
        f"| final_top3_accuracy | {fmt(metrics['final_top3_accuracy'])} |",
        f"| final_mrr | {fmt(metrics['final_mrr'])} |",
        f"| no_result_accuracy | {fmt(metrics['no_result_accuracy'])} |",
        f"| abstain_ratio | {fmt(metrics['abstain_ratio'])} |",
        f"| mean_latency_ms | {fmt(metrics['mean_latency_ms'])} |",
        "",
        "## Confidence / Candidate",
        "",
        "| item | value |",
        "| --- | ---: |",
        f"| 전체 평가 후보 수 | {payload['candidate_count']} |",
        f"| LLM confidence 호출 횟수 | {confidence['llm_calls']} |",
        f"| Case당 평균 LLM 호출 횟수 | {fmt(confidence['avg_llm_calls_per_case'])} |",
        f"| LLM 평가 실패 횟수 | {confidence['llm_failures']} |",
        f"| confidence 통과 후보 수 | {confidence['passed_candidates']} |",
        f"| confidence 거절 후보 수 | {confidence['rejected_candidates']} |",
        f"| pre-LLM reject | {confidence['pre_llm_rejections']} |",
        f"| LLM low confidence reject | {confidence['llm_low_confidence_rejections']} |",
        "",
        "## 실패 유형",
        "",
    ]
    for name in [
        "RETRIEVAL_MISS",
        "RRF_RANKING_MISS",
        "CONFIDENCE_REJECT",
        "QUERY_REWRITE_ISSUE",
        "EXECUTION_ERROR",
    ]:
        lines.append(f"- {name}: {payload['failure_counts'].get(name, 0)}")

    lines.extend(
        [
            "",
            "## 실패 Case",
            "",
            "| case_key | category | project | vector | bm25 | rrf | original_rrf | abstained | failure_type |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in payload["failures"]:
        lines.append(
            f"| `{item['case_key']}` | {item['category']} | {item['project_name']} | "
            f"{fmt(item['vector_rank'])}/{fmt(item['vector_score'])} | "
            f"{fmt(item['bm25_rank'])}/{fmt(item['bm25_score'])} | "
            f"{fmt(item['rrf_rank'])}/{fmt(item['rrf_score'])} | "
            f"{fmt(item['original_query_rrf_rank'])} | "
            f"{item['abstained']} | {item['failure_type']} |"
        )
    REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        cases = materialize_cases(session)
        validation = validate_cases(session, cases)
        save_candidate_json(cases, validation)
        reset_and_insert_cases(session, cases)
        validation_after_save = validate_cases(session, cases)
        run_detail = run_baseline(session)
        payload = build_report_payload(session, run_detail)
        write_report(payload, validation_after_save)
        print("REPORT_JSON", REPORT_JSON_PATH)
        print("REPORT_MD", REPORT_MD_PATH)
        print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
        print(json.dumps(payload["confidence"], ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
