import json

import pytest

from fintrace_eval.dataset import load_finqa, table_row_to_text


def test_table_row_matches_official_corrected_serialization():
    assert (
        table_row_to_text(
            ["company", "revenue", "cost"],
            ["example inc.", "100", "80"],
        )
        == "company the example inc. of revenue is 100 ; the example inc. of cost is 80 ;"
    )


def test_load_finqa_preserves_official_ids(tmp_path):
    path = tmp_path / "dev.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "report-1",
                    "pre_text": ["before"],
                    "post_text": ["after"],
                    "table": [["year", "revenue"], ["2025", "100"]],
                    "qa": {
                        "question": "revenue?",
                        "gold_inds": {"text_1": "after", "table_1": "row"},
                        "program": "add(50, 50)",
                        "answer": "100",
                        "exe_ans": 100,
                    },
                }
            ]
        )
    )
    example = load_finqa(path)[0]
    assert [candidate.evidence_id for candidate in example.candidates] == [
        "text_0",
        "text_1",
        "table_0",
        "table_1",
    ]
    assert example.gold_evidence_ids == frozenset({"text_1", "table_1"})


def test_private_split_is_rejected_when_scoring(tmp_path):
    path = tmp_path / "private_test.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "private-1",
                    "pre_text": [],
                    "post_text": [],
                    "table": [["year", "revenue"]],
                    "qa": {"question": "revenue?"},
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="cannot be scored locally"):
        load_finqa(path)
