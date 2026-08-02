# Confidence v2 Baseline 결과

## Run 정보

- 이전 baseline run_id: `336c6a1f-3f8d-4baf-b9e0-d4ffc3537bbc`
- 새 baseline run_id: `fa8a0e14-ece6-445a-a88b-737d35cf36ca`
- 새 retrieval_version: `hybrid-rrf-confidence:v2`
- 전체 케이스 수: `46`
- 정답 존재 케이스 수: `40`
- 정답 없음 케이스 수: `6`

## 지표 비교

| 지표 | 변경 전 | 변경 후 | 차이 |
| --- | ---: | ---: | ---: |
| retrieval_top1_accuracy | 0.500 | 0.475 | -0.025 |
| retrieval_top3_accuracy | 0.600 | 0.575 | -0.025 |
| retrieval_mrr | 0.595 | 0.571 | -0.024 |
| final_top1_accuracy | 0.175 | 0.550 | 0.375 |
| final_top3_accuracy | 0.175 | 0.575 | 0.400 |
| final_mrr | 0.175 | 0.562 | 0.388 |
| no_result_accuracy | 1.000 | 1.000 | 0.000 |
| abstain_ratio | 0.848 | 0.457 | -0.391 |
| mean_latency_ms | 2111.358 | 5622.670 | 3511.312 |

## Confidence Telemetry

- 전체 평가 후보 수: `138`
- LLM confidence 호출 횟수: `138`
- 전체 후보 수 대비 LLM 호출 비율: `1.000`
- Case당 평균 LLM 호출 횟수: `3.000`
- LLM 평가 실패 횟수: `0`
- 통과 후보 수: `33`
- LLM low confidence reject 수: `105`
- LLM 호출 전 reject 수: `0`

## Confidence rejection 사유별 건수

- llm_low_confidence: `105`

## 새 baseline 실패 유형

- RRF_RANKING_MISS: `17`

## 결론

Confidence v2에서는 Vector 점수 단독 탈락 조건을 제거하고 Hybrid Retrieval 근거와 Incident 내용을 LLM이 함께 검증하도록 변경했다. 그 결과 Final Top1 Accuracy가 17.5%에서 55.0%로 상승했고, No-result Accuracy는 100%를 유지했다. Confidence 단계에서 정답 후보가 과도하게 제거되던 문제는 완화되었다.

반면 모든 후보에 LLM 검증을 수행하면서 평균 지연시간이 2.11초에서 5.62초로 증가했다. 현재 주요 실패 원인은 Confidence Reject가 아니라 정답이 RRF Top3에 진입하지 못하는 RRF Ranking Miss 17건이다.

다음 실험에서는 Confidence v2를 유지한 채 RRF 실패 사례를 세분화하여 Retrieval 단계의 병목을 개선한다.
