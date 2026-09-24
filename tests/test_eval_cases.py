"""Shape and expected-outcome checks for evals/cases/property_search.yaml (WO-004).

Temporary until the WO-005 runner. No model call: this proves the case file parses,
every case is well formed, every expected filter object is one the validator accepts
as written, every expected clarification uses a documented reason code, and the `ci`
cases (raw filter mapping in, validator outcome out) pass.

PyYAML is not a direct dependency; it comes with the `dev` extra through pre-commit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from idx_agent.domain.models import Clarification, PropertySearchFilters

CASES_FILE = (
    Path(__file__).resolve().parents[1] / "evals" / "cases" / "property_search.yaml"
)

REQUIRED_KEYS = {"id", "category", "suite", "expect", "check"}
SUITES = {"ci", "local", "manual"}
# docs/EVALUATION.md check types, plus `clarification` (proposed in evals/README.md).
CHECKS = {
    "filters_exact",
    "filters_subset",
    "rowcount_max",
    "fields_absent",
    "refusal",
    "regex",
    "human",
    "clarification",
}
FILTER_CHECKS = {"filters_exact", "filters_subset"}
# Clarification reason codes documented in docs/CONTRACTS.md.
REASONS = {
    "missing_location",
    "unknown_city",
    "unknown_subtype",
    "min_above_max",
    "not_half_step",
    "below_minimum",
    "above_maximum",
    "invalid_format",
    "unsupported_filter",
    "invalid_value",
}


def _load_cases() -> list[dict[str, Any]]:
    """Read the case file; it must be a YAML list of mappings."""
    data = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, list), "the case file must be a list of cases"
    assert all(isinstance(case, dict) for case in data), "every case is a mapping"
    return data


CASES = _load_cases()
FILTER_CASES = [c for c in CASES if "filters" in c.get("expect", {})]
CLARIFY_CASES = [c for c in CASES if "clarification" in c.get("expect", {})]
CI_CASES = [c for c in CASES if c.get("suite") == "ci"]


def _ids(cases: list[dict[str, Any]]) -> list[str]:
    """Case ids for pytest parametrization labels."""
    return [str(c.get("id")) for c in cases]


def _outcome_matches(
    result: PropertySearchFilters | Clarification, case: dict[str, Any]
) -> None:
    """Assert a from_input result matches the case's `expect` under its `check`."""
    expect = case["expect"]
    if "clarification" in expect:
        assert isinstance(result, Clarification), f"{case['id']}: expected a question"
        assert result.field == expect["clarification"]["field"]
        assert result.reason == expect["clarification"]["reason"]
        return
    assert isinstance(result, PropertySearchFilters), (
        f"{case['id']}: expected filters, got a Clarification ({result.reason})"
    )
    if "max_rows" in expect:
        # The row count needs the fixture database; here the filters must only validate.
        return
    actual = result.model_dump(exclude_defaults=True)
    wanted = expect["filters"]
    if case["check"] == "filters_exact":
        assert actual == wanted
    else:
        assert {k: actual.get(k) for k in wanted} == wanted


def test_case_file_has_the_ten_local_parser_queries() -> None:
    local = [c for c in CASES if c.get("suite") == "local"]
    assert len(local) == 10
    assert len(CI_CASES) >= 10, "at least ten ci cases run without a model"


def test_case_ids_are_unique_and_prefixed() -> None:
    ids = _ids(CASES)
    assert len(ids) == len(set(ids))
    assert all(i.startswith("search-") for i in ids)


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_case_shape(case: dict[str, Any]) -> None:
    missing = REQUIRED_KEYS - case.keys()
    assert not missing, f"missing keys {sorted(missing)}"
    assert case["category"] == "property_search"
    assert case["suite"] in SUITES
    assert case["check"] in CHECKS
    expect = case["expect"]
    assert isinstance(expect, dict) and len(expect) == 1
    assert next(iter(expect)) in {"filters", "clarification", "max_rows"}
    if "filters" in expect:
        assert case["check"] in FILTER_CHECKS
        assert isinstance(expect["filters"], dict) and expect["filters"]
    elif "max_rows" in expect:
        assert case["check"] == "rowcount_max"
        assert type(expect["max_rows"]) is int and 1 <= expect["max_rows"] <= 50
    else:
        assert case["check"] == "clarification"
        assert set(expect["clarification"]) == {"field", "reason"}
    if case["suite"] == "local":
        assert isinstance(case.get("input"), str) and case["input"].strip()
        assert "input_filters" not in case
    if case["suite"] == "ci":
        assert isinstance(case.get("input_filters"), dict)


@pytest.mark.parametrize("case", FILTER_CASES, ids=_ids(FILTER_CASES))
def test_expected_filters_pass_the_validator_unchanged(case: dict[str, Any]) -> None:
    wanted = case["expect"]["filters"]
    result = PropertySearchFilters.from_input(wanted)
    assert isinstance(result, PropertySearchFilters), (
        f"expected filters are refused ({getattr(result, 'reason', '')})"
    )
    # Stored city spelling, ints, and half-step floats survive validation as written.
    assert result.model_dump(exclude_defaults=True) == wanted


@pytest.mark.parametrize("case", CLARIFY_CASES, ids=_ids(CLARIFY_CASES))
def test_expected_clarification_uses_a_documented_reason(case: dict[str, Any]) -> None:
    clarification = case["expect"]["clarification"]
    assert clarification["reason"] in REASONS
    # An unsupported key is named as given; every other question names a real field.
    if clarification["reason"] != "unsupported_filter":
        assert clarification["field"] in PropertySearchFilters.model_fields


@pytest.mark.parametrize("case", CI_CASES, ids=_ids(CI_CASES))
def test_ci_case_outcome(case: dict[str, Any]) -> None:
    _outcome_matches(PropertySearchFilters.from_input(case["input_filters"]), case)
