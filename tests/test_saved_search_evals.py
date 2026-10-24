"""Saved-search CI scenarios exercise the same public bodies and gate in scratch."""

from pathlib import Path

from evals import run
from evals.saved_search_checks import run_steps, validate_steps


def test_saved_search_cases_load_and_pass_offline():
    cases, errors = run.load_cases(Path(__file__).resolve().parents[1] / "evals/cases")
    assert not errors
    mine = [case for case in cases if case.category == "saved_searches"]
    assert len(mine) == 6
    for case in mine:
        outcome, detail = run.CHECKS[case.check].run(case, case.input_filters)
        assert outcome == run.PASS, (case.id, detail)


def test_wrong_saved_search_expectation_fails():
    ok, _ = run_steps([{"do": "list", "outcome": "listed:1"}])
    assert not ok


def test_invalid_operations_fail_validation():
    assert validate_steps({"steps": []})
    assert validate_steps({"steps": [{"do": "send", "outcome": "sent"}]})
    assert validate_steps(
        {"steps": [{"do": "save", "outcome": "saved", "email": "owner"}]}
    )


def test_both_server_schemas_reach_routing_and_prefix_is_normalized():
    names = {schema["function"]["name"] for schema in run.all_tool_schemas()}
    assert run.ALERT_TOOLS <= names and len(names) == 11
    call = run._routed_call(
        {
            "function": {
                "name": "idx_alerts__save_search",
                "arguments": '{"city":"Pasadena"}',
            }
        }
    )
    assert call.name == "save_search" and call.arguments == {"city": "Pasadena"}
    invalid = run._routed_call(
        {"function": {"name": "idx__idx_alerts__save_search", "arguments": "{}"}}
    )
    assert invalid.name not in run.ROUTE_TOOLS
