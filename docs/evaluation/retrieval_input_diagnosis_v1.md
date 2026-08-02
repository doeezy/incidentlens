# Retrieval Input Diagnosis v1

- source_report: `/Users/doeezy/Documents/toy-project/incidentlens/docs/evaluation/rrf_ranking_miss_analysis.json`
- 분석 대상: `RRF_RANKING_MISS`
- 케이스 수: `17`

## Executive Summary

- 17건 모두 정답 Incident가 BM25 후보에 없고, Vector에서는 후보에 존재하지만 Top3 밖입니다.
- expected Incident의 primary_error_summary 누락: `17` / 17
- RRF Top3 오답 후보의 primary_error_summary 누락: `37` / 51
- expected Incident vector_score=0.0: `11` / 17

## 데이터 완성도 Overview

| project_name | total | summary_present | keywords_present | domain_tags_present | resolution_present |
| --- | ---: | ---: | ---: | ---: | ---: |
| admin-portal | 12 | 0 | 0 | 0 | 8 |
| batch-platform | 12 | 0 | 0 | 0 | 0 |
| data-portal | 14 | 2 | 2 | 2 | 13 |

- raw table row counts: `{'raw_logs': 111, 'raw_tickets': 27, 'raw_prs': 21}`
- 생성 시점 기준 초반 incident에는 summary/keywords/domain_tags가 채워진 사례가 있으나, 이후 seed incident는 대부분 비어 있습니다.
- 이는 report 조회 문제가 아니라 데이터 생성/enrichment 경로 차이입니다.

초기 incident 샘플:

| id | project | summary_present | keywords | domain_tags | created_at |
| --- | --- | --- | --- | --- | --- |
| `072e1cca-72be-4116-b1de-618b9b42c499` | data-portal | Y | AuthService ClassNotFoundException ERROR com.example.auth.JwtTokenProvider lo... | auth login | 2026-06-07 16:27:28.860171 |
| `7f929778-811d-4ec0-b344-74f54f61b5aa` | data-portal | Y | ERROR NullPointerException PaymentService pay payment request is null null pa... | payment | 2026-06-07 16:28:46.132133 |
| `f75ed7cd-926a-43d5-918c-e2c2a0031b1e` | data-portal | N | - | - | 2026-07-13 18:56:38.165713 |
| `307fca68-d871-463c-b2e9-9bc51652fd0b` | data-portal | N | - | - | 2026-07-13 18:56:38.212038 |
| `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8` | data-portal | N | - | - | 2026-07-13 18:56:38.236037 |
| `3caa466f-49bd-4762-bb00-d4f27ac9f314` | data-portal | N | - | - | 2026-07-13 18:56:38.266099 |
| `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4` | data-portal | N | - | - | 2026-07-13 18:56:38.280674 |
| `14861fa5-b251-48a5-822b-947f83fc8e34` | data-portal | N | - | - | 2026-07-13 18:56:38.303180 |

최근 incident 샘플:

| id | project | summary_present | keywords | domain_tags | created_at |
| --- | --- | --- | --- | --- | --- |
| `d8c2d1ac-3e4d-4906-a429-4bbf76119c57` | batch-platform | N | - | - | 2026-07-13 18:56:39.098746 |
| `d4253455-0df0-4733-8c52-a768a47d47f9` | batch-platform | N | - | - | 2026-07-13 18:56:39.074224 |
| `cf5b6945-b8e5-472a-b5cc-4e6791b1a44d` | batch-platform | N | - | - | 2026-07-13 18:56:39.057618 |
| `5772b2f7-ba7a-4538-bfa0-a5b460e99270` | batch-platform | N | - | - | 2026-07-13 18:56:39.026314 |
| `f7684112-d72d-4bc2-a9c6-162002937333` | batch-platform | N | - | - | 2026-07-13 18:56:39.001943 |
| `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` | batch-platform | N | - | - | 2026-07-13 18:56:38.984894 |
| `2136ba47-6d5c-4436-8635-b6d71e5bdcf1` | batch-platform | N | - | - | 2026-07-13 18:56:38.952197 |
| `e3b07adc-a00a-4afb-ac77-ae9ba8ddbdd8` | batch-platform | N | - | - | 2026-07-13 18:56:38.928285 |

### Primary Root Cause Counts

| root cause | count |
| --- | ---: |
| `INCIDENT_ENRICHMENT_MISSING` | 7 |
| `RAW_EVIDENCE_NOT_PROPAGATED` | 10 |

### BM25 Failure Reason Counts

| reason | count |
| --- | ---: |
| `ARRAY_JSON_NOT_INDEXED` | 17 |
| `ENGLISH_KOREAN_SYNONYM_MISMATCH` | 17 |
| `INCIDENT_DATA_MISSING` | 17 |
| `KOREAN_TOKENIZATION_MISMATCH` | 10 |
| `QUERY_TOO_GENERIC` | 2 |

## BM25 Index 점검

현재 BM25 document는 `public.incident_searchable_text(...)` 함수 결과를 `pdb.simple`로 인덱싱합니다.

의도 검색 필드 포함 여부:

| field | 포함 여부 | 비고 |
| --- | --- | --- |
| `primary_error_summary` | Y | 함수 정의에 포함 |
| `primary_error_type` | Y | 함수 정의에 포함 |
| `primary_error_message` | Y | 함수 정의에 포함 |
| `error_keywords` | Y | 함수 정의에 포함, jsonb_array_elements_text로 배열 문자열화 |
| `domain_tags` | Y | 함수 정의에 포함, jsonb_array_elements_text로 배열 문자열화 |
| `suspected_cause` | Y | 함수 정의에 포함 |
| `root_cause_summary` | Y | 함수 정의에 포함 |
| `resolution_summary` | Y | 함수 정의에 포함 |

