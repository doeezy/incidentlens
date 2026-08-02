from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents.incident_agent import IncidentAnswerAgent
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models.evaluation import EvaluationCase
from app.models.incident import Incident
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.evaluation import EvaluationRunCreate
from app.services.evaluation import EvaluationService
from app.services.retrieval import IncidentRetrievalService


OUTPUT_PATH = ROOT_DIR / "seed_data" / "retrieval_evaluation_candidates.json"
CASE_PREFIX = "retrieval_eval_v1"


@dataclass(frozen=True)
class CaseSpec:
    suffix: str
    category: str
    project_name: str
    question: str
    expected_intent: str
    difficulty: str
    expected_no_result: bool = False
    error_type: str | None = None
    module_name: str | None = None
    class_name: str | None = None
    expected_incident_id: str | None = None

    @property
    def case_key(self) -> str:
        return f"{CASE_PREFIX}_{self.category}_{self.suffix}"


def _incident_key(incident: Incident) -> tuple[str, str | None, str | None, str | None]:
    return (
        incident.project_name,
        incident.primary_error_type,
        incident.module_name,
        incident.class_name,
    )


def _load_incident_maps(session) -> dict[tuple[str, str | None, str | None, str | None], Incident]:
    incidents = session.scalars(select(Incident)).all()
    return {_incident_key(incident): incident for incident in incidents}


