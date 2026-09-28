"""End-to-end FinQA program and citation evaluation."""

from __future__ import annotations

import json
import math
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dataset import FinQAExample, load_finqa
from .generation import CachedProgramClient, build_user_prompt
from .program import execute_program, execution_matches, programs_equivalent
from .runner import git_state, sha256_file


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _load_rankings(path: Path) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        record = json.loads(line)
        example_id = record["example_id"]
        if example_id in rankings:
            raise ValueError(f"{path}:{line_number}: duplicate example id {example_id}")
        rankings[example_id] = [
            item["evidence_id"] for item in record["ranked_evidence"]
        ]
    return rankings


def _score_example(
    example: FinQAExample,
    ranking: list[str],
    client: CachedProgramClient,
    top_k: int,
    verify: bool,
) -> dict[str, Any]:
    candidates = {candidate.evidence_id: candidate for candidate in example.candidates}
    selected_ids = ranking[:top_k]
    expected_count = min(top_k, len(candidates))
    if len(selected_ids) != expected_count or any(
        item not in candidates for item in selected_ids
    ):
        raise ValueError(f"invalid top-{top_k} ranking for {example.example_id}")
    user_prompt = build_user_prompt(
        example, [candidates[item] for item in selected_ids]
    )
    draft = client.predict(user_prompt)
    draft_valid, draft_result = execute_program(draft.program, example.table)
    if verify:
        prediction = client.predict(
            f"{user_prompt}\n\nReview this draft against the question and evidence. "
            "Correct wrong operands, operation order, percentage scaling, row selection, or DSL "
            "syntax. Return the final JSON contract even when the draft is already correct.\n"
            f"Draft program: {draft.program or '<invalid format>'}\n"
            f"Draft execution: {draft_result if draft_valid else 'n/a'}"
        )
    else:
        prediction = draft
    valid, execution_result = execute_program(prediction.program, example.table)
    predicted_citations = set(prediction.citations)
    gold_citations = set(example.gold_evidence_ids)
    correct_citations = predicted_citations.intersection(gold_citations)
    citation_precision = (
        len(correct_citations) / len(predicted_citations)
        if predicted_citations
        else 0.0
    )
    citation_recall = len(correct_citations) / len(gold_citations)
    citation_f1 = (
        2
        * citation_precision
        * citation_recall
        / (citation_precision + citation_recall)
        if citation_precision + citation_recall
        else 0.0
    )
    return {
        "example_id": example.example_id,
        "question": example.question,
        "retrieved_evidence_ids": selected_ids,
        "gold_evidence_ids": sorted(gold_citations),
        "predicted_program": prediction.program,
        "draft_program": draft.program,
        "draft_execution_result": draft_result,
        "verification_changed_program": prediction.program != draft.program,
        "gold_program": example.gold_program,
        "predicted_citations": list(prediction.citations),
        "format_valid": prediction.parse_error is None,
        "format_error": prediction.parse_error,
        "program_valid": valid,
        "execution_result": execution_result,
        "gold_execution_result": example.gold_execution_answer,
        "metrics": {
            "execution_accuracy": float(
                valid
                and execution_matches(execution_result, example.gold_execution_answer)
            ),
            "program_accuracy": float(
                example.gold_program is not None
                and programs_equivalent(example.gold_program, prediction.program)
            ),
            "citation_precision": citation_precision,
            "citation_recall": citation_recall,
            "citation_f1": citation_f1,
        },
        "model": {
            "cache_hit": prediction.cache_hit,
            "latency_ms": prediction.latency_ms,
            "prompt_tokens": prediction.prompt_tokens,
            "completion_tokens": prediction.completion_tokens,
            "total_tokens": prediction.total_tokens,
            "draft_cache_hit": draft.cache_hit,
            "draft_latency_ms": draft.latency_ms,
            "draft_prompt_tokens": draft.prompt_tokens,
            "draft_completion_tokens": draft.completion_tokens,
            "draft_total_tokens": draft.total_tokens,
        },
    }


def run_end_to_end(
    dataset_path: str | Path,
    retrieval_predictions_path: str | Path,
    output_directory: str | Path,
    *,
    split: str,
    client: CachedProgramClient,
    top_k: int = 5,
    workers: int = 4,
    verify: bool = False,
    max_examples: int | None = None,
) -> dict[str, Any]:
    if top_k <= 0 or workers <= 0:
        raise ValueError("top_k and workers must be positive")
    dataset = Path(dataset_path).resolve()
    retrieval_predictions = Path(retrieval_predictions_path).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_examples = load_finqa(dataset)
    examples = (
        source_examples[:max_examples] if max_examples is not None else source_examples
    )
    if max_examples is not None and max_examples <= 0:
        raise ValueError("max_examples must be positive")
    rankings = _load_rankings(retrieval_predictions)
    missing = [
        example.example_id for example in examples if example.example_id not in rankings
    ]
    if missing:
        raise ValueError(
            f"retrieval predictions are missing {len(missing)} evaluated examples"
        )

    started = time.perf_counter()
    indexed_records: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _score_example,
                example,
                rankings[example.example_id],
                client,
                top_k,
                verify,
            ): index
            for index, example in enumerate(examples)
        }
        for future in as_completed(futures):
            indexed_records[futures[future]] = future.result()
    records = [indexed_records[index] for index in range(len(examples))]
    elapsed_seconds = time.perf_counter() - started

    metric_names = (
        "execution_accuracy",
        "program_accuracy",
        "citation_precision",
        "citation_recall",
        "citation_f1",
    )
    metrics = {
        name: statistics.fmean(record["metrics"][name] for record in records)
        for name in metric_names
    }
    latencies = [
        record["model"]["latency_ms"]
        + (record["model"]["draft_latency_ms"] if verify else 0.0)
        for record in records
    ]
    token_totals = {
        key: sum(
            record["model"][key] + (record["model"][f"draft_{key}"] if verify else 0)
            for record in records
        )
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    project_root = Path(__file__).resolve().parents[2]
    report: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "name": "FinQA",
            "split": split,
            "path": str(dataset),
            "sha256": sha256_file(dataset),
            "source_examples": len(source_examples),
            "evaluated_examples": len(examples),
            "scope": "full" if len(examples) == len(source_examples) else "smoke",
        },
        "retrieval": {
            "predictions_path": str(retrieval_predictions),
            "predictions_sha256": sha256_file(retrieval_predictions),
            "top_k": top_k,
        },
        "system": {
            "name": "fintrace-program-agent",
            "model": client.stats(),
            "workers": workers,
            "verification_rounds": 1 if verify else 0,
        },
        "code": git_state(project_root),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "metrics": metrics,
        "program_valid_rate": statistics.fmean(
            float(record["program_valid"]) for record in records
        ),
        "format_valid_rate": statistics.fmean(
            float(record["format_valid"]) for record in records
        ),
        "usage": token_totals,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "scope": "sum of original online generation rounds per example; cached entries retain first-call latency",
        },
        "elapsed_seconds": elapsed_seconds,
        "artifacts": {"predictions": "predictions.jsonl"},
    }
    (output / "predictions.jsonl").write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
