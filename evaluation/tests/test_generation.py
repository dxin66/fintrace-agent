import pytest

from fintrace_eval.dataset import EvidenceCandidate, FinQAExample
from fintrace_eval.generation import _extract_prediction, build_user_prompt


def test_build_prompt_preserves_evidence_ids():
    example = FinQAExample(
        example_id="x",
        question="what changed?",
        table=(("", "2024"),),
        candidates=(),
        gold_evidence_ids=frozenset(),
        gold_program=None,
        gold_answer=None,
        gold_execution_answer=None,
    )
    prompt = build_user_prompt(
        example, [EvidenceCandidate("table_1", "revenue is 100", "table")]
    )
    assert "[table_1] revenue is 100" in prompt


def test_extract_prediction_requires_json_contract():
    assert _extract_prediction(
        '```json\n{"program":"add(1, 2)","citations":["text_1","text_1"]}\n```'
    ) == ("add(1, 2)", ("text_1",))
    with pytest.raises(ValueError):
        _extract_prediction("add(1, 2)")
