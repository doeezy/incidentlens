from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine
from app.main import app


SEED_VERSION = "hybrid-search-v1"
SEED_NAMESPACE = uuid.UUID("619dfca4-26d1-4b03-ad17-e7f273709ce7")
EXPECTED_PATH = Path("seed_data/hybrid_search_expected.json")
BASE_TIME = datetime(2026, 6, 1, 9, 0, 0)


@dataclass(frozen=True)
class Scenario:
    key: str
    project: str
    repo: str
    module: str
    class_name: str
    method: str
    error_type: str
    error_message: str
    summary: str
    cause: str
    fix: str
    exact_terms: list[str]
    alt_phrases: list[str]


def stable_uuid(name: str) -> str:
    return str(uuid.uuid5(SEED_NAMESPACE, name))


def iso(dt: datetime) -> str:
    return dt.isoformat()


def build_scenarios() -> list[Scenario]:
    project_specs = {
        "data-portal": {
            "repo": "data-portal-service",
            "prefix": "Data",
            "domain": "데이터 포털",
        },
        "admin-portal": {
            "repo": "admin-portal-service",
            "prefix": "Admin",
            "domain": "관리자 포털",
        },
        "batch-platform": {
            "repo": "batch-platform-service",
            "prefix": "Batch",
            "domain": "배치 플랫폼",
        },
    }
    templates = [
        (
            "jwt-class-not-found",
            "auth",
            "AuthService",
            "login",
            "ClassNotFoundException",
            "com.example.auth.JwtTokenProvider",
            "로그인 인증 클래스 로딩 실패",
            "JwtTokenProvider 라이브러리 또는 패키지 경로가 런타임 classpath와 맞지 않았습니다.",
            "빌드 의존성과 import 경로를 정리했습니다.",
            ["JwtTokenProvider", "ClassNotFoundException", "login"],
            ["인증 토큰 provider를 못 찾음", "로그인 직후 클래스 로딩 실패"],
        ),
        (
            "payment-null-pointer",
            "payment",
            "PaymentService",
            "approve",
            "NullPointerException",
            "paymentMethod is null",
            "결제 승인 중 널 참조",
            "결제 수단 검증 전에 paymentMethod를 참조했습니다.",
            "null guard와 결제 수단 기본값 검증을 추가했습니다.",
            ["paymentMethod", "NullPointerException", "PAY-4021"],
            ["결제 승인 NPE", "결제수단 없이 승인 요청"],
        ),
        (
            "redis-pool-exhausted",
            "cache",
            "RedisCacheClient",
            "get",
            "RedisConnectionException",
            "ERR max number of clients reached",
            "Redis 연결 풀 고갈",
            "커넥션 반환 누락으로 Redis client pool이 고갈되었습니다.",
            "try-finally 반환 처리와 pool maxTotal 설정을 조정했습니다.",
            ["RedisConnectionException", "maxTotal", "cache"],
            ["캐시 서버 접속 실패", "Redis client pool exhausted"],
        ),
        (
            "sql-bad-column",
            "report",
            "ReportQueryRepository",
            "findDaily",
            "SQLGrammarException",
            "column report_status_cd does not exist",
            "리포트 조회 SQL 컬럼 오류",
            "마이그레이션 후 컬럼명이 report_state_cd로 바뀌었지만 쿼리가 갱신되지 않았습니다.",
            "쿼리 컬럼명과 매핑 DTO를 수정했습니다.",
            ["report_status_cd", "SQLGrammarException", "report_state_cd"],
            ["리포트 화면 500", "없는 컬럼 조회"],
        ),
        (
            "partner-timeout",
            "integration",
            "PartnerApiClient",
            "fetchProfile",
            "TimeoutException",
            "partner profile API timed out after 3000ms",
            "외부 파트너 API 타임아웃",
            "파트너 API 지연 시 재시도 없이 동기 호출이 누적되었습니다.",
            "timeout 값을 분리하고 circuit breaker fallback을 추가했습니다.",
            ["TimeoutException", "partner-profile", "3000ms"],
            ["외부 API 응답 지연", "파트너 프로필 조회 지연"],
        ),
        (
            "config-file-missing",
            "config",
            "FeatureFlagLoader",
            "load",
            "FileNotFoundException",
            "/etc/incidentlens/feature-flags.yml",
            "feature flag 설정 파일 누락",
            "배포 이미지에 feature-flags.yml이 포함되지 않았습니다.",
            "컨테이너 이미지에 설정 파일을 포함하고 mount 경로를 보정했습니다.",
            ["feature-flags.yml", "FileNotFoundException", "/etc/incidentlens"],
            ["설정 파일 없음", "feature flag 로딩 실패"],
        ),
        (
            "docker-container-exit",
            "runtime",
            "ContainerSupervisor",
            "watch",
            "ContainerExitError",
            "Docker container exited with code 137",
            "Docker 컨테이너 비정상 종료",
            "메모리 제한 초과로 컨테이너가 OOM 종료되었습니다.",
            "memory limit을 상향하고 heap 옵션을 낮췄습니다.",
            ["Docker", "ContainerExitError", "code 137"],
            ["컨테이너가 갑자기 종료", "OOMKilled"],
        ),
        (
            "kafka-serialization",
            "stream",
            "KafkaEventPublisher",
            "publish",
            "KafkaSerializationException",
            "cannot serialize schema version v3",
            "Kafka 이벤트 직렬화 실패",
            "producer와 schema registry의 이벤트 버전이 맞지 않았습니다.",
            "schema version pinning과 호환 필드를 추가했습니다.",
            ["KafkaSerializationException", "schema registry", "v3"],
            ["이벤트 발행 실패", "스키마 버전 불일치"],
        ),
        (
            "access-denied",
            "security",
            "PermissionEvaluator",
            "check",
            "AccessDeniedException",
            "role REPORT_ADMIN required",
            "권한 검증 실패",
            "권한 role 매핑에서 신규 role이 누락되었습니다.",
            "REPORT_ADMIN role seed와 권한 캐시 갱신을 추가했습니다.",
            ["AccessDeniedException", "REPORT_ADMIN", "permission"],
            ["권한 없음", "관리자 권한인데 차단"],
        ),
        (
            "json-mapping",
            "api",
            "WebhookController",
            "receive",
            "JsonMappingException",
            "Cannot deserialize value of type EventStatus",
            "Webhook JSON 매핑 실패",
            "외부 webhook status enum 값이 새로 추가되었지만 서버 enum이 갱신되지 않았습니다.",
            "UNKNOWN enum fallback과 신규 status 값을 추가했습니다.",
            ["JsonMappingException", "EventStatus", "webhook"],
            ["웹훅 파싱 실패", "enum 역직렬화 오류"],
        ),
        (
            "optimistic-lock",
            "order",
            "OrderCommandService",
            "confirm",
            "OptimisticLockException",
            "row was updated or deleted by another transaction",
            "동시 처리 중 optimistic lock 충돌",
            "중복 confirm 요청이 같은 주문 row를 동시에 갱신했습니다.",
            "idempotency key와 재시도 정책을 추가했습니다.",
            ["OptimisticLockException", "idempotency", "order"],
            ["동시성 충돌", "중복 요청으로 주문 확정 실패"],
        ),
        (
            "ssl-handshake",
            "client",
            "SecureHttpClient",
            "request",
            "SSLHandshakeException",
            "PKIX path building failed",
            "TLS 인증서 검증 실패",
            "신규 인증서 체인이 truststore에 반영되지 않았습니다.",
            "truststore를 갱신하고 인증서 만료 모니터링을 추가했습니다.",
            ["SSLHandshakeException", "PKIX", "truststore"],
            ["TLS handshake 실패", "인증서 체인 오류"],
        ),
    ]

    scenarios: list[Scenario] = []
    for project, spec in project_specs.items():
        for index, tpl in enumerate(templates, start=1):
            (
                key,
                module,
                class_name,
                method,
                error_type,
                error_message,
                summary,
                cause,
                fix,
                terms,
                phrases,
            ) = tpl
            prefix = spec["prefix"]
            project_key = project.replace("-", "_")
            scenarios.append(
                Scenario(
                    key=f"{project_key}-{key}",
                    project=project,
                    repo=spec["repo"],
                    module=module,
                    class_name=f"{prefix}{class_name}",
                    method=method,
                    error_type=error_type,
                    error_message=error_message,
                    summary=f"{spec['domain']} {summary}",
                    cause=cause,
                    fix=fix,
                    exact_terms=terms + [SEED_VERSION, project],
                    alt_phrases=phrases,
                )
            )
    return scenarios


