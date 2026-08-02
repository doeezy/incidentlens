# Batch Confidence Compact v1

Batch Multi-Candidate Confidence는 유지하고 prompt payload만 줄인 실험 결과다. Query Analyzer, Vector, BM25, RRF, Evaluation Dataset, Seed 데이터, 모델은 변경하지 않았다.

## Compact 변경

- 후보별 점수(`vector_score`, `bm25_score`, `rrf_score`)는 prompt에서 제거했다. 최종 응답과 evaluation trace에는 기존처럼 저장한다.
- 후보별 입력은 `incident_id`, `rrf`, `vec`, `bm25`, `type`, `msg`, `summary` 중심으로 제한했다.
- `ROOT_CAUSE`는 `cause`, `root`, 구분 단서용 `keywords`, `tags`만 추가한다.
- `RESOLUTION`은 `resolution`만 추가한다.
- `SIMILAR_CASE`는 `keywords`, `tags`만 최대 5개씩 추가한다.
- `SUMMARY`는 `summary` 중심이며, 구분 단서용 `keywords`, `tags`, 짧은 원인/해결 문맥만 추가한다.
- null, 빈 문자열, 빈 배열은 prompt에서 제거한다.
- summary/cause/resolution 계열 텍스트는 지정 길이로 잘라 전송한다.
- Batch 판단 기준, ranking 적용, should_include 처리, fallback 정책은 변경하지 않았다.

## Run 설정

- previous batch run: `9845f7cd-e880-4021-9b9b-f7b144650c8b`
- compact run: `f7850759-8942-4596-aa88-5b6122f2a70d`
- top_k: `3`
- candidate_limit: `20`
- rrf_k: `60`
- case_count: `46`

## Metrics 비교

| metric | batch baseline | compact | delta |
| --- | ---: | ---: | ---: |
| retrieval_top1_accuracy | 0.825 | 0.825 | +0.000 |
| retrieval_top3_accuracy | 0.975 | 0.975 | +0.000 |
| retrieval_mrr | 0.898 | 0.898 | +0.000 |
| final_top1_accuracy | 0.950 | 0.950 | +0.000 |
| final_top3_accuracy | 0.975 | 0.975 | +0.000 |
| final_mrr | 0.963 | 0.963 | +0.000 |
| no_result_accuracy | 1.000 | 1.000 | +0.000 |
| abstain_ratio | 0.152 | 0.152 | +0.000 |
| mean_latency_ms | 6322.981 | 6076.877 | -246.105 |
| p95_latency_ms | 7934.967 | 7493.091 | -441.876 |

## Confidence Telemetry 비교

| metric | batch baseline | compact | delta |
| --- | ---: | ---: | ---: |
| llm_calls | 46 | 46 | +0.000 |
| avg_llm_calls_per_case | 1.000 | 1.000 | +0.000 |
| batch_llm_calls | 46 | 46 | +0.000 |
| individual_llm_calls | 0 | 0 | +0.000 |
| fallback_executions | 0 | 0 | +0.000 |
| llm_failures | 0 | 0 | +0.000 |
| evaluated_candidates | 138 | 138 | +0.000 |
| passed_candidates | 47 | 45 | -2.000 |
| rejected_candidates | 91 | 93 | +2.000 |
| avg_prompt_input_tokens | n/a | 1044.435 | n/a |
| avg_output_tokens | n/a | 266.435 | n/a |
| token_observations | n/a | 46 | n/a |

## 변화 요약

- final_top1_accuracy 변화: `+0.000`
- final_top3_accuracy 변화: `+0.000`
- no_result_accuracy 변화: `+0.000`
- mean_latency_ms 변화율: `-3.9%`
- LLM 호출 수 변화율: `+0.0%`
- fallback 실행 수: `0`

이전 batch baseline에는 OpenAI usage token telemetry가 저장되어 있지 않아 실제 변경 전 token 수는 `n/a`로 둔다. compact run부터 `avg_prompt_input_tokens`, `avg_output_tokens`, `token_observations`를 실제 OpenAI usage 값으로 저장한다.

## Case 변화

- 개선된 Case: `0`
- 동일한 Case: `46`
- 하락한 Case: `0`

## 개선된 Case

| case_key | previous final | compact final | previous confidence | compact confidence | vector rank | BM25 rank | RRF rank | query |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## 하락한 Case

| case_key | previous final | compact final | previous confidence | compact confidence | vector rank | BM25 rank | RRF rank | query |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
