"""WO-020/WO-028 measurement sets: case shape, SQL-truth goldens, oracle runs, and
four separate scores.

Set version 1 lives in evals/cases/measurement.yaml and set version 2 (WO-028) in
evals/cases/measurement_v2.yaml (both check `measurement`). Their answer facts are
computed by `evals.truth.sql` over the committed synthetic fixture, never by the tools
under test: `python -m evals.measurement --write-goldens` fills them, and both
`tests/test_measurement*.py` (SQLite copy of the fixture) and the ci suite (the MySQL
fixture) fail when a golden and the truth disagree. Scores stay separate: tool choice,
arguments, tool-result facts, and (only on a supplied transcript with a final text)
whether every figure in the final answer is supported, per set, split and family,
never one number. Envelope facts do not prove a model's final prose is correct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from evals.truth.sql import (
    ANALYTICS_KINDS,
    CARD_KINDS,
    COMP_KINDS,
    FACT_KINDS,
    Truth,
)
from idx_agent.domain.models import (
    Clarification,
    MarketStatsRequest,
    PropertySearchFilters,
    RecommendRequest,
)
from idx_agent.email.verify import _numbers as reply_numbers

__all__ = [
    "CHECK",
    "SETS",
    "SET_VERSION",
    "Truth",
    "answer_support",
    "case_problem",
    "expected_facts",
    "fact_matches",
    "fixture_sqlite",
    "golden_problems",
    "score_conversation",
    "score_transcript",
    "split_hash",
    "summary",
]

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases" / "measurement.yaml"
CASES_V2 = ROOT / "evals" / "cases" / "measurement_v2.yaml"
TRANSCRIPTS = ROOT / "evals" / "transcripts" / "measurement_synthetic.yaml"
CHECK = "measurement"
CATEGORY = "measurement"
SET_VERSION = 1  # the WO-020 set; its file and split hash never change
SPLITS = ("dev", "heldout")
FAMILIES = {
    "search": "search_listings",
    "market": "get_market_stats",
    "comps": "recommend",
}
TOOL_FAMILY = {tool: family for family, tool in FAMILIES.items()}
PARSERS = {
    "search_listings": PropertySearchFilters.from_input,
    "get_market_stats": MarketStatsRequest.from_input,
    "recommend": RecommendRequest.from_input,
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
# Arguments that never change a fact: how many rows or which page is shown, extras,
# and how many similar homes come with a price check. `include_extended` counts only
# when a case asks for an extended figure (then it changes the answer).
PRESENTATION = {
    "search_listings": frozenset({"page", "limit"}),
    "get_market_stats": frozenset({"include_extended"}),
    "recommend": frozenset({"k", "sender_id"}),
}
FAMILY_FACTS = {
    "search": frozenset({"total_matches"}),
    "market": FACT_KINDS - {"total_matches"},
}
# Set version 2 adds the card readings, the trend, the extended figures and comps.
FAMILY_FACTS_V2 = {
    "search": FAMILY_FACTS["search"],
    "market": FAMILY_FACTS["market"] | CARD_KINDS | ANALYTICS_KINDS,
    "comps": COMP_KINDS,
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
# Set version 2: labels and counts exact; the two-decimal means and one-decimal
# changes exact after rounding, compared to a millionth (float representation only).
TOLERANCE_V2 = {
    **TOLERANCE,
    **dict.fromkeys(CARD_KINDS | COMP_KINDS, 0),
    **dict.fromkeys(ANALYTICS_KINDS, 0.000001),
}


class MeasurementSet:
    """One versioned case set: its file, category, id pattern, families and facts."""

    def __init__(
        self,
        version: int,
        path: Path,
        category: str,
        id_pattern: str,
        family_facts: Mapping[str, frozenset[str]],
    ) -> None:
        self.version = version
        self.path = path
        self.category = category
        self.id = re.compile(id_pattern)
        self.family_facts = dict(family_facts)


SETS = {
    1: MeasurementSet(1, CASES, CATEGORY, r"^meas-[0-9]{3}$", FAMILY_FACTS),
    2: MeasurementSet(
        2, CASES_V2, "measurement_v2", r"^meas2-[0-9]{3}$", FAMILY_FACTS_V2
    ),
}


# --- case shape ---


def set_of(entry: Mapping[str, Any]) -> int:
    """The case's set version: absent in version 1 (its file never changes)."""
    return entry.get("set_version", SET_VERSION)


