# Retrieval Evaluation Baseline 분석 리포트

- run_id: `336c6a1f-3f8d-4baf-b9e0-d4ffc3537bbc`
- 전체 케이스 수: `46`
- 정답 존재 케이스 수: `40`
- 정답 없음 케이스 수: `6`

## 지표

| 단계 | Top1 | Top3 | MRR | answerable_recall | no_result_accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Confidence 적용 전 순수 Retrieval | 0.500 | 0.600 | 0.595 | n/a | n/a |
| Confidence 적용 후 최종 Pipeline | 0.175 | 0.175 | 0.175 | 0.175 | 1.000 |

## 실패 유형 분류

- RETRIEVAL_MISS: 0
- RRF_RANKING_MISS: 12
- CONFIDENCE_REJECT: 14
- QUERY_REWRITE_ISSUE: 7
- EXECUTION_ERROR: 0

## Confidence 점수 분석

- 현재 confidence filtering은 `rrf_score`가 아니라 `vector_score`를 입력 점수로 사용한다.
- `vector_score = max(0.0, 1.0 - cosine_distance)`로 계산된다.
- 현재 threshold는 vector high `>= 0.65`, vector reject `< 0.45`, LLM confidence reject `< 0.5`이다.
- RRF score는 최종 `score`로 저장되지만 `_evaluate_confidence()`에는 `hit.vector_score`가 전달된다. 즉 RRF 점수를 confidence 확률처럼 직접 사용하지는 않는다.
- 다만 RRF Top3 안에 들어온 많은 정답 후보의 vector_score가 `0.45`보다 낮아서 confidence 단계에서 제거된다.

저장된 candidate 기준 점수 범위:

| 점수 | 개수 | 최소 | 최대 | 평균 |
| --- | ---: | ---: | ---: | ---: |
| vector_score | 1200 | 0.000 | 0.666 | 0.040 |
| bm25_score | 94 | 1.627 | 15.663 | 4.265 |
| rrf_score | 600 | 0.014 | 0.033 | 0.016 |
| expected_vector_score | 40 | 0.000 | 0.666 | 0.127 |
| expected_rrf_score | 40 | 0.014 | 0.033 | 0.024 |

## Threshold 후보별 시뮬레이션

이 시뮬레이션은 저장된 RRF Top3 candidate에 vector_score gate만 적용했다. 저장 데이터에는 candidate별 LLM confidence score가 없으므로 최종 pipeline의 완전한 재현은 아니다.

| threshold | answerable_recall | final_top1_accuracy | no_result_accuracy |
| ---: | ---: | ---: | ---: |
| 0.45 | 0.175 | 0.175 | 1.000 |
| 0.60 | 0.075 | 0.075 | 1.000 |
| 0.50 | 0.150 | 0.150 | 1.000 |
| 0.40 | 0.175 | 0.175 | 1.000 |
| 0.30 | 0.200 | 0.200 | 0.667 |

## 실패 케이스

