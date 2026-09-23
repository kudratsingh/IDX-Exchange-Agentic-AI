"""The allowlist, deny-list, and agent-contact set keep sensitive fields out."""

import pathlib
import re

import pytest

from idx_agent.domain import valid_values
from idx_agent.safety import columns

NOTES = (
    pathlib.Path(__file__).resolve().parents[1] / "docs" / "data" / "schema_notes.md"
)


def test_allowlist_and_denylist_are_disjoint():
    assert not columns.ALL_ALLOWED & columns.DENYLIST


def test_no_agent_contact_field_is_allowlisted():
    assert not columns.ALL_ALLOWED & columns.AGENT_CONTACT
    for name in columns.ALL_ALLOWED:
        assert not re.search(r"Agent.*(Email|Phone|Name)|^LA[0-9]_", name), name


def test_denylist_covers_every_candidate_from_the_safety_invariants():
    candidates = {
        "AccessCode",
        "LockBoxSerialNumber",
        "LockBoxLocation",
        "PrivateRemarks",
        "PrivateOfficeRemarks",
        "ShowingInstructions",
        "OwnerName",
        "OwnerPhone",
        "OccupantName",
        "OccupantPhone",
    }
    assert candidates <= columns.DENYLIST


def test_check_column_enforces_the_lists():
    assert columns.check_column("california_sold", "ClosePrice") == "ClosePrice"
    with pytest.raises(ValueError, match="deny-listed"):
        columns.check_column("rets_property", "PrivateRemarks")
    with pytest.raises(ValueError, match="agent contact"):
        columns.check_column("rets_property", "ListAgentEmail")
    with pytest.raises(ValueError, match="not allowlisted"):
        columns.check_column("rets_property", "SomeOtherColumn")
    with pytest.raises(ValueError, match="unknown table"):
        columns.check_column("users", "id")


@pytest.mark.skipif(
    not NOTES.exists(),
    reason="docs/data/schema_notes.md arrives with the profiling run",
)
def test_every_allowlisted_column_exists_in_the_schema_notes():
    text = NOTES.read_text(encoding="utf-8")
    missing = sorted(
        c
        for c in columns.ALL_ALLOWED
        if f"| {c} |" not in text and f"`{c}`" not in text
    )
    assert not missing, f"allowlisted but not in schema_notes.md: {missing}"


def test_flags_and_city_normalization():
    assert valid_values.parse_flag("Y") is True
    assert valid_values.parse_flag("no") is False
    assert valid_values.parse_flag("") is None
    assert valid_values.normalize_city("  san  JOSE ") == "San Jose"