def case_problem(entry: Mapping[str, Any]) -> str | None:
    """Why a measurement case is malformed, or None."""
    missing = [k for k in REQUIRED if k not in entry]
    if missing:
        return f"missing keys {missing}"
    version = set_of(entry)
    if version not in SETS or ("set_version" in entry) != (version != SET_VERSION):
        return "set_version is 2 or later, and absent in set version 1"
    spec = SETS[version]
    unknown = sorted(set(entry) - set(REQUIRED) - {"note", "set_version"})
    if unknown:
        return f"unknown keys {unknown}"
    if not isinstance(entry["id"], str) or not spec.id.match(entry["id"]):
        return f"id must match {spec.id.pattern}"
    if entry["category"] != spec.category or entry["suite"] != "ci":
        return f"a measurement case is category {spec.category}, suite ci"
    families = spec.family_facts
    if entry["split"] not in SPLITS or entry["family"] not in families:
        return f"split must be dev or heldout and family one of {sorted(families)}"
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
    allowed = families[entry["family"]]
    if set(facts) - allowed:
        return f"facts for {entry['family']} are {sorted(allowed)}"
    if (
        set(facts) & ANALYTICS_KINDS
        and expect["args"].get("include_extended") is not True
    ):
        return "an extended figure needs include_extended: true in args"
    return None


def load_entries(path: Path = CASES) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must be a list of cases")
    return data


# --- truth ---


