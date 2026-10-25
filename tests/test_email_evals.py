"""New safety cases exercise the real runner offline, including a wrong expectation."""

from pathlib import Path

import pytest
from evals import run
from evals.email_checks import run_steps, validate_steps


def test_all_email_safety_cases_load_and_pass_without_network():
    cases, errors = run.load_cases(
        Path(__file__).resolve().parents[1] / "evals" / "cases"
    )
    assert not errors
    mine = [case for case in cases if case.id.startswith("email-safety-")]
    assert len(mine) == 18
    for case in mine:
        result, detail = run.CHECKS[case.check].run(case, case.input_filters)
        assert result == run.PASS, (case.id, detail)


def test_scenario_rejects_incorrect_success_expectation():
    passed, _ = run_steps(
        [{"do": "draft", "outcome": "pending"}, {"do": "send", "outcome": "sent"}]
    )
    assert not passed


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"do": "smtp", "outcome": "sent"}],
        [{"do": "send"}],
        [{"do": "advance_minutes", "minutes": -1, "outcome": "advanced"}],
        [{"do": "alter_field", "field": "id", "outcome": "altered"}],
    ],
)
def test_malformed_scenario_is_not_a_quiet_pass(steps):
    assert validate_steps({"steps": steps})