def raw_log_payload(scenario: Scenario, scenario_index: int, log_index: int) -> dict[str, Any]:
    occurred_at = BASE_TIME + timedelta(days=scenario_index * 3, minutes=log_index * 7)
    phrase = scenario.alt_phrases[log_index % len(scenario.alt_phrases)]
    raw_message = "\n".join(
        [
            (
                f"{occurred_at:%Y-%m-%d %H:%M:%S} ERROR "
                f"com.example.{scenario.module}.{scenario.class_name} - "
                f"{scenario.summary}; {phrase}; seed={SEED_VERSION}; scenario={scenario.key}"
            ),
            f"java.lang.{scenario.error_type}: {scenario.error_message}",
            (
                f"    at com.example.{scenario.module}.{scenario.class_name}."
                f"{scenario.method}({scenario.class_name}.java:{40 + log_index})"
            ),
            "    at org.springframework.web.filter.OncePerRequestFilter.doFilter(OncePerRequestFilter.java:116)",
        ]
    )
    return {
        "id": stable_uuid(f"{scenario.key}:log:{log_index}"),
        "project_name": scenario.project,
        "raw_message": raw_message,
        "occurred_at": iso(occurred_at),
    }


def ticket_payload(
    scenario: Scenario,
    scenario_index: int,
    issue_number: int,
    has_pr: bool,
) -> dict[str, Any]:
    created_at = BASE_TIME + timedelta(days=scenario_index * 3, hours=2)
    state = "closed" if has_pr else "open"
    title = f"[{SEED_VERSION}] {scenario.summary} - {scenario.error_type}"
    body = (
        f"seed={SEED_VERSION}\n"
        f"scenario={scenario.key}\n"
        f"증상: {scenario.alt_phrases[0]}\n"
        f"에러: {scenario.error_type}\n"
        f"메시지: {scenario.error_message}\n"
        f"추정 원인: {scenario.cause}\n"
        f"정확 키워드: {', '.join(scenario.exact_terms)}"
    )
    return {
        "project_name": scenario.project,
        "repository_name": scenario.repo,
        "issue": {
            "number": issue_number,
            "title": title,
            "body": body,
            "state": state,
            "user": {"login": "incidentlens-seed"},
            "assignees": [{"login": "oncall-seed"}],
            "labels": [{"name": "priority: p2"}, {"name": f"seed:{SEED_VERSION}"}],
            "created_at": iso(created_at),
            "updated_at": iso(created_at + timedelta(minutes=30)),
            "closed_at": iso(created_at + timedelta(hours=4)) if has_pr else None,
        },
    }


