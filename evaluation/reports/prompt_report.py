from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


def write_prompt_report(
    *,
    prompt_payloads: dict[str, dict[str, Any]],
    comparison: dict[str, Any],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    first = next(iter(prompt_payloads.values()))
    params = first["parameters"]
    lines = [
        "# LLM Context Experiment",
        "",
        "## Hypothesis",
        "",
        "LLM에 전달하는 Context의 양과 구조가 Incident 판단 정확도와 Evidence Groundedness에 영향을 미칠 것이다.",
        "",
        "## Setup",
        "",
        f"- Model: {params['model']}",
        f"- Temperature: {params['temperature']}",
        f"- Query Count: {first['dataset']['query_count']}",
        f"- Retrieval Method: {first['fixed_retrieval']['method']}",
        f"- Top-K: {first['fixed_retrieval']['top_k']}",
        "- Prompt Version: prompt_a, prompt_b, prompt_c, prompt_d",
        "- Context Fields: recorded per prompt result file",
        "",
        "## Overall Result",
        "",
        "| Prompt | Incident Accuracy | Hypothesis Accuracy | Unsupported Claim | Schema | Input Token | Latency |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for prompt, payload in prompt_payloads.items():
        metrics = payload["metrics"]
        lines.append(
            f"| {prompt} | {_fmt(metrics['incident_selection_accuracy'])} | "
            f"{_fmt(metrics['hypothesis_accuracy'])} | "
            f"{_fmt(metrics['unsupported_claim_rate'])} | "
            f"{_fmt(metrics['schema_compliance'])} | "
            f"{_fmt(metrics['average_input_tokens'])} | "
            f"{_fmt(metrics['average_latency_ms'])} |"
        )
    lines.extend(["", "## Result by Query Type", ""])
    by_type = _metrics_by_query_type(prompt_payloads)
    for query_type, prompt_rows in by_type.items():
        lines.extend([f"### {query_type}", ""])
        lines.append("| Prompt | Schema | Unsupported Claim | Input Token | Latency |")
        lines.append("|---|---:|---:|---:|---:|")
        for prompt, metrics in prompt_rows.items():
            lines.append(
                f"| {prompt} | {_fmt(metrics['schema'])} | {_fmt(metrics['unsupported'])} | "
                f"{_fmt(metrics['input_tokens'])} | {_fmt(metrics['latency'])} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Context Sensitivity",
            "",
            f"- Selected Incident Changed: {comparison['changed_selection_count']}",
            f"- Hypothesis Changed: {comparison['changed_hypothesis_count']}",
            f"- Evidence Changed: {comparison['changed_evidence_count']}",
            "",
            "## Failure Cases",
            "",
            "- A는 실패하고 B는 성공: context_sensitivity.json과 prompt별 결과에서 수동 검토",
            "- B는 성공하고 C는 실패: context_sensitivity.json과 prompt별 결과에서 수동 검토",
            "- Raw Context에서는 hallucination 발생: unsupported_claims와 human review로 판정",
            "- Compressed Context에서 중요한 Evidence가 사라진 Case: context_fields와 evidence_used 비교",
            "- Context를 압축했는데도 결과가 동일한 Case: selected_incident_changed=false 케이스 검토",
            "",
            "## Token / Latency Trade-off",
            "",
            "정확도 향상 대비 추가 Input Token과 Latency를 비교한다.",
            "",
            "## Observations",
            "",
            "결과에서 확인 가능한 사실만 작성한다.",
            "",
            "## Decision",
            "",
            "가장 높은 Accuracy만 보지 않고 정확도, 비용, latency, unsupported claim을 함께 고려한다.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _metrics_by_query_type(prompt_payloads: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for prompt, payload in prompt_payloads.items():
        for case in payload["cases"]:
            grouped[str(case["query_type"])][prompt].append(case)
    output: dict[str, dict[str, dict[str, Any]]] = {}
    for query_type, prompts in grouped.items():
        output[query_type] = {}
        for prompt, cases in prompts.items():
            output[query_type][prompt] = {
                "schema": _avg([1.0 if case.get("schema_compliance") else 0.0 for case in cases]),
                "unsupported": _avg([
                    len((case.get("output") or {}).get("unsupported_claims") or [])
                    / max(1, len((case.get("output") or {}).get("claims") or []))
                    for case in cases
                    if case.get("output")
                ]),
                "input_tokens": _avg([case.get("input_tokens") for case in cases if case.get("input_tokens") is not None]),
                "latency": _avg([case.get("latency_ms") for case in cases if case.get("latency_ms") is not None]),
            }
    return dict(sorted(output.items()))


def _avg(values: list[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)

