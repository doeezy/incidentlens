# Query Rewrite Prompt v2 Baseline

Query Rewrite 프롬프트 변경 효과만 확인하기 위한 재실행 결과다. Evaluation Dataset, seed 데이터, BM25, Vector, RRF, Confidence 로직은 변경하지 않았다.

## Run 설정

- previous_run_id: `6ad06c86-9c69-42b2-ba28-34d89ed951a7`
- current_run_id: `a69c71f3-ad79-46f8-92b5-ea7b9e5c120e`
- top_k: `3`
- candidate_limit: `20`
- rrf_k: `60`
- case_count: `46`

## Metrics 비교

| metric | previous | current | delta |
| --- | ---: | ---: | ---: |
| retrieval_top1_accuracy | 0.825 | 0.775 | -0.050 |
| retrieval_top3_accuracy | 0.975 | 0.975 | +0.000 |
| retrieval_mrr | 0.897 | 0.876 | -0.021 |
| final_top1_accuracy | 0.825 | 0.800 | -0.025 |
| final_top3_accuracy | 0.975 | 0.975 | +0.000 |
| final_mrr | 0.896 | 0.887 | -0.008 |
| no_result_accuracy | 1.000 | 1.000 | +0.000 |
| abstain_ratio | 0.152 | 0.152 | +0.000 |
| mean_latency_ms | 6220.159 | 6203.540 | -16.619 |

## 지정 Case 비교

- original query: `배치 컨테이너가 메모리 제한 때문에 비정상 종료된 장애 요약해줘`
- 이전 rewritten_query: `배치 컨테이너 메모리 제한 비정상 종료 장애 요약`
- 현재 rewritten_query: `배치 컨테이너 메모리 제한 비정상 종료 장애 요약`
- 이전 RRF rank: `5`
- 현재 RRF rank: `5`
- 이전 최종 상태: `miss`
- 현재 최종 상태: `miss`
- 변화: `same`

## Case 변화 요약

- 개선된 Case: `1`
- 동일한 Case: `43`
- 하락한 Case: `2`
- rewritten_query가 바뀐 Case: `27`
- RRF rank가 바뀐 Case: `3`

## 개선된 Case

| case_key | previous rewrite | current rewrite | previous RRF | current RRF | previous final | current final |
| --- | --- | --- | ---: | ---: | --- | --- |
| `enriched_seed_v1_ambiguous_query_006` | admin-portal 외부 연동 호출 실패 장애 설명 | admin-portal 외부 연동 호출 실패 장애 요약 | 3 | 2 | top3 | top1 |

## 하락한 Case

| case_key | previous rewrite | current rewrite | previous RRF | current RRF | previous final | current final |
| --- | --- | --- | ---: | ---: | --- | --- |
| `enriched_seed_v1_ambiguous_query_004` | batch-platform 이벤트 발행 실패 사례 | batch-platform 이벤트 발행 실패 유사 장애 사례 | 1 | 2 | top1 | top3 |
| `enriched_seed_v1_cross_project_conflict_001` | data-portal 로그인 클래스 로딩 실패 사례 | data-portal 로그인 클래스 로딩 실패 유사 장애 사례 | 1 | 2 | top1 | top3 |

## rewritten_query 변경 Case