| case_key | category | Vector | BM25 | RRF | abstained | failure_type |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `retrieval_eval_v1_ambiguous_query_002` | ambiguous_query | 1 / 0.256 | 1 / 2.122 | 1 / 0.033 (orig: 1 / 0.033) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_ambiguous_query_003` | ambiguous_query | 6 / 0.003 | n/a | 6 / 0.015 (orig: 11 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_ambiguous_query_004` | ambiguous_query | 8 / 0.000 | n/a | 8 / 0.015 (orig: 8 / 0.015) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_ambiguous_query_005` | ambiguous_query | 12 / 0.000 | n/a | 12 / 0.014 (orig: 13 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_ambiguous_query_006` | ambiguous_query | 4 / 0.013 | n/a | 4 / 0.016 (orig: 5 / 0.015) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_cross_project_conflict_002` | cross_project_conflict | 4 / 0.021 | n/a | 4 / 0.016 (orig: 5 / 0.015) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_cross_project_conflict_003` | cross_project_conflict | 6 / 0.000 | n/a | 6 / 0.015 (orig: 5 / 0.015) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_cross_project_conflict_004` | cross_project_conflict | 11 / 0.000 | n/a | 11 / 0.014 (orig: 11 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_cross_project_conflict_005` | cross_project_conflict | 4 / 0.032 | n/a | 4 / 0.016 (orig: 4 / 0.016) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_cross_project_conflict_006` | cross_project_conflict | 9 / 0.000 | n/a | 9 / 0.014 (orig: 10 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_exact_keyword_003` | exact_keyword | 3 / 0.028 | 1 / 8.335 | 1 / 0.032 (orig: 1 / 0.032) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_exact_keyword_004` | exact_keyword | 5 / 0.026 | 1 / 9.204 | 1 / 0.032 (orig: 1 / 0.032) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_exact_keyword_005` | exact_keyword | 2 / 0.030 | 1 / 6.710 | 1 / 0.033 (orig: 1 / 0.032) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_exact_keyword_006` | exact_keyword | 8 / 0.006 | 1 / 12.960 | 1 / 0.031 (orig: 1 / 0.033) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_exact_keyword_007` | exact_keyword | 6 / 0.000 | 1 / 15.663 | 1 / 0.032 (orig: 1 / 0.031) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_exact_keyword_008` | exact_keyword | 4 / 0.052 | 1 / 11.448 | 1 / 0.032 (orig: 1 / 0.032) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_same_error_different_cause_002` | same_error_different_cause | 13 / 0.000 | 3 / 2.007 | 3 / 0.030 (orig: 2 / 0.030) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_same_error_different_cause_004` | same_error_different_cause | 5 / 0.023 | 1 / 3.355 | 1 / 0.032 (orig: 8 / 0.015) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_same_error_different_cause_005` | same_error_different_cause | 6 / 0.002 | 1 / 9.204 | 1 / 0.032 (orig: 1 / 0.032) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_same_error_different_cause_006` | same_error_different_cause | 11 / 0.000 | n/a | 11 / 0.014 (orig: 12 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_same_error_different_cause_007` | same_error_different_cause | 1 / 0.056 | n/a | 1 / 0.016 (orig: 1 / 0.016) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_same_error_different_cause_008` | same_error_different_cause | 11 / 0.000 | 1 / 2.003 | 1 / 0.030 (orig: 10 / 0.014) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_same_error_different_cause_009` | same_error_different_cause | 1 / 0.043 | n/a | 1 / 0.016 (orig: 1 / 0.016) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_same_error_different_cause_010` | same_error_different_cause | 11 / 0.000 | n/a | 11 / 0.014 (orig: 12 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_semantic_paraphrase_002` | semantic_paraphrase | 1 / 0.365 | 1 / 2.122 | 1 / 0.033 (orig: 1 / 0.033) | True | CONFIDENCE_REJECT |
| `retrieval_eval_v1_semantic_paraphrase_003` | semantic_paraphrase | 5 / 0.017 | n/a | 5 / 0.015 (orig: 4 / 0.016) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_semantic_paraphrase_004` | semantic_paraphrase | 8 / 0.017 | n/a | 8 / 0.015 (orig: 7 / 0.015) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_semantic_paraphrase_005` | semantic_paraphrase | 9 / 0.000 | n/a | 9 / 0.014 (orig: 9 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_semantic_paraphrase_006` | semantic_paraphrase | 11 / 0.000 | n/a | 11 / 0.014 (orig: 9 / 0.014) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_semantic_paraphrase_007` | semantic_paraphrase | 2 / 0.029 | n/a | 2 / 0.016 (orig: 1 / 0.016) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_semantic_paraphrase_008` | semantic_paraphrase | 6 / 0.005 | 1 / 2.139 | 3 / 0.032 (orig: 1 / 0.032) | True | QUERY_REWRITE_ISSUE |
| `retrieval_eval_v1_semantic_paraphrase_009` | semantic_paraphrase | 11 / 0.000 | n/a | 11 / 0.014 (orig: 13 / 0.014) | True | RRF_RANKING_MISS |
| `retrieval_eval_v1_semantic_paraphrase_010` | semantic_paraphrase | 8 / 0.022 | 3 / 1.833 | 3 / 0.031 (orig: 6 / 0.015) | True | CONFIDENCE_REJECT |
