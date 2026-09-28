from fintrace_eval.program import (
    execute_program,
    execution_matches,
    parse_program,
    program_tokens,
    programs_equivalent,
)


TABLE = (
    ("", "2019", "2020"),
    ("revenue", "$100", "$120"),
    ("margin", "10%", "20%"),
)


def test_program_parser_and_official_token_layout():
    program = "subtract(120, 100), divide(#0, 100)"
    assert len(parse_program(program)) == 2
    assert program_tokens(program) == [
        "subtract(",
        "120",
        "100",
        ")",
        "divide(",
        "#0",
        "100",
        ")",
        "EOF",
    ]


def test_execute_program_supports_step_references_and_constants():
    valid, result = execute_program("subtract(120, 100), divide(#0, const_100)", TABLE)
    assert valid is True
    assert result == 0.2
    assert execution_matches(result, 0.2)


def test_execute_table_aggregation():
    assert execute_program("table_average(revenue, none)", TABLE) == (True, 110.0)


def test_invalid_program_is_not_executed():
    assert execute_program("divide(1, 0)", TABLE) == (False, "n/a")
    assert execute_program("unknown(1, 2)", TABLE) == (False, "n/a")


def test_program_equivalence_is_symbolic_but_rejects_new_operands():
    assert programs_equivalent("add(1, 2)", "add(2, 1)")
    assert (
        programs_equivalent(
            "add(1, 2), multiply(#0, 3)",
            "multiply(add_placeholder, 3)",
        )
        is False
    )
    assert programs_equivalent("add(1, 2)", "add(1, 3)") is False
