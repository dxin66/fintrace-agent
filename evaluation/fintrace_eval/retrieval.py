"""Deterministic retrieval baselines for the FinQA evidence task."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .dataset import EvidenceCandidate

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?%?", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower().replace(",", ""))


@dataclass(frozen=True)
class RankedEvidence:
    evidence_id: str
    score: float


class Embedder(Protocol):
    def embed_many(self, texts: list[str]) -> list[list[float]]: ...


class BM25Retriever:
    """Small, dependency-free Okapi BM25 implementation with stable tie-breaking."""

    name = "bm25"

    def __init__(
        self,
        candidates: tuple[EvidenceCandidate, ...],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ):
        if not candidates:
            raise ValueError("BM25 requires at least one evidence candidate")
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 parameters must satisfy k1 > 0 and 0 <= b <= 1")
        self.candidates = candidates
        self.k1 = k1
        self.b = b
        self.documents = [tokenize(candidate.text) for candidate in candidates]
        self.term_frequencies = [Counter(document) for document in self.documents]
        self.document_lengths = [len(document) for document in self.documents]
        self.average_document_length = sum(self.document_lengths) / len(
            self.document_lengths
        )
        document_frequency: Counter[str] = Counter()
        for document in self.documents:
            document_frequency.update(set(document))
        count = len(self.documents)
        self.inverse_document_frequency = {
            term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def rank(self, query: str) -> list[RankedEvidence]:
        query_terms = tokenize(query)
        ranked: list[RankedEvidence] = []
        for candidate, frequencies, document_length in zip(
            self.candidates,
            self.term_frequencies,
            self.document_lengths,
        ):
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                length_ratio = document_length / self.average_document_length
                denominator = frequency + self.k1 * (1 - self.b + self.b * length_ratio)
                score += self.inverse_document_frequency.get(term, 0.0) * (
                    frequency * (self.k1 + 1) / denominator
                )
            ranked.append(RankedEvidence(candidate.evidence_id, score))
        return sorted(ranked, key=lambda item: (-item.score, item.evidence_id))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cosine vectors have different dimensions")
    dot_product = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot_product / (left_norm * right_norm)


class DenseRetriever:
    name = "dense"

    def __init__(self, candidates: tuple[EvidenceCandidate, ...], embedder: Embedder):
        if not candidates:
            raise ValueError("dense retrieval requires at least one evidence candidate")
        self.candidates = candidates
        self.embedder = embedder
        self.candidate_vectors = embedder.embed_many(
            [candidate.text for candidate in candidates]
        )

    def rank(self, query: str) -> list[RankedEvidence]:
        query_vector = self.embedder.embed_many([query])[0]
        ranked = [
            RankedEvidence(
                candidate.evidence_id, cosine_similarity(query_vector, vector)
            )
            for candidate, vector in zip(self.candidates, self.candidate_vectors)
        ]
        return sorted(ranked, key=lambda item: (-item.score, item.evidence_id))


def reciprocal_rank_fusion(
    rankings: list[list[RankedEvidence]],
    *,
    rank_constant: int = 60,
) -> list[RankedEvidence]:
    if not rankings:
        raise ValueError("RRF requires at least one ranking")
    if rank_constant <= 0:
        raise ValueError("RRF rank constant must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item.evidence_id] = scores.get(item.evidence_id, 0.0) + 1 / (
                rank_constant + rank
            )
    return sorted(
        (RankedEvidence(evidence_id, score) for evidence_id, score in scores.items()),
        key=lambda item: (-item.score, item.evidence_id),
    )
