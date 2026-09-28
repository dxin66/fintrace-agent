import pytest

from fintrace_eval.metrics import aggregate_retrieval_metrics, percentile, score_ranking


def test_score_ranking_handles_multiple_gold_items():
    metrics = score_ranking(
        ["noise", "gold-a", "gold-b"],
        frozenset({"gold-a", "gold-b"}),
        cutoffs=(1, 2, 3),
    )
    assert metrics["reciprocal_rank"] == 0.5
    assert metrics["recall@2"] == 0.5
    assert metrics["all_evidence@2"] == 0.0
    assert metrics["all_evidence@3"] == 1.0


def test_duplicate_ranked_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        score_ranking(["same", "same"], frozenset({"same"}))


def test_aggregate_includes_latency_percentiles():
    rows = [
        {"metrics": {"reciprocal_rank": 1.0}, "latency_ms": 10.0},
        {"metrics": {"reciprocal_rank": 0.0}, "latency_ms": 30.0},
    ]
    result = aggregate_retrieval_metrics(rows)
    assert result["reciprocal_rank"] == 0.5
    assert result["latency_ms_p50"] == 20.0
    assert percentile([10.0, 20.0, 30.0], 95) == 29.0
