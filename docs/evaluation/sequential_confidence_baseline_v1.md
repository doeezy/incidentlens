# Sequential Confidence Baseline v1

Confidence 단계만 Sequential 정책으로 변경한 baseline 결과다. BM25, Vector, RRF, Query Analyzer prompt, Confidence prompt, Evaluation Dataset, Seed 데이터는 변경하지 않았다.

## Run 설정

- previous_run_id: `c244fba7-ee7d-408d-aa79-ab4efdda67d8`
- current_run_id: `9e27379d-89ac-4ef2-bc5e-3c50a005caa2`
- top_k: `3`
- candidate_limit: `20`
- rrf_k: `60`

## Metrics 비교

| metric | previous | sequential | delta |
| --- | ---: | ---: | ---: |
| final_top1_accuracy | 0.850 | 0.825 | -0.025 |
| final_top3_accuracy | 0.975 | 0.825 | -0.150 |
| final_mrr | 0.908 | 0.825 | -0.083 |
| no_result_accuracy | 1.000 | 1.000 | +0.000 |
| mean_latency_ms | 5760.042 | 3717.756 | -2042.285 |
| abstain_ratio | 0.152 | 0.152 | +0.000 |

## LLM 호출량 비교

| metric | previous | sequential | delta | reduction |
| --- | ---: | ---: | ---: | ---: |
| 전체 LLM 호출 수 | 138 | 61 | -77 | 0.558 |
| Case당 평균 호출 수 | 3.000 | 1.326 | -1.674 | 0.558 |

## 효과 요약

- final_top1_accuracy: `0.850` -> `0.825`
- final_top3_accuracy: `0.975` -> `0.825`
- final_mrr: `0.908` -> `0.825`
- no_result_accuracy: `1.000` -> `1.000`
- mean_latency_ms 감소율: `0.355`
- LLM 호출량 감소율: `0.558`

## 유지율 / 감소율

- final_top1_accuracy 유지율: `97.1%`
- final_top3_accuracy 유지율: `84.6%`
- final_mrr 유지율: `90.8%`
- no_result_accuracy 유지율: `100.0%`
- mean_latency_ms: `5760.042ms` -> `3717.756ms`, `2042.285ms` 감소, `35.5%` 감소
- 전체 LLM 호출 수: `138` -> `61`, `77`회 감소, `55.8%` 감소
- Case당 평균 LLM 호출 수: `3.000` -> `1.326`, `55.8%` 감소

## 해석

Sequential Confidence는 LLM 호출량과 평균 지연시간을 크게 줄였지만, Top3 기반 최종 정확도는 유지하지 못했다.
정책상 첫 통과 후보만 반환하므로 기존에 정답이 2위 또는 3위에 있던 Case가 최종 miss로 바뀌었다.
Top1 기준 정확도는 `0.850 -> 0.825`로 비교적 작게 하락했지만, final_top3_accuracy는 `0.975 -> 0.825`로 크게 하락했다.

## Case 변화

- 개선된 Case: `0`
- 동일한 Case: `40`
- 하락한 Case: `6`

## 개선된 Case

| case_key | previous final | sequential final | previous confidence | sequential confidence | rewritten_query |
| --- | --- | --- | --- | --- | --- |
| n/a | n/a | n/a | n/a | n/a | n/a |

## 하락한 Case

| case_key | previous final | sequential final | previous confidence | sequential confidence | rewritten_query |
| --- | --- | --- | --- | --- | --- |
| `enriched_seed_v1_ambiguous_query_001` | top3 | miss | medium | medium | data-portal 로그인 장애 |
| `enriched_seed_v1_ambiguous_query_005` | top1 | miss | high | medium | data-portal 캐시 장애 원인 |
| `enriched_seed_v1_ambiguous_query_006` | top3 | miss | high | medium | admin-portal 외부 연동 호출 실패 |
| `enriched_seed_v1_cross_project_conflict_002` | top3 | miss | medium | medium | admin-portal 로그인 클래스 로딩 실패 |
| `enriched_seed_v1_exact_keyword_001` | top3 | miss | high | high | JwtTokenProvider ClassNotFoundException DataAuthService login |
| `enriched_seed_v1_semantic_paraphrase_001` | top3 | miss | high | high | 로그인 인증 토큰 클래스 로딩 실패 |
