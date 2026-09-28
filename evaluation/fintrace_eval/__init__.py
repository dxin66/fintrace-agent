"""Reproducible evaluation utilities for FinTrace."""

from .dataset import EvidenceCandidate, FinQAExample, load_finqa
from .metrics import aggregate_retrieval_metrics, score_ranking
from .retrieval import BM25Retriever

__all__ = [
    "BM25Retriever",
    "EvidenceCandidate",
    "FinQAExample",
    "aggregate_retrieval_metrics",
    "load_finqa",
    "score_ranking",
]