BM25 인덱스 정의:

- `incidents_bm25_search_idx`: `CREATE INDEX incidents_bm25_search_idx ON public.incidents USING bm25 (id, project_name, ((incident_searchable_text(primary_error_summary, (primary_error_type)::text, primary_error_message, error_keywords, domain_tags, suspected_cause, root_cause_summary, resolution_summary))::pdb.simple('alias=searchable_text'))) WITH (key_field=id)`

판단:

- `concat_ws`를 사용하므로 일부 필드가 null이어도 전체 searchable text가 null이 되지는 않습니다.
- 배열 필드는 함수 정의상 문자열화됩니다. 다만 값 자체가 빈 배열이면 인덱싱할 token이 없습니다.
- `CREATE INDEX IF NOT EXISTS` 구조라 함수 정의가 바뀐 뒤 기존 인덱스가 자동 재생성되지는 않습니다. 이번 진단에서는 인덱스를 재생성하지 않았습니다.
- project_name 필터와 BM25 조건은 같은 WHERE 절에 함께 적용됩니다.

## Summary=None 원인

- 리포트 코드의 조회 문제나 ORM mapping 문제라기보다, 실제 `incidents.primary_error_summary`가 null인 데이터가 많습니다.
- 초기 일부 incident는 summary가 존재하지만, seed 이후 생성된 다수 incident는 error_type/message 중심으로만 채워지고 summary/keywords/domain_tags/root_cause/resolution이 비어 있습니다.
- 따라서 `summary=None`은 report mapping bug가 아니라 incident enrichment 누락 또는 seed 데이터 생성 경로 차이로 보는 것이 맞습니다.

## Embedding 점검

- embedding_text는 incident 필드만 조합합니다: project/module/class/status/error_type/summary/message/cause/root_cause/resolution/keywords/tags.
- raw_logs/raw_tickets/raw_prs 원문은 embedding_text에 직접 포함되지 않습니다.
- incident의 summary, keywords, tags, cause, resolution이 비어 있으면 embedding_text도 error_type/message 위주로 짧아집니다.

## Vector Score 0.0 원인

- 현재 score 계산은 `max(0.0, 1.0 - cosine_distance)`입니다.
- pgvector cosine distance는 `1 - cosine_similarity`이므로, distance가 1 이상이면 similarity가 0 이하입니다.
- 따라서 vector_score=0.0은 표시 반올림 문제가 아니라 음수 또는 0 이하 similarity가 clipping된 결과입니다.

## 실패 케이스별 진단표

| case_key | expected_incident_id | summary | embedding | embedding 핵심어 | raw similarity | vector rank | BM25 doc | BM25 match token | BM25 rank | primary root cause | recommended fix |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | ---: | --- | --- |
| `retrieval_eval_v1_ambiguous_query_003` | `433dff0c-eeaf-481f-99cf-b9d041befd1e` | N | Y | - | 0.002504 | 6 | Y | - | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_ambiguous_query_004` | `f7684112-d72d-4bc2-a9c6-162002937333` | N | Y | - | -0.023983 | 8 | Y | - | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_ambiguous_query_005` | `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8` | N | Y | - | -0.026811 | 12 | Y | - | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_ambiguous_query_006` | `ddf82944-5f08-46f8-9e95-f6b3ddafa590` | N | Y | - | 0.013421 | 4 | Y | - | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_cross_project_conflict_002` | `7efeab5b-e531-496c-8a41-69d72e239439` | N | Y | admin, portal | 0.021416 | 4 | Y | admin | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_cross_project_conflict_003` | `9233f432-d5ef-4d51-b607-6f5a2eb28305` | N | Y | redis | -0.004565 | 6 | Y | redis | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_cross_project_conflict_004` | `6f48f638-1d3f-46af-bd87-a77f17652e57` | N | Y | redis | -0.016503 | 11 | Y | redis | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_cross_project_conflict_005` | `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4` | N | Y | data, portal, timeout | 0.031547 | 4 | Y | data, timeout | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_cross_project_conflict_006` | `e3b07adc-a00a-4afb-ac77-ae9ba8ddbdd8` | N | Y | batch, platform | -0.034293 | 11 | Y | - | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_same_error_different_cause_006` | `074fa857-4bf2-4ba1-9c42-b5db1f97cb2e` | N | Y | json | -0.004159 | 11 | Y | json | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_same_error_different_cause_008` | `36b6be9d-8fb0-497d-983b-f010e0d0a564` | N | Y | - | -0.007300 | 13 | Y | - | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_same_error_different_cause_010` | `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8` | N | Y | redis | -0.002183 | 11 | Y | redis | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_semantic_paraphrase_003` | `3caa466f-49bd-4762-bb00-d4f27ac9f314` | N | Y | - | 0.015694 | 5 | Y | - | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |
| `retrieval_eval_v1_semantic_paraphrase_004` | `433dff0c-eeaf-481f-99cf-b9d041befd1e` | N | Y | - | 0.017022 | 8 | Y | - | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_semantic_paraphrase_005` | `1e841c64-16f9-44e8-a856-a636ca807f1b` | N | Y | - | -0.001195 | 9 | Y | - | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_semantic_paraphrase_006` | `f7684112-d72d-4bc2-a9c6-162002937333` | N | Y | - | -0.026277 | 10 | Y | - | - | `INCIDENT_ENRICHMENT_MISSING` | incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다. |
| `retrieval_eval_v1_semantic_paraphrase_009` | `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8` | N | Y | redis | -0.034395 | 14 | Y | redis | - | `RAW_EVIDENCE_NOT_PROPAGATED` | raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다. |