def expected_facts(
    truth: Truth,
    family: str,
    args: Mapping[str, Any],
    kinds: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """The family's facts from the truth SQL alone. Set version 1 (`kinds` None or
    only its own kinds) runs exactly its five-fact statements; card readings, the
    trend, extended figures and comps are computed only when asked for."""
    if family == "search":
        filters = {k: v for k, v in args.items() if k not in ("page", "limit")}
        return {"total_matches": truth.total_matches(filters)}
    if family == "comps":
        return truth.comps(int(args["listing_key"]))
    place = {k: args[k] for k in ("city", "postal_code") if args.get(k) is not None}
    subtype, months = args.get("property_subtype"), args.get("months") or 6
    wanted = set(kinds or ())
    if not wanted - FAMILY_FACTS["market"]:
        return truth.market(place, subtype, months)
    facts = truth.market_card(place, subtype, months)
    if wanted & ANALYTICS_KINDS:
        facts.update(truth.analytics(place, subtype, months))
    return facts


def fact_matches(kind: str, expected: Any, got: Any) -> bool:
    """Equal within the kind's tolerance; None matches only None. Lists and mappings
    (the trend, the monthly rows) match item by item with the same tolerance."""
    if kind in TOLERANCE:
        if expected is None or got is None:
            return expected is None and got is None
        return abs(float(expected) - float(got)) <= TOLERANCE[kind]
    return _same(expected, got, TOLERANCE_V2[kind])


def _same(expected: Any, got: Any, tolerance: float) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return abs(float(expected) - float(got)) <= tolerance
    if isinstance(expected, Mapping) and isinstance(got, Mapping):
        return set(expected) == set(got) and all(
            _same(v, got[k], tolerance) for k, v in expected.items()
        )
    if isinstance(expected, list) and isinstance(got, list):
        return len(expected) == len(got) and all(
            _same(a, b, tolerance) for a, b in zip(expected, got, strict=True)
        )
    return expected == got


def golden_problems(entries: Sequence[Mapping[str, Any]], truth: Truth) -> list[str]:
    """`case id: fact` for every golden the truth SQL disagrees with (no values)."""
    problems = []
    for entry in entries:
        expect = entry["expect"]
        truth_facts = expected_facts(
            truth, entry["family"], expect["args"], set(expect["facts"])
        )
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


# The extended monthly row fields WO-028 has truth for (its median PPSF is stopped).
MONTH_FIELDS = (
    "month",
    "sample_count",
    "partial",
    "mean_close_price",
    "mean_dom",
    "price_mom_pct",
    "price_yoy_pct",
    "ppsf_mom_pct",
    "ppsf_yoy_pct",
)
TREND_FIELDS = ("month", "sample_count", "median_close_price")


def _field(obj: Any, name: str) -> Any:
    """An attribute of a model or a key of a mapping (recorded envelopes)."""
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def envelope_facts(family: str, envelope: Any) -> dict[str, Any]:
    """The facts a tool's envelope reports, or {} without data. A recorded synthetic
    envelope (a mapping with `facts`) reports its facts as written."""
    if isinstance(envelope, Mapping) and "facts" in envelope:
        return dict(envelope["facts"] or {})
    data = _field(envelope, "data")
    if data is None or isinstance(data, Clarification):
        return {}
    if family == "comps":
        check = _field(data, "subject_check")
        return {} if check is None else _comp_facts(check)
    facts = {kind: _field(data, kind) for kind in FAMILY_FACTS[family]}
    if family == "market":
        for kind in CARD_KINDS - {"trend"}:
            facts[kind] = _field(data, kind)
        facts["trend"] = [
            {name: _field(row, name) for name in TREND_FIELDS}
            for row in _field(data, "trend") or ()
        ]
        analytics = _field(data, "analytics")
        if analytics is not None:
            for kind in ANALYTICS_KINDS - {"analytics_months"}:
                facts[kind] = _field(analytics, kind.removeprefix("analytics_"))
            facts["analytics_months"] = [
                {name: _field(row, name) for name in MONTH_FIELDS}
                for row in _field(analytics, "months") or ()
            ]
    return facts


def _comp_facts(check: Any) -> dict[str, Any]:
    """CompEvidence as comp facts; the verdict band read from its documented shape:
    no level is not checkable, under 5 comps insufficient, else the delta's sign."""
    delta = _field(check, "delta_pct")
    if _field(check, "level") is None:
        verdict = "not_checkable"
    elif not _field(check, "sufficient"):
        verdict = "insufficient"
    else:
        verdict = "above" if delta > 0 else "below" if delta < 0 else "at"
    return {
        "comp_verdict": verdict,
        "comp_level": _field(check, "level"),
        "comp_count": _field(check, "count"),
        "comp_median_ppsf": _field(check, "median_price_per_sqft"),
        "comp_range_low_ppsf": _field(check, "range_low_price_per_sqft"),
        "comp_range_high_ppsf": _field(check, "range_high_price_per_sqft"),
        "comp_delta_pct": delta,
    }


def _args_match(
    tool: str,
    expected: Mapping[str, Any],
    got: Mapping[str, Any],
    facts: Mapping[str, Any] | None = None,
) -> bool:
    """Both validated through the tool's own validator, then equal on every field that
    changes the answer (defaults included); page size and extras are presentation,
    except `include_extended` when an extended figure is expected."""
    want, have = PARSERS[tool](expected), PARSERS[tool](got)
    if isinstance(want, Clarification) or isinstance(have, Clarification):
        return False
    ignored = PRESENTATION[tool]
    if set(facts or ()) & ANALYTICS_KINDS:
        ignored = ignored - {"include_extended"}
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
    ok_args = _args_match(tool, expect["args"], args, expect["facts"])
    ok_answer, _ = answer_matches(entry["family"], expect["facts"], envelope)
    return {"route": 1, "args": int(ok_args), "answer": int(ok_answer)}


# --- the fourth score: is every figure in the final answer supported? ---


def _support_values(value: Any, out: list[Decimal]) -> None:
    """Every number a fact, an envelope or an argument holds: scalars, the numbers
    written inside text (a month, a reading, the card), lists and mappings."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float, Decimal)):
        out.append(Decimal(str(value)))
    elif isinstance(value, str):
        out.extend(number for number, _ in reply_numbers(value))
    elif isinstance(value, Mapping):
        for item in value.values():
            _support_values(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _support_values(item, out)


def _with_forms(values: list[Decimal], facts: Mapping[str, Any]) -> set[Decimal]:
    """The values, their magnitudes (prose writes "5% below", not "-5%"), and a
    ratio written as a percent (0.998 as 99.8)."""
    forms = {abs(v) for v in values}
    ratio = facts.get("sale_to_list_ratio")
    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
        forms.add(Decimal(str(ratio)) * 100)
    return forms


def _supported(stated: Decimal, values: set[Decimal]) -> bool:
    """Some value rounds to the figure at the precision it is written in."""
    exponent = stated.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    half = Decimal(1).scaleb(-places) / 2
    return any(abs(abs(stated) - value) <= half for value in values)


def answer_support(
    final: str | None,
    facts: Mapping[str, Any],
    calls: Sequence[tuple[str, Mapping[str, Any], Any]],
    question: str = "",
) -> dict[str, Any]:
    """The fourth score, only for a supplied final answer (None: not measured).

    Every figure written in `final` must match an expected fact or a value in the
    transcript's tool envelopes (their facts and message text), the call arguments or
    the user's own words, at the precision it is written in. Numbers are read with the
    existing post-check tokenizer (`idx_agent.email.verify`); units are not bound.
    `ungrounded` counts figures that only the truth supports: no tool result in the
    transcript carried them (right for the wrong reason, or a failed call overclaimed).
    This checks numeric support, not wording, completeness or reasoning."""
    if final is None:
        return {"measured": False}
    stated = [number for number, _ in reply_numbers(final)]
    truth_values: list[Decimal] = []
    _support_values(dict(facts), truth_values)
    grounded: list[Decimal] = []
    _support_values(question, grounded)
    for tool, args, envelope in calls:
        _support_values(dict(args), grounded)
        family = TOOL_FAMILY.get(tool)
        if family is not None:
            _support_values(envelope_facts(family, envelope), grounded)
        _support_values(_field(envelope, "message"), grounded)
    from_tools = _with_forms(grounded, {})
    from_truth = _with_forms(truth_values, facts)
    unsupported = [n for n in stated if not _supported(n, from_tools | from_truth)]
    ungrounded = [
        n for n in stated if not _supported(n, from_tools) and _supported(n, from_truth)
    ]
    return {
        "measured": True,
        "figures": len(stated),
        "unsupported": len(unsupported),
        "ungrounded": len(ungrounded),
        "supported": int(not unsupported),
    }


# --- recorded synthetic transcripts (no model): multi-turn and failure scenarios ---


def load_transcripts(path: Path = TRANSCRIPTS) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(
        isinstance(t, dict) and t.get("label") == "synthetic" for t in data
    ):
        raise ValueError("every recorded transcript must be labelled synthetic")
    return data


def _recorded_envelope(
    truth: Truth, tool: str, args: Mapping[str, Any], result: Any
) -> dict[str, Any]:
    """A recorded envelope: `truth` (the truth facts for the call's own arguments;
    extended figures only when the call asked for them, as the tool does),
    `{truth: true, override: {...}}` (a wrong figure), `{clarification: question}`,
    or `{ok: false, message}` (unavailable)."""
    if isinstance(result, Mapping) and "clarification" in result:
        return {"ok": True, "facts": {}, "message": str(result["clarification"])}
    if isinstance(result, Mapping) and result.get("ok") is False:
        return {"ok": False, "facts": {}, "message": str(result.get("message", ""))}
    if result == "truth" or (isinstance(result, Mapping) and result.get("truth")):
        family = TOOL_FAMILY[tool]
        kinds = set(SETS[2].family_facts[family])
        if family == "market" and not args.get("include_extended"):
            kinds -= ANALYTICS_KINDS
        facts = expected_facts(truth, family, args, kinds)
        facts = {k: v for k, v in facts.items() if k in kinds}
        if isinstance(result, Mapping):
            facts.update(result.get("override") or {})
        message = result.get("message", "") if isinstance(result, Mapping) else ""
        return {"ok": True, "facts": facts, "message": message}
    raise ValueError(f"unknown recorded result {result!r}")


class _Got:
    """`{got.kind}` in a recorded final answer: the last call's reported fact."""

    def __init__(self, facts: Mapping[str, Any]) -> None:
        self.__dict__.update(facts)


def score_conversation(
    transcript: Mapping[str, Any], truth: Truth
) -> list[dict[str, Any]]:
    """Four scores per turn of a recorded transcript. Each turn names what it expects
    (family, route, args, fact kinds); the facts come from the truth SQL, the turn's
    calls get recorded envelopes, and `final` may name expected facts in braces."""
    scored = []
    for turn in transcript["turns"]:
        expect = turn["expect"]
        facts = expected_facts(
            truth, expect["family"], expect["args"], set(expect["facts"])
        )
        wanted = {k: facts[k] for k in expect["facts"]}
        entry = {
            "family": expect["family"],
            "expect": {
                "route": expect["route"],
                "args": expect["args"],
                "facts": wanted,
            },
        }
        calls = [
            (
                call["tool"],
                dict(call["args"]),
                _recorded_envelope(truth, call["tool"], call["args"], call["result"]),
            )
            for call in turn.get("calls") or ()
        ]
        final = turn.get("final")
        if final is not None:
            got = calls[-1][2]["facts"] if calls else {}
            final = final.format(**facts, got=_Got(got))
        scores = score_transcript(entry, calls)
        support = answer_support(final, wanted, calls, turn.get("user", ""))
        scored.append({"scores": scores, "support": support})
    return scored


# --- reports ---


def split_hash(entries: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 over the sorted (case id, split) pairs."""
    pairs = sorted((str(e["id"]), str(e["split"])) for e in entries)
    return hashlib.sha256(json.dumps(pairs).encode("utf-8")).hexdigest()


def summary(
    records: Sequence[Mapping[str, Any]], mode: str, set_version: int = SET_VERSION
) -> dict[str, Any]:
    """Per split and family: cases scored and each score's total, kept apart. The
    fourth score (`answer_support`) is a separate table: it counts only records that
    carried a final answer, so an oracle run (no prose) measures none."""
    table: dict[str, dict[str, dict[str, int]]] = {}
    support: dict[str, dict[str, dict[str, int]]] = {}
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
        row = support.setdefault(record["split"], {}).setdefault(
            record["family"], {"measured": 0, "supported": 0}
        )
        checked = record.get("support") or {}
        if checked.get("measured"):
            row["measured"] += 1
            row["supported"] += checked["supported"]
    return {
        "set_version": set_version,
        "mode": mode,
        "scores": table,
        "answer_support": support,
        "answer_support_note": SUPPORT_NOTE,
    }


SUPPORT_NOTE = (
    "Tool-result facts are checked against SQL truth; that does not prove a model's "
    "final prose is correct. Answer support is measured only on transcripts that "
    "carry a final answer (synthetic recorded transcripts in CI); oracle runs have "
    "none."
)


# --- goldens ---


def write_goldens(path: Path = CASES) -> int:
    """Recompute every case's facts from the committed fixture and rewrite the file."""
    entries = load_entries(path)
    truth = Truth(fixture_sqlite(), mark="?")
    for entry in entries:
        expect = entry["expect"]
        facts = expected_facts(
            truth, entry["family"], expect["args"], set(expect["facts"])
        )
        expect["facts"] = {k: facts[k] for k in expect["facts"]}
    header = path.read_text(encoding="utf-8").split("\n- id:", 1)[0].rstrip() + "\n"
    body = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=88)
    path.write_text(header + body, encoding="utf-8")
    return len(entries)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write-goldens", action="store_true")
    parser.add_argument(
        "--set", type=int, choices=sorted(SETS), help="one set version (default: all)"
    )
    args = parser.parse_args(argv)
    chosen = [SETS[args.set]] if args.set else list(SETS.values())
    if args.write_goldens:
        for spec in chosen:
            count = write_goldens(spec.path)
            print(f"set {spec.version}: wrote facts for {count} cases")
        return 0
    truth = Truth(fixture_sqlite(), mark="?")
    failed = False
    for spec in chosen:
        entries = load_entries(spec.path)
        problems = golden_problems(entries, truth)
        print(
            f"set {spec.version}: {len(entries)} cases, "
            f"split {split_hash(entries)[:12]}"
        )
        for problem in problems:
            print(f"golden differs: {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