def pr_payload(
    scenario: Scenario,
    scenario_index: int,
    issue_number: int,
    pr_number: int,
) -> dict[str, Any]:
    created_at = BASE_TIME + timedelta(days=scenario_index * 3, hours=3)
    merged_at = created_at + timedelta(hours=1)
    file_name = f"src/main/java/com/example/{scenario.module}/{scenario.class_name}.java"
    patch = (
        "@@ -20,6 +20,10 @@\n"
        f"- throw new {scenario.error_type}(\"{scenario.error_message}\");\n"
        f"+ // {scenario.fix}\n"
        f"+ metrics.increment(\"{scenario.key}.fixed\");\n"
    )
    return {
        "project_name": scenario.project,
        "repository_name": scenario.repo,
        "pull_request": {
            "number": pr_number,
            "title": f"[{SEED_VERSION}] fix: {scenario.summary}",
            "body": (
                f"Fixes #{issue_number}\n\n"
                f"seed={SEED_VERSION}\n"
                f"scenario={scenario.key}\n"
                f"원인: {scenario.cause}\n"
                f"해결: {scenario.fix}\n"
                f"keywords: {', '.join(scenario.exact_terms)}"
            ),
            "state": "closed",
            "merged": True,
            "user": {"login": "incidentlens-seed"},
            "head": {"ref": f"fix/{scenario.key}-#{issue_number}"},
            "base": {"ref": "main"},
            "created_at": iso(created_at),
            "updated_at": iso(merged_at),
            "merged_at": iso(merged_at),
        },
        "files": [
            {
                "filename": file_name,
                "status": "modified",
                "patch": patch,
            }
        ],
        "commits": [
            {"message": f"fix {scenario.error_type} for {scenario.key} #{issue_number}"}
        ],
    }