def build_case_specs() -> list[CaseSpec]:
    return [
        CaseSpec("001", "exact_keyword", "data-portal", "ClassNotFoundException JwtTokenProvider login 장애", "ROOT_CAUSE", "easy", error_type="ClassNotFoundException", module_name="auth", class_name="AuthService"),
        CaseSpec("002", "exact_keyword", "data-portal", "payment request is null NullPointerException pay", "ROOT_CAUSE", "easy", error_type="NullPointerException", module_name="payment", class_name="PaymentService"),
        CaseSpec("003", "exact_keyword", "data-portal", "SQLGrammarException report_status_cd findDaily", "ROOT_CAUSE", "easy", error_type="SQLGrammarException", module_name="report", class_name="DataReportQueryRepository"),
        CaseSpec("004", "exact_keyword", "admin-portal", "AccessDeniedException REPORT_ADMIN AdminPermissionEvaluator", "ROOT_CAUSE", "easy", error_type="AccessDeniedException", module_name="security", class_name="AdminPermissionEvaluator"),
        CaseSpec("005", "exact_keyword", "admin-portal", "PKIX SSLHandshakeException AdminSecureHttpClient", "ROOT_CAUSE", "easy", error_type="SSLHandshakeException", module_name="client", class_name="AdminSecureHttpClient"),
        CaseSpec("006", "exact_keyword", "batch-platform", "KafkaSerializationException schema version v3 BatchKafkaEventPublisher", "ROOT_CAUSE", "easy", error_type="KafkaSerializationException", module_name="stream", class_name="BatchKafkaEventPublisher"),
        CaseSpec("007", "exact_keyword", "batch-platform", "Docker container exited code 137 BatchContainerSupervisor", "ROOT_CAUSE", "easy", error_type="ContainerExitError", module_name="runtime", class_name="BatchContainerSupervisor"),
        CaseSpec("008", "exact_keyword", "data-portal", "feature-flags.yml FileNotFoundException DataFeatureFlagLoader", "ROOT_CAUSE", "easy", error_type="FileNotFoundException", module_name="config", class_name="DataFeatureFlagLoader"),
        CaseSpec("001", "semantic_paraphrase", "data-portal", "로그인 직후 인증 토큰 클래스를 못 찾아서 실패한 건 왜였어?", "ROOT_CAUSE", "medium", error_type="ClassNotFoundException", module_name="auth", class_name="AuthService"),
        CaseSpec("002", "semantic_paraphrase", "data-portal", "결제 요청 객체가 비어 있을 때 발생한 장애 해결 방향 알려줘", "RESOLUTION", "medium", error_type="NullPointerException", module_name="payment", class_name="PaymentService"),
        CaseSpec("003", "semantic_paraphrase", "data-portal", "리포트 조회에서 없는 상태 컬럼 때문에 터진 사례 찾아줘", "SIMILAR_CASE", "medium", error_type="SQLGrammarException", module_name="report", class_name="DataReportQueryRepository"),
        CaseSpec("004", "semantic_paraphrase", "admin-portal", "관리자 권한이 있는데 리포트 접근이 막힌 장애 원인이 뭐야?", "ROOT_CAUSE", "medium", error_type="AccessDeniedException", module_name="security", class_name="AdminPermissionEvaluator"),
        CaseSpec("005", "semantic_paraphrase", "admin-portal", "외부 HTTPS 호출에서 인증서 체인 문제로 실패한 건 어떻게 처리했어?", "RESOLUTION", "medium", error_type="SSLHandshakeException", module_name="client", class_name="AdminSecureHttpClient"),
        CaseSpec("006", "semantic_paraphrase", "batch-platform", "배치 이벤트 발행 중 스키마 버전이 안 맞아서 직렬화가 실패한 사례", "SIMILAR_CASE", "medium", error_type="KafkaSerializationException", module_name="stream", class_name="BatchKafkaEventPublisher"),
        CaseSpec("007", "semantic_paraphrase", "batch-platform", "배치 컨테이너가 메모리 문제처럼 종료된 과거 장애 요약해줘", "SUMMARY", "medium", error_type="ContainerExitError", module_name="runtime", class_name="BatchContainerSupervisor"),
        CaseSpec("008", "semantic_paraphrase", "data-portal", "feature flag 설정을 못 읽어서 배포 후 기능 토글 로딩이 실패한 케이스", "SIMILAR_CASE", "medium", error_type="FileNotFoundException", module_name="config", class_name="DataFeatureFlagLoader"),
        CaseSpec("009", "semantic_paraphrase", "data-portal", "Redis 접속 수가 꽉 차서 캐시 조회가 실패한 장애 해결 내용", "RESOLUTION", "medium", error_type="RedisConnectionException", module_name="cache", class_name="DataRedisCacheClient"),
        CaseSpec("010", "semantic_paraphrase", "data-portal", "파트너 프로필 API가 3초 안에 안 끝나서 지연된 장애 있었어?", "SIMILAR_CASE", "medium", error_type="TimeoutException", module_name="integration", class_name="DataPartnerApiClient"),
        CaseSpec("001", "same_error_different_cause", "data-portal", "로그인 도메인에서 클래스 로딩 실패가 났던 원인을 찾아줘", "ROOT_CAUSE", "hard", error_type="ClassNotFoundException", module_name="auth", class_name="AuthService"),
        CaseSpec("002", "same_error_different_cause", "data-portal", "결제 승인 흐름의 null 참조 장애를 찾아줘", "SIMILAR_CASE", "hard", error_type="NullPointerException", module_name="payment", class_name="DataPaymentService"),
        CaseSpec("003", "same_error_different_cause", "data-portal", "결제 pay 요청 자체가 비어 있어서 난 null 문제는 뭐였어?", "ROOT_CAUSE", "hard", error_type="NullPointerException", module_name="payment", class_name="PaymentService"),
        CaseSpec("004", "same_error_different_cause", "admin-portal", "관리자 리포트 권한 role이 맞지 않아 접근 거부된 장애", "SIMILAR_CASE", "hard", error_type="AccessDeniedException", module_name="security", class_name="AdminPermissionEvaluator"),
        CaseSpec("005", "same_error_different_cause", "batch-platform", "배치 권한 검사에서 REPORT_ADMIN role 때문에 막힌 케이스", "SIMILAR_CASE", "hard", error_type="AccessDeniedException", module_name="security", class_name="BatchPermissionEvaluator"),
        CaseSpec("006", "same_error_different_cause", "data-portal", "데이터 포털 웹훅 상태값 파싱이 안 된 JSON 매핑 장애", "ROOT_CAUSE", "hard", error_type="JsonMappingException", module_name="api", class_name="DataWebhookController"),
        CaseSpec("007", "same_error_different_cause", "admin-portal", "관리자 웹훅 enum 값 역직렬화가 실패한 사례", "SIMILAR_CASE", "hard", error_type="JsonMappingException", module_name="api", class_name="AdminWebhookController"),
        CaseSpec("008", "same_error_different_cause", "data-portal", "주문 확정 중 같은 row를 동시에 갱신해서 충돌난 장애", "ROOT_CAUSE", "hard", error_type="OptimisticLockException", module_name="order", class_name="DataOrderCommandService"),
        CaseSpec("009", "same_error_different_cause", "batch-platform", "배치 주문 confirm 중 동시성 충돌이 난 케이스", "SIMILAR_CASE", "hard", error_type="OptimisticLockException", module_name="order", class_name="BatchOrderCommandService"),
        CaseSpec("010", "same_error_different_cause", "data-portal", "데이터 포털 Redis 클라이언트 수 제한에 걸린 장애", "ROOT_CAUSE", "hard", error_type="RedisConnectionException", module_name="cache", class_name="DataRedisCacheClient"),
        CaseSpec("001", "cross_project_conflict", "data-portal", "로그인 클래스 로딩 실패가 data-portal에서 발생한 사례", "SIMILAR_CASE", "hard", error_type="ClassNotFoundException", module_name="auth", class_name="AuthService"),
        CaseSpec("002", "cross_project_conflict", "admin-portal", "로그인 클래스 로딩 실패가 admin-portal에서 난 사례", "SIMILAR_CASE", "hard", error_type="ClassNotFoundException", module_name="auth", class_name="AdminAuthService"),
        CaseSpec("003", "cross_project_conflict", "batch-platform", "배치 플랫폼에서 Redis 접속 수 초과로 캐시 장애 난 사례", "SIMILAR_CASE", "hard", error_type="RedisConnectionException", module_name="cache", class_name="BatchRedisCacheClient"),
        CaseSpec("004", "cross_project_conflict", "admin-portal", "관리자 포털에서 Redis 접속 제한으로 캐시 조회가 실패한 사례", "SIMILAR_CASE", "hard", error_type="RedisConnectionException", module_name="cache", class_name="AdminRedisCacheClient"),
        CaseSpec("005", "cross_project_conflict", "data-portal", "data-portal의 파트너 프로필 조회 timeout 장애", "SIMILAR_CASE", "hard", error_type="TimeoutException", module_name="integration", class_name="DataPartnerApiClient"),
        CaseSpec("006", "cross_project_conflict", "batch-platform", "batch-platform의 파트너 프로필 조회 지연 장애", "SIMILAR_CASE", "hard", error_type="TimeoutException", module_name="integration", class_name="BatchPartnerApiClient"),
        CaseSpec("001", "ambiguous_query", "data-portal", "로그인 장애 원인 알려줘", "ROOT_CAUSE", "medium", error_type="ClassNotFoundException", module_name="auth", class_name="AuthService"),
        CaseSpec("002", "ambiguous_query", "data-portal", "결제 장애 있었던 거 요약해줘", "SUMMARY", "medium", error_type="NullPointerException", module_name="payment", class_name="PaymentService"),
        CaseSpec("003", "ambiguous_query", "admin-portal", "권한 문제로 막힌 장애 찾아줘", "SIMILAR_CASE", "medium", error_type="AccessDeniedException", module_name="security", class_name="AdminPermissionEvaluator"),
        CaseSpec("004", "ambiguous_query", "batch-platform", "배치에서 이벤트 발행 실패한 사례", "SIMILAR_CASE", "medium", error_type="KafkaSerializationException", module_name="stream", class_name="BatchKafkaEventPublisher"),
        CaseSpec("005", "ambiguous_query", "data-portal", "캐시 쪽 장애 원인이 뭐였어?", "ROOT_CAUSE", "medium", error_type="RedisConnectionException", module_name="cache", class_name="DataRedisCacheClient"),
        CaseSpec("006", "ambiguous_query", "admin-portal", "외부 연동 호출 실패한 장애 설명해줘", "SUMMARY", "medium", error_type="TimeoutException", module_name="integration", class_name="AdminPartnerApiClient"),
        CaseSpec("001", "no_relevant_result", "data-portal", "이미지 업로드 썸네일 생성 실패 장애 원인", "ROOT_CAUSE", "medium", expected_no_result=True),
        CaseSpec("002", "no_relevant_result", "data-portal", "메일 발송 SMTP 인증 실패 해결 방법", "RESOLUTION", "medium", expected_no_result=True),
        CaseSpec("003", "no_relevant_result", "admin-portal", "관리자 화면 CSS 깨짐과 정적 리소스 캐시 문제", "SUMMARY", "easy", expected_no_result=True),
        CaseSpec("004", "no_relevant_result", "batch-platform", "S3 백업 파일 압축 해제 실패 사례", "SIMILAR_CASE", "medium", expected_no_result=True),
        CaseSpec("005", "no_relevant_result", "batch-platform", "Elasticsearch 색인 shard allocation 실패", "ROOT_CAUSE", "medium", expected_no_result=True),
        CaseSpec("006", "no_relevant_result", "data-portal", "사용자 프로필 이미지 크롭 기능 오류", "SUMMARY", "easy", expected_no_result=True),
    ]