## 케이스별 상세

### retrieval_eval_v1_ambiguous_query_003

- project_name: `admin-portal`
- expected_incident_id: `433dff0c-eeaf-481f-99cf-b9d041befd1e`
- original_query: 권한 문제로 막힌 장애 찾아줘
- rewritten_query / BM25 actual query: 권한 문제 장애 사례
- query tokens: `권한, 문제`
- indexed token hits: `-`
- indexed token misses: `권한, 문제`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH, QUERY_TOO_GENERIC`
- vector distance: `0.997496`
- cosine similarity: `0.002504`
- vector score: `0.002504`
- vector clipped: `N`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `212` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | AccessDeniedException |
| `primary_error_message` | `present` | role REPORT_ADMIN required |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | 50ba44d9-7180-59ed-87a7-dece4be192bd 960d2494-e90e-5a18-96d6-1a69a881be1c 9b272661-387f-5374-9a99-6540e35fb381 9e6d7e... |
| `related_ticket_ids` | `present` | c956e9bd-a854-4bab-83d3-4acea7a72450 |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: AccessDeniedException role REPORT_ADMIN required
- embedding_text: project=admin-portal module=security class=AdminPermissionEvaluator status=investigating error_type=AccessDeniedException summary= message=role REPORT_ADMIN required cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `313f2864-d8a0-480c-a487-d7fb5afa81b9` | - | KafkaSerializationException | 0.046816 | - | - |
| 2 | `087f5d77-20eb-4487-84da-4253cc128eca` | - | JsonMappingException | 0.028668 | - | - |
| 3 | `1e841c64-16f9-44e8-a856-a636ca807f1b` | - | SSLHandshakeException | 0.018232 | - | - |

### retrieval_eval_v1_ambiguous_query_004

- project_name: `batch-platform`
- expected_incident_id: `f7684112-d72d-4bc2-a9c6-162002937333`
- original_query: 배치에서 이벤트 발행 실패한 사례
- rewritten_query / BM25 actual query: 배치 이벤트 발행 실패 사례
- query tokens: `배치, 이벤트, 발행`
- indexed token hits: `-`
- indexed token misses: `배치, 이벤트, 발행`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.023983`
- cosine similarity: `-0.023983`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `217` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 3, 'raw_tickets': 0, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 0, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | KafkaSerializationException |
| `primary_error_message` | `present` | cannot serialize schema version v3 |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | fd78742d-e657-50e0-8c5f-cb939fc7c3b4 28f20719-ba34-59b8-9085-31e92f516459 61113179-d21a-5564-80f7-df97400d2db3 |
| `related_ticket_ids` | `empty_array` | - |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: KafkaSerializationException cannot serialize schema version v3
- embedding_text: project=batch-platform module=stream class=BatchKafkaEventPublisher status=open error_type=KafkaSerializationException summary= message=cannot serialize schema version v3 cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` | - | ClassNotFoundException | 0.036737 | - | - |
| 2 | `d4253455-0df0-4733-8c52-a768a47d47f9` | - | OptimisticLockException | 0.026569 | - | - |
| 3 | `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` | - | ContainerExitError | 0.022772 | - | - |

### retrieval_eval_v1_ambiguous_query_005

- project_name: `data-portal`
- expected_incident_id: `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8`
- original_query: 캐시 쪽 장애 원인이 뭐였어?
- rewritten_query / BM25 actual query: 캐시 장애 원인
- query tokens: `캐시`
- indexed token hits: `-`
- indexed token misses: `캐시`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH, QUERY_TOO_GENERIC`
- vector distance: `1.026811`
- cosine similarity: `-0.026811`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `304` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | RedisConnectionException |
| `primary_error_message` | `present` | ERR max number of clients reached |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 073056ef-e5ed-510f-8972-bb486cd7289e fdf78b12-1148-565b-936e-5a053ef970ae 5983d529-d6b3-554e-b8d1-76833cb921ea 67d24b... |
| `related_ticket_ids` | `present` | d75185ae-70ca-4743-ba0a-73ffff41c450 |
| `related_pr_ids` | `present` | 7ad267f4-9510-4020-9e2d-0183778c6dfe |

- BM25 indexed text: RedisConnectionException ERR max number of clients reached src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=cache class=DataRedisCacheClient status=resolved error_type=RedisConnectionException summary= message=ERR max number of clients reached cause= root_cause= resolution=src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.238754 | 1 | - |
| 2 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.184468 | - | - |
| 3 | `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4` | - | TimeoutException | 0.039600 | - | - |

### retrieval_eval_v1_ambiguous_query_006

