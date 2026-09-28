"""Evidence-retrieval metrics with per-example audit records."""

from __future__ import annotations

import math
from statistics import mean
from typing import Any, Iterable


def score_ranking(
    ranked_ids: list[str],
    gold_ids: frozenset[str],
    *,
    cutoffs: tuple[int, ...] = (1, 3, 5, 8, 10),
) -> dict[str, float]:
    if not gold_ids:
        raise ValueError("retrieval metrics require at least one gold evidence id")
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("ranked evidence ids must be unique")
    result: dict[str, float] = {}
    first_relevant_rank = next(
        (
            rank
            for rank, evidence_id in enumerate(ranked_ids, 1)
            if evidence_id in gold_ids
        ),
        None,
    )
    result["reciprocal_rank"] = (
        0.0 if first_relevant_rank is None else 1 / first_relevant_rank
    )
    for cutoff in cutoffs:
        retrieved = set(ranked_ids[:cutoff])
        matches = len(retrieved.intersection(gold_ids))
        result[f"recall@{cutoff}"] = matches / len(gold_ids)
        result[f"precision@{cutoff}"] = matches / cutoff
        result[f"all_evidence@{cutoff}"] = float(gold_ids.issubset(retrieved))
    return result


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile of an empty sequence")
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def aggregate_retrieval_metrics(
    records: Iterable[dict[str, Any]],
) -> dict[str, float | int]:
    rows = list(records)
    if not rows:
        raise ValueError("cannot aggregate an empty evaluation")
    metric_names = sorted(rows[0]["metrics"])
    aggregate: dict[str, float | int] = {"examples": len(rows)}
    for name in metric_names:
        aggregate[name] = mean(float(row["metrics"][name]) for row in rows)
    latencies = [float(row["latency_ms"]) for row in rows]
    aggregate["latency_ms_p50"] = percentile(latencies, 50)
    aggregate["latency_ms_p95"] = percentile(latencies, 95)
    return aggregate
