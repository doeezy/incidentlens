# RRF Ranking Miss 분석 리포트

- run_id: `fa8a0e14-ece6-445a-a88b-737d35cf36ca`
- run_name: `retrieval_eval_v1_confidence_v2_baseline`
- 분석 대상: `RRF_RANKING_MISS`
- 대상 케이스 수: `17`
- top_k: `3`
- 저장 candidate_limit: `20`
- 확장 비교 candidate_limit: `100`
- rrf_k: `60`

## 요약

### Primary Type

| 유형 | 건수 | 의미 |
| --- | ---: | --- |
| `BM25_MISS_AND_VECTOR_NOT_TOP3` | 17 | BM25 후보에 없고 Vector도 Top3 밖 |

### Factor Counts

| 요인 | 건수 |
| --- | ---: |
| `vector_miss` | 0 |
| `vector_not_top3` | 17 |
| `bm25_miss` | 17 |
| `bm25_not_top3` | 17 |
| `query_rewrite_top3_loss` | 0 |
| `query_rewrite_rank_drop` | 7 |
| `candidate_limit_direct` | 0 |

### Secondary Signals

| 신호 | 건수 |
| --- | ---: |
| `BM25_MISS` | 17 |
| `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL` | 17 |
| `QUERY_REWRITE_RANK_DROP` | 7 |
| `VECTOR_NOT_TOP3` | 17 |

## Candidate Limit 판단

- 저장된 candidate_limit은 `20`이고, 프로젝트별 incident 수는 `{'data-portal': 14, 'admin-portal': 12, 'batch-platform': 12}`입니다.
- 이번 17건에서는 candidate_limit을 100으로 확장해도 정답이 Top3로 올라온 케이스가 없었습니다.
- 따라서 현재 데이터 기준으로는 Candidate Limit이 RRF Top3 실패의 직접 원인으로 보이지 않습니다.

## 케이스별 상세

### retrieval_eval_v1_ambiguous_query_003

- category: `ambiguous_query`
- project_name: `admin-portal`
- expected_incident_id: `433dff0c-eeaf-481f-99cf-b9d041befd1e`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 권한 문제로 막힌 장애 찾아줘
- rewritten_query: 권한 문제 장애 사례
- rewritten 저장 순위: V 6/0.002504, B -/-, RRF 6/0.015152
- original query 비교 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- limit 100 비교 순위: V 6/0.002504, B -/-, RRF 6/0.015152
- rewritten 기준 RRF Top3 후보:
  - #1 `313f2864-d8a0-480c-a487-d7fb5afa81b9` RRF 0.016393, V 0.046816, B -, summary=None
  - #2 `087f5d77-20eb-4487-84da-4253cc128eca` RRF 0.016129, V 0.028668, B -, summary=None
  - #3 `1e841c64-16f9-44e8-a856-a636ca807f1b` RRF 0.015873, V 0.018232, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=6, bm25_rank=None, rrf_rank=6.

### retrieval_eval_v1_ambiguous_query_004

- category: `ambiguous_query`
- project_name: `batch-platform`
- expected_incident_id: `f7684112-d72d-4bc2-a9c6-162002937333`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 배치에서 이벤트 발행 실패한 사례
- rewritten_query: 배치 이벤트 발행 실패 사례
- rewritten 저장 순위: V 8/0.000000, B -/-, RRF 8/0.014706
- original query 비교 순위: V 8/0.000000, B -/-, RRF 8/0.014706
- limit 100 비교 순위: V 8/0.000000, B -/-, RRF 8/0.014706
- rewritten 기준 RRF Top3 후보:
  - #1 `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` RRF 0.016393, V 0.036737, B -, summary=None
  - #2 `d4253455-0df0-4733-8c52-a768a47d47f9` RRF 0.016129, V 0.026569, B -, summary=None
  - #3 `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` RRF 0.015873, V 0.022772, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=8, bm25_rank=None, rrf_rank=8.

### retrieval_eval_v1_ambiguous_query_005