- project_name: `admin-portal`
- expected_incident_id: `ddf82944-5f08-46f8-9e95-f6b3ddafa590`
- original_query: 외부 연동 호출 실패한 장애 설명해줘
- rewritten_query / BM25 actual query: 외부 연동 호출 실패 장애 설명
- query tokens: `외부, 연동, 호출`
- indexed token hits: `-`
- indexed token misses: `외부, 연동, 호출`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `0.986579`
- cosine similarity: `0.013421`
- vector score: `0.013421`
- vector clipped: `N`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `320` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 3, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | TimeoutException |
| `primary_error_message` | `present` | partner profile API timed out after 3000ms |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/integration/AdminPartnerApiClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | b2b208d5-c8b3-58ec-b95e-3ba3b970bdc0 5011794b-1ef1-5cc7-843b-b94ce0f34a0d f8a8d086-43cd-5b76-add9-184188991707 |
| `related_ticket_ids` | `present` | 97683389-b912-4385-990d-9c6f54c9e236 |
| `related_pr_ids` | `present` | 36dc3953-014a-497a-b23d-e042ebedeff4 |

- BM25 indexed text: TimeoutException partner profile API timed out after 3000ms src/main/java/com/example/integration/AdminPartnerApiClient.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=admin-portal module=integration class=AdminPartnerApiClient status=resolved error_type=TimeoutException summary= message=partner profile API timed out after 3000ms cause= root_cause= resolution=src/main/java/com/example/integration/AdminPartnerApiClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `21071d6e-449f-480f-bb8b-671e3f6ba8a3` | - | ContainerExitError | 0.032286 | - | - |
| 2 | `313f2864-d8a0-480c-a487-d7fb5afa81b9` | - | KafkaSerializationException | 0.030546 | - | - |
| 3 | `7efeab5b-e531-496c-8a41-69d72e239439` | - | ClassNotFoundException | 0.020238 | - | - |

### retrieval_eval_v1_cross_project_conflict_002

- project_name: `admin-portal`
- expected_incident_id: `7efeab5b-e531-496c-8a41-69d72e239439`
- original_query: 로그인 클래스 로딩 실패가 admin-portal에서 난 사례
- rewritten_query / BM25 actual query: 로그인 클래스 로딩 실패 admin-portal 사례
- query tokens: `로그인, 클래스, 로딩, admin, portal`
- indexed token hits: `admin`
- indexed token misses: `로그인, 클래스, 로딩, portal`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `0.978584`
- cosine similarity: `0.021416`
- vector score: `0.021416`
- vector clipped: `N`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `293` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 2, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | ClassNotFoundException |
| `primary_error_message` | `present` | com.example.auth.JwtTokenProvider |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/auth/AdminAuthService.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 7c126297-0277-5fab-8d7e-0d2a1f9d8213 dc5877f6-b650-59d2-b516-188f4e34954e |
| `related_ticket_ids` | `present` | daf78576-5697-4820-a935-0d573a20a8c2 |
| `related_pr_ids` | `present` | 7f5520a5-61b9-4830-81cc-f6b455dbd61a |

- BM25 indexed text: ClassNotFoundException com.example.auth.JwtTokenProvider src/main/java/com/example/auth/AdminAuthService.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=admin-portal module=auth class=AdminAuthService status=resolved error_type=ClassNotFoundException summary= message=com.example.auth.JwtTokenProvider cause= root_cause= resolution=src/main/java/com/example/auth/AdminAuthService.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `433dff0c-eeaf-481f-99cf-b9d041befd1e` | - | AccessDeniedException | 0.036005 | 1 | admin |
| 2 | `087f5d77-20eb-4487-84da-4253cc128eca` | - | JsonMappingException | 0.050045 | - | - |
| 3 | `1e841c64-16f9-44e8-a856-a636ca807f1b` | - | SSLHandshakeException | 0.041821 | - | - |

### retrieval_eval_v1_cross_project_conflict_003

- project_name: `batch-platform`
- expected_incident_id: `9233f432-d5ef-4d51-b607-6f5a2eb28305`
- original_query: 배치 플랫폼에서 Redis 접속 수 초과로 캐시 장애 난 사례
- rewritten_query / BM25 actual query: 배치 플랫폼 Redis 접속 수 초과 캐시 장애 사례
- query tokens: `배치, 플랫폼, redis, 접속, 초과, 캐시`
- indexed token hits: `redis`
- indexed token misses: `배치, 플랫폼, 접속, 초과, 캐시`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.004565`
- cosine similarity: `-0.004565`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `209` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 0, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 0, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | RedisConnectionException |
| `primary_error_message` | `present` | ERR max number of clients reached |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | 0f7d5a09-accf-5503-825d-f3e9796b1170 8933a3f6-e835-54e2-9a10-7384846ee16a 2bb7c924-11b3-50f3-ad34-bb5a1df7ccca 13e5c7... |
| `related_ticket_ids` | `empty_array` | - |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: RedisConnectionException ERR max number of clients reached
- embedding_text: project=batch-platform module=cache class=BatchRedisCacheClient status=open error_type=RedisConnectionException summary= message=ERR max number of clients reached cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` | - | ContainerExitError | 0.044218 | - | - |
| 2 | `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` | - | ClassNotFoundException | 0.025236 | - | - |
| 3 | `d4253455-0df0-4733-8c52-a768a47d47f9` | - | OptimisticLockException | 0.016025 | - | - |

### retrieval_eval_v1_cross_project_conflict_004