def materialize_cases(session) -> list[dict[str, object]]:
    incident_map = _load_incident_maps(session)
    cases: list[dict[str, object]] = []
    missing: list[CaseSpec] = []
    for spec in build_case_specs():
        expected_incident_id = spec.expected_incident_id
        answer_basis: dict[str, object] | None = None
        if not spec.expected_no_result:
            incident = incident_map.get(
                (spec.project_name, spec.error_type, spec.module_name, spec.class_name)
            )
            if incident is None:
                missing.append(spec)
                continue
            expected_incident_id = str(incident.id)
            answer_basis = {
                "incident_id": str(incident.id),
                "project_name": incident.project_name,
                "error_type": incident.primary_error_type,
                "module_name": incident.module_name,
                "class_name": incident.class_name,
                "method_name": incident.method_name,
                "error_message": incident.primary_error_message,
                "status": incident.status,
            }
        cases.append(
            {
                "case_key": spec.case_key,
                "category": spec.category,
                "project_name": spec.project_name,
                "question": spec.question,
                "expected_incident_id": expected_incident_id,
                "expected_no_result": spec.expected_no_result,
                "expected_intent": spec.expected_intent,
                "difficulty": spec.difficulty,
                "answer_basis": answer_basis,
            }
        )
    if missing:
        details = [
            {
                "case_key": spec.case_key,
                "project_name": spec.project_name,
                "error_type": spec.error_type,
                "module_name": spec.module_name,
                "class_name": spec.class_name,
            }
            for spec in missing
        ]
        raise RuntimeError("incident mapping failed: " + json.dumps(details, ensure_ascii=False))
    return cases