- category: `ambiguous_query`
- project_name: `data-portal`
- expected_incident_id: `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 캐시 쪽 장애 원인이 뭐였어?
- rewritten_query: 캐시 장애 원인
- rewritten 저장 순위: V 12/0.000000, B -/-, RRF 12/0.013889
- original query 비교 순위: V 13/0.000000, B -/-, RRF 13/0.013699
- limit 100 비교 순위: V 12/0.000000, B -/-, RRF 12/0.013889
- rewritten 기준 RRF Top3 후보:
  - #1 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.032787, V 0.238754, B 2.021206, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #2 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.016129, V 0.184468, B -, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #3 `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4` RRF 0.015873, V 0.039600, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=12, bm25_rank=None, rrf_rank=12.

### retrieval_eval_v1_ambiguous_query_006

- category: `ambiguous_query`
- project_name: `admin-portal`
- expected_incident_id: `ddf82944-5f08-46f8-9e95-f6b3ddafa590`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 외부 연동 호출 실패한 장애 설명해줘
- rewritten_query: 외부 연동 호출 실패 장애 설명
- rewritten 저장 순위: V 4/0.013394, B -/-, RRF 4/0.015625
- original query 비교 순위: V 5/0.011998, B -/-, RRF 5/0.015385
- limit 100 비교 순위: V 4/0.013421, B -/-, RRF 4/0.015625
- rewritten 기준 RRF Top3 후보:
  - #1 `21071d6e-449f-480f-bb8b-671e3f6ba8a3` RRF 0.016393, V 0.032274, B -, summary=None
  - #2 `313f2864-d8a0-480c-a487-d7fb5afa81b9` RRF 0.016129, V 0.030607, B -, summary=None
  - #3 `7efeab5b-e531-496c-8a41-69d72e239439` RRF 0.015873, V 0.018798, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=4, bm25_rank=None, rrf_rank=4.

### retrieval_eval_v1_cross_project_conflict_002

- category: `cross_project_conflict`
- project_name: `admin-portal`
- expected_incident_id: `7efeab5b-e531-496c-8a41-69d72e239439`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 로그인 클래스 로딩 실패가 admin-portal에서 난 사례
- rewritten_query: 로그인 클래스 로딩 실패 admin-portal 사례
- rewritten 저장 순위: V 4/0.021278, B -/-, RRF 4/0.015625
- original query 비교 순위: V 5/0.024480, B -/-, RRF 5/0.015385
- limit 100 비교 순위: V 4/0.021278, B -/-, RRF 4/0.015625
- rewritten 기준 RRF Top3 후보:
  - #1 `433dff0c-eeaf-481f-99cf-b9d041befd1e` RRF 0.032266, V 0.036005, B 3.355135, summary=None
  - #2 `087f5d77-20eb-4487-84da-4253cc128eca` RRF 0.016393, V 0.050045, B -, summary=None
  - #3 `1e841c64-16f9-44e8-a856-a636ca807f1b` RRF 0.016129, V 0.041821, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=4, bm25_rank=None, rrf_rank=4.

### retrieval_eval_v1_cross_project_conflict_003

- category: `cross_project_conflict`
- project_name: `batch-platform`
- expected_incident_id: `9233f432-d5ef-4d51-b607-6f5a2eb28305`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 배치 플랫폼에서 Redis 접속 수 초과로 캐시 장애 난 사례
- rewritten_query: 배치 플랫폼 Redis 접속 수 초과 캐시 장애 사례
- rewritten 저장 순위: V 6/0.000000, B -/-, RRF 6/0.015152
- original query 비교 순위: V 5/0.008800, B -/-, RRF 5/0.015385
- limit 100 비교 순위: V 6/0.000000, B -/-, RRF 6/0.015152
- rewritten 기준 RRF Top3 후보:
  - #1 `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` RRF 0.016393, V 0.044218, B -, summary=None
  - #2 `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` RRF 0.016129, V 0.025236, B -, summary=None
  - #3 `d4253455-0df0-4733-8c52-a768a47d47f9` RRF 0.015873, V 0.016025, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=6, bm25_rank=None, rrf_rank=6.

### retrieval_eval_v1_cross_project_conflict_004

- category: `cross_project_conflict`
- project_name: `admin-portal`
- expected_incident_id: `6f48f638-1d3f-46af-bd87-a77f17652e57`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 관리자 포털에서 Redis 접속 제한으로 캐시 조회가 실패한 사례
- rewritten_query: 관리자 포털 Redis 접속 제한 캐시 조회 실패 사례
- rewritten 저장 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- original query 비교 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- limit 100 비교 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- rewritten 기준 RRF Top3 후보:
  - #1 `1e841c64-16f9-44e8-a856-a636ca807f1b` RRF 0.016393, V 0.064329, B -, summary=None
  - #2 `7efeab5b-e531-496c-8a41-69d72e239439` RRF 0.016129, V 0.054489, B -, summary=None
  - #3 `433dff0c-eeaf-481f-99cf-b9d041befd1e` RRF 0.015873, V 0.039978, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=11, bm25_rank=None, rrf_rank=11.

### retrieval_eval_v1_cross_project_conflict_005

- category: `cross_project_conflict`
- project_name: `data-portal`
- expected_incident_id: `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: data-portal의 파트너 프로필 조회 timeout 장애
- rewritten_query: data-portal 파트너 프로필 조회 timeout 장애
- rewritten 저장 순위: V 4/0.031525, B -/-, RRF 4/0.015625
- original query 비교 순위: V 4/0.033197, B -/-, RRF 4/0.015625
- limit 100 비교 순위: V 4/0.031525, B -/-, RRF 4/0.015625
- rewritten 기준 RRF Top3 후보:
  - #1 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.032787, V 0.483783, B 2.021206, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #2 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.016129, V 0.483701, B -, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #3 `14861fa5-b251-48a5-822b-947f83fc8e34` RRF 0.015873, V 0.037415, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=4, bm25_rank=None, rrf_rank=4.