- project_name: `admin-portal`
- expected_incident_id: `6f48f638-1d3f-46af-bd87-a77f17652e57`
- original_query: 관리자 포털에서 Redis 접속 제한으로 캐시 조회가 실패한 사례
- rewritten_query / BM25 actual query: 관리자 포털 Redis 접속 제한 캐시 조회 실패 사례
- query tokens: `관리자, 포털, redis, 접속, 제한, 캐시, 조회`
- indexed token hits: `redis`
- indexed token misses: `관리자, 포털, 접속, 제한, 캐시, 조회`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.016503`
- cosine similarity: `-0.016503`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `307` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | RedisConnectionException |
| `primary_error_message` | `present` | ERR max number of clients reached |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/cache/AdminRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | f2421d85-9cd4-5df7-ab95-05a7c674ac40 5fef771e-1452-5ec7-8899-39051ad45a71 6d70c12a-d0b2-52a7-8b80-14c9cd8f3605 222d28... |
| `related_ticket_ids` | `present` | 99806638-0801-426b-ace0-f0094c082a8a |
| `related_pr_ids` | `present` | f1eb8252-b508-471f-a83d-f9a333ba25e0 |

- BM25 indexed text: RedisConnectionException ERR max number of clients reached src/main/java/com/example/cache/AdminRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=admin-portal module=cache class=AdminRedisCacheClient status=resolved error_type=RedisConnectionException summary= message=ERR max number of clients reached cause= root_cause= resolution=src/main/java/com/example/cache/AdminRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `1e841c64-16f9-44e8-a856-a636ca807f1b` | - | SSLHandshakeException | 0.064329 | - | - |
| 2 | `7efeab5b-e531-496c-8a41-69d72e239439` | - | ClassNotFoundException | 0.054489 | - | - |
| 3 | `433dff0c-eeaf-481f-99cf-b9d041befd1e` | - | AccessDeniedException | 0.039978 | - | - |

### retrieval_eval_v1_cross_project_conflict_005

- project_name: `data-portal`
- expected_incident_id: `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4`
- original_query: data-portal의 파트너 프로필 조회 timeout 장애
- rewritten_query / BM25 actual query: data-portal 파트너 프로필 조회 timeout 장애
- query tokens: `data, portal, 파트너, 프로필, 조회, timeout`
- indexed token hits: `data, timeout`
- indexed token misses: `portal, 파트너, 프로필, 조회`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `0.968453`
- cosine similarity: `0.031547`
- vector score: `0.031547`
- vector clipped: `N`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `317` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 3, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | TimeoutException |
| `primary_error_message` | `present` | partner profile API timed out after 3000ms |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/integration/DataPartnerApiClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 3de80e0e-7fa7-51a0-8d1e-4ce9fe16daea 92eb6f7d-cf42-50f2-b763-1212743c64ca fa4e1e2c-6c2c-575a-a6c3-94ee201dd426 |
| `related_ticket_ids` | `present` | aeeceb88-60eb-47e7-b61e-ddbf9e5be6d6 |
| `related_pr_ids` | `present` | 9d79dab7-1469-4a66-a69d-bd806c7e2152 |

- BM25 indexed text: TimeoutException partner profile API timed out after 3000ms src/main/java/com/example/integration/DataPartnerApiClient.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=integration class=DataPartnerApiClient status=resolved error_type=TimeoutException summary= message=partner profile API timed out after 3000ms cause= root_cause= resolution=src/main/java/com/example/integration/DataPartnerApiClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.483783 | 1 | - |
| 2 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.483700 | - | - |
| 3 | `14861fa5-b251-48a5-822b-947f83fc8e34` | - | FileNotFoundException | 0.037415 | - | data |

### retrieval_eval_v1_cross_project_conflict_006

- project_name: `batch-platform`
- expected_incident_id: `e3b07adc-a00a-4afb-ac77-ae9ba8ddbdd8`
- original_query: batch-platform의 파트너 프로필 조회 지연 장애
- rewritten_query / BM25 actual query: batch-platform 파트너 프로필 조회 지연 장애
- query tokens: `batch, platform, 파트너, 프로필, 조회, 지연`
- indexed token hits: `-`
- indexed token misses: `batch, platform, 파트너, 프로필, 조회, 지연`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.034293`
- cosine similarity: `-0.034293`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `216` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 3, 'raw_tickets': 0, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 0, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | TimeoutException |
| `primary_error_message` | `present` | partner profile API timed out after 3000ms |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | ad76391b-04a4-5c3b-a444-6dfb5f6c7074 a808a90b-0e4d-516e-b707-53df4950e6ee e05dfda9-79ba-5994-aeef-c4fa0385eebb |
| `related_ticket_ids` | `empty_array` | - |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: TimeoutException partner profile API timed out after 3000ms
- embedding_text: project=batch-platform module=integration class=BatchPartnerApiClient status=open error_type=TimeoutException summary= message=partner profile API timed out after 3000ms cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` | - | ContainerExitError | 0.040919 | - | - |
| 2 | `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` | - | ClassNotFoundException | 0.017045 | - | - |
| 3 | `d4253455-0df0-4733-8c52-a768a47d47f9` | - | OptimisticLockException | 0.010722 | - | - |

### retrieval_eval_v1_same_error_different_cause_006

- project_name: `data-portal`
- expected_incident_id: `074fa857-4bf2-4ba1-9c42-b5db1f97cb2e`
- original_query: 데이터 포털 웹훅 상태값 파싱이 안 된 JSON 매핑 장애
- rewritten_query / BM25 actual query: 데이터 포털 웹훅 상태값 파싱 JSON 매핑 장애 원인
- query tokens: `데이터, 포털, 웹훅, 상태값, 파싱, json, 매핑`
- indexed token hits: `json`
- indexed token misses: `데이터, 포털, 웹훅, 상태값, 파싱, 매핑`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.004159`
- cosine similarity: `-0.004159`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `309` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 2, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | JsonMappingException |
| `primary_error_message` | `present` | Cannot deserialize value of type EventStatus |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/api/DataWebhookController.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | f0abbda0-d488-5580-b09f-e994fa84a16f 0c853d69-6e1f-586d-b0cd-d543895820db |
| `related_ticket_ids` | `present` | be44d508-fa30-4cef-acfb-211c4c239d1c |
| `related_pr_ids` | `present` | 8d9ba4a0-5c7a-457c-8d4d-68704a204a31 |