def seed_already_present() -> bool:
    with engine.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT count(*)
                FROM raw_logs
                WHERE raw_message LIKE :marker
                """
            ),
            {"marker": f"%seed={SEED_VERSION}%"},
        ).scalar_one()
    return int(count) > 0


def collect_existing_expectations(scenarios: list[Scenario]) -> dict[str, Any]:
    first_log_ids = [stable_uuid(f"{scenario.key}:log:0") for scenario in scenarios]
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    rl.id AS raw_log_id,
                    rl.incident_id AS incident_id,
                    i.project_name,
                    i.primary_error_type,
                    i.primary_error_message,
                    i.status,
                    i.resolved_at
                FROM raw_logs rl
                JOIN incidents i ON i.id = rl.incident_id
                WHERE rl.id = ANY(CAST(:ids AS uuid[]))
                ORDER BY i.project_name, i.first_detected_at
                """
            ),
            {"ids": first_log_ids},
        ).mappings().all()
        counts = conn.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM incidents i WHERE EXISTS (
                        SELECT 1 FROM raw_logs rl
                        WHERE rl.incident_id = i.id
                          AND rl.raw_message LIKE :marker
                    )) AS incidents,
                    (SELECT count(*) FROM raw_logs WHERE raw_message LIKE :marker) AS raw_logs,
                    (SELECT count(*) FROM raw_tickets WHERE description LIKE :marker) AS tickets,
                    (SELECT count(*) FROM raw_prs WHERE description LIKE :marker) AS prs
                """
            ),
            {"marker": f"%seed={SEED_VERSION}%"},
        ).mappings().one()

    by_scenario = {}
    row_by_log_id = {str(row["raw_log_id"]): row for row in rows}
    for scenario in scenarios:
        row = row_by_log_id.get(stable_uuid(f"{scenario.key}:log:0"))
        by_scenario[scenario.key] = {
            "project_name": scenario.project,
            "description": scenario.summary,
            "error_type": scenario.error_type,
            "error_message": scenario.error_message,
            "expected_incident_id": str(row["incident_id"]) if row else None,
            "expected_status": row["status"] if row else None,
            "exact_terms": scenario.exact_terms,
            "alternative_phrases": scenario.alt_phrases,
        }

    return {
        "seed_version": SEED_VERSION,
        "counts": dict(counts),
        "scenarios": by_scenario,
        "hybrid_search_queries": [
            {
                "name": "exact_class_and_exception",
                "project_name": "data-portal",
                "query": "JwtTokenProvider ClassNotFoundException",
                "expected_scenario": "data_portal-jwt-class-not-found",
                "expected_incident_id": by_scenario[
                    "data_portal-jwt-class-not-found"
                ]["expected_incident_id"],
            },
            {
                "name": "same_error_different_cause",
                "project_name": "data-portal",
                "query": "결제 NullPointerException paymentMethod",
                "expected_scenario": "data_portal-payment-null-pointer",
                "expected_incident_id": by_scenario[
                    "data_portal-payment-null-pointer"
                ]["expected_incident_id"],
            },
            {
                "name": "project_filter_similar_incident",
                "project_name": "admin-portal",
                "query": "Docker 컨테이너 종료 code 137",
                "expected_scenario": "admin_portal-docker-container-exit",
                "expected_incident_id": by_scenario[
                    "admin_portal-docker-container-exit"
                ]["expected_incident_id"],
            },
            {
                "name": "keyword_required_config_path",
                "project_name": "batch-platform",
                "query": "/etc/incidentlens/feature-flags.yml FileNotFoundException",
                "expected_scenario": "batch_platform-config-file-missing",
                "expected_incident_id": by_scenario[
                    "batch_platform-config-file-missing"
                ]["expected_incident_id"],
            },
            {
                "name": "natural_language_variant",
                "project_name": "data-portal",
                "query": "웹훅 enum 역직렬화 오류",
                "expected_scenario": "data_portal-json-mapping",
                "expected_incident_id": by_scenario["data_portal-json-mapping"][
                    "expected_incident_id"
                ],
            },
        ],
    }


def write_expectations(scenarios: list[Scenario]) -> dict[str, Any]:
    expectations = collect_existing_expectations(scenarios)
    EXPECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPECTED_PATH.write_text(
        json.dumps(expectations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return expectations


def post_or_raise(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{path} failed: {response.status_code}\n"
            f"payload={json.dumps(payload, ensure_ascii=False)}\n"
            f"response={response.text}"
        )
    return response.json()


def ingest_seed(scenarios: list[Scenario]) -> dict[str, int]:
    stats = {"raw_logs": 0, "tickets": 0, "prs": 0}
    with TestClient(app) as client:
        for scenario_index, scenario in enumerate(scenarios):
            log_count = 2 + (scenario_index % 3)
            for log_index in range(log_count):
                post_or_raise(
                    client,
                    "/raw-logs",
                    raw_log_payload(scenario, scenario_index, log_index),
                )
                stats["raw_logs"] += 1

        for scenario_index, scenario in enumerate(scenarios[:25]):
            issue_number = 910000 + scenario_index
            has_pr = scenario_index < 20
            post_or_raise(
                client,
                "/raw-tickets",
                ticket_payload(scenario, scenario_index, issue_number, has_pr),
            )
            stats["tickets"] += 1

        for scenario_index, scenario in enumerate(scenarios[:20]):
            issue_number = 910000 + scenario_index
            pr_number = 920000 + scenario_index
            post_or_raise(
                client,
                "/raw-prs",
                pr_payload(scenario, scenario_index, issue_number, pr_number),
            )
            stats["prs"] += 1
    return stats


def main() -> None:
    scenarios = build_scenarios()
    if seed_already_present():
        expectations = write_expectations(scenarios)
        print(
            json.dumps(
                {
                    "seed_version": SEED_VERSION,
                    "action": "skipped_existing_seed",
                    "expected_file": str(EXPECTED_PATH),
                    "counts": expectations["counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    ingested = ingest_seed(scenarios)
    expectations = write_expectations(scenarios)
    print(
        json.dumps(
            {
                "seed_version": SEED_VERSION,
                "action": "ingested",
                "ingested": ingested,
                "expected_file": str(EXPECTED_PATH),
                "counts": expectations["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