### retrieval_eval_v1_cross_project_conflict_006

- category: `cross_project_conflict`
- project_name: `batch-platform`
- expected_incident_id: `e3b07adc-a00a-4afb-ac77-ae9ba8ddbdd8`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: batch-platform의 파트너 프로필 조회 지연 장애
- rewritten_query: batch-platform 파트너 프로필 조회 지연 장애
- rewritten 저장 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- original query 비교 순위: V 10/0.000000, B -/-, RRF 10/0.014286
- limit 100 비교 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- rewritten 기준 RRF Top3 후보:
  - #1 `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` RRF 0.016393, V 0.040919, B -, summary=None
  - #2 `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` RRF 0.016129, V 0.017045, B -, summary=None
  - #3 `d4253455-0df0-4733-8c52-a768a47d47f9` RRF 0.015873, V 0.010722, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=11, bm25_rank=None, rrf_rank=11.

### retrieval_eval_v1_same_error_different_cause_006

- category: `same_error_different_cause`
- project_name: `data-portal`
- expected_incident_id: `074fa857-4bf2-4ba1-9c42-b5db1f97cb2e`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 데이터 포털 웹훅 상태값 파싱이 안 된 JSON 매핑 장애
- rewritten_query: 데이터 포털 웹훅 상태값 파싱 JSON 매핑 장애 원인
- rewritten 저장 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- original query 비교 순위: V 12/0.000000, B -/-, RRF 12/0.013889
- limit 100 비교 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- rewritten 기준 RRF Top3 후보:
  - #1 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.032522, V 0.368172, B 2.021206, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #2 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.016393, V 0.456126, B -, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #3 `14861fa5-b251-48a5-822b-947f83fc8e34` RRF 0.015873, V 0.067130, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=11, bm25_rank=None, rrf_rank=11.

### retrieval_eval_v1_same_error_different_cause_008

- category: `same_error_different_cause`
- project_name: `data-portal`
- expected_incident_id: `36b6be9d-8fb0-497d-983b-f010e0d0a564`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 주문 확정 중 같은 row를 동시에 갱신해서 충돌난 장애
- rewritten_query: 주문 확정 동시 갱신 충돌 원인
- rewritten 저장 순위: V 13/0.000000, B -/-, RRF 13/0.013699
- original query 비교 순위: V 10/0.002618, B -/-, RRF 10/0.014286
- limit 100 비교 순위: V 13/0.000000, B -/-, RRF 13/0.013699
- rewritten 기준 RRF Top3 후보:
  - #1 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.016393, V 0.314101, B -, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #2 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.016129, V 0.208894, B -, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #3 `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8` RRF 0.015873, V 0.023237, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=13, bm25_rank=None, rrf_rank=13.