def save_candidate_json(cases: list[dict[str, object]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    by_category: dict[str, int] = {}
    for case in cases:
        category = str(case["category"])
        by_category[category] = by_category.get(category, 0) + 1
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "distribution": by_category,
        "cases": cases,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def upsert_cases(session, cases: list[dict[str, object]]) -> None:
    case_keys = [str(case["case_key"]) for case in cases]
    existing_cases = {
        case.case_key: case
        for case in session.scalars(
            select(EvaluationCase).where(EvaluationCase.case_key.in_(case_keys))
        ).all()
    }
    for stale_case in session.scalars(select(EvaluationCase)).all():
        stale_case.is_active = stale_case.case_key in case_keys

    for case in cases:
        row = existing_cases.get(str(case["case_key"]))
        if row is None:
            row = EvaluationCase(case_key=str(case["case_key"]))
            session.add(row)
        row.project_name = str(case["project_name"])
        row.question = str(case["question"])
        row.expected_incident_id = (
            uuid.UUID(str(case["expected_incident_id"]))
            if case["expected_incident_id"] is not None
            else None
        )
        row.expected_no_result = bool(case["expected_no_result"])
        row.expected_intent = str(case["expected_intent"])
        row.category = str(case["category"])
        row.difficulty = str(case["difficulty"])
        row.is_active = True
    session.commit()


def run_smoke(session, cases: list[dict[str, object]]) -> list[dict[str, object]]:
    settings = get_settings()
    retrieval_service = IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )
    query_agent = IncidentAnswerAgent(
        settings=settings,
        retrieval_service=retrieval_service,
    )
    smoke_keys = [
        "retrieval_eval_v1_exact_keyword_001",
        "retrieval_eval_v1_semantic_paraphrase_007",
        "retrieval_eval_v1_semantic_paraphrase_008",
        "retrieval_eval_v1_semantic_paraphrase_003",
        "retrieval_eval_v1_cross_project_conflict_002",
        "retrieval_eval_v1_no_relevant_result_001",
    ]
    by_key = {case["case_key"]: case for case in cases}
    results: list[dict[str, object]] = []
    for key in smoke_keys:
        case = by_key[key]
        started = perf_counter()
        analysis = query_agent.analyze_query(str(case["question"]))
        trace = retrieval_service.search_for_evaluation(
            query=analysis.rewritten_query or str(case["question"]),
            top_k=3,
            candidate_limit=20,
            rrf_k=60,
            project_name=str(case["project_name"]),
        )
        elapsed_ms = (perf_counter() - started) * 1000.0
        expected = case["expected_incident_id"]
        ranks = {
            str(item.incident_id): item.rank
            for item in trace.rrf_candidates
        }
        results.append(
            {
                "scenario": "normal_or_no_result",
                "case_key": key,
                "expected_incident_id": expected,
                "expected_no_result": case["expected_no_result"],
                "result_count": len(trace.search_response.results),
                "expected_rank": ranks.get(expected),
                "top_incident_id": (
                    str(trace.search_response.results[0].incident_id)
                    if trace.search_response.results
                    else None
                ),
                "latency_ms": elapsed_ms,
            }
        )

    try:
        retrieval_service.search_for_evaluation(
            query="case error",
            top_k=3,
            candidate_limit=20,
            rrf_k=60,
            project_name=None,  # type: ignore[arg-type]
        )
    except Exception as exc:
        results.append(
            {
                "scenario": "case_error",
                "case_key": "smoke_invalid_empty_query",
                "error_message": str(exc),
            }
        )
    return results


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
            run_name=f"{CASE_PREFIX}_baseline",
            top_k=3,
            candidate_limit=20,
            rrf_k=60,
        )
    )


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        cases = materialize_cases(session)
        save_candidate_json(cases)
        upsert_cases(session, cases)
        smoke_results = run_smoke(session, cases)
        print("SMOKE_RESULTS_JSON")
        print(json.dumps(smoke_results, ensure_ascii=False, indent=2, default=str))
        baseline = run_baseline(session)
        print("BASELINE_RUN_JSON")
        print(
            json.dumps(
                baseline.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
