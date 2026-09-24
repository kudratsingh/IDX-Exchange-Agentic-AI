"""Eval runner (WO-005): load evals/cases/*.yaml, check each case in code, report.

The ci suite calls the tool body directly: no model, no MCP transport, no network.
The local suite first asks a model to fill the tool schema; that is a paid run.
Case format and check semantics: docs/EVALUATION.md. Run: python -m evals.run --suite ci
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import yaml

from idx_agent.db import pool as db_pool
from idx_agent.domain.models import Clarification, PropertySearchFilters, SearchResult
from idx_agent.domain.results import ErrorCategory
from idx_agent.mcp_server import server as mcp_server

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_DIR = ROOT / "evals" / "cases"
# The report is gitignored; it is evidence for a run, never a tracked file.
DEFAULT_OUT = ROOT / "evals" / "last_run.json"

SUITES = ("ci", "local", "manual")
REQUIRED_KEYS = ("id", "category", "suite", "check", "expect")
ALLOWED_KEYS = frozenset(REQUIRED_KEYS) | {"note", "tool", "input", "input_filters"}
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


@dataclass(frozen=True)
class Case:
    """One validated eval case; `source` is the file it came from."""

    id: str
    category: str
    suite: str
    check: str
    expect: Any
    tool: str
    input: str | None
    input_filters: Mapping[str, Any] | None
    source: str


@dataclass(frozen=True)
class LoadError:
    """A case file or entry that could not be used; it counts as a failure."""

    source: str
    case_id: str | None
    message: str


# --- checks: each takes (case, raw filter mapping), returns (result, detail) ---


def _parsed(raw: Mapping[str, Any]) -> PropertySearchFilters | Clarification:
    """Validate the raw mapping exactly as the tool body does."""
    return PropertySearchFilters.from_input(raw)


def _filters_or_fail(raw: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return the accepted filters (exclude_defaults dump), or None and why not."""
    got = _parsed(raw)
    if isinstance(got, Clarification):
        return None, f"got a Clarification ({got.field}, {got.reason})"
    return got.model_dump(exclude_defaults=True), ""


