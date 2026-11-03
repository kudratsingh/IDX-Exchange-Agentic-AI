"""WO-020 measurement set: case shape, SQL-truth goldens, oracle runs, three scores.

Cases live in evals/cases/measurement.yaml (check `measurement`). Their answer facts
are computed by `evals.truth.sql` over the committed synthetic fixture, never by the
tools under test: `python -m evals.measurement --write-goldens` fills them, and both
`tests/test_measurement.py` (SQLite copy of the fixture) and the ci suite (the MySQL
fixture) fail when a golden and the truth disagree. Scores stay separate: tool choice,
arguments and answer, per split and family, never one number.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from evals.truth.sql import FACT_KINDS, Truth
from idx_agent.domain.models import (
    Clarification,
    MarketStatsRequest,
    PropertySearchFilters,
)

__all__ = [
    "CHECK",
    "Truth",
    "SET_VERSION",
    "case_problem",
    "expected_facts",
    "fact_matches",
    "fixture_sqlite",
    "golden_problems",
    "score_transcript",
    "split_hash",
    "summary",
]

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases" / "measurement.yaml"
CHECK = "measurement"
CATEGORY = "measurement"
SET_VERSION = 1
SPLITS = ("dev", "heldout")
FAMILIES = {"search": "search_listings", "market": "get_market_stats"}
PARSERS = {
    "search_listings": PropertySearchFilters.from_input,
    "get_market_stats": MarketStatsRequest.from_input,
}
REQUIRED = (
    "id",
    "category",
    "suite",
    "check",
    "split",
    "family",
    "database",
    "input",
    "expect",
)
# Arguments that never change a fact: how many rows or which page is shown, extras.
PRESENTATION = {
    "search_listings": frozenset({"page", "limit"}),
    "get_market_stats": frozenset({"include_extended"}),
}
FAMILY_FACTS = {
    "search": frozenset({"total_matches"}),
    "market": FACT_KINDS - {"total_matches"},
}
# Tolerance per fact kind (absolute): counts and whole-dollar medians exact; median DOM
# exact to the half day it may end in; the ratio to its third decimal.
TOLERANCE = {
    "total_matches": 0,
    "sample_count": 0,
    "median_close_price": 0,
    "median_price_per_sqft": 0,
    "median_dom": 0,
    "sale_to_list_ratio": 0.0005,
}
_ID = re.compile(r"^meas-[0-9]{3}$")


# --- case shape ---


def case_problem(entry: Mapping[str, Any]) -> str | None:
    """Why a measurement case is malformed, or None."""
    missing = [k for k in REQUIRED if k not in entry]
    if missing:
        return f"missing keys {missing}"
    unknown = sorted(set(entry) - set(REQUIRED) - {"note"})
    if unknown:
        return f"unknown keys {unknown}"
    if not isinstance(entry["id"], str) or not _ID.match(entry["id"]):
        return "id must look like meas-001"
    if entry["category"] != CATEGORY or entry["suite"] != "ci":
        return "a measurement case is category measurement, suite ci"
    if entry["split"] not in SPLITS or entry["family"] not in FAMILIES:
        return "split must be dev or heldout and family search or market"
    if entry["database"] != "fixture":
        return "measurement facts hold only for the fixture"
    if not isinstance(entry["input"], str) or not entry["input"].strip():
        return "input must be the question in words"
    expect = entry["expect"]
    if not isinstance(expect, dict) or set(expect) != {"route", "args", "facts"}:
        return "expect needs exactly route, args and facts"
    tool = FAMILIES[entry["family"]]
    if expect["route"] != [tool]:
        return f"route must be [{tool}] for family {entry['family']}"
    if not isinstance(expect["args"], dict) or isinstance(
        PARSERS[tool](expect["args"]), Clarification
    ):
        return "args must validate with the tool's own validator"
    facts = expect["facts"]
    if not isinstance(facts, dict) or not facts:
        return "facts must name at least one fact"
    if set(facts) - FAMILY_FACTS[entry["family"]]:
        return (
            f"facts for {entry['family']} are {sorted(FAMILY_FACTS[entry['family']])}"
        )
    return None


def load_entries(path: Path = CASES) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("measurement.yaml must be a list of cases")
    return data


# --- truth ---


def expected_facts(
    truth: Truth, family: str, args: Mapping[str, Any]
) -> dict[str, Any]:
    """Every fact the family reports, from the truth SQL alone."""
    if family == "search":
        filters = {k: v for k, v in args.items() if k not in ("page", "limit")}
        return {"total_matches": truth.total_matches(filters)}
    place = {k: args[k] for k in ("city", "postal_code") if k in args}
    return truth.market(place, args.get("property_subtype"), args.get("months", 6))


def fact_matches(kind: str, expected: Any, got: Any) -> bool:
    """Equal within the kind's tolerance; None matches only None."""
    if expected is None or got is None:
        return expected is None and got is None
    return abs(float(expected) - float(got)) <= TOLERANCE[kind]


def golden_problems(entries: Sequence[Mapping[str, Any]], truth: Truth) -> list[str]:
    """`case id: fact` for every golden the truth SQL disagrees with (no values)."""
    problems = []
    for entry in entries:
        expect = entry["expect"]
        truth_facts = expected_facts(truth, entry["family"], expect["args"])
        for kind, golden in expect["facts"].items():
            if not fact_matches(kind, golden, truth_facts[kind]):
                problems.append(f"{entry['id']}: {kind}")
    return problems


# --- the committed fixture as SQLite (goldens without a server) ---


