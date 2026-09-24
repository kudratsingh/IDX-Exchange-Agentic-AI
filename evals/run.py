"""Eval runner (WO-005): load evals/cases/*.yaml, check each case in code, report.

The ci suite calls the tool body directly: no model, no MCP transport, no network.
The local suite first asks a model to fill the tool schema; that is a paid run.
Case format and check semantics: docs/EVALUATION.md. Run: python -m evals.run --suite ci
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import yaml

from idx_agent.db import pool as db_pool
from idx_agent.domain.models import Clarification, PropertySearchFilters, SearchResult
from idx_agent.domain.results import ErrorCategory
from idx_agent.mcp_server import server as mcp_server
from idx_agent.memory.identity import secret_configured

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_DIR = ROOT / "evals" / "cases"
# The report is gitignored; it is evidence for a run, never a tracked file.
DEFAULT_OUT = ROOT / "evals" / "last_run.json"

SUITES = ("ci", "local", "manual")
# Blanked at startup unless --allow-tracing (WO-007); see main().
TRACING_ENV = ("IDX_OTLP_ENDPOINT", "IDX_LOG_FILE")
REQUIRED_KEYS = ("id", "category", "suite", "check", "expect")
ALLOWED_KEYS = frozenset(REQUIRED_KEYS) | {"note", "tool", "input", "input_filters"}
# A conversation case (`check: turns`, WO-006) has no case-level input or expect;
# each turn carries its own. Format: docs/EVALUATION.md, "Multi-turn cases".
TURNS_REQUIRED = ("id", "category", "suite", "check", "turns")
TURNS_ALLOWED = frozenset(TURNS_REQUIRED) | {"note", "tool", "sender_id"}
TURN_KEYS = frozenset(
    {"input", "input_filters", "expect", "check", "sender_id", "warning", "note"}
)
# Tool arguments about the conversation, not filters; validation checks drop them.
SESSION_ARGS = frozenset({"sender_id", "mode", "clear"})
# Cases name senders by label only, so a case file can never hold a real sender id.
SENDER_LABEL = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
DEFAULT_SENDER = "sender-a"
# The load error for a sender_id inside input_filters, in any case or turn.
SENDER_IN_FILTERS = (
    "input_filters must not hold sender_id (sender-label rule: a conversation names"
    " senders by label, e.g. sender_id: sender-a; the runner derives the id)"
)
# The fictional range every derived sender id sits in: +1 555 010 then 4 digits.
SYNTHETIC_SENDER_PREFIX = "1555010"
# A conversation case's detail when the tool module cannot empty its session store.
NO_STORE_RESET = (
    "the tool module has no reset_store_for_tests; a conversation needs an empty"
    " session store per case"
)
# The HMAC key a conversation runs under when IDX_SENDER_KEY is unset (a test value).
SENDER_KEY_ENV = "IDX_SENDER_KEY"
EVAL_SENDER_KEY = "5e7de4a1" * 8
# Tools a case may name. Only search_listings exists so far; later tools add entries.
TOOLS = frozenset({"search_listings"})

# The tool's result cap: a max_rows above it could never bind.
ROW_CAP = 50
ERROR_CATEGORIES = frozenset(get_args(ErrorCategory))

PASS, FAIL, SKIPPED, MANUAL = "pass", "fail", "skipped", "manual"
RESULTS = (PASS, FAIL, SKIPPED, MANUAL)

# The local driver: both variables and --allow-paid are required before any call.
LOCAL_ENV = ("OPENAI_API_KEY", "IDX_EVAL_MODEL")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
SYSTEM_PROMPT = (
    "You help people search active real-estate listings. Call search_listings with "
    "only the filters the user stated. If the request is not a listing search, do "
    "not call any tool."
)
PAID_NOTICE = (
    "PAID RUN: every local case with `input` sends one request to the OpenAI API. "
    "It needs a human `paid` consent token for this run (docs/AGENT_RULES.md); "
    "read the cost from the provider console afterwards."
)

NO_DATABASE_REQUIRED = (
    "no database, and one is required (--require-database or CI=true)"
)
SELECTION_SOURCES = frozenset({"--case", "--category", "selection"})

Outcome = tuple[str, str]
# Earlier turns of a local conversation: (the user's words, the tool's reply text).
History = Sequence[tuple[str, str]]


@dataclass(frozen=True)
class Turn:
    """One step of a conversation case: its input, check, and sender label."""

    check: str
    expect: Any
    input: str | None
    input_filters: Mapping[str, Any] | None
    sender_id: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class Case:
    """One validated eval case; `source` is the file it came from.

    A conversation case has `check == "turns"`, its steps in `turns`, and an
    optional case-level sender label; its `expect` and inputs are None.
    """

    id: str
    category: str
    suite: str
    check: str
    expect: Any
    tool: str
    input: str | None
    input_filters: Mapping[str, Any] | None
    source: str
    turns: tuple[Turn, ...] = ()
    sender_id: str | None = None


@dataclass(frozen=True)
class LoadError:
    """A case file or entry that could not be used; it counts as a failure."""

    source: str
    case_id: str | None
    message: str


# --- checks: each takes (case, raw filter mapping), returns (result, detail) ---


def _parsed(raw: Mapping[str, Any]) -> PropertySearchFilters | Clarification:
    """Validate the raw mapping as the tool body does, minus the session arguments."""
    return PropertySearchFilters.from_input(
        {k: v for k, v in raw.items() if k not in SESSION_ARGS}
    )


def call_tool(raw: Mapping[str, Any]) -> Any:
    """Call the tool body once. Session arguments in `raw` (sender_id, mode, clear)
    go as keywords when the body names them, else they stay in the mapping."""
    body = mcp_server.search_result
    session = {k: v for k, v in raw.items() if k in SESSION_ARGS}
    if session and "sender_id" in inspect.signature(body).parameters:
        filters = {k: v for k, v in raw.items() if k not in SESSION_ARGS}
        return body(filters, **session)
    return body(raw)


def _filters_or_fail(raw: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return the accepted filters (exclude_defaults dump), or None and why not."""
    got = _parsed(raw)
    if isinstance(got, Clarification):
        return None, f"got a Clarification ({got.field}, {got.reason})"
    return got.model_dump(exclude_defaults=True), ""


