# IncidentLens Evaluation Framework

This framework keeps evaluation code separate from the service path and enforces
two independent experiment tracks:

1. Retrieval comparison: Vector, BM25, Hybrid RRF.
2. Prompt/context comparison: Prompt A/B/C/D over the same fixed Top-K retrieval results.

## Dataset Workflow

Generate candidate queries with LLM:

```bash
python -m evaluation.cli generate-candidates
```

Review `evaluation_data/retrieval_queries_candidate.json` manually. Reviewers
may edit `query_text`, `query_type`, `note`, `review_note`, and
`reviewed_by_human` directly. Mark unusable candidates with `excluded=true` and
add `exclude_reason`.

Export the reviewed snapshot:

```bash
python -m evaluation.cli export-frozen
```

The export removes `excluded=true` queries and writes
`evaluation_data/retrieval_queries_frozen.json` with `status` as `frozen`.
Experiment runners reject non-frozen or empty datasets.

Create an LLM ground truth review template after the frozen dataset is ready:

```bash
python -m evaluation.cli create-llm-ground-truth-template
```

Fill `evaluation_data/llm_ground_truth.json` manually. LLM-generated answers are
not treated as ground truth.

## Retrieval Experiment

```bash
python -m evaluation.cli run-retrieval --top-k 5 --candidate-limit 20 --rrf-k 60
```

Outputs:

- `evaluation_results/retrieval/vector.json`
- `evaluation_results/retrieval/bm25.json`
- `evaluation_results/retrieval/hybrid.json`
- `evaluation_results/retrieval/failure_analysis.json`
- `reports/retrieval_experiment.md`

## Prompt Context Experiment

Run retrieval first, then:

```bash
python -m evaluation.cli run-prompts \
  --retrieval evaluation_results/retrieval/hybrid.json \
  --top-k 5 \
  --temperature 0 \
  --max-output-tokens 1200
```

Outputs:

- `evaluation_results/prompt/prompt_a.json`
- `evaluation_results/prompt/prompt_b.json`
- `evaluation_results/prompt/prompt_c.json`
- `evaluation_results/prompt/prompt_d.json`
- `evaluation_results/prompt/context_sensitivity.json`
- `reports/prompt_context_experiment.md`

Model prices are read from `evaluation/config/model_pricing.json`. The default
values are zero so cost estimates are explicit placeholders until reviewed.