- BM25 indexed text: JsonMappingException Cannot deserialize value of type EventStatus src/main/java/com/example/api/DataWebhookController.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=api class=DataWebhookController status=resolved error_type=JsonMappingException summary= message=Cannot deserialize value of type EventStatus cause= root_cause= resolution=src/main/java/com/example/api/DataWebhookController.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.368172 | 1 | - |
| 2 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.456126 | - | - |
| 3 | `14861fa5-b251-48a5-822b-947f83fc8e34` | - | FileNotFoundException | 0.067130 | - | - |

### retrieval_eval_v1_same_error_different_cause_008

- project_name: `data-portal`
- expected_incident_id: `36b6be9d-8fb0-497d-983b-f010e0d0a564`
- original_query: 주문 확정 중 같은 row를 동시에 갱신해서 충돌난 장애
- rewritten_query / BM25 actual query: 주문 확정 동시 갱신 충돌 원인
- query tokens: `주문, 확정, 동시, 갱신, 충돌`
- indexed token hits: `-`
- indexed token misses: `주문, 확정, 동시, 갱신, 충돌`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.007300`
- cosine similarity: `-0.007300`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `325` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 3, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | OptimisticLockException |
| `primary_error_message` | `present` | row was updated or deleted by another transaction |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/order/DataOrderCommandService.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 38a18fd7-b1e1-57a3-af55-37c842011788 09f0d193-419a-52ab-9e22-c72cfd15ba1d 7702b5ed-0759-569c-8be4-bf0b8380536a |
| `related_ticket_ids` | `present` | af5c2b87-1b06-4ab9-a7b4-0d14e427bc0e |
| `related_pr_ids` | `present` | 4acf6510-1c50-48f8-9a38-a7a8af5a692e |

- BM25 indexed text: OptimisticLockException row was updated or deleted by another transaction src/main/java/com/example/order/DataOrderCommandService.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=order class=DataOrderCommandService status=resolved error_type=OptimisticLockException summary= message=row was updated or deleted by another transaction cause= root_cause= resolution=src/main/java/com/example/order/DataOrderCommandService.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.314101 | - | - |
| 2 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.208894 | - | - |
| 3 | `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8` | - | RedisConnectionException | 0.023237 | - | - |

### retrieval_eval_v1_same_error_different_cause_010

- project_name: `data-portal`
- expected_incident_id: `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8`
- original_query: 데이터 포털 Redis 클라이언트 수 제한에 걸린 장애
- rewritten_query / BM25 actual query: 데이터 포털 Redis 클라이언트 수 제한 장애 원인
- query tokens: `데이터, 포털, redis, 클라이언트, 제한`
- indexed token hits: `redis`
- indexed token misses: `데이터, 포털, 클라이언트, 제한`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.002183`
- cosine similarity: `-0.002183`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `304` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | RedisConnectionException |
| `primary_error_message` | `present` | ERR max number of clients reached |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 073056ef-e5ed-510f-8972-bb486cd7289e fdf78b12-1148-565b-936e-5a053ef970ae 5983d529-d6b3-554e-b8d1-76833cb921ea 67d24b... |
| `related_ticket_ids` | `present` | d75185ae-70ca-4743-ba0a-73ffff41c450 |
| `related_pr_ids` | `present` | 7ad267f4-9510-4020-9e2d-0183778c6dfe |

- BM25 indexed text: RedisConnectionException ERR max number of clients reached src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=cache class=DataRedisCacheClient status=resolved error_type=RedisConnectionException summary= message=ERR max number of clients reached cause= root_cause= resolution=src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.342291 | 1 | - |
| 2 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.279220 | - | - |
| 3 | `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4` | - | TimeoutException | 0.053366 | - | - |

### retrieval_eval_v1_semantic_paraphrase_003

- project_name: `data-portal`
- expected_incident_id: `3caa466f-49bd-4762-bb00-d4f27ac9f314`
- original_query: 리포트 조회에서 없는 상태 컬럼 때문에 터진 사례 찾아줘
- rewritten_query / BM25 actual query: 리포트 조회 상태 컬럼 없어서 오류 사례
- query tokens: `리포트, 조회, 상태, 컬럼, 없어서`
- indexed token hits: `-`
- indexed token misses: `리포트, 조회, 상태, 컬럼, 없어서`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `0.984306`
- cosine similarity: `0.015694`
- vector score: `0.015694`
- vector clipped: `N`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `316` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 2, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | SQLGrammarException |
| `primary_error_message` | `present` | column report_status_cd does not exist |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/report/DataReportQueryRepository.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 5ea438cf-6d18-589e-a6f4-9243f9961970 96e612b9-a07b-58b4-ba6c-c41c509ee574 |
| `related_ticket_ids` | `present` | b7ab3f55-9548-48e0-8586-c120a4415bfd |
| `related_pr_ids` | `present` | 3d42e97b-75c7-4f52-8457-2c3b7187d7aa |

