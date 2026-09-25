"""The end-to-end demo script as eval cases (WO-014), checked with no model.

`evals/cases/end_to_end.yaml` holds the 25 WhatsApp messages as `local` routing cases
and the same script as one `manual` case. These tests load it through the runner, tie
each case to a real row of docs/ROUTING.md, and pin the plan and mint line it prints.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from evals import run as runner
from tests.test_routing_contract import (
    CONTRACT,
    Row,
    _route_fits,
    expected_routes,
    parse_contract,
)

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "evals" / "cases"
CASES_FILE = CASES_DIR / "end_to_end.yaml"
README = ROOT / "evals" / "README.md"
CATEGORY = "end_to_end"
LOCAL_IDS = [f"e2e-local-{n:03d}" for n in range(1, 26)]
MANUAL_ID = "e2e-manual-001"
SCRIPT_LINE = re.compile(r"^(\d+)\. (.+)$")
KEY_LIKE = re.compile(r"\d{6,}")


@pytest.fixture(scope="module")
def entries() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)
    return loaded


@pytest.fixture(scope="module")
def rows() -> dict[str, Row]:
    return {r.intent: r for r in parse_contract(CONTRACT.read_text(encoding="utf-8"))}


def local_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e["suite"] == "local"]


def script_lines(entries: list[dict[str, Any]]) -> list[str]:
    """The manual case's numbered lines, checked to run 1, 2, 3, ... in order."""
    (manual,) = [e for e in entries if e["suite"] == "manual"]
    lines = [SCRIPT_LINE.match(line) for line in manual["input"].splitlines()]
    assert all(lines), "every script line is '<n>. <message>'"
    assert [int(m.group(1)) for m in lines] == list(range(1, len(lines) + 1))
    return [m.group(2) for m in lines]


def test_the_file_loads_through_the_runner_with_no_errors() -> None:
    cases, errors = runner.load_cases(CASES_DIR)
    assert [e for e in errors if e.source.endswith("end_to_end.yaml")] == []
    mine = [c for c in cases if c.category == CATEGORY]
    assert len(mine) == 26


def test_ids_order_suites_and_checks(entries) -> None:
    """25 local route_exact cases in script order, then the one manual case."""
    assert [e["id"] for e in entries] == [*LOCAL_IDS, MANUAL_ID]
    assert all(e["category"] == CATEGORY for e in entries)
    for e in entries[:25]:
        assert (e["suite"], e["check"]) == ("local", "route_exact"), e["id"]
    assert (entries[25]["suite"], entries[25]["check"]) == ("manual", "human")


def test_every_case_names_a_real_contract_row_and_fits_it(entries, rows) -> None:
    """Each note is exactly "row: <intent>" of a docs/ROUTING.md row, and every
    route the case accepts fits that row's Tool cell."""
    problems = []
    for e in local_entries(entries):
        note = str(e.get("note", ""))
        intent = note.removeprefix("row: ")
        row = rows.get(intent) if note.startswith("row: ") else None
        if row is None:
            problems.append(f"{e['id']}: note {note!r} names no contract row")
            continue
        for route in expected_routes(e):
            if not _route_fits(row, route):
                problems.append(f"{e['id']}: route {route} does not fit {intent!r}")
    assert problems == [], "\n".join(problems)


def test_the_local_inputs_are_the_manual_script_in_order(entries) -> None:
    inputs = [e["input"] for e in local_entries(entries)]
    assert script_lines(entries) == inputs
    assert len(inputs) == 25


def _history_numbers(entry: dict[str, Any]) -> list[str]:
    """Every 6+ digit run in a case's history text and string arguments, plus each
    listing_key argument, as text (a price argument is a number, not a key)."""
    found = []
    for turn in entry.get("history", []):
        texts = [turn["user"], turn["assistant"], turn.get("tool_result", "")]
        for call in turn.get("tool_calls", []):
            key = call["arguments"].get("listing_key")
            if key is not None:
                found.append(str(key))
            texts += [v for v in call["arguments"].values() if isinstance(v, str)]
        for text in texts:
            found += KEY_LIKE.findall(text)
    return found


def test_history_keys_are_fixture_keys_and_no_sender_id_appears(entries) -> None:
    """Invented keys only (9 then 5-6 digits); no `sender_id` anywhere in the file."""
    for e in local_entries(entries):
        for number in _history_numbers(e):
            assert runner.INVENTED_KEY.match(number), f"{e['id']}: {number}"
        for step in e["expect"].get("filters", []):
            if "listing_key" in step:
                assert runner.INVENTED_KEY.match(str(step["listing_key"])), e["id"]
    assert "sender_id" not in CASES_FILE.read_text(encoding="utf-8")


def test_the_contract_decisions_the_wo_table_predates(entries) -> None:
    """Where docs/ROUTING.md overrides the WO's draft table: paging after the search
    is `more`; after market-stats or docs-qa, and for recall, no call; the injection
    row takes routing-local-019's two options; start over is `reset`."""
    by_id = {e["id"]: e["expect"] for e in entries}
    assert by_id["e2e-local-004"] == {
        "route": ["search_listings"],
        "filters": [{"mode": "more"}],
    }
    for n in (5, 9, 11, 21, 22, 23):
        assert by_id[f"e2e-local-{n:03d}"] == {"route": []}
    assert by_id["e2e-local-024"] == {
        "route_any_of": [[], ["search_listings"]],
        "filters_any_of": [[], [{"city": "Pasadena"}]],
    }
    assert by_id["e2e-local-025"]["filters"] == [{"mode": "reset"}]


def test_the_dependent_mixed_case_uses_the_earlier_turns_second_key(entries) -> None:
    by_id = {e["id"]: e for e in entries}
    case = by_id["e2e-local-016"]
    (earlier,) = case["history"]
    assert earlier["user"] == by_id["e2e-local-015"]["input"]
    second = KEY_LIKE.findall(earlier["tool_result"])[1]
    assert case["expect"]["filters"][1] == {"listing_key": int(second), "k": 0}


def test_the_plan_is_100_chat_calls_and_no_embedding() -> None:
    cases, _ = runner.load_cases(CASES_DIR)
    chosen, errors = runner.select_cases(cases, "local", [CATEGORY])
    assert errors == [] and len(chosen) == 25
    assert runner.paid_ceiling(chosen) == (100, 0)


def test_the_readme_prints_the_end_to_end_mint_line() -> None:
    """The mint line evals/README.md shows is the one the plan prints for the 25
    end-to-end cases, typed with any python path and without --allow-paid."""
    typed = ["/x/.venv/bin/python3", "-m", "evals.run", "--suite", "local"]
    typed += ["--category", CATEGORY, "--no-temperature", "--reasoning-effort", "none"]
    line = consent.mint_command(runner.paid_argv(typed), 100)
    assert line == (
        '! scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite '
        "local --allow-paid --category end_to_end --no-temperature --reasoning-effort "
        'none" --max-calls 100'
    )
    assert line in README.read_text("utf-8")
