# Batch Multi-Candidate Confidence Baseline v1

RRF Top3 후보를 한 번의 LLM 호출에서 함께 비교 평가하는 Batch Confidence 실험 결과다. Query Analyzer, Query Rewrite, Vector, BM25, RRF, Evaluation Dataset, Seed 데이터는 변경하지 않았다.

## 처리 흐름

1. Hybrid Retrieval이 기존과 동일하게 RRF 후보를 만든다.
2. RRF Top3 후보의 incident 요약, 에러, 키워드, 원인, 해결 정보와 Vector/BM25/RRF 근거를 하나의 LLM 요청에 전달한다.
3. LLM은 후보를 서로 비교해 각 후보의 confidence와 should_include를 판단하고, 관련 후보 ranking을 반환한다.
4. 최종 search results는 LLM ranking 순서로 구성한다.
5. batch LLM 호출 또는 JSON parsing 실패 시 기존 개별 confidence 평가로 fallback한다. 근거 없이 전체 후보를 통과시키지 않는다.

## JSON Schema

```json
{
  "evaluations": [
    {
      "incident_id": "uuid",
      "confidence": "high | medium | low",
      "confidence_score": 0.0,
      "should_include": true,
      "reason": "한국어 한 문장"
    }
  ],
  "ranking": [
    "uuid"
  ],
  "no_relevant_candidate": false
}
```

## Fallback 정책

Batch LLM 호출 실패, JSON parsing 실패, incident_id 누락/생성 등 출력 계약 위반이 있으면 기존 개별 confidence 평가로 fallback한다. 이 정책은 latency 이점은 일부 잃지만, 무근거 통과보다 보수적이고 기존 baseline과 비교 가능한 정확도 경로를 유지한다.

## Run 설정

- intent 제거 baseline: `c244fba7-ee7d-408d-aa79-ab4efdda67d8`
- sequential baseline: `9e27379d-89ac-4ef2-bc5e-3c50a005caa2`
- batch baseline: `9845f7cd-e880-4021-9b9b-f7b144650c8b`
- top_k: `3`
- candidate_limit: `20`
- rrf_k: `60`

## Metrics 비교

| metric | intent 제거 baseline | sequential confidence | batch multi-candidate |
| --- | ---: | ---: | ---: |
| retrieval_top1_accuracy | 0.825 | 0.825 | 0.825 |
| retrieval_top3_accuracy | 0.975 | 0.975 | 0.975 |
| retrieval_mrr | 0.898 | 0.898 | 0.898 |
| final_top1_accuracy | 0.850 | 0.825 | 0.950 |
| final_top3_accuracy | 0.975 | 0.825 | 0.975 |
| final_mrr | 0.908 | 0.825 | 0.963 |
| no_result_accuracy | 1.000 | 1.000 | 1.000 |
| abstain_ratio | 0.152 | 0.152 | 0.152 |
| mean_latency_ms | 5760.042 | 3717.756 | 6322.981 |

## Confidence 호출량 비교

| metric | intent 제거 baseline | sequential confidence | batch multi-candidate |
| --- | ---: | ---: | ---: |
| llm_calls | 138 | 61 | 46 |
| avg_llm_calls_per_case | 3.000 | 1.326 | 1.000 |
| llm_failures | 0 | 0 | 0 |
| fallback_executions | n/a | n/a | 0 |
| passed_candidates | 58 | 39 | 47 |
| rejected_candidates | 80 | 22 | 91 |

## 효과 요약

- final_top1_accuracy: `0.850` -> `0.950` (0.100)
- final_top3_accuracy: `0.975` -> `0.975` (0.000)
- final_mrr: `0.908` -> `0.963` (0.054)
- no_result_accuracy: `1.000` -> `1.000`
- mean_latency_ms 감소율: `-9.8%`
- LLM confidence 호출량 감소율: `66.7%`
- fallback 실행 횟수: `0`

## Case 변화 vs intent 제거 baseline

- 개선된 Case: `4`
- 동일한 Case: `42`
- 하락한 Case: `0`

## 개선된 Case

| case_key | base final | batch final | base confidence | batch confidence | query |
| --- | --- | --- | --- | --- | --- |
| `enriched_seed_v1_ambiguous_query_001` | top3 | top1 | medium | high | data-portal 로그인 장애 |
| `enriched_seed_v1_ambiguous_query_006` | top3 | top1 | high | high | admin-portal 외부 연동 호출 실패 |
| `enriched_seed_v1_cross_project_conflict_002` | top3 | top1 | medium | high | admin-portal 로그인 클래스 로딩 실패 |
| `enriched_seed_v1_exact_keyword_001` | top3 | top1 | high | high | JwtTokenProvider ClassNotFoundException DataAuthService login |

## 하락한 Case

| case_key | base final | batch final | base confidence | batch confidence | base RRF | batch RRF | query | 원인 |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## 최종 판단

Batch Multi-Candidate Confidence는 정확도와 LLM 호출량 측면에서는 채택 가능하다. intent 제거 baseline의 final_top3_accuracy와 no-result accuracy를 유지했고, LLM confidence 호출 수를 `138 -> 46`으로 줄였다.

다만 이번 run에서는 mean_latency_ms가 `5760.042 -> 6322.981`로 증가했다. Batch prompt가 후보 3개를 한 번에 비교하면서 단일 호출 payload가 커진 영향으로 보인다. 운영 채택 전에는 prompt compact화, 후보 payload 축약, 더 빠른 confidence 전용 모델 분리 중 하나를 추가로 실험해야 한다.