- BM25 indexed text: SQLGrammarException column report_status_cd does not exist src/main/java/com/example/report/DataReportQueryRepository.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=report class=DataReportQueryRepository status=resolved error_type=SQLGrammarException summary= message=column report_status_cd does not exist cause= root_cause= resolution=src/main/java/com/example/report/DataReportQueryRepository.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.296665 | 1 | - |
| 2 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.327632 | - | - |
| 3 | `14861fa5-b251-48a5-822b-947f83fc8e34` | - | FileNotFoundException | 0.040381 | - | - |

### retrieval_eval_v1_semantic_paraphrase_004

- project_name: `admin-portal`
- expected_incident_id: `433dff0c-eeaf-481f-99cf-b9d041befd1e`
- original_query: 관리자 권한이 있는데 리포트 접근이 막힌 장애 원인이 뭐야?
- rewritten_query / BM25 actual query: 관리자 권한 리포트 접근 차단 원인
- query tokens: `관리자, 권한, 리포트, 접근, 차단`
- indexed token hits: `-`
- indexed token misses: `관리자, 권한, 리포트, 접근, 차단`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `0.982978`
- cosine similarity: `0.017022`
- vector score: `0.017022`
- vector clipped: `N`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `212` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | AccessDeniedException |
| `primary_error_message` | `present` | role REPORT_ADMIN required |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | 50ba44d9-7180-59ed-87a7-dece4be192bd 960d2494-e90e-5a18-96d6-1a69a881be1c 9b272661-387f-5374-9a99-6540e35fb381 9e6d7e... |
| `related_ticket_ids` | `present` | c956e9bd-a854-4bab-83d3-4acea7a72450 |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: AccessDeniedException role REPORT_ADMIN required
- embedding_text: project=admin-portal module=security class=AdminPermissionEvaluator status=investigating error_type=AccessDeniedException summary= message=role REPORT_ADMIN required cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `313f2864-d8a0-480c-a487-d7fb5afa81b9` | - | KafkaSerializationException | 0.042662 | - | - |
| 2 | `c4a14ead-6af3-4a3f-98a9-99899d5cc1f4` | - | NullPointerException | 0.041049 | - | - |
| 3 | `7efeab5b-e531-496c-8a41-69d72e239439` | - | ClassNotFoundException | 0.030708 | - | - |

### retrieval_eval_v1_semantic_paraphrase_005

- project_name: `admin-portal`
- expected_incident_id: `1e841c64-16f9-44e8-a856-a636ca807f1b`
- original_query: 외부 HTTPS 호출에서 인증서 체인 문제로 실패한 건 어떻게 처리했어?
- rewritten_query / BM25 actual query: 외부 HTTPS 호출 인증서 체인 문제 해결 방법
- query tokens: `외부, https, 호출, 인증서, 체인, 문제`
- indexed token hits: `-`
- indexed token misses: `외부, https, 호출, 인증서, 체인, 문제`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.001195`
- cosine similarity: `-0.001195`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `206` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | SSLHandshakeException |
| `primary_error_message` | `present` | PKIX path building failed |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | 43280353-36f0-5ae2-9fb9-9b1b99e1c00a bc5c373e-b0f7-5f52-b8fe-959fe74abd8e 8d8d2549-a432-5b2a-8c7c-34cc9fcdff75 1b353d... |
| `related_ticket_ids` | `present` | 41f8d000-bcd0-49a0-8484-66a5674f3fa3 |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: SSLHandshakeException PKIX path building failed
- embedding_text: project=admin-portal module=client class=AdminSecureHttpClient status=investigating error_type=SSLHandshakeException summary= message=PKIX path building failed cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `ddf82944-5f08-46f8-9e95-f6b3ddafa590` | - | TimeoutException | 0.043227 | - | - |
| 2 | `6f48f638-1d3f-46af-bd87-a77f17652e57` | - | RedisConnectionException | 0.042215 | - | - |
| 3 | `b343b1f2-3972-4349-8c26-5027276b68f1` | - | SQLGrammarException | 0.029196 | - | - |

### retrieval_eval_v1_semantic_paraphrase_006

- project_name: `batch-platform`
- expected_incident_id: `f7684112-d72d-4bc2-a9c6-162002937333`
- original_query: 배치 이벤트 발행 중 스키마 버전이 안 맞아서 직렬화가 실패한 사례
- rewritten_query / BM25 actual query: 배치 이벤트 발행 스키마 버전 불일치 직렬화 실패 사례
- query tokens: `배치, 이벤트, 발행, 스키마, 버전, 불일치, 직렬화`
- indexed token hits: `-`
- indexed token misses: `배치, 이벤트, 발행, 스키마, 버전, 불일치, 직렬화`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, KOREAN_TOKENIZATION_MISMATCH, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.026277`
- cosine similarity: `-0.026277`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `217` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 3, 'raw_tickets': 0, 'raw_prs': 0}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 0, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 0}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | KafkaSerializationException |
| `primary_error_message` | `present` | cannot serialize schema version v3 |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `null` | - |
| `related_log_ids` | `present` | fd78742d-e657-50e0-8c5f-cb939fc7c3b4 28f20719-ba34-59b8-9085-31e92f516459 61113179-d21a-5564-80f7-df97400d2db3 |
| `related_ticket_ids` | `empty_array` | - |
| `related_pr_ids` | `empty_array` | - |

