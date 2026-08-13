from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.database import SessionLocal, init_db
from evaluation.common import EVALUATION_DATA_DIR, EVALUATION_RESULTS_DIR, write_json
from evaluation.datasets.candidate_generator import generate_candidate_dataset
from evaluation.datasets.models import LlmGroundTruth, LlmGroundTruthItem, RetrievalDataset
from evaluation.datasets.prompt_ground_truth_generator import (
    generate_prompt_ground_truth_candidate,
)
from evaluation.datasets.review import (
    export_frozen_dataset,
    load_frozen_dataset,
    validate_candidate_dataset,
)
from evaluation.prompts.runner import run_prompt_experiment
from evaluation.prompts.prompt_ablation_runner import run_prompt_ablation_experiment
from evaluation.retrieval.candidate_ab_runner import run_candidate_retrieval_ab_experiment
from evaluation.retrieval.query_rewrite_ablation_runner import (
    run_query_rewrite_ablation_experiment,
)
from evaluation.retrieval.reranker_ablation_runner import (
    run_reranker_ablation_experiment,
)
from evaluation.retrieval.reranker_candidate_pool_runner import (
    run_reranker_candidate_pool_experiment,
)
from evaluation.retrieval.runner import run_retrieval_experiment
from evaluation.retrieval.weighted_rrf_runner import run_weighted_rrf_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="IncidentLens evaluation framework")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-candidates")
    generate.add_argument("--output", type=Path, default=EVALUATION_DATA_DIR / "retrieval_queries_candidate.json")
    generate.add_argument("--project-name")
    generate.add_argument("--limit", type=int)

    subparsers.add_parser("validate-candidate")
    subparsers.add_parser("validate-frozen")

    freeze = subparsers.add_parser("export-frozen")
    freeze.add_argument(
        "--candidate",
        type=Path,
        default=EVALUATION_DATA_DIR / "retrieval_queries_candidate.json",
    )
    freeze.add_argument(
        "--output",
        type=Path,
        default=EVALUATION_DATA_DIR / "retrieval_queries_frozen.json",
    )

    gt = subparsers.add_parser("create-llm-ground-truth-template")
    gt.add_argument("--frozen", type=Path, default=EVALUATION_DATA_DIR / "retrieval_queries_frozen.json")
    gt.add_argument("--output", type=Path, default=EVALUATION_DATA_DIR / "llm_ground_truth.json")

    prompt_gt = subparsers.add_parser("generate-prompt-ground-truth-candidate")
    prompt_gt.add_argument(
        "--candidate",
        type=Path,
        default=EVALUATION_DATA_DIR / "retrieval_queries_candidate.json",
    )
    prompt_gt.add_argument(
        "--output",
        type=Path,
        default=EVALUATION_DATA_DIR / "prompt_ground_truth_candidate.json",
    )

    retrieval = subparsers.add_parser("run-retrieval")
    retrieval.add_argument("--frozen", type=Path, default=EVALUATION_DATA_DIR / "retrieval_queries_frozen.json")
    retrieval.add_argument("--output-dir", type=Path, default=EVALUATION_RESULTS_DIR / "retrieval")
    retrieval.add_argument("--top-k", type=int, default=5)
    retrieval.add_argument("--candidate-limit", type=int, default=20)
    retrieval.add_argument("--rrf-k", type=int, default=60)

    candidate_retrieval = subparsers.add_parser("run-candidate-retrieval-ab")
    candidate_retrieval.add_argument(
        "--candidate",
        type=Path,
        default=EVALUATION_DATA_DIR / "retrieval_queries_candidate.json",
    )
    candidate_retrieval.add_argument("--output-dir", type=Path, default=Path("evaluation_result"))
    candidate_retrieval.add_argument("--top-k", type=int, default=5)
    candidate_retrieval.add_argument("--candidate-limit", type=int, default=20)
    candidate_retrieval.add_argument("--rrf-k", type=int, default=60)

    weighted_rrf = subparsers.add_parser("run-weighted-rrf")
    weighted_rrf.add_argument(
        "--cases",
        type=Path,
        default=Path("evaluation_result/retrieval_cases.json"),
    )
    weighted_rrf.add_argument(
        "--metrics",
        type=Path,
        default=Path("evaluation_result/retrieval_metrics.json"),
    )
    weighted_rrf.add_argument("--output-dir", type=Path, default=Path("evaluation_result"))

    rewrite_ablation = subparsers.add_parser("run-query-rewrite-ablation")
    rewrite_ablation.add_argument(
        "--cases",
        type=Path,
        default=Path("evaluation_result/retrieval_cases.json"),
    )
    rewrite_ablation.add_argument(
        "--metrics",
        type=Path,
        default=Path("evaluation_result/retrieval_metrics.json"),
    )
    rewrite_ablation.add_argument("--output-dir", type=Path, default=Path("evaluation_result"))

    reranker_ablation = subparsers.add_parser("run-reranker-ablation")
    reranker_ablation.add_argument(
        "--cases",
        type=Path,
        default=Path("evaluation_result/retrieval_cases.json"),
    )
    reranker_ablation.add_argument(
        "--metrics",
        type=Path,
        default=Path("evaluation_result/retrieval_metrics.json"),
    )
    reranker_ablation.add_argument("--output-dir", type=Path, default=Path("evaluation_result"))

    reranker_candidate_pool = subparsers.add_parser("run-reranker-candidate-pool")
    reranker_candidate_pool.add_argument(
        "--cases",
        type=Path,
        default=Path("evaluation_result/retrieval_cases.json"),
    )
    reranker_candidate_pool.add_argument(
        "--metrics",
        type=Path,
        default=Path("evaluation_result/retrieval_metrics.json"),
    )
    reranker_candidate_pool.add_argument(
        "--r5-cases",
        type=Path,
        default=Path("evaluation_result/reranker_ablation_cases.json"),
    )
    reranker_candidate_pool.add_argument("--output-dir", type=Path, default=Path("evaluation_result"))

    prompts = subparsers.add_parser("run-prompts")
    prompts.add_argument("--frozen", type=Path, default=EVALUATION_DATA_DIR / "retrieval_queries_frozen.json")
    prompts.add_argument("--retrieval", type=Path, default=EVALUATION_RESULTS_DIR / "retrieval" / "hybrid.json")
    prompts.add_argument("--ground-truth", type=Path, default=EVALUATION_DATA_DIR / "llm_ground_truth.json")
    prompts.add_argument("--output-dir", type=Path, default=EVALUATION_RESULTS_DIR / "prompt")
    prompts.add_argument("--model")
    prompts.add_argument("--temperature", type=float, default=0.0)
    prompts.add_argument("--max-output-tokens", type=int, default=1200)
    prompts.add_argument("--seed", type=int)
    prompts.add_argument("--top-k", type=int, default=5)

    prompt_ablation = subparsers.add_parser("run-prompt-ablation")
    prompt_ablation.add_argument(
        "--candidate",
        type=Path,
        default=EVALUATION_DATA_DIR / "prompt_ground_truth_candidate.json",
    )
    prompt_ablation.add_argument(
        "--frozen-output",
        type=Path,
        default=EVALUATION_DATA_DIR / "prompt_ground_truth_frozen.json",
    )
    prompt_ablation.add_argument(
        "--snapshot-output",
        type=Path,
        default=EVALUATION_DATA_DIR / "prompt_retrieval_snapshot.json",
    )
    prompt_ablation.add_argument("--output-dir", type=Path, default=Path("evaluation_result"))
    prompt_ablation.add_argument("--model")
    prompt_ablation.add_argument("--judge-model")
    prompt_ablation.add_argument("--temperature", type=float, default=0.0)
    prompt_ablation.add_argument("--max-tokens", type=int, default=900)
    prompt_ablation.add_argument("--retrieval-top-k", type=int, default=5)
    prompt_ablation.add_argument("--candidate-limit", type=int, default=20)
    prompt_ablation.add_argument("--rrf-k", type=int, default=60)
    prompt_ablation.add_argument("--no-judge", action="store_true")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "validate-candidate":
        dataset = validate_candidate_dataset()
        print(f"candidate ok: {len(dataset.queries)} queries")
        return
    if args.command == "validate-frozen":
        dataset = load_frozen_dataset()
        print(f"frozen ok: {len(dataset.queries)} queries")
        return
    if args.command == "export-frozen":
        dataset = export_frozen_dataset(
            candidate_path=args.candidate,
            output_path=args.output,
        )
        print(f"wrote {args.output}: {len(dataset.queries)} frozen queries")
        return

    init_db()
    session = SessionLocal()
    try:
        if args.command == "generate-candidates":
            dataset = generate_candidate_dataset(
                session=session,
                settings=settings,
                output_path=args.output,
                project_name=args.project_name,
                limit=args.limit,
            )
            print(f"wrote {args.output}: {len(dataset.queries)} candidate queries")
        elif args.command == "create-llm-ground-truth-template":
            dataset = RetrievalDataset.model_validate_json(args.frozen.read_text(encoding="utf-8"))
            items = [
                LlmGroundTruthItem(
                    query_id=query.query_id,
                    expected_incident_id=query.expected_incident_id,
                    reviewed_by_human=False,
                )
                for query in dataset.queries
            ]
            write_json(args.output, LlmGroundTruth(items=items).model_dump())
            print(f"wrote {args.output}: {len(items)} ground-truth items")
        elif args.command == "generate-prompt-ground-truth-candidate":
            payload = generate_prompt_ground_truth_candidate(
                session=session,
                retrieval_candidate_path=args.candidate,
                output_path=args.output,
            )
            summary = payload["summary"]
            print(
                f"wrote {args.output}: {summary['item_count']} prompt ground-truth candidate items; "
                f"validation_passed={summary['validation_passed']}"
            )
        elif args.command == "run-retrieval":
            dataset = load_frozen_dataset(args.frozen)
            run_retrieval_experiment(
                session=session,
                settings=settings,
                dataset=dataset,
                output_dir=args.output_dir,
                top_k=args.top_k,
                candidate_limit=args.candidate_limit,
                rrf_k=args.rrf_k,
            )
            print(f"wrote retrieval results to {args.output_dir}")
        elif args.command == "run-candidate-retrieval-ab":
            run_candidate_retrieval_ab_experiment(
                session=session,
                settings=settings,
                candidate_path=args.candidate,
                output_dir=args.output_dir,
                top_k=args.top_k,
                candidate_limit=args.candidate_limit,
                rrf_k=args.rrf_k,
            )
            print(f"wrote candidate retrieval A/B/C results to {args.output_dir}")
        elif args.command == "run-weighted-rrf":
            run_weighted_rrf_experiment(
                input_cases_path=args.cases,
                input_metrics_path=args.metrics,
                output_dir=args.output_dir,
            )
            print(f"wrote weighted RRF results to {args.output_dir}")
        elif args.command == "run-query-rewrite-ablation":
            run_query_rewrite_ablation_experiment(
                session=session,
                settings=settings,
                baseline_cases_path=args.cases,
                baseline_metrics_path=args.metrics,
                output_dir=args.output_dir,
            )
            print(f"wrote query rewrite ablation results to {args.output_dir}")
        elif args.command == "run-reranker-ablation":
            run_reranker_ablation_experiment(
                settings=settings,
                input_cases_path=args.cases,
                input_metrics_path=args.metrics,
                output_dir=args.output_dir,
            )
            print(f"wrote reranker ablation results to {args.output_dir}")
        elif args.command == "run-reranker-candidate-pool":
            run_reranker_candidate_pool_experiment(
                settings=settings,
                retrieval_cases_path=args.cases,
                retrieval_metrics_path=args.metrics,
                r5_cases_path=args.r5_cases,
                output_dir=args.output_dir,
            )
            print(f"wrote reranker candidate pool results to {args.output_dir}")
        elif args.command == "run-prompts":
            dataset = load_frozen_dataset(args.frozen)
            run_prompt_experiment(
                session=session,
                settings=settings,
                dataset=dataset,
                retrieval_path=args.retrieval,
                ground_truth_path=args.ground_truth,
                output_dir=args.output_dir,
                model=args.model,
                temperature=args.temperature,
                max_output_tokens=args.max_output_tokens,
                seed=args.seed,
                top_k=args.top_k,
            )
            print(f"wrote prompt results to {args.output_dir}")
        elif args.command == "run-prompt-ablation":
            run_prompt_ablation_experiment(
                session=session,
                settings=settings,
                candidate_path=args.candidate,
                frozen_path=args.frozen_output,
                snapshot_path=args.snapshot_output,
                output_dir=args.output_dir,
                model=args.model,
                judge_model=args.judge_model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                retrieval_top_k=args.retrieval_top_k,
                candidate_limit=args.candidate_limit,
                rrf_k=args.rrf_k,
                run_judge=not args.no_judge,
            )
            print(f"wrote prompt ablation results to {args.output_dir}")
        else:
            parser.error(f"unknown command: {args.command}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
