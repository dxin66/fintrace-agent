from fintrace_eval.dataset import EvidenceCandidate
from fintrace_eval.retrieval import (
    BM25Retriever,
    DenseRetriever,
    RankedEvidence,
    reciprocal_rank_fusion,
    tokenize,
)


class FakeEmbedder:
    vectors = {
        "operating expense was 80": [1.0, 0.0],
        "revenue in 2025 was 100": [0.0, 1.0],
        "what was 2025 revenue?": [0.0, 0.9],
    }

    def embed_many(self, texts):
        return [self.vectors[text] for text in texts]


def test_tokenize_normalizes_commas_in_numbers():
    assert tokenize("Revenue was $2,457.5") == ["revenue", "was", "2457.5"]


def test_bm25_ranks_matching_evidence_first():
    candidates = (
        EvidenceCandidate("text_0", "operating expense was 80", "text"),
        EvidenceCandidate("table_1", "revenue in 2025 was 100", "table"),
    )
    ranking = BM25Retriever(candidates).rank("what was 2025 revenue?")
    assert ranking[0].evidence_id == "table_1"


def test_dense_ranks_by_cosine_similarity():
    candidates = (
        EvidenceCandidate("text_0", "operating expense was 80", "text"),
        EvidenceCandidate("table_1", "revenue in 2025 was 100", "table"),
    )
    ranking = DenseRetriever(candidates, FakeEmbedder()).rank("what was 2025 revenue?")
    assert ranking[0].evidence_id == "table_1"


def test_rrf_rewards_agreement_and_has_stable_ties():
    first = [RankedEvidence("a", 10), RankedEvidence("b", 9), RankedEvidence("c", 8)]
    second = [RankedEvidence("b", 10), RankedEvidence("c", 9), RankedEvidence("a", 8)]
    assert reciprocal_rank_fusion([first, second])[0].evidence_id == "b"