def fixture_sqlite() -> sqlite3.Connection:
    """The rows tests/fixtures/make_synthetic.py writes, in an in-memory SQLite
    database, generated date columns derived as the fixture's DDL defines them."""
    from tests.fixtures import make_synthetic as fixture

    tables = fixture.parse_columns(fixture.NOTES.read_text(encoding="utf-8"))
    db = sqlite3.connect(":memory:")
    make = fixture.Maker()
    groups = {
        "rets_property": fixture.active_groups(make),
        "california_sold": fixture.sold_groups(make),
    }
    for table, columns in tables.items():
        if table not in groups:
            continue
        names = [name for name, _ in columns]
        db.execute(f"CREATE TABLE {table} ({', '.join(names)})")
        marks = ", ".join("?" * len(names))
        for number, row in enumerate((r for _, rows in groups[table] for r in rows), 1):
            values = dict.fromkeys(names)
            values.update({k: _sqlite_value(v) for k, v in row.items()})
            if "id" in values and table == "rets_property":
                values["id"] = number
            for (owner, name), source in fixture.GENERATED.items():
                if owner == table:
                    values[name] = _date_text(values.get(source))
            db.execute(
                f"INSERT INTO {table} VALUES ({marks})", [values[n] for n in names]
            )
    return db


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _date_text(value: Any) -> str | None:
    """LEFT(text, 10) when it is a real YYYY-MM-DD date, else NULL (the DDL's rule)."""
    if value is None:
        return None
    head = str(value)[:10]
    try:
        return date.fromisoformat(head).isoformat() if len(head) == 10 else None
    except ValueError:
        return None


# --- scores ---


def envelope_facts(family: str, envelope: Any) -> dict[str, Any]:
    """The facts a tool's envelope reports (data attributes), or {} without data."""
    data = getattr(envelope, "data", None)
    if data is None or isinstance(data, Clarification):
        return {}
    return {kind: getattr(data, kind, None) for kind in FAMILY_FACTS[family]}


def _args_match(tool: str, expected: Mapping[str, Any], got: Mapping[str, Any]) -> bool:
    """Both validated through the tool's own validator, then equal on every field that
    changes the answer (defaults included); page size and extras are presentation."""
    want, have = PARSERS[tool](expected), PARSERS[tool](got)
    if isinstance(want, Clarification) or isinstance(have, Clarification):
        return False
    ignored = PRESENTATION[tool]
    left = {k: v for k, v in want.model_dump().items() if k not in ignored}
    right = {k: v for k, v in have.model_dump().items() if k not in ignored}
    return left == right


def answer_matches(
    family: str, facts: Mapping[str, Any], envelope: Any
) -> tuple[bool, list[str]]:
    got = envelope_facts(family, envelope)
    wrong = [k for k, v in facts.items() if not fact_matches(k, v, got.get(k))]
    return not wrong, wrong


def score_transcript(
    entry: Mapping[str, Any], calls: Sequence[tuple[str, Mapping[str, Any], Any]]
) -> dict[str, int]:
    """Three scores for one case from (tool, arguments, envelope) calls in order.

    Route: the tools called equal expect.route exactly. A wrong route scores zero on
    arguments and answer. Arguments: the expected fields agree after validation.
    Answer: every expected fact is in the last call's envelope within tolerance.
    """
    expect = entry["expect"]
    route = [tool for tool, _, _ in calls] == list(expect["route"])
    if not route:
        return {"route": 0, "args": 0, "answer": 0}
    tool, args, envelope = calls[-1]
    ok_args = _args_match(tool, expect["args"], args)
    ok_answer, _ = answer_matches(entry["family"], expect["facts"], envelope)
    return {"route": 1, "args": int(ok_args), "answer": int(ok_answer)}


def split_hash(entries: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 over the sorted (case id, split) pairs."""
    pairs = sorted((str(e["id"]), str(e["split"])) for e in entries)
    return hashlib.sha256(json.dumps(pairs).encode("utf-8")).hexdigest()


def summary(records: Sequence[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    """Per split and family: cases scored and each score's total, kept apart."""
    table: dict[str, dict[str, dict[str, int]]] = {}
    for record in records:
        scores = record.get("scores")
        if scores is None:
            continue
        cell = table.setdefault(record["split"], {}).setdefault(
            record["family"], {"cases": 0, "route": 0, "args": 0, "answer": 0}
        )
        cell["cases"] += 1
        for name in ("route", "args", "answer"):
            cell[name] += scores[name]
    return {"set_version": SET_VERSION, "mode": mode, "scores": table}


# --- goldens ---


def write_goldens(path: Path = CASES) -> int:
    """Recompute every case's facts from the committed fixture and rewrite the file."""
    entries = load_entries(path)
    truth = Truth(fixture_sqlite(), mark="?")
    for entry in entries:
        expect = entry["expect"]
        facts = expected_facts(truth, entry["family"], expect["args"])
        expect["facts"] = {k: facts[k] for k in expect["facts"]}
    header = path.read_text(encoding="utf-8").split("\n- id:", 1)[0].rstrip() + "\n"
    body = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=88)
    path.write_text(header + body, encoding="utf-8")
    return len(entries)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write-goldens", action="store_true")
    args = parser.parse_args(argv)
    if args.write_goldens:
        print(f"wrote facts for {write_goldens()} cases")
        return 0
    entries = load_entries()
    problems = golden_problems(entries, Truth(fixture_sqlite(), mark="?"))
    print(f"{len(entries)} cases, split {split_hash(entries)[:12]}")
    for problem in problems:
        print(f"golden differs: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