### retrieval_eval_v1_same_error_different_cause_010

- category: `same_error_different_cause`
- project_name: `data-portal`
- expected_incident_id: `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 데이터 포털 Redis 클라이언트 수 제한에 걸린 장애
- rewritten_query: 데이터 포털 Redis 클라이언트 수 제한 장애 원인
- rewritten 저장 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- original query 비교 순위: V 12/0.000000, B -/-, RRF 12/0.013889
- limit 100 비교 순위: V 11/0.000000, B -/-, RRF 11/0.014085
- rewritten 기준 RRF Top3 후보:
  - #1 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.032787, V 0.342291, B 2.021206, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #2 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.016129, V 0.279220, B -, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #3 `dcfcf63e-ab2e-47df-8bd8-d25c16d88dc4` RRF 0.015873, V 0.053366, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=11, bm25_rank=None, rrf_rank=11.

### retrieval_eval_v1_semantic_paraphrase_003

- category: `semantic_paraphrase`
- project_name: `data-portal`
- expected_incident_id: `3caa466f-49bd-4762-bb00-d4f27ac9f314`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 리포트 조회에서 없는 상태 컬럼 때문에 터진 사례 찾아줘
- rewritten_query: 리포트 조회 상태 컬럼 없어서 오류 사례
- rewritten 저장 순위: V 5/0.015694, B -/-, RRF 5/0.015385
- original query 비교 순위: V 4/0.030241, B -/-, RRF 4/0.015625
- limit 100 비교 순위: V 5/0.015921, B -/-, RRF 5/0.015385
- rewritten 기준 RRF Top3 후보:
  - #1 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.032522, V 0.296665, B 2.021206, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #2 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.016393, V 0.327920, B -, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #3 `14861fa5-b251-48a5-822b-947f83fc8e34` RRF 0.015873, V 0.040381, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=5, bm25_rank=None, rrf_rank=5.

### retrieval_eval_v1_semantic_paraphrase_004

- category: `semantic_paraphrase`
- project_name: `admin-portal`
- expected_incident_id: `433dff0c-eeaf-481f-99cf-b9d041befd1e`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 관리자 권한이 있는데 리포트 접근이 막힌 장애 원인이 뭐야?
- rewritten_query: 관리자 권한 리포트 접근 차단 원인
- rewritten 저장 순위: V 8/0.017004, B -/-, RRF 8/0.014706
- original query 비교 순위: V 7/0.017875, B -/-, RRF 7/0.014925
- limit 100 비교 순위: V 8/0.017004, B -/-, RRF 8/0.014706
- rewritten 기준 RRF Top3 후보:
  - #1 `313f2864-d8a0-480c-a487-d7fb5afa81b9` RRF 0.016393, V 0.042711, B -, summary=None
  - #2 `c4a14ead-6af3-4a3f-98a9-99899d5cc1f4` RRF 0.016129, V 0.041040, B -, summary=None
  - #3 `7efeab5b-e531-496c-8a41-69d72e239439` RRF 0.015873, V 0.030708, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=8, bm25_rank=None, rrf_rank=8.

### retrieval_eval_v1_semantic_paraphrase_005

- category: `semantic_paraphrase`
- project_name: `admin-portal`
- expected_incident_id: `1e841c64-16f9-44e8-a856-a636ca807f1b`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 외부 HTTPS 호출에서 인증서 체인 문제로 실패한 건 어떻게 처리했어?
- rewritten_query: 외부 HTTPS 호출 인증서 체인 문제 해결 방법
- rewritten 저장 순위: V 9/0.000000, B -/-, RRF 9/0.014493
- original query 비교 순위: V 9/0.002269, B -/-, RRF 9/0.014493
- limit 100 비교 순위: V 9/0.000000, B -/-, RRF 9/0.014493
- rewritten 기준 RRF Top3 후보:
  - #1 `ddf82944-5f08-46f8-9e95-f6b3ddafa590` RRF 0.016393, V 0.043227, B -, summary=None
  - #2 `6f48f638-1d3f-46af-bd87-a77f17652e57` RRF 0.016129, V 0.042256, B -, summary=None
  - #3 `b343b1f2-3972-4349-8c26-5027276b68f1` RRF 0.015873, V 0.029196, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=9, bm25_rank=None, rrf_rank=9.

### retrieval_eval_v1_semantic_paraphrase_006

- category: `semantic_paraphrase`
- project_name: `batch-platform`
- expected_incident_id: `f7684112-d72d-4bc2-a9c6-162002937333`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: 배치 이벤트 발행 중 스키마 버전이 안 맞아서 직렬화가 실패한 사례
- rewritten_query: 배치 이벤트 발행 스키마 버전 불일치 직렬화 실패 사례
- rewritten 저장 순위: V 10/0.000000, B -/-, RRF 10/0.014286
- original query 비교 순위: V 9/0.000000, B -/-, RRF 9/0.014493
- limit 100 비교 순위: V 10/0.000000, B -/-, RRF 10/0.014286
- rewritten 기준 RRF Top3 후보:
  - #1 `e89555ef-89a2-4c64-91a8-3f268bf8ea7a` RRF 0.016393, V 0.031894, B -, summary=None
  - #2 `d4253455-0df0-4733-8c52-a768a47d47f9` RRF 0.016129, V 0.026478, B -, summary=None
  - #3 `ed080f24-e33f-4a24-9df8-0c0d5b22b93b` RRF 0.015873, V 0.015271, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=10, bm25_rank=None, rrf_rank=10.

### retrieval_eval_v1_semantic_paraphrase_009

- category: `semantic_paraphrase`
- project_name: `data-portal`
- expected_incident_id: `f0ec1c83-4ae3-4841-8446-a9f29dc2c5c8`
- primary_type: `BM25_MISS_AND_VECTOR_NOT_TOP3`
- secondary_types: `QUERY_REWRITE_RANK_DROP, CANDIDATE_LIMIT_NOT_RELEVANT_PROJECT_SMALL, VECTOR_NOT_TOP3, BM25_MISS`
- original_query: Redis 접속 수가 꽉 차서 캐시 조회가 실패한 장애 해결 내용
- rewritten_query: Redis 접속 수 초과 캐시 조회 실패 해결 방법
- rewritten 저장 순위: V 14/0.000000, B -/-, RRF 14/0.013514
- original query 비교 순위: V 13/0.000000, B -/-, RRF 13/0.013699
- limit 100 비교 순위: V 14/0.000000, B -/-, RRF 14/0.013514
- rewritten 기준 RRF Top3 후보:
  - #1 `7f929778-811d-4ec0-b344-74f54f61b5aa` RRF 0.032522, V 0.227081, B 2.122015, summary=2026년 5월 7일 10시 05분에 PaymentService 클래스의 pay 메서드에서 NullPointerException 예외가 발생했습니다.
  - #2 `072e1cca-72be-4116-b1de-618b9b42c499` RRF 0.016393, V 0.274084, B -, summary=AuthService 클래스의 login 메서드에서 ClassNotFoundException이 발생했습니다.
  - #3 `074fa857-4bf2-4ba1-9c42-b5db1f97cb2e` RRF 0.015873, V 0.038009, B -, summary=None
- 판단: 정답이 BM25에는 잡히지 않았고 Vector에서도 Top3 밖이라 RRF 합산에서 보강 신호가 없었다. vector_rank=14, bm25_rank=None, rrf_rank=14.

## 결론

17건의 RRF_RANKING_MISS는 confidence 단계가 아니라 RRF 후보 Top3 구성 단계에서 정답이 밀린 케이스입니다.
가장 큰 원인은 BM25가 정답을 전혀 후보로 올리지 못하고, Vector도 정답을 Top3까지 끌어올리지 못한 조합입니다. 이번 17건에서 BM25 miss는 17건, Vector Top3 실패도 17건입니다.
Query Rewrite는 일부 케이스에서 순위 하락 신호가 있었지만, 원본 질의 기준으로도 Top3에 들지 못한 케이스가 많아 단독 원인으로 보기는 어렵습니다.
Candidate Limit은 이번 데이터에서는 직접 원인이 아닙니다. 프로젝트별 incident 수가 저장 candidate_limit보다 작거나, limit 100 확장에서도 Top3 개선이 없었습니다.
