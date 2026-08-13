from __future__ import annotations

from pathlib import Path

from evaluation.common import EVALUATION_DATA_DIR, read_json, utc_now_iso, write_json
from evaluation.datasets.models import RetrievalDataset


def load_frozen_dataset(path: Path | None = None) -> RetrievalDataset:
    dataset_path = path or EVALUATION_DATA_DIR / "retrieval_queries_frozen.json"
    dataset = RetrievalDataset.model_validate(read_json(dataset_path))
    if dataset.status != "frozen":
        raise ValueError(f"{dataset_path} must have status='frozen'.")
    if not dataset.queries:
        raise ValueError(f"{dataset_path} has no approved queries.")
    return dataset


def validate_candidate_dataset(path: Path | None = None) -> RetrievalDataset:
    dataset_path = path or EVALUATION_DATA_DIR / "retrieval_queries_candidate.json"
    dataset = RetrievalDataset.model_validate(read_json(dataset_path))
    if dataset.status != "candidate":
        raise ValueError(f"{dataset_path} must have status='candidate'.")
    for query in dataset.queries:
        if query.excluded and not query.exclude_reason:
            raise ValueError(f"{query.query_id} is excluded but has no exclude_reason.")
    return dataset


def export_frozen_dataset(
    *,
    candidate_path: Path | None = None,
    output_path: Path | None = None,
) -> RetrievalDataset:
    source_path = candidate_path or EVALUATION_DATA_DIR / "retrieval_queries_candidate.json"
    target_path = output_path or EVALUATION_DATA_DIR / "retrieval_queries_frozen.json"
    candidate = validate_candidate_dataset(source_path)
    approved_queries = [query for query in candidate.queries if not query.excluded]
    if not approved_queries:
        raise ValueError("candidate dataset has no non-excluded queries to freeze.")

    frozen = RetrievalDataset(
        status="frozen",
        generated_at=candidate.generated_at,
        frozen_at=utc_now_iso(),
        source={
            **candidate.source,
            "candidate_path": str(source_path),
            "excluded_query_count": len(candidate.queries) - len(approved_queries),
            "freeze_export": "evaluation.datasets.review.export_frozen_dataset",
        },
        review_policy=candidate.review_policy,
        queries=approved_queries,
    )
    payload = frozen.model_dump()
    for query in payload["queries"]:
        query.pop("reviewed_by_human", None)
        query.pop("review_note", None)
        query.pop("excluded", None)
        query.pop("exclude_reason", None)
    write_json(target_path, payload)
    return frozen