def check_filters_exact(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the accepted filters equal expect.filters, nothing more or less."""
    actual, why = _filters_or_fail(raw)
    if actual is None:
        return FAIL, why
    wanted = dict(case.expect["filters"])
    if actual == wanted:
        return PASS, "filters match"
    return FAIL, f"got {actual}"


def check_filters_subset(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when every key in expect.filters is accepted with the same value."""
    actual, why = _filters_or_fail(raw)
    if actual is None:
        return FAIL, why
    missing = object()
    wrong = {
        key: actual.get(key, missing)
        for key, value in case.expect["filters"].items()
        if actual.get(key, missing) != value
    }
    if not wrong:
        return PASS, "expected keys match"
    shown = {k: ("<unset>" if v is missing else v) for k, v in wrong.items()}
    return FAIL, f"differs on {shown}"


def check_clarification(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when validation asks back with the expected field and reason code."""
    got = _parsed(raw)
    want = case.expect["clarification"]
    if not isinstance(got, Clarification):
        return FAIL, "filters were accepted; no Clarification"
    actual = (got.field, got.reason)
    if actual == (want.get("field"), want.get("reason")):
        return PASS, f"{got.field}, {got.reason}"
    return FAIL, f"got {actual[0]}, {actual[1]}"


def check_rowcount_max(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when a search ran and returned at most expect.max_rows listings."""
    env = mcp_server.search_result(raw)
    if not env.ok or not isinstance(env.data, SearchResult):
        return FAIL, f"no search result ({_kind(env)})"
    rows, cap = len(env.data.listings), case.expect["max_rows"]
    return (PASS if rows <= cap else FAIL), f"{rows} rows, max {cap}"


def _tool_envelope(raw: Mapping[str, Any]) -> tuple[Any, str | None]:
    """Call the tool body; return the envelope and, when the filters validate but
    no ok SearchResult came back, why that is a failure (else None)."""
    env = mcp_server.search_result(raw)
    if isinstance(_parsed(raw), PropertySearchFilters):
        if not env.ok or not isinstance(env.data, SearchResult):
            return env, f"a search should have run, got {_kind(env)}"
    return env, None


def check_fields_absent(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when no listed string appears (case-insensitive) in the envelope dump."""
    env, failed = _tool_envelope(raw)
    if failed:
        return FAIL, failed
    text = json.dumps(env.model_dump(mode="json")).lower()
    found = [f for f in case.expect["fields"] if f.lower() in text]
    if found:
        return FAIL, f"found {found} ({_kind(env)})"
    return PASS, f"{len(case.expect['fields'])} strings absent ({_kind(env)})"


def check_regex(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when expect.pattern (re.search) matches the envelope's message text."""
    env, failed = _tool_envelope(raw)
    if failed:
        return FAIL, failed
    text = env.message or (env.error.message if env.error else "") or ""
    # The message is not echoed: for a search it holds listing cards from the data.
    if re.search(case.expect["pattern"], text):
        return PASS, f"pattern matched ({_kind(env)})"
    return FAIL, f"no match in the {len(text)}-char message ({_kind(env)})"


def check_refusal(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when no query ran. Filters that validate fail at once, before the tool.

    An error envelope passes only when expect.category names its category; a
    Clarification passes when expect.reason matches or no reason is given.
    """
    if isinstance(_parsed(raw), PropertySearchFilters):
        return FAIL, "a query would run (the filters validate)"
    env = mcp_server.search_result(raw)
    expect = case.expect
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
    value = expect.get("pattern")
    if not _nonempty_str(value):
        return "expect.pattern must be a non-empty string"
    try:
        re.compile(value)
    except re.error as exc:
        return f"expect.pattern does not compile: {exc}"
    return None


def _expect_refusal(expect: Mapping[str, Any]) -> str | None:
    if "reason" in expect and not _nonempty_str(expect["reason"]):
        return "expect.reason must be a non-empty string"
    if "category" in expect and expect["category"] not in ERROR_CATEGORIES:
        return f"expect.category must be one of {sorted(ERROR_CATEGORIES)}"
    return None


@dataclass(frozen=True)
class CheckType:
    """A registry entry: the check function, the `expect` keys it allows and their
    validator, and whether valid filters make it run a query (and need a database).
    """

    run: Callable[[Case, Mapping[str, Any]], Outcome]
    keys: frozenset[str]
    validate: Callable[[Mapping[str, Any]], str | None]
    needs_database: bool


def _check(
    run: Callable[[Case, Mapping[str, Any]], Outcome],
    keys: set[str],
    validate: Callable[[Mapping[str, Any]], str | None],
    db: bool,
) -> CheckType:
    return CheckType(run, frozenset(keys), validate, db)


# Adding a check type is one entry here plus its row in docs/EVALUATION.md.
# refusal needs no database: valid filters fail it before the tool is called.
CHECKS: dict[str, CheckType] = {
    "filters_exact": _check(
        check_filters_exact, {"filters"}, _expect_filters_exact, False
    ),
    "filters_subset": _check(
        check_filters_subset, {"filters"}, _expect_filters_subset, False
    ),
    "clarification": _check(
        check_clarification, {"clarification"}, _expect_clarification, False
    ),
    "rowcount_max": _check(
        check_rowcount_max, {"max_rows"}, _expect_rowcount_max, True
    ),
    "fields_absent": _check(
        check_fields_absent, {"fields"}, _expect_fields_absent, True
    ),
    "regex": _check(check_regex, {"pattern"}, _expect_regex, True),
    "refusal": _check(check_refusal, {"reason", "category"}, _expect_refusal, False),
}
# `human` is never executed: a reviewer decides, so it has no function.
KNOWN_CHECKS = frozenset(CHECKS) | {"human"}


# --- loading ---


def _case_problem(entry: Mapping[str, Any]) -> str | None:
    """Return why a case entry is malformed, or None when it is usable."""
    missing = [k for k in REQUIRED_KEYS if k not in entry]
    if missing:
        return f"missing keys {missing}"
    unknown = sorted(set(entry) - ALLOWED_KEYS)
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
    has_text, has_filters = "input" in entry, "input_filters" in entry
    if has_text == has_filters:
        return "needs exactly one of input and input_filters"
    if has_text and (not isinstance(entry["input"], str) or not entry["input"].strip()):
        return "input must be a non-empty string"
    if has_filters and not isinstance(entry["input_filters"], dict):
        return "input_filters must be a mapping"
    if entry["suite"] == "ci" and not has_filters:
        return "a ci case needs input_filters (the ci suite calls no model)"
    return _expect_problem(entry["check"], entry["expect"])


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
            cases.append(
                Case(
                    id=case_id,
                    category=entry["category"],
                    suite=entry["suite"],
                    check=entry["check"],
                    expect=entry["expect"],
                    tool=entry.get("tool", "search_listings"),
                    input=entry.get("input"),
                    input_filters=entry.get("input_filters"),
                    source=path.name,
                )
            )
    return cases, errors


# --- running ---


class RunContext:
    """Per-run state: the database probe (done once, on first need), whether a
    missing database fails a case instead of skipping it, and, for the local
    suite, the function that turns a case's `input` text into a tool call."""

    def __init__(
        self,
        fill: Callable[[str], dict[str, Any] | None] | None = None,
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


def run_case(case: Case, ctx: RunContext | None = None) -> dict[str, Any]:
    """Run one case and return its record: pass, fail, skipped, or manual.

    A check that runs a query when its filters validate is skipped with no
    database configured, or fails when ctx.require_database is set. Any
    exception is a failure.
    """
    ctx = ctx or RunContext()
    if case.check == "human" or case.suite == "manual":
        return _record(case, MANUAL, "for a reviewer; not executed")
    try:
        if case.input_filters is not None:
            raw: dict[str, Any] | None = dict(case.input_filters)
        elif ctx.fill is None:
            return _record(case, SKIPPED, "needs a model (local suite)")
        else:
            raw = ctx.fill(case.input or "")
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
    text: str, schema: Mapping[str, Any], model: str, api_key: str
) -> dict[str, Any] | None:
    """Send `text` with the one tool; return its call arguments, or None if no call.

    Arguments that are null are dropped, as the MCP entry point does.
    """
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
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


def _local_plan(cases: Sequence[Case], allow_paid: bool, out: Any = None) -> bool:
    """Print what the local suite would run and what it needs; True when ready.

    Variable values are never printed, only whether each is set.
    """
    out = out or sys.stdout
    print(f"Local suite: {len(cases)} cases selected.", file=out)
    for case in cases:
        what = case.input if case.input is not None else "input_filters (no model)"
        print(f"  {case.id} [{case.check}] {what}", file=out)
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
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected cases, print the table, write the report.

    Exit 1 when any case failed, a case file is malformed, or the selection is
    empty or names a case or category outside the suite; else 0. `--suite local`
    without both variables and --allow-paid only prints its plan.
    """
    args = _parser().parse_args(argv)
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
        ctx.fill = lambda text: model_tool_call(text, schema, model, key)
    records = [_error_record(e) for e in errors]
    records += [run_case(case, ctx) for case in chosen]
    print_table(records)
    write_report(args.out, args.suite, records, ctx.database, ctx.require_database)
    print(f"report: {args.out}")
    return 1 if any(r["result"] == FAIL for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