| case_key | previous rewrite | current rewrite | previous RRF | current RRF | previous final | current final |
| --- | --- | --- | ---: | ---: | --- | --- |
| `enriched_seed_v1_ambiguous_query_003` | admin-portal 권한 문제 장애 사례 | admin-portal 권한 문제 장애 유사 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_ambiguous_query_004` | batch-platform 이벤트 발행 실패 사례 | batch-platform 이벤트 발행 실패 유사 장애 사례 | 1 | 2 | top1 | top3 |
| `enriched_seed_v1_ambiguous_query_006` | admin-portal 외부 연동 호출 실패 장애 설명 | admin-portal 외부 연동 호출 실패 장애 요약 | 3 | 2 | top3 | top1 |
| `enriched_seed_v1_cross_project_conflict_001` | data-portal 로그인 클래스 로딩 실패 사례 | data-portal 로그인 클래스 로딩 실패 유사 장애 사례 | 1 | 2 | top1 | top3 |
| `enriched_seed_v1_cross_project_conflict_002` | admin-portal 로그인 클래스 로딩 실패 사례 | admin-portal 로그인 클래스 로딩 실패 유사 장애 사례 | 3 | 3 | top3 | top3 |
| `enriched_seed_v1_cross_project_conflict_003` | batch-platform Redis 접속 수 초과 원인 | batch-platform Redis 접속 수 초과 캐시 장애 요약 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_cross_project_conflict_004` | admin-portal Redis 연결 풀 고갈 캐시 조회 실패 사례 | admin-portal Redis 연결 풀 고갈 캐시 조회 실패 유사 장애 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_cross_project_conflict_005` | data-portal 파트너 프로필 조회 timeout 3000ms 원인 | data-portal 파트너 프로필 조회 3000ms timeout 원인 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_exact_keyword_002` | paymentMethod NullPointerException 원인 DataPaymentService PAY-4021 | paymentMethod NullPointerException PAY-4021 DataPaymentService 원인 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_exact_keyword_006` | KafkaSerializationException schema version v3 원인 | KafkaSerializationException schema version v3 BatchKafkaEventPublisher 장애 요약 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_exact_keyword_007` | Docker container exited code 137 BatchContainerSupervisor 원인 | Docker container exited code 137 BatchContainerSupervisor 장애 요약 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_no_relevant_result_003` | 관리자 화면 CSS 깨짐 원인 정적 리소스 캐시 문제 | 관리자 화면 CSS 깨짐 정적 리소스 캐시 문제 원인 | n/a | n/a | no_result_correct | no_result_correct |
| `enriched_seed_v1_no_relevant_result_004` | S3 백업 파일 압축 해제 실패 사례 | S3 백업 파일 압축 해제 실패 유사 장애 사례 | n/a | n/a | no_result_correct | no_result_correct |
| `enriched_seed_v1_no_relevant_result_006` | 사용자 프로필 이미지 크롭 오류 원인 | 사용자 프로필 이미지 크롭 기능 오류 | n/a | n/a | no_result_correct | no_result_correct |
| `enriched_seed_v1_same_error_different_cause_003` | 데이터 포털 결제 승인 paymentMethod null 문제 원인 | 데이터 포털 결제 결제 승인 전에 paymentMethod null 문제 원인 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_same_error_different_cause_004` | 관리자 포털 결제 승인 결제수단 검증 전 Null 오류 원인 | 관리자 포털 결제 승인 결제수단 검증 전 NullPointerException 원인 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_same_error_different_cause_006` | 배치 권한 검사 REPORT_ADMIN role 문제 사례 | 배치 권한 검사 REPORT_ADMIN role 차단 유사 장애 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_same_error_different_cause_008` | 관리자 webhook JSON 매핑 실패 새 status enum 값 사례 | 관리자 webhook 새 status enum 값 JSON 매핑 실패 유사 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_same_error_different_cause_009` | 주문 confirm 중복 요청 optimistic lock 장애 요약 | 주문 confirm 중복 요청 동일 row 동시 갱신 optimistic lock 장애 원인 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_same_error_different_cause_010` | 배치 주문 confirm 동시 갱신 충돌 사례 | 배치 주문 confirm 동일 row 동시 갱신 충돌 유사 장애 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_semantic_paraphrase_001` | 로그인 인증 토큰 클래스 미발견 원인 | 로그인 인증 토큰 클래스 로딩 실패 원인 | 2 | 2 | top3 | top3 |
| `enriched_seed_v1_semantic_paraphrase_002` | 결제 승인 결제수단 값 비어 장애 해결 방법 | 결제 승인 결제수단 값 비어 오류 해결 방법 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_semantic_paraphrase_003` | 리포트 화면 상태 컬럼 조회 500 에러 사례 | 리포트 화면 상태 컬럼 없음 500 오류 유사 장애 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_semantic_paraphrase_004` | 관리자 리포트 접근 권한 role 원인 | 관리자 리포트 접근 권한 role 제한 원인 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_semantic_paraphrase_006` | 배치 이벤트 직렬화 실패 스키마 버전 불일치 사례 | 배치 이벤트 발행 스키마 버전 불일치 직렬화 실패 유사 장애 사례 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_semantic_paraphrase_009` | 캐시 서버 연결 수 과다 Redis 조회 실패 해결 방법 | 캐시 서버 연결 수 초과 Redis 조회 실패 장애 해결 방법 | 1 | 1 | top1 | top1 |
| `enriched_seed_v1_semantic_paraphrase_010` | 파트너 프로필 API 응답 지연 장애 사례 | 파트너 프로필 API 3초 응답 지연 장애 유사 사례 | 1 | 1 | top1 | top1 |

## RRF rank 변경 Case

| case_key | previous rewrite | current rewrite | previous RRF | current RRF | previous final | current final |
| --- | --- | --- | ---: | ---: | --- | --- |
| `enriched_seed_v1_ambiguous_query_004` | batch-platform 이벤트 발행 실패 사례 | batch-platform 이벤트 발행 실패 유사 장애 사례 | 1 | 2 | top1 | top3 |
| `enriched_seed_v1_ambiguous_query_006` | admin-portal 외부 연동 호출 실패 장애 설명 | admin-portal 외부 연동 호출 실패 장애 요약 | 3 | 2 | top3 | top1 |
| `enriched_seed_v1_cross_project_conflict_001` | data-portal 로그인 클래스 로딩 실패 사례 | data-portal 로그인 클래스 로딩 실패 유사 장애 사례 | 1 | 2 | top1 | top3 |