def _match_exact(expect: Mapping[str, Any], actual: dict[str, Any]) -> Outcome:
    """Pass when `actual` equals expect.filters, nothing more or less."""
    if actual == dict(expect["filters"]):
        return PASS, "filters match"
    return FAIL, f"got {actual}"


def _match_subset(expect: Mapping[str, Any], actual: dict[str, Any]) -> Outcome:
    """Pass when every key in expect.filters is in `actual` with the same value."""
    missing = object()
    wrong = {
        key: actual.get(key, missing)
        for key, value in expect["filters"].items()
        if actual.get(key, missing) != value
    }
    if not wrong:
        return PASS, "expected keys match"
    shown = {k: ("<unset>" if v is missing else v) for k, v in wrong.items()}
    return FAIL, f"differs on {shown}"


def _match_clarification(expect: Mapping[str, Any], got: Any) -> Outcome:
    """Pass when `got` is a Clarification with expect's field and reason."""
    want = expect["clarification"]
    if not isinstance(got, Clarification):
        return FAIL, "filters were accepted; no Clarification"
    actual = (got.field, got.reason)
    if actual == (want.get("field"), want.get("reason")):
        return PASS, f"{got.field}, {got.reason}"
    return FAIL, f"got {actual[0]}, {actual[1]}"


