# Enriched Seed Retrieval Baseline v1

이번 Run은 LLM enrichment가 정상 적용된 seed 데이터 기준 최초의 유효 baseline이다. 이전 데이터 품질 문제가 있던 결과와 섞지 않는다.

## Dataset 검증

- 총 케이스 수: `46`
- 카테고리 분포: `{'exact_keyword': 8, 'semantic_paraphrase': 10, 'same_error_different_cause': 10, 'cross_project_conflict': 6, 'ambiguous_query': 6, 'no_relevant_result': 6}`
- case_key 중복: `False`
- 질문 중복: `False`
- 정답 Incident UUID 현재 seed incidents 존재: `True`
- no-result case expected_incident_id null: `True`
- 후보 JSON: `seed_data/enriched_seed_evaluation_candidates_v1.json`

## Run 설정

- run_id: `6ad06c86-9c69-42b2-ba28-34d89ed951a7`
- run_name: `enriched_seed_baseline_v1`
- top_k: `3`
- candidate_limit: `20`
- rrf_k: `60`
- retrieval_version: `hybrid-rrf-confidence:v2`
- query_analyzer_version: `incident-agent-query-analyzer:v1`

## Metrics

| metric | value |
| --- | ---: |
| retrieval_top1_accuracy | 0.825 |
| retrieval_top3_accuracy | 0.975 |
| retrieval_mrr | 0.897 |
| final_top1_accuracy | 0.825 |
| final_top3_accuracy | 0.975 |
| final_mrr | 0.896 |
| no_result_accuracy | 1.000 |
| abstain_ratio | 0.152 |
| mean_latency_ms | 6220.159 |

## Confidence / Candidate

| item | value |
| --- | ---: |
| 전체 평가 후보 수 | 1583 |
| LLM confidence 호출 횟수 | 138 |
| Case당 평균 LLM 호출 횟수 | 3.000 |
| LLM 평가 실패 횟수 | 0 |
| confidence 통과 후보 수 | 61 |
| confidence 거절 후보 수 | 77 |
| pre-LLM reject | 0 |
| LLM low confidence reject | 77 |

## 실패 유형

- RETRIEVAL_MISS: 0
- RRF_RANKING_MISS: 0
- CONFIDENCE_REJECT: 0
- QUERY_REWRITE_ISSUE: 1
- EXECUTION_ERROR: 0

## 실패 Case

| case_key | category | project | vector | bm25 | rrf | original_rrf | abstained | failure_type |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `enriched_seed_v1_semantic_paraphrase_007` | semantic_paraphrase | batch-platform | 3/0.275 | 8/1.704 | 5/0.031 | 1 | True | QUERY_REWRITE_ISSUE |
