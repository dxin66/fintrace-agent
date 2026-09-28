"""FinQA adapter that preserves the official evidence identifiers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_id: str
    text: str
    source_type: str


@dataclass(frozen=True)
class FinQAExample:
    example_id: str
    question: str
    table: tuple[tuple[str, ...], ...]
    candidates: tuple[EvidenceCandidate, ...]
    gold_evidence_ids: frozenset[str]
    gold_program: str | None
    gold_answer: str | None
    gold_execution_answer: float | str | None


def table_row_to_text(header: list[str], row: list[str]) -> str:
    """Serialize a table row exactly as the corrected official FinQA utility does."""
    if len(header) != len(row):
        raise ValueError("FinQA table header and row have different lengths")
    pieces = [header[0]] if header[0] else []
    for column, cell in zip(header[1:], row[1:]):
        pieces.append(f"the {row[0]} of {column} is {cell} ;")
    return " ".join(" ".join(pieces).split())


def _validate_record(record: dict[str, Any], source: Path, index: int) -> None:
    required = {"id", "pre_text", "post_text", "table", "qa"}
    missing = required.difference(record)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"{source}: record {index} is missing: {names}")
    if not record["table"]:
        raise ValueError(f"{source}: record {index} has no table")
    if "question" not in record["qa"]:
        raise ValueError(f"{source}: record {index} has no question")


def _convert_record(record: dict[str, Any], source: Path, index: int) -> FinQAExample:
    _validate_record(record, source, index)
    qa = record["qa"]
    candidates: list[EvidenceCandidate] = []
    for text_index, text in enumerate(record["pre_text"] + record["post_text"]):
        candidates.append(EvidenceCandidate(f"text_{text_index}", text, "text"))

    table = record["table"]
    header = table[0]
    for row_index, row in enumerate(table):
        candidates.append(
            EvidenceCandidate(
                f"table_{row_index}",
                table_row_to_text(header, row),
                "table",
            )
        )

    candidate_ids = {candidate.evidence_id for candidate in candidates}
    gold_ids = frozenset(qa.get("gold_inds", {}).keys())
    unknown_gold = gold_ids.difference(candidate_ids)
    if unknown_gold:
        names = ", ".join(sorted(unknown_gold))
        raise ValueError(
            f"{source}: record {index} references unknown evidence: {names}"
        )

    return FinQAExample(
        example_id=record["id"],
        question=qa["question"],
        table=tuple(tuple(str(cell) for cell in row) for row in table),
        candidates=tuple(candidates),
        gold_evidence_ids=gold_ids,
        gold_program=qa.get("program"),
        gold_answer=qa.get("answer"),
        gold_execution_answer=qa.get("exe_ans"),
    )


def load_finqa(path: str | Path, *, require_labels: bool = True) -> list[FinQAExample]:
    source = Path(path)
    records = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{source}: expected a JSON array")
    examples = [
        _convert_record(record, source, index) for index, record in enumerate(records)
    ]
    if require_labels:
        unlabeled = [
            example.example_id for example in examples if not example.gold_evidence_ids
        ]
        if unlabeled:
            raise ValueError(
                f"{source}: {len(unlabeled)} examples have no gold evidence; "
                "the private FinQA split cannot be scored locally"
            )
    return examples