def check_filters_exact(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the accepted filters equal expect.filters, nothing more or less."""
    actual, why = _filters_or_fail(raw)
    if actual is None:
        return FAIL, why
    return _match_exact(case.expect, actual)


def check_filters_subset(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when every key in expect.filters is accepted with the same value."""
    actual, why = _filters_or_fail(raw)
    if actual is None:
        return FAIL, why
    return _match_subset(case.expect, actual)


def check_clarification(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when validation asks back with the expected field and reason code."""
    return _match_clarification(case.expect, _parsed(raw))


def _judge_rowcount(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope holds a SearchResult of at most expect.max_rows."""
    if not env.ok or not isinstance(env.data, SearchResult):
        return FAIL, f"no search result ({_kind(env)})"
    rows, cap = len(env.data.listings), expect["max_rows"]
    return (PASS if rows <= cap else FAIL), f"{rows} rows, max {cap}"


def check_rowcount_max(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when a search ran and returned at most expect.max_rows listings."""
    return _judge_rowcount(case.expect, call_tool(raw))


def _tool_envelope(raw: Mapping[str, Any]) -> tuple[Any, str | None]:
    """Call the tool body; return the envelope and, when the filters validate but
    no ok SearchResult came back, why that is a failure (else None)."""
    env = call_tool(raw)
    if isinstance(_parsed(raw), PropertySearchFilters):
        if not env.ok or not isinstance(env.data, SearchResult):
            return env, f"a search should have run, got {_kind(env)}"
    return env, None


def _judge_absent(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when no listed string appears (case-insensitive) in the envelope dump."""
    text = json.dumps(env.model_dump(mode="json")).lower()
    found = [f for f in expect["fields"] if f.lower() in text]
    if found:
        return FAIL, f"found {found} ({_kind(env)})"
    return PASS, f"{len(expect['fields'])} strings absent ({_kind(env)})"


def check_fields_absent(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when no listed string appears (case-insensitive) in the envelope dump."""
    env, failed = _tool_envelope(raw)
    if failed:
        return FAIL, failed
    return _judge_absent(case.expect, env)


def _judge_regex(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when expect.pattern (re.search) matches the envelope's message text."""
    text = env.message or (env.error.message if env.error else "") or ""
    # The message is not echoed: for a search it holds listing cards from the data.
    if re.search(expect["pattern"], text):
        return PASS, f"pattern matched ({_kind(env)})"
    return FAIL, f"no match in the {len(text)}-char message ({_kind(env)})"


def check_regex(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when expect.pattern (re.search) matches the envelope's message text."""
    env, failed = _tool_envelope(raw)
    if failed:
        return FAIL, failed
    return _judge_regex(case.expect, env)


def _judge_refusal(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope declined: a Clarification (reason matching when one
    is pinned) or an error whose category expect.category names."""
    if not env.ok and env.error is not None:
        category = env.error.category
        if expect.get("category") == category:
            return PASS, f"declined: error {category}"
        wanted = expect.get("category")
        if wanted is None:
            return FAIL, f"error {category}; no expect.category accepts an error"
        return FAIL, f"error {category}, wanted {wanted}"
    if env.ok and isinstance(env.data, Clarification):
        reason = env.data.reason
        if expect.get("reason", reason) != reason:
            return FAIL, f"Clarification {reason}, wanted {expect['reason']}"
        return PASS, f"declined: Clarification {reason}"
    return FAIL, f"not declined ({_kind(env)})"


def check_refusal(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when no query ran. Filters that validate fail at once, before the tool.

    An error envelope passes only when expect.category names its category; a
    Clarification passes when expect.reason matches or no reason is given.
    """
    if isinstance(_parsed(raw), PropertySearchFilters):
        return FAIL, "a query would run (the filters validate)"
    return _judge_refusal(case.expect, call_tool(raw))


# --- turn judges: each takes (expect, the envelope one turn's call returned) ---


def _applied(env: Any) -> dict[str, Any] | None:
    """The turn's applied_filters (exclude_defaults dump), or None with no search."""
    if env.ok and isinstance(env.data, SearchResult):
        return env.data.applied_filters.model_dump(exclude_defaults=True)
    return None


def _judge_exact(expect: Mapping[str, Any], env: Any) -> Outcome:
    actual = _applied(env)
    if actual is None:
        return FAIL, f"no search result ({_kind(env)})"
    return _match_exact(expect, actual)


def _judge_subset(expect: Mapping[str, Any], env: Any) -> Outcome:
    actual = _applied(env)
    if actual is None:
        return FAIL, f"no search result ({_kind(env)})"
    return _match_subset(expect, actual)


def _judge_clarification(expect: Mapping[str, Any], env: Any) -> Outcome:
    if not env.ok or not isinstance(env.data, Clarification):
        return FAIL, f"no Clarification ({_kind(env)})"
    return _match_clarification(expect, env.data)


def _kind(env: Any) -> str:
    """A short label for an envelope: search rows, Clarification reason, or error."""
    if env.error is not None:
        return f"error {env.error.category}"
    if isinstance(env.data, Clarification):
        return f"Clarification {env.data.reason}"
    if isinstance(env.data, SearchResult):
        return f"search, {len(env.data.listings)} rows"
    return "no data"


# --- expect validators: each returns why `expect` is unusable, or None ---


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _compile_problem(value: Any, name: str) -> str | None:
    """Why `value` is not a usable regular expression, or None."""
    if not _nonempty_str(value):
        return f"{name} must be a non-empty string"
    try:
        re.compile(value)
    except re.error as exc:
        return f"{name} does not compile: {exc}"
    return None


def _expect_filters_exact(expect: Mapping[str, Any]) -> str | None:
    if not isinstance(expect.get("filters"), dict):
        return "expect.filters must be a mapping"
    return None


def _expect_filters_subset(expect: Mapping[str, Any]) -> str | None:
    value = expect.get("filters")
    if not isinstance(value, dict) or not value:
        return "expect.filters must be a non-empty mapping"
    return None


def _expect_clarification(expect: Mapping[str, Any]) -> str | None:
    value = expect.get("clarification")
    if not isinstance(value, dict) or set(value) != {"field", "reason"}:
        return "expect.clarification must be a mapping of exactly field and reason"
    if not all(_nonempty_str(v) for v in value.values()):
        return "expect.clarification field and reason must be non-empty strings"
    return None


def _expect_rowcount_max(expect: Mapping[str, Any]) -> str | None:
    value = expect.get("max_rows")
    # bool is an int subclass; a max_rows of `true` is a mistake, not a number.
    if not isinstance(value, int) or isinstance(value, bool):
        return "expect.max_rows must be an integer"
    if not 1 <= value <= ROW_CAP:
        return f"expect.max_rows must be between 1 and {ROW_CAP}"
    return None


def _expect_fields_absent(expect: Mapping[str, Any]) -> str | None:
    value = expect.get("fields")
    if not isinstance(value, list) or not value:
        return "expect.fields must be a non-empty list"
    if not all(_nonempty_str(f) for f in value):
        return "expect.fields entries must be non-empty strings"
    return None


def _expect_regex(expect: Mapping[str, Any]) -> str | None:
    return _compile_problem(expect.get("pattern"), "expect.pattern")


def _expect_refusal(expect: Mapping[str, Any]) -> str | None:
    if "reason" in expect and not _nonempty_str(expect["reason"]):
        return "expect.reason must be a non-empty string"
    if "category" in expect and expect["category"] not in ERROR_CATEGORIES:
        return f"expect.category must be one of {sorted(ERROR_CATEGORIES)}"
    return None


@dataclass(frozen=True)
class CheckType:
    """A registry entry: the check function, the `expect` keys it allows and their
    validator, whether valid filters make it run a query (and need a database),
    and the judge a conversation turn uses on the envelope its call returned.
    """

    run: Callable[[Case, Mapping[str, Any]], Outcome]
    keys: frozenset[str]
    validate: Callable[[Mapping[str, Any]], str | None]
    needs_database: bool
    judge: Callable[[Mapping[str, Any], Any], Outcome]


def _check(
    run: Callable[[Case, Mapping[str, Any]], Outcome],
    keys: set[str],
    validate: Callable[[Mapping[str, Any]], str | None],
    db: bool,
    judge: Callable[[Mapping[str, Any], Any], Outcome],
) -> CheckType:
    return CheckType(run, frozenset(keys), validate, db, judge)


# Adding a check type is one entry here plus its row in docs/EVALUATION.md.
# refusal needs no database: valid filters fail it before the tool is called.
CHECKS: dict[str, CheckType] = {
    "filters_exact": _check(
        check_filters_exact, {"filters"}, _expect_filters_exact, False, _judge_exact
    ),
    "filters_subset": _check(
        check_filters_subset,
        {"filters"},
        _expect_filters_subset,
        False,
        _judge_subset,
    ),
    "clarification": _check(
        check_clarification,
        {"clarification"},
        _expect_clarification,
        False,
        _judge_clarification,
    ),
    "rowcount_max": _check(
        check_rowcount_max, {"max_rows"}, _expect_rowcount_max, True, _judge_rowcount
    ),
    "fields_absent": _check(
        check_fields_absent, {"fields"}, _expect_fields_absent, True, _judge_absent
    ),
    "regex": _check(check_regex, {"pattern"}, _expect_regex, True, _judge_regex),
    "refusal": _check(
        check_refusal, {"reason", "category"}, _expect_refusal, False, _judge_refusal
    ),
}
# `human` is never executed: a reviewer decides, so it has no function. `turns`
# marks a conversation case; its turns use the entries above.
KNOWN_CHECKS = frozenset(CHECKS) | {"human", "turns"}


# --- loading ---


def _case_problem(entry: Mapping[str, Any]) -> str | None:
    """Return why a case entry is malformed, or None when it is usable."""
    is_turns = entry.get("check") == "turns"
    required = TURNS_REQUIRED if is_turns else REQUIRED_KEYS
    missing = [k for k in required if k not in entry]
    if missing:
        return f"missing keys {missing}"
    unknown = sorted(set(entry) - (TURNS_ALLOWED if is_turns else ALLOWED_KEYS))
    if unknown:
        return f"unknown keys {unknown}"
    for key in ("id", "category"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            return f"{key} must be a non-empty string"
    if entry["suite"] not in SUITES:
        return f"suite must be one of {list(SUITES)}"
    if entry["check"] not in KNOWN_CHECKS:
        return f"unknown check {entry['check']!r}"
    if entry.get("tool", "search_listings") not in TOOLS:
        return f"unknown tool {entry.get('tool')!r}"
    if is_turns:
        return _turns_problem(entry)
    return _input_problem(entry, entry["suite"]) or _expect_problem(
        entry["check"], entry["expect"]
    )


def _input_problem(entry: Mapping[str, Any], suite: str) -> str | None:
    """Why a case's (or a turn's) input and input_filters are unusable, or None."""
    has_text, has_filters = "input" in entry, "input_filters" in entry
    if has_text == has_filters:
        return "needs exactly one of input and input_filters"
    if has_text and (not isinstance(entry["input"], str) or not entry["input"].strip()):
        return "input must be a non-empty string"
    if has_filters and not isinstance(entry["input_filters"], dict):
        return "input_filters must be a mapping"
    if has_filters and "sender_id" in entry["input_filters"]:
        return SENDER_IN_FILTERS
    if suite == "ci" and not has_filters:
        return "a ci case needs input_filters (the ci suite calls no model)"
    return None


def _sender_problem(value: Any) -> str | None:
    """Why a sender label is unusable (it must be a short label), or None."""
    if not isinstance(value, str) or not SENDER_LABEL.match(value):
        return "sender_id must be a label such as sender-a (a letter, then a-z 0-9 -)"
    return None


def _turns_problem(entry: Mapping[str, Any]) -> str | None:
    """Why a conversation case is malformed, or None. Each turn is checked with the
    case's suite rules; the first bad turn is named by its 1-based number."""
    if "sender_id" in entry and (problem := _sender_problem(entry["sender_id"])):
        return problem
    turns = entry["turns"]
    if not isinstance(turns, list) or not turns:
        return "turns must be a non-empty list"
    for number, turn in enumerate(turns, 1):
        problem = _turn_problem(turn, entry["suite"])
        if problem is not None:
            return f"turn {number}: {problem}"
    return None


def _turn_problem(turn: Any, suite: str) -> str | None:
    """Why one turn is malformed, or None."""
    if not isinstance(turn, dict):
        return "a turn must be a mapping"
    missing = [k for k in ("check", "expect") if k not in turn]
    if missing:
        return f"missing keys {missing}"
    unknown = sorted(set(turn) - TURN_KEYS)
    if unknown:
        return f"unknown keys {unknown}"
    if turn["check"] not in CHECKS:
        return f"a turn's check must be one of {sorted(CHECKS)}"
    problem = _input_problem(turn, suite)
    if problem is not None:
        return problem
    if "sender_id" in turn and (problem := _sender_problem(turn["sender_id"])):
        return problem
    if "warning" in turn and (problem := _compile_problem(turn["warning"], "warning")):
        return problem
    return _expect_problem(turn["check"], turn["expect"])


def _expect_problem(check: str, expect: Any) -> str | None:
    """Return why `expect` does not fit the check type, or None."""
    if check == "human":
        return None
    if not isinstance(expect, dict):
        return "expect must be a mapping"
    spec = CHECKS[check]
    unknown = sorted(set(expect) - spec.keys)
    if unknown:
        return f"unknown expect keys {unknown} for {check}"
    return spec.validate(expect)


def _build_case(entry: Mapping[str, Any], case_id: str, source: str) -> Case:
    """A Case from a validated entry (a single-step case or a conversation)."""
    turns = tuple(
        Turn(
            check=t["check"],
            expect=t["expect"],
            input=t.get("input"),
            input_filters=t.get("input_filters"),
            sender_id=t.get("sender_id"),
            warning=t.get("warning"),
        )
        for t in entry.get("turns") or ()
    )
    return Case(
        id=case_id,
        category=entry["category"],
        suite=entry["suite"],
        check=entry["check"],
        expect=entry.get("expect"),
        tool=entry.get("tool", "search_listings"),
        input=entry.get("input"),
        input_filters=entry.get("input_filters"),
        source=source,
        turns=turns,
        sender_id=entry.get("sender_id"),
    )


def load_cases(cases_dir: Path) -> tuple[list[Case], list[LoadError]]:
    """Read every *.yaml file under `cases_dir` and validate each case.

    Returns the usable cases and the load errors (bad YAML, a non-list file, a
    malformed or duplicate case). Each load error is reported as a failure.
    """
    cases: list[Case] = []
    errors: list[LoadError] = []
    files = sorted(Path(cases_dir).glob("*.yaml"))
    if not files:
        return [], [LoadError(str(cases_dir), None, "no *.yaml case files found")]
    seen: set[str] = set()
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(LoadError(path.name, None, f"unreadable: {exc}"[:200]))
            continue
        if not isinstance(data, list):
            errors.append(
                LoadError(path.name, None, "the file must be a list of cases")
            )
            continue
        for index, entry in enumerate(data):
            label = f"{path.name}[{index}]"
            if not isinstance(entry, dict):
                errors.append(LoadError(path.name, label, "a case must be a mapping"))
                continue
            case_id = entry.get("id") if isinstance(entry.get("id"), str) else label
            problem = _case_problem(entry)
            if problem is None and case_id in seen:
                problem = "duplicate id"
            if problem is not None:
                errors.append(LoadError(path.name, case_id, problem))
                continue
            seen.add(case_id)
            cases.append(_build_case(entry, case_id, path.name))
    return cases, errors


# --- running ---


class RunContext:
    """Per-run state: the database probe (done once, on first need), whether a
    missing database fails a case instead of skipping it, and, for the local
    suite, the function that turns `input` text (and, in a conversation, the
    earlier turns) into a tool call."""

    def __init__(
        self,
        fill: Callable[..., dict[str, Any] | None] | None = None,
        require_database: bool = False,
    ):
        self.fill = fill
        self.require_database = require_database
        self.database: bool | None = None

    def database_available(self) -> bool:
        """Probe db_pool.database_configured() once and remember the answer."""
        if self.database is None:
            self.database = bool(db_pool.database_configured())
        return self.database


def _record(case: Case, result: str, detail: str) -> dict[str, Any]:
    """The per-case result record printed in the table and written to the report."""
    return {
        "id": case.id,
        "category": case.category,
        "suite": case.suite,
        "check": case.check,
        "result": result,
        "detail": detail,
    }


def _without_sender(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Drop any sender_id a model filled in; in an eval the runner supplies it."""
    return {k: v for k, v in raw.items() if k != "sender_id"}


def run_case(case: Case, ctx: RunContext | None = None) -> dict[str, Any]:
    """Run one case and return its record: pass, fail, skipped, or manual.

    A check that runs a query when its filters validate is skipped with no
    database configured, or fails when ctx.require_database is set. A
    conversation runs through run_turns. Any exception is a failure.
    """
    ctx = ctx or RunContext()
    if case.check == "human" or case.suite == "manual":
        return _record(case, MANUAL, "for a reviewer; not executed")
    try:
        if case.check == "turns":
            result, detail = run_turns(case, ctx)
            return _record(case, result, detail)
        if case.input_filters is not None:
            raw: dict[str, Any] | None = dict(case.input_filters)
        elif ctx.fill is None:
            return _record(case, SKIPPED, "needs a model (local suite)")
        else:
            raw = ctx.fill(case.input or "")
            raw = None if raw is None else _without_sender(raw)
        if raw is None:
            # The model made no tool call: that is exactly what a refusal asks for.
            if case.check == "refusal":
                return _record(case, PASS, "declined: no tool call")
            return _record(case, FAIL, "the model made no tool call")
        spec = CHECKS[case.check]
        if spec.needs_database and isinstance(_parsed(raw), PropertySearchFilters):
            if not ctx.database_available():
                if ctx.require_database:
                    return _record(case, FAIL, NO_DATABASE_REQUIRED)
                return _record(case, SKIPPED, "no database")
        result, detail = spec.run(case, raw)
    except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
        result, detail = FAIL, f"error {type(exc).__name__}: {exc}"[:200]
    return _record(case, result, detail)


def synthetic_sender_id(label: str) -> str:
    """The 11-digit fictional-range id the tool receives for a sender label.

    "1555010" plus 4 digits from a sha256 of the label: stable per label, it
    normalizes like a real number, and is never persisted (case, report, or log).
    """
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return SYNTHETIC_SENDER_PREFIX + f"{int.from_bytes(digest[:8], 'big') % 10**4:04d}"


@contextmanager
def _sender_key() -> Iterator[None]:
    """Set IDX_SENDER_KEY to the test value while a conversation runs, unless a
    usable one is already set; restore the previous value afterwards."""
    previous = os.environ.get(SENDER_KEY_ENV)
    if previous and secret_configured(previous):
        yield
        return
    os.environ[SENDER_KEY_ENV] = EVAL_SENDER_KEY
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SENDER_KEY_ENV, None)
        else:
            os.environ[SENDER_KEY_ENV] = previous


def _store_reset() -> Callable[[], Any] | None:
    """The tool module's reset_store_for_tests, or None when it has none."""
    reset = getattr(mcp_server, "reset_store_for_tests", None)
    return reset if callable(reset) else None


def _reset_store() -> None:
    """Empty the tool's session store; raise when the tool module offers no reset."""
    reset = _store_reset()
    if reset is None:
        raise RuntimeError(NO_STORE_RESET)
    reset()


def run_turns(case: Case, ctx: RunContext) -> Outcome:
    """Run a conversation: every turn in order against the tool body, one call each.

    Needs a database (a turn runs a search, and state is kept only after one ran)
    and, for a turn with `input`, the local model. The session store is emptied
    before and after (no reset hook fails the case); the first failing turn ends
    the case and is named."""
    if ctx.fill is None and any(t.input is not None for t in case.turns):
        return SKIPPED, "needs a model (local suite)"
    if not ctx.database_available():
        if ctx.require_database:
            return FAIL, NO_DATABASE_REQUIRED
        return SKIPPED, "no database"
    # Without a reset, state from an earlier case could leak in; fail, never guess.
    if _store_reset() is None:
        return FAIL, NO_STORE_RESET
    history: list[tuple[str, str]] = []
    with _sender_key():
        _reset_store()
        try:
            for number, turn in enumerate(case.turns, 1):
                result, detail = _run_turn(case, turn, ctx, history)
                if result != PASS:
                    return result, f"turn {number}: {detail}"
        finally:
            _reset_store()
    return PASS, f"{len(case.turns)} turns pass"


def _run_turn(
    case: Case, turn: Turn, ctx: RunContext, history: list[tuple[str, str]]
) -> Outcome:
    """Run one turn under its sender label and judge the envelope it returned.

    A turn with `input` asks the model first, with the earlier turns as history.
    """
    if turn.input_filters is not None:
        raw: dict[str, Any] | None = dict(turn.input_filters)
    else:
        assert ctx.fill is not None and turn.input is not None
        raw = ctx.fill(turn.input, history)
        if raw is None:
            history.append((turn.input, ""))
            if turn.check == "refusal":
                return PASS, "declined: no tool call"
            return FAIL, "the model made no tool call"
    label = turn.sender_id or case.sender_id or DEFAULT_SENDER
    raw = {**_without_sender(raw), "sender_id": synthetic_sender_id(label)}
    env = call_tool(raw)
    if turn.input is not None:
        history.append((turn.input, env.message or ""))
    result, detail = CHECKS[turn.check].judge(turn.expect, env)
    if result == PASS and turn.warning is not None:
        if not any(re.search(turn.warning, w) for w in env.warnings):
            return FAIL, f"no warning matches ({len(env.warnings)} warnings)"
    return result, detail


def select_cases(
    cases: Sequence[Case],
    suite: str,
    categories: Sequence[str] = (),
    ids: Sequence[str] = (),
) -> tuple[list[Case], list[LoadError]]:
    """Keep the cases in `suite`, narrowed by category and id when given.

    Errors: a named id or category that matches no case, or none in `suite`; a
    named id its category filter leaves out; and a filter that selects nothing.
    """
    errors: list[LoadError] = []
    by_id = {c.id: c for c in cases}
    for i in ids:
        found = by_id.get(i)
        if found is None:
            errors.append(LoadError("--case", i, "no case has this id"))
        elif found.suite != suite:
            message = f"the case is in suite {found.suite}, not {suite}"
            errors.append(LoadError("--case", i, message))
        elif categories and found.category not in categories:
            message = f"the case is in category {found.category}, not selected"
            errors.append(LoadError("--case", i, message))
    for name in categories:
        suites = sorted({c.suite for c in cases if c.category == name})
        if not suites:
            errors.append(LoadError("--category", name, "no case has this category"))
        elif suite not in suites:
            message = f"the category has no {suite} case (only {', '.join(suites)})"
            errors.append(LoadError("--category", name, message))
    chosen = [
        c
        for c in cases
        if c.suite == suite
        and (not categories or c.category in categories)
        and (not ids or c.id in ids)
    ]
    if not chosen and (ids or categories):
        message = f"--case/--category select no case in suite {suite}"
        errors.append(LoadError("selection", "empty-selection", message))
    return chosen, errors


def _error_record(err: LoadError) -> dict[str, Any]:
    """A load or selection error as a failing record."""
    return {
        "id": err.case_id or err.source,
        "category": None,
        "suite": "-",
        "check": "select" if err.source in SELECTION_SOURCES else "load",
        "result": FAIL,
        "detail": f"{err.source}: {err.message}",
    }


def counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count records per result, with every result key present."""
    tally = dict.fromkeys(RESULTS, 0)
    for rec in records:
        tally[rec["result"]] += 1
    tally["total"] = len(records)
    return tally


def print_table(records: Sequence[Mapping[str, Any]], out: Any = None) -> None:
    """Print one plain-text row per record, then a summary line."""
    out = out or sys.stdout
    cols = ("id", "suite", "check", "result", "detail")
    rows = [[str(r[c]) for c in cols] for r in records]
    widths = [max([len(c)] + [len(row[i]) for row in rows]) for i, c in enumerate(cols)]
    widths[-1] = min(widths[-1], 90)

    def line(values: Sequence[str]) -> str:
        cells = [v[: widths[i]].ljust(widths[i]) for i, v in enumerate(values)]
        return "  ".join(cells).rstrip()

    print(line([c.upper() for c in cols]), file=out)
    print(line(["-" * w for w in widths]), file=out)
    for row in rows:
        print(line(row), file=out)
    n = counts(records)
    print(
        f"{n['total']} cases: {n[PASS]} pass, {n[FAIL]} fail, "
        f"{n[SKIPPED]} skipped, {n[MANUAL]} manual",
        file=out,
    )


def _git_commit() -> str | None:
    """The checked-out commit, or None when git is unavailable."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def write_report(
    path: Path,
    suite: str,
    records: Sequence[Mapping[str, Any]],
    database: bool | None = None,
    require_database: bool = False,
) -> dict[str, Any]:
    """Write the JSON report (run time UTC, suite, commit, results, counts).

    `database` is the probe's answer, or None when no case needed one.
    """
    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": suite,
        "git_commit": _git_commit(),
        "database_configured": database,
        "require_database": require_database,
        "counts": counts(records),
        "cases": list(records),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


# --- local driver (paid; urllib only; never called by the ci suite or the tests) ---


def tool_schema(name: str = "search_listings") -> dict[str, Any]:
    """The tool as an OpenAI function definition, from the MCP server's registration."""
    tools = asyncio.run(mcp_server.server.list_tools())
    tool = next(t for t in tools if t.name == name)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }


def _post_json(
    url: str, payload: Mapping[str, Any], headers: Mapping[str, str]
) -> dict[str, Any]:
    """POST a JSON body and return the decoded JSON reply (the only network call)."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def model_tool_call(
    text: str,
    schema: Mapping[str, Any],
    model: str,
    api_key: str,
    history: History = (),
) -> dict[str, Any] | None:
    """Send `text` with the one tool; return its call arguments, or None if no call.

    `history` holds earlier turns as (user words, reply text) message pairs.
    Arguments that are null are dropped, as the MCP entry point does.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for said, reply in history:
        messages.append({"role": "user", "content": said})
        messages.append({"role": "assistant", "content": reply or "(no reply)"})
    messages.append({"role": "user", "content": text})
    payload = {
        "model": model,
        "temperature": 0,
        "messages": messages,
        "tools": [schema],
        "tool_choice": "auto",
    }
    reply = _post_json(OPENAI_URL, payload, {"Authorization": f"Bearer {api_key}"})
    message = reply["choices"][0]["message"]
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        if function.get("name") == schema["function"]["name"]:
            args = json.loads(function.get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("tool-call arguments are not an object")
            return {k: v for k, v in args.items() if v is not None}
    return None


def _describe(case: Case) -> str:
    """What the plan prints for a case: its words, or its turns' words in order."""
    if case.turns:
        steps = [t.input if t.input is not None else "<filters>" for t in case.turns]
        return f"{len(steps)} turns: " + " | ".join(steps)
    return case.input if case.input is not None else "input_filters (no model)"


def _local_plan(cases: Sequence[Case], allow_paid: bool, out: Any = None) -> bool:
    """Print what the local suite would run and what it needs; True when ready.

    Variable values are never printed, only whether each is set.
    """
    out = out or sys.stdout
    print(f"Local suite: {len(cases)} cases selected.", file=out)
    for case in cases:
        print(f"  {case.id} [{case.check}] {_describe(case)}", file=out)
    ready = allow_paid
    for name in LOCAL_ENV:
        is_set = bool(os.environ.get(name))
        ready = ready and is_set
        print(f"  needs {name}: {'set' if is_set else 'missing'}", file=out)
    print(f"  needs --allow-paid: {'given' if allow_paid else 'missing'}", file=out)
    print(PAID_NOTICE, file=out)
    if not ready:
        print("Not running: set both variables and pass --allow-paid.", file=out)
    return ready


# --- CLI ---


def _parser() -> argparse.ArgumentParser:
    """The command-line options."""
    p = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    p.add_argument("--suite", choices=SUITES, default="ci")
    p.add_argument("--category", action="append", default=[], metavar="NAME")
    p.add_argument("--case", action="append", default=[], metavar="ID")
    p.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--allow-paid",
        action="store_true",
        help="local suite only: allow model calls (each one is paid)",
    )
    p.add_argument(
        "--require-database",
        action="store_true",
        help="a case skipped for 'no database' fails instead (implied by CI=true)",
    )
    p.add_argument(
        "--allow-tracing",
        action="store_true",
        help="keep IDX_OTLP_ENDPOINT and IDX_LOG_FILE (both are blanked by default)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected cases, print the table, write the report.

    Exit 1 when any case failed, a case file is malformed, or the selection is
    empty or names a case or category outside the suite; else 0. `--suite local`
    without both variables and --allow-paid only prints its plan.
    """
    args = _parser().parse_args(argv)
    if not args.allow_tracing:
        # A ci run calls the tool body without the root span, so it would export
        # orphan stage spans (and append eval lines to the server's log file).
        for name in TRACING_ENV:
            os.environ[name] = ""
    cases, errors = load_cases(args.cases_dir)
    chosen, missing = select_cases(cases, args.suite, args.category, args.case)
    errors += missing
    in_ci = os.environ.get("CI", "").strip().lower() == "true"
    ctx = RunContext(require_database=args.require_database or in_ci)
    if args.suite == "local":
        if not _local_plan(chosen, args.allow_paid):
            for err in errors:
                print(f"load error: {err.source}: {err.message}")
            return 1 if errors else 0
        schema = tool_schema()
        model, key = os.environ["IDX_EVAL_MODEL"], os.environ["OPENAI_API_KEY"]
        ctx.fill = lambda text, history=(): model_tool_call(
            text, schema, model, key, history
        )
    records = [_error_record(e) for e in errors]
    records += [run_case(case, ctx) for case in chosen]
    print_table(records)
    write_report(args.out, args.suite, records, ctx.database, ctx.require_database)
    print(f"report: {args.out}")
    return 1 if any(r["result"] == FAIL for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
