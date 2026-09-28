"""Run and persist deterministic FinQA retrieval experiments."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dataset import load_finqa
from .embedding import CachedEmbeddingClient
from .metrics import aggregate_retrieval_metrics, score_ranking
from .retrieval import BM25Retriever, DenseRetriever, reciprocal_rank_fusion


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_state(repository: Path) -> dict[str, str | bool | None]:
    def command(*arguments: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    revision = command("rev-parse", "HEAD")
    status = command("status", "--porcelain")
    return {"revision": revision, "dirty": bool(status) if status is not None else None}


def run_retrieval(
    dataset_path: str | Path,
    output_directory: str | Path,
    *,
    split: str,
    retriever_name: str = "bm25",
    cutoffs: tuple[int, ...] = (1, 3, 5, 8, 10),
    k1: float = 1.5,
    b: float = 0.75,
    rrf_rank_constant: int = 60,
    embedding_client: CachedEmbeddingClient | None = None,
    max_examples: int | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_path).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_examples = load_finqa(dataset)
    if max_examples is not None:
        if max_examples <= 0:
            raise ValueError("max_examples must be positive")
        examples = source_examples[:max_examples]
    else:
        examples = source_examples
    if retriever_name in {"dense", "rrf"} and embedding_client is None:
        raise ValueError(f"{retriever_name} retrieval requires an embedding client")
    if retriever_name not in {"bm25", "dense", "rrf"}:
        raise ValueError(f"unknown retriever: {retriever_name}")
    records: list[dict[str, Any]] = []

    embedding_preparation: dict[str, Any] | None = None
    if embedding_client is not None:
        unique_texts = list(
            dict.fromkeys(
                [
                    candidate.text
                    for example in examples
                    for candidate in example.candidates
                ]
                + [example.question for example in examples]
            )
        )
        stats_before = embedding_client.stats()
        preparation_started = time.perf_counter()
        embedding_client.embed_many(unique_texts)
        preparation_seconds = time.perf_counter() - preparation_started
        stats_after = embedding_client.stats()
        embedding_preparation = {
            "unique_texts": len(unique_texts),
            "elapsed_seconds": preparation_seconds,
            "request_count": int(stats_after["request_count"])
            - int(stats_before["request_count"]),
            "cache_hits": int(stats_after["cache_hits"])
            - int(stats_before["cache_hits"]),
            "cache_misses": int(stats_after["cache_misses"])
            - int(stats_before["cache_misses"]),
        }

    started = time.perf_counter()
    for example in examples:
        retrieval_started = time.perf_counter()
        bm25 = BM25Retriever(example.candidates, k1=k1, b=b)
        if retriever_name == "bm25":
            ranking = bm25.rank(example.question)
        else:
            dense = DenseRetriever(example.candidates, embedding_client)
            dense_ranking = dense.rank(example.question)
            ranking = (
                dense_ranking
                if retriever_name == "dense"
                else reciprocal_rank_fusion(
                    [bm25.rank(example.question), dense_ranking],
                    rank_constant=rrf_rank_constant,
                )
            )
        latency_ms = (time.perf_counter() - retrieval_started) * 1000
        ranked_ids = [item.evidence_id for item in ranking]
        records.append(
            {
                "example_id": example.example_id,
                "question": example.question,
                "gold_evidence_ids": sorted(example.gold_evidence_ids),
                "ranked_evidence": [
                    {"evidence_id": item.evidence_id, "score": item.score}
                    for item in ranking
                ],
                "metrics": score_ranking(
                    ranked_ids, example.gold_evidence_ids, cutoffs=cutoffs
                ),
                "latency_ms": latency_ms,
            }
        )
    elapsed_seconds = time.perf_counter() - started

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
        "system": {
            "name": "fintrace-retrieval",
            "retriever": retriever_name,
            "parameters": {
                "k1": k1,
                "b": b,
                "rrf_rank_constant": rrf_rank_constant,
                "cutoffs": list(cutoffs),
            },
        },
        "code": git_state(project_root),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "metrics": aggregate_retrieval_metrics(records),
        "elapsed_seconds": elapsed_seconds,
        "latency_scope": "cached ranking; offline embedding preparation excluded",
        "artifacts": {"predictions": "predictions.jsonl"},
    }
    if embedding_client is not None:
        report["embedding"] = {
            **embedding_client.stats(),
            "preparation": embedding_preparation,
        }

    predictions_path = output / "predictions.jsonl"
    predictions_path.write_text(
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