- BM25 indexed text: KafkaSerializationException cannot serialize schema version v3
- embedding_text: project=batch-platform module=stream class=BatchKafkaEventPublisher status=open error_type=KafkaSerializationException summary= message=cannot serialize schema version v3 cause= root_cause= resolution= keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` | - | ClassNotFoundException | 0.031894 | - | - |
| 2 | `d4253455-0df0-4733-8c52-a768a47d47f9` | - | OptimisticLockException | 0.026478 | - | - |
| 3 | `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` | - | ContainerExitError | 0.015271 | - | - |

### retrieval_eval_v1_semantic_paraphrase_009

- project_name: `data-portal`
- expected_incident_id: `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8`
- original_query: Redis 접속 수가 꽉 차서 캐시 조회가 실패한 장애 해결 내용
- rewritten_query / BM25 actual query: Redis 접속 수 초과 캐시 조회 실패 해결 방법
- query tokens: `redis, 접속, 초과, 캐시, 조회`
- indexed token hits: `redis`
- indexed token misses: `접속, 초과, 캐시, 조회`
- bm25 failure reasons: `INCIDENT_DATA_MISSING, ARRAY_JSON_NOT_INDEXED, ENGLISH_KOREAN_SYNONYM_MISMATCH`
- vector distance: `1.034395`
- cosine similarity: `-0.034395`
- vector score: `0.000000`
- vector clipped: `Y`
- BM25 rank/score: `-` / `-`
- embedding length/dim: `304` / `1536`
- embedding stale vs incident.updated_at: `N`
- raw evidence counts: `{'raw_logs': 4, 'raw_tickets': 1, 'raw_prs': 1}`
- raw evidence signal counts: `{'raw_logs_with_summary': 0, 'raw_logs_with_keywords': 0, 'raw_logs_with_domain_tags': 0, 'raw_tickets_with_summary': 1, 'raw_tickets_with_keywords': 0, 'raw_tickets_with_cause_or_resolution': 0, 'raw_prs_with_summary': 0, 'raw_prs_with_keywords': 0, 'raw_prs_with_fix_or_diff': 1}`

Incident field states:

| field | state | value preview |
| --- | --- | --- |
| `primary_error_type` | `present` | RedisConnectionException |
| `primary_error_message` | `present` | ERR max number of clients reached |
| `primary_error_summary` | `null` | - |
| `error_keywords` | `empty_array` | - |
| `domain_tags` | `empty_array` | - |
| `suspected_cause` | `null` | - |
| `root_cause_summary` | `null` | - |
| `resolution_summary` | `present` | src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ |
| `related_log_ids` | `present` | 073056ef-e5ed-510f-8972-bb486cd7289e fdf78b12-1148-565b-936e-5a053ef970ae 5983d529-d6b3-554e-b8d1-76833cb921ea 67d24b... |
| `related_ticket_ids` | `present` | d75185ae-70ca-4743-ba0a-73ffff41c450 |
| `related_pr_ids` | `present` | 7ad267f4-9510-4020-9e2d-0183778c6dfe |

- BM25 indexed text: RedisConnectionException ERR max number of clients reached src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@
- embedding_text: project=data-portal module=cache class=DataRedisCacheClient status=resolved error_type=RedisConnectionException summary= message=ERR max number of clients reached cause= root_cause= resolution=src/main/java/com/example/cache/DataRedisCacheClient.java (modified, +2/-1): @@ -20,6 +20,10 @@ keywords= tags=

RRF Top3 오답 후보:

| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | `7f929778-811d-4ec0-b344-74f54f61b5aa` | 2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발... | NullPointerException | 0.227081 | 1 | - |
| 2 | `072e1cca-72be-4116-b1de-618b9b42c499` | AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다. | ClassNotFoundException | 0.274084 | - | - |
| 3 | `074fa857-4bf2-4ba1-9c42-b5db1f97cb2e` | - | JsonMappingException | 0.038009 | - | - |

## 수정 우선순위 제안

A. 데이터 생성/보강 오류

- 최우선입니다. 실패 expected incident 대부분이 summary/keywords/domain_tags/root_cause/resolution이 비어 있어 BM25와 embedding 입력이 모두 약합니다.
- raw_*에 존재하는 정규화 요약, 키워드, 도메인, PR resolution 정보를 incidents로 확실히 merge하는 경로를 점검해야 합니다.

B. embedding 재생성 필요

- incident 보강 이후에는 반드시 incident_embeddings를 재생성해야 합니다.
- 현재 embedding row 자체는 존재하지만, 비어 있는 incident 필드를 기반으로 생성된 텍스트라 검색력이 낮습니다.

C. BM25 인덱스 또는 searchable text 오류

- 함수 구성 자체는 의도 필드를 포함하고 null 전체 전파 문제도 없습니다.
- 다만 인덱스가 `CREATE INDEX IF NOT EXISTS`라 함수 변경 이후 재생성이 필요한 상황은 별도 migration으로 관리해야 합니다.

D. 한국어/영어 표현 불일치

- BM25 miss 17건 모두 query token과 indexed text token의 직접 일치가 약합니다.
- 예: `권한 문제` vs `AccessDeniedException`, `Redis 접속 제한` vs 저장 message에 Redis/connection 정보 없음.

E. Query Rewrite 문제

- 7건에서 rewritten query가 원본 대비 rank를 낮췄지만, Top3 loss는 0건입니다.
- 현재 주 원인은 Query Rewrite보다 입력 데이터 부족입니다.

F. 검색 알고리즘 자체 문제

- 데이터 보강 후에도 BM25/Vector가 Top3를 못 올리는 케이스에 한해 RRF 가중치, BM25 analyzer, synonym expansion, field weighting을 실험하는 순서가 맞습니다.
