"""Official-compatible FinQA program parsing, execution, and equivalence scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from sympy import Symbol, simplify

SUPPORTED_OPERATIONS = frozenset(
    {
        "add",
        "subtract",
        "multiply",
        "divide",
        "exp",
        "greater",
        "table_max",
        "table_min",
        "table_sum",
        "table_average",
    }
)
_STEP = re.compile(r"\s*([a-z_]+)\((.*?),\s*(.*?)\)\s*(?:,\s*|$)")
Number: TypeAlias = float
ExecutionResult: TypeAlias = float | str


@dataclass(frozen=True)
class ProgramStep:
    operation: str
    left: str
    right: str

    def render(self) -> str:
        return f"{self.operation}({self.left}, {self.right})"


def parse_program(program: str) -> tuple[ProgramStep, ...]:
    """Parse the sequential DSL used by FinQA and reject trailing or malformed text."""
    normalized = program.strip()
    if normalized.endswith("EOF"):
        normalized = normalized[:-3].rstrip(" ,")
    if not normalized:
        raise ValueError("program is empty")

    steps: list[ProgramStep] = []
    position = 0
    while position < len(normalized):
        match = _STEP.match(normalized, position)
        if match is None:
            raise ValueError(
                f"invalid program near: {normalized[position : position + 40]}"
            )
        operation, left, right = (part.strip() for part in match.groups())
        if operation not in SUPPORTED_OPERATIONS:
            raise ValueError(f"unsupported operation: {operation}")
        if not left or not right:
            raise ValueError("program operands cannot be empty")
        steps.append(ProgramStep(operation, left, right))
        position = match.end()
    return tuple(steps)


def program_tokens(program: str) -> list[str]:
    """Return the token layout expected by the official FinQA evaluator."""
    tokens: list[str] = []
    for step in parse_program(program):
        tokens.extend([f"{step.operation}(", step.left, step.right, ")"])
    tokens.append("EOF")
    return tokens


def _number(value: str) -> Number:
    text = value.replace(",", "")
    try:
        return float(text)
    except ValueError:
        if "%" in text:
            return float(text.replace("%", "")) / 100.0
        if "const" in text:
            constant = text.replace("const_", "")
            return float("-1" if constant == "m1" else constant)
        raise ValueError(f"not a FinQA number: {value}") from None


def _table_numbers(cells: tuple[str, ...]) -> list[float]:
    numbers: list[float] = []
    for cell in cells:
        cleaned = cell.replace("$", "").strip().split("(")[0].strip()
        numbers.append(_number(cleaned))
    return numbers


def execute_program(
    program: str, table: tuple[tuple[str, ...], ...]
) -> tuple[bool, ExecutionResult]:
    """Execute a FinQA program, returning ``(valid, result)``."""
    try:
        steps = parse_program(program)
        results: dict[int, ExecutionResult] = {}
        rows = {row[0]: row[1:] for row in table}

        def operand(value: str, current_step: int) -> ExecutionResult:
            if value.startswith("#"):
                reference = int(value[1:])
                if reference >= current_step:
                    raise ValueError("program references a future step")
                return results[reference]
            return _number(value)

        for index, step in enumerate(steps):
            if step.operation.startswith("table_"):
                if step.left not in rows:
                    raise ValueError(f"unknown table row: {step.left}")
                values = _table_numbers(rows[step.left])
                if step.operation == "table_max":
                    result: ExecutionResult = max(values)
                elif step.operation == "table_min":
                    result = min(values)
                elif step.operation == "table_sum":
                    result = sum(values)
                else:
                    result = sum(values) / len(values)
            else:
                left = operand(step.left, index)
                right = operand(step.right, index)
                if not isinstance(left, float) or not isinstance(right, float):
                    raise ValueError("boolean result used as a numeric operand")
                if step.operation == "add":
                    result = left + right
                elif step.operation == "subtract":
                    result = left - right
                elif step.operation == "multiply":
                    result = left * right
                elif step.operation == "divide":
                    result = left / right
                elif step.operation == "exp":
                    result = left**right
                else:
                    result = "yes" if left > right else "no"
            results[index] = result

        final = results[len(steps) - 1]
        if isinstance(final, float):
            final = round(final, 5)
        return True, final
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False, "n/a"


def _symbolic_expression(
    steps: tuple[ProgramStep, ...], symbols: dict[str, Symbol], *, require_known: bool
):
    expressions: dict[int, object] = {}

    def leaf(value: str, current_step: int):
        if value.startswith("#"):
            reference = int(value[1:])
            if reference >= current_step:
                raise ValueError("program references a future step")
            return expressions[reference]
        if require_known and value not in symbols:
            raise ValueError(
                "prediction introduced an operand absent from the gold program"
            )
        return symbols.setdefault(value, Symbol(f"a{len(symbols)}"))

    for index, step in enumerate(steps):
        if step.operation.startswith("table_"):
            key = step.render()
            if require_known and key not in symbols:
                raise ValueError(
                    "prediction introduced a table operation absent from gold"
                )
            expressions[index] = symbols.setdefault(key, Symbol(f"a{len(symbols)}"))
            continue
        left = leaf(step.left, index)
        right = leaf(step.right, index)
        if step.operation == "add":
            expression = left + right
        elif step.operation == "subtract":
            expression = left - right
        elif step.operation == "multiply":
            expression = left * right
        elif step.operation == "divide":
            expression = left / right
        elif step.operation == "exp":
            expression = left**right
        elif step.operation == "greater":
            expression = left > right
        else:
            raise ValueError(f"unsupported symbolic operation: {step.operation}")
        expressions[index] = expression
    return simplify(expressions[len(steps) - 1], evaluate=False)


def programs_equivalent(gold_program: str, predicted_program: str) -> bool:
    """Match FinQA's symbolic program accuracy semantics."""
    try:
        gold_steps = parse_program(gold_program)
        predicted_steps = parse_program(predicted_program)
        symbols: dict[str, Symbol] = {}
        gold_expression = _symbolic_expression(gold_steps, symbols, require_known=False)
        predicted_expression = _symbolic_expression(
            predicted_steps, symbols, require_known=True
        )
        return bool(gold_expression == predicted_expression)
    except (IndexError, KeyError, TypeError, ValueError):
        return False


def execution_matches(predicted: ExecutionResult, gold: float | str | None) -> bool:
    if gold is None:
        return False
    if isinstance(predicted, float) and isinstance(gold, (float, int)):
        return predicted == round(float(gold), 5)
    return predicted == gold
