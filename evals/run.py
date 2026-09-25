"""Eval runner (WO-005): load evals/cases/*.yaml, check each case in code, report.

The ci suite calls the tool body directly: no model, no MCP transport, no network.
The local suite first asks a model to fill the tool schema; that is a paid run.
A routing case (`route_exact`, WO-013) gives the model every skill and every tool,
answers each call with a stub, and judges which tools it called, in order.
Case format and check semantics: docs/EVALUATION.md. Run: python -m evals.run --suite ci
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, get_args

import yaml

from idx_agent.db import pool as db_pool
from idx_agent.domain.models import (
    RAG_TOP_K,
    RECOMMEND_MAX_K,
    Clarification,
    CompEvidence,
    MarketStats,
    MarketStatsRequest,
    PropertySearchFilters,
    RagAnswer,
    RagRequest,
    RecommendationResult,
    RecommendRequest,
    SearchResult,
    SimilarListingsRequest,
    SimilarResult,
)
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
ALLOWED_KEYS = frozenset(REQUIRED_KEYS) | {
    "note",
    "tool",
    "input",
    "input_filters",
    "database",
    "index_as_of",
}
# A conversation case (`check: turns`, WO-006) has no case-level input or expect;
# each turn carries its own. Format: docs/EVALUATION.md, "Multi-turn cases".
TURNS_REQUIRED = ("id", "category", "suite", "check", "turns")
TURNS_ALLOWED = frozenset(TURNS_REQUIRED) | {"note", "tool", "sender_id", "database"}
# A case's `database` key: `fixture` when its expectations hold only against the
# synthetic fixture rows. --database-kind names the database a run points at.
CASE_DATABASES = ("fixture", "any")
DEFAULT_CASE_DATABASE = "any"
DATABASE_KINDS = ("fixture", "real")
FIXTURE_ONLY_SKIP = "fixture-only case; real database run"
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
MARKET_PROMPT = (
    "You answer questions about closed-sale market figures. Call get_market_stats "
    "with only the place, property type, and period the user stated. If the request "
    "is not a market question, do not call any tool."
)
SIMILAR_PROMPT = (
    "You find active listings that fit a description of a home. Call "
    "find_similar_listings with the descriptive words in text and only the city, "
    "maximum price, minimum bedrooms, property type, and number of matches the user "
    "stated, each in its own field. If the request does not describe a home to find, "
    "do not call any tool."
)
RECOMMEND_PROMPT = (
    "You find active listings like a listing the user already has in view, each "
    "with a price check against comparable sales. Call recommend with that "
    "listing's key and, only if the user said how many, k (0 for the price check "
    "alone). If the request does not name or point to a listing, do not call any "
    "tool."
)
RAG_PROMPT = (
    "You answer questions about what a term, a field, or a column means, which "
    "columns a table has, and how a metric is defined, from the reference documents. "
    "Call rag_answer with the user's question. If the request is not such a "
    "question, do not call any tool."
)
# The live gateway shows the model the skill body before it calls a tool, so the local
# driver does the same: the skill text (frontmatter stripped) follows the base prompt.
SKILL_PATH = ROOT / "skills" / "property-search" / "SKILL.md"
MARKET_SKILL_PATH = ROOT / "skills" / "market-stats" / "SKILL.md"
SIMILAR_SKILL_PATH = ROOT / "skills" / "similar-listings" / "SKILL.md"
RECOMMEND_SKILL_PATH = ROOT / "skills" / "recommend" / "SKILL.md"
RAG_SKILL_PATH = ROOT / "skills" / "docs-qa" / "SKILL.md"

# find_similar_listings (WO-010). A ci case runs against the CI fixture index, built
# once per run from the generator's rows with the test:hashing embedder (no paid call).
SIMILAR_TOOL = "find_similar_listings"
# recommend (WO-011) ranks by the subject's stored vector: the same fixture index.
RECOMMEND_TOOL = "recommend"
INDEXED_TOOLS = frozenset({SIMILAR_TOOL, RECOMMEND_TOOL})
SEMANTIC_FIXTURE = ROOT / "tests" / "semantic_fixture.py"
FIXTURE_EMBED_MODEL = "test:hashing"
SEMANTIC_ENV = ("IDX_SEMANTIC_INDEX_DIR", "IDX_EMBED_MODEL", "IDX_EMBED_DIMS")
# The human's relevance marks for the judged local cases: a gitignored file under data/.
JUDGMENTS_ENV = "IDX_SEMANTIC_JUDGMENTS"
JUDGMENTS_ROOT = ROOT / "data"
JUDGMENTS_FORMAT = 1
# Listing keys a case file may pin: the fixture's invented pattern, never a real key.
INVENTED_KEY = re.compile(r"^9[0-9]{5,6}$")
MAX_SIMILAR_K = 10

# rag_answer (WO-012) reads a document index, never the database. A ci case runs
# against the fixture index tests/rag_fixture.py builds from the own-words corpus under
# tests/fixtures/docs/ (lexical route, no provider), once per run.
RAG_TOOL = "rag_answer"
RAG_FIXTURE = ROOT / "tests" / "rag_fixture.py"
RAG_FIXTURE_ROUTE = "bm25"
# A chunks_from source: a registry id, "#", and a chunk key (field, section, table).
CHUNK_ID = re.compile(r"^[a-z_]+#[^\s#]+$")


@dataclass(frozen=True)
class ToolSpec:
    """What the runner needs to know about one tool a case may name: its validator
    (`from_input`), the tool body's name in the server module (looked up per call),
    its success data type, the checks it supports, whether it takes the session
    arguments, and the local driver's base prompt and skill file. `label` names
    the query in a failure detail; `database` is False for a tool that reads none."""

    parse: Callable[[Mapping[str, Any]], Any]
    body: str
    label: str
    success: type
    checks: frozenset[str]
    session: bool
    prompt: str
    skill: Path
    database: bool = True


# Checks every tool supports; each tool adds its own (docs/EVALUATION.md, Check types).
_COMMON_CHECKS = frozenset(
    {
        "filters_exact",
        "filters_subset",
        "clarification",
        "fields_absent",
        "regex",
        "refusal",
        "human",
    }
)
TOOL_SPECS: dict[str, ToolSpec] = {
    "search_listings": ToolSpec(
        PropertySearchFilters.from_input,
        "search_result",
        "a search",
        SearchResult,
        _COMMON_CHECKS | {"rowcount_max", "turns"},
        True,
        SYSTEM_PROMPT,
        SKILL_PATH,
    ),
    # No session: a market call takes no sender id and never reads search state.
    "get_market_stats": ToolSpec(
        MarketStatsRequest.from_input,
        "market_result",
        "a market query",
        MarketStats,
        _COMMON_CHECKS | {"stats_exact"},
        False,
        MARKET_PROMPT,
        MARKET_SKILL_PATH,
    ),
    # Stateless too: no sender id, no session arguments (WO-010).
    SIMILAR_TOOL: ToolSpec(
        SimilarListingsRequest.from_input,
        "similar_result",
        "a similar-listings search",
        SimilarResult,
        _COMMON_CHECKS | {"rowcount_max", "ranked_keys", "recall_at_k"},
        False,
        SIMILAR_PROMPT,
        SIMILAR_SKILL_PATH,
    ),
    # sender_id is a real argument here (with position), but a case file names no
    # sender, so there is nothing to strip (WO-011).
    RECOMMEND_TOOL: ToolSpec(
        RecommendRequest.from_input,
        "recommend_result",
        "a recommendation",
        RecommendationResult,
        _COMMON_CHECKS
        | {"rowcount_max", "ranked_keys", "price_check_exact", "error_category"},
        False,
        RECOMMEND_PROMPT,
        RECOMMEND_SKILL_PATH,
    ),
    # No session and no database: the tool reads only its document index (WO-012),
    # so its cases always run, with or without a database.
    RAG_TOOL: ToolSpec(
        RagRequest.from_input,
        "rag_result",
        "a document answer",
        RagAnswer,
        _COMMON_CHECKS | {"chunks_from"},
        False,
        RAG_PROMPT,
        RAG_SKILL_PATH,
        database=False,
    ),
}
# Tools a case may name; `tool` defaults to search_listings.
TOOLS = frozenset(TOOL_SPECS)
DEFAULT_TOOL = "search_listings"

# The routing mode (WO-013): a `route_exact` case gives the model every configured
# skill and every registered tool, answers each tool call with a fixed stub, and
# compares the tools called, in order, with expect.route. Format: docs/EVALUATION.md,
# "Routing cases".
ROUTE_CHECK = "route_exact"
HEALTH_TOOL = "health"
# Every registered tool a route may name: the five data tools plus health (no args).
ROUTE_TOOLS = TOOLS | {HEALTH_TOOL}
ROUTE_MAX_STEPS = 3  # at most three tool calls in one turn (docs/ROUTING.md)
ROUTE_MAX_CALLS = 4  # model calls per routing case; a fifth would be "too many calls"
ROUTE_REQUIRED = (*REQUIRED_KEYS, "input")
ROUTE_ALLOWED = frozenset(ROUTE_REQUIRED) | {"note", "history"}
# A routing case's expect: `route` (+ `filters`), or `route_any_of` (+ its filters).
ROUTE_EXPECT_KEYS = frozenset({"route", "filters", "route_any_of", "filters_any_of"})
# A history turn: the user's words and the reply, plus an optional tool-call record.
HISTORY_REQUIRED = frozenset({"user", "assistant"})
HISTORY_ALLOWED = HISTORY_REQUIRED | {"tool_calls", "tool_result"}
# The gateway exposes our tools as idx__<name>; a call may carry the prefix.
TOOL_PREFIX = "idx__"
# What every routed tool call gets back: no data, no listing, nothing from a document.
ROUTE_STUB_RESULT = json.dumps(
    {"ok": True, "message": "The result was shown to the user."}
)
# The routing prompt's base: framing only, with no rule of its own. routing_prompt puts
# the server `instructions` after it, then the skills list and the skill bodies.
ROUTING_PROMPT = (
    "You are a real-estate assistant that people reach on WhatsApp. Below are your "
    "skills, each listed by name and description, then each skill's instructions in "
    "the same order. When you use a skill, follow its instructions."
)
# The heading line before the MCP server's `instructions` in the routing prompt: the
# live model always sees that string, so the driver sends it too (decision 6 of
# 2026-09-25 put two routing rules in it).
SERVER_INSTRUCTIONS_HEADING = "Tool server instructions:"
# The idx agent's skill list (its order is the prompt's order) and the skills folder
# the routing prompt reads (--skills-dir, so a baseline can use unchanged skills).
OPENCLAW_CONFIG = ROOT / "config" / "openclaw.idx.json5"
MERGE_SCRIPT = ROOT / "scripts" / "openclaw_merge_config.py"
ROUTING_AGENT = "idx"
DEFAULT_SKILLS_DIR = ROOT / "skills"
FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)(.*)\Z", re.DOTALL)
# A run of 6+ digits in routing words may only be an invented fixture key.
LISTING_KEY_LIKE = re.compile(r"\d{6,}")
# A routing case's report entry keeps this much of the model's final text reply.
REPLY_PREVIEW_CHARS = 200
# A routing request the provider refuses (HTTP 400) fails its case with this much of
# the provider's message, the API key masked; the request is never resent.
PROVIDER_MESSAGE_CHARS = 140
API_KEY_LIKE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")


def system_prompt(tool: str = DEFAULT_TOOL) -> str:
    """Return the tool's base prompt plus its skill body, if the skill file exists."""
    spec = TOOL_SPECS[tool]
    try:
        text = spec.skill.read_text(encoding="utf-8")
    except OSError:
        return spec.prompt
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return spec.prompt + "\n\nSkill instructions:\n" + body.strip()


PAID_NOTICE = (
    "PAID RUN: every local case with `input` sends one request to the OpenAI API, "
    "and every local find_similar_listings case that reaches the tool embeds its "
    "text with the provider (one more paid call), as does every local rag_answer "
    "case served a hybrid index (its question is embedded). "
    f"Every local {ROUTE_CHECK} (routing) case sends up to {ROUTE_MAX_CALLS} "
    "requests, each with every skill and all six tool schemas; it runs no tool, so "
    "it embeds and queries nothing. "
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
    """One validated eval case from `source`. A `turns` case has steps, no `expect` or
    inputs; `database` "fixture" marks a fixture-only case; `index_as_of` dates the CI
    fixture index. A `route_exact` case has `tool` "" and its earlier turns in
    `history`, as HistoryTurn records (the user's words, any tool calls with their
    result text, the assistant's reply)."""

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
    database: str = DEFAULT_CASE_DATABASE
    index_as_of: date | None = None
    history: tuple[HistoryTurn, ...] = ()


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model made in a routing case, in call order."""

    name: str  # the registered tool name, without the idx__ prefix
    arguments: dict[str, Any]  # nulls dropped, sender_id dropped


@dataclass(frozen=True)
class HistoryTurn:
    """One earlier turn of a routing case, in own words: the user's message, the tool
    calls the assistant made for it (invented arguments; none on a plain turn) with
    the result text each call got back, and the reply the assistant relayed."""

    user: str
    assistant: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_result: str = ""


# Earlier turns of a routing case: HistoryTurn records, or plain (user, reply) pairs.
RouteHistory = Sequence[HistoryTurn | tuple[str, str]]


class TooManyCalls(Exception):
    """The model still called tools on its last allowed model call."""

    def __init__(self, calls: Sequence[ToolCall], max_calls: int) -> None:
        self.calls = list(calls)
        super().__init__(
            f"too many calls: tools were still being called at model call "
            f"{max_calls} ({len(self.calls)} tool calls: "
            f"{[c.name for c in self.calls]})"
        )


class RoutingSetupError(ValueError):
    """The routing prompt cannot be built: a config, skills folder, or skill file
    problem. Raised before any model call."""


class ProviderRejected(Exception):
    """The provider refused a routing request (HTTP 400). The message holds a masked
    fragment of the provider's error text; the request is not resent."""


@dataclass(frozen=True)
class LoadError:
    """A case file or entry that could not be used; it counts as a failure."""

    source: str
    case_id: str | None
    message: str


# --- checks: each takes (case, raw filter mapping), returns (result, detail) ---


def _parsed(raw: Mapping[str, Any], tool: str = DEFAULT_TOOL) -> Any:
    """Validate the raw mapping with the tool's own `from_input`, as its body does;
    a tool with session arguments validates without them. A request or Clarification."""
    spec = TOOL_SPECS[tool]
    if spec.session:
        raw = {k: v for k, v in raw.items() if k not in SESSION_ARGS}
    return spec.parse(raw)


def _is_request(raw: Mapping[str, Any], tool: str = DEFAULT_TOOL) -> bool:
    """True when the mapping validates, so the tool body would run a query."""
    return not isinstance(_parsed(raw, tool), Clarification)


def call_tool(raw: Mapping[str, Any], tool: str = DEFAULT_TOOL) -> Any:
    """Call the tool body once. For a tool with a session, the session arguments in
    `raw` (sender_id, mode, clear) go as keywords when the body names them, else
    they stay in the mapping. The body is looked up per call (tests replace it)."""
    spec = TOOL_SPECS[tool]
    body = getattr(mcp_server, spec.body)
    session = {k: v for k, v in raw.items() if k in SESSION_ARGS}
    if spec.session and session and "sender_id" in inspect.signature(body).parameters:
        filters = {k: v for k, v in raw.items() if k not in SESSION_ARGS}
        return body(filters, **session)
    return body(raw)


def _filters_or_fail(
    raw: Mapping[str, Any], tool: str = DEFAULT_TOOL
) -> tuple[dict[str, Any] | None, str]:
    """Return the accepted request (exclude_defaults dump), or None and why not."""
    got = _parsed(raw, tool)
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
    actual, why = _filters_or_fail(raw, case.tool)
    if actual is None:
        return FAIL, why
    return _match_exact(case.expect, actual)


def check_filters_subset(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when every key in expect.filters is accepted with the same value."""
    actual, why = _filters_or_fail(raw, case.tool)
    if actual is None:
        return FAIL, why
    return _match_subset(case.expect, actual)


def check_clarification(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when validation asks back with the expected field and reason code."""
    return _match_clarification(case.expect, _parsed(raw, case.tool))


def _judge_rowcount(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope holds a SearchResult (listings), a SimilarResult
    (matches), or a RecommendationResult (recommendations) of at most max_rows."""
    if env.ok and isinstance(env.data, SimilarResult):
        rows = len(env.data.matches)
    elif env.ok and isinstance(env.data, RecommendationResult):
        rows = len(env.data.recommendations)
    elif env.ok and isinstance(env.data, SearchResult):
        rows = len(env.data.listings)
    else:
        return FAIL, f"no result with rows ({_kind(env)})"
    cap = expect["max_rows"]
    return (PASS if rows <= cap else FAIL), f"{rows} rows, max {cap}"


def check_rowcount_max(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when a search ran and returned at most expect.max_rows listings."""
    return _judge_rowcount(case.expect, call_tool(raw, case.tool))


def _tool_envelope(
    raw: Mapping[str, Any], tool: str = DEFAULT_TOOL
) -> tuple[Any, str | None]:
    """Call the tool body; return the envelope and, when the input validates but
    no ok result of the tool's success type came back, why that fails (else None)."""
    env = call_tool(raw, tool)
    spec = TOOL_SPECS[tool]
    if _is_request(raw, tool):
        if not env.ok or not isinstance(env.data, spec.success):
            return env, f"{spec.label} should have run, got {_kind(env)}"
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
    env, failed = _tool_envelope(raw, case.tool)
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
    env, failed = _tool_envelope(raw, case.tool)
    if failed:
        return FAIL, failed
    return _judge_regex(case.expect, env)


def _plain(value: Any) -> Any:
    """A YAML value as JSON would carry it (a date becomes "YYYY-MM-DD")."""
    return json.loads(json.dumps(value, default=str))


def _judge_stats(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope holds MarketStats whose listed fields equal expect.stats
    exactly (JSON form; `trend` as a list of month rows), and, when expect.warning is
    given, one of the envelope's warnings matches it."""
    if not env.ok or not isinstance(env.data, MarketStats):
        return FAIL, f"no market stats ({_kind(env)})"
    actual = env.data.model_dump(mode="json")
    wrong = [k for k, v in expect["stats"].items() if _plain(v) != actual.get(k)]
    if wrong:
        # Aggregates only (no row can reach MarketStats), so the values may be shown.
        shown = "; ".join(f"{k} got {json.dumps(actual.get(k))[:60]}" for k in wrong)
        return FAIL, f"differs on {shown}"
    warning = expect.get("warning")
    if warning is not None and not any(re.search(warning, w) for w in env.warnings):
        return FAIL, f"no warning matches ({len(env.warnings)} warnings)"
    return PASS, f"{len(expect['stats'])} fields match ({_kind(env)})"


def check_stats_exact(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the tool returned MarketStats with exactly the expected fields."""
    return _judge_stats(case.expect, call_tool(raw, case.tool))


def _match_keys(env: Any) -> list[int]:
    """The listing keys in rank order: a SimilarResult's matches, or a
    RecommendationResult's recommendations."""
    if isinstance(env.data, RecommendationResult):
        return [rec.listing.listing_key for rec in env.data.recommendations]
    return [match.listing.listing_key for match in env.data.matches]


def _judge_ranked(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope holds a SimilarResult (or a RecommendationResult) whose
    listing keys, in rank order, equal expect.keys exactly, and, with expect.warning,
    one warning matches it."""
    if not env.ok or not isinstance(env.data, SimilarResult | RecommendationResult):
        return FAIL, f"no ranked result ({_kind(env)})"
    got, want = _match_keys(env), list(expect["keys"])
    if got != want:
        # Keys are not echoed: on a real database they would be real listing keys.
        first = next(
            (
                i
                for i, pair in enumerate(zip(got, want, strict=False), 1)
                if pair[0] != pair[1]
            ),
            min(len(got), len(want)) + 1,
        )
        return (
            FAIL,
            f"got {len(got)} keys, want {len(want)}; first difference at rank {first}",
        )
    warning = expect.get("warning")
    if warning is not None and not any(re.search(warning, w) for w in env.warnings):
        return FAIL, f"no warning matches ({len(env.warnings)} warnings)"
    return PASS, f"{len(want)} keys in order ({_kind(env)})"


def check_ranked_keys(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the ranked matches' keys equal expect.keys, in order."""
    return _judge_ranked(case.expect, call_tool(raw, case.tool))


def _evidence_diff(
    label: str, fields: Mapping[str, Any], evidence: CompEvidence
) -> list[str]:
    """The listed CompEvidence fields that differ (JSON form), each with its value.
    Evidence holds counts, a place name, and a sentence: never a key or a row."""
    actual = evidence.model_dump(mode="json")
    return [
        f"{label} {k} got {json.dumps(actual.get(k))[:60]}"
        for k, v in fields.items()
        if _plain(v) != actual.get(k)
    ]


def _judge_price_check(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope holds a RecommendationResult whose subject check has
    every field in expect.subject, and, with expect.ranks, exactly that many
    recommendations, each check with the fields listed for its rank."""
    if not env.ok or not isinstance(env.data, RecommendationResult):
        return FAIL, f"no recommendation result ({_kind(env)})"
    wrong = _evidence_diff("subject", expect["subject"], env.data.subject_check)
    listed = len(expect["subject"])
    if "ranks" in expect:
        got, ranks = env.data.recommendations, expect["ranks"]
        if len(got) != len(ranks):
            return FAIL, f"{len(got)} recommendations, want {len(ranks)}"
        for rank, fields in sorted(ranks.items()):
            wrong += _evidence_diff(f"rank {rank}", fields, got[rank - 1].comp_evidence)
            listed += len(fields)
    if wrong:
        return FAIL, "differs on " + "; ".join(wrong)
    return PASS, f"{listed} fields match ({_kind(env)})"


def check_price_check_exact(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the price checks carry exactly the expected CompEvidence fields."""
    return _judge_price_check(case.expect, call_tool(raw, case.tool))


def _judge_chunks(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope holds a found RagAnswer and each of expect.sources is
    among its first `top` chunk ids (`doc#key`); with `exact`, those first `top`
    ids equal expect.sources in order. Ids are field names and section positions,
    never passage text, so a failure may name them."""
    if not env.ok or not isinstance(env.data, RagAnswer):
        return FAIL, f"no document answer ({_kind(env)})"
    if not env.data.found:
        return FAIL, "not found: no chunks came back"
    top, want = expect["top"], list(expect["sources"])
    got = env.data.chunk_ids()[:top]
    if expect.get("exact"):
        if got != want:
            return FAIL, f"top {top} is {got}, want {want}"
        return PASS, f"top {len(got)} in order ({_kind(env)})"
    missing = [s for s in want if s not in got]
    if missing:
        return FAIL, f"{missing} not in the top {top} {got}"
    return PASS, f"{len(want)} sources in the top {top} ({_kind(env)})"


def check_chunks_from(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the expected sources are among the top chunks (in order, exact)."""
    return _judge_chunks(case.expect, call_tool(raw, case.tool))


def _judge_error(expect: Mapping[str, Any], env: Any) -> Outcome:
    """Pass when the envelope is ok=False with a ToolError of expect.category."""
    if env.ok or env.error is None:
        return FAIL, f"no error ({_kind(env)})"
    if env.error.category != expect["category"]:
        return FAIL, f"error {env.error.category}, wanted {expect['category']}"
    return PASS, f"error {env.error.category}"


def check_error_category(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Pass when the tool ran and answered with an error of the expected category
    (input that validates, so unlike `refusal` a query may have run)."""
    return _judge_error(case.expect, call_tool(raw, case.tool))


@dataclass(frozen=True)
class Judgment:
    """One judged query: the sheet's top 10 in rank order and the relevant keys."""

    judged: tuple[int, ...]
    relevant: frozenset[int]


def _judgment(entry: Mapping[str, Any]) -> Judgment:
    """One query's entry; ValueError when a relevant key was not on its sheet."""
    judged = tuple(int(key) for key in entry["judged"])
    relevant = frozenset(int(key) for key in entry["relevant"])
    if not relevant <= set(judged):
        raise ValueError("a relevant key is not among the judged keys")
    return Judgment(judged, relevant)


def load_judgments() -> tuple[dict[str, Judgment] | None, Outcome]:
    """Read the marks file IDX_SEMANTIC_JUDGMENTS names (the spike's `--score` format:
    {"format_version": 1, "queries": {id: {"judged": [...], "relevant": [...]}}}).
    Returns (marks, ("", "")) or (None, (result, why)): skipped when unset or absent,
    failed outside data/ or unreadable. No key is ever echoed."""
    name = os.environ.get(JUDGMENTS_ENV) or db_pool.env_setting(JUDGMENTS_ENV)
    if not name:
        return None, (SKIPPED, f"no judgments file ({JUDGMENTS_ENV} is unset)")
    path = Path(name) if Path(name).is_absolute() else ROOT / name
    path = path.resolve()
    if not path.is_relative_to(JUDGMENTS_ROOT.resolve()):
        return None, (FAIL, f"{JUDGMENTS_ENV} must name a file under data/")
    if not path.is_file():
        return None, (SKIPPED, f"no judgments file at {JUDGMENTS_ENV}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format_version") != JUDGMENTS_FORMAT:
            raise ValueError("unknown format_version")
        marks = {str(q): _judgment(e) for q, e in data["queries"].items()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None, (FAIL, "the judgments file is unreadable")
    return marks, ("", "")


def _score_recall(
    expect: Mapping[str, Any], env: Any, marks: Mapping[str, Judgment]
) -> Outcome:
    """recall@k = hits / min(k, relevant) and precision@k = hits / k over the top k
    matches, which must all be on the query's judged sheet. Numbers only in the
    detail, never a key. With no relevant row the query is skipped (left out of the
    mean) unless expect.none_relevant says that is the point."""
    if not env.ok or not isinstance(env.data, SimilarResult):
        return FAIL, f"no similar-listings result ({_kind(env)})"
    query, k = expect["query_id"], expect["k"]
    if query not in marks:
        return FAIL, "the query is not in the judgments file"
    top, judgment = _match_keys(env)[:k], marks[query]
    unjudged = len(set(top) - set(judgment.judged))
    if unjudged:
        # The index or data changed since the sheet was made: the marks do not apply.
        return FAIL, f"{unjudged} of the top {k} were not on the judged sheet"
    relevant = judgment.relevant
    hits = len(set(top) & relevant)
    precision = f"precision@{k} {hits / k:.2f}"
    if expect.get("none_relevant"):
        if relevant:
            return FAIL, f"{len(relevant)} rows marked relevant, none expected"
        return PASS, f"no row marked relevant, as intended; {precision}"
    if not relevant:
        return SKIPPED, "no row marked relevant; left out of the mean"
    recall = hits / min(k, len(relevant))
    return PASS, f"recall@{k} {recall:.2f}, {precision}, {len(relevant)} relevant"


def _judge_recall(expect: Mapping[str, Any], env: Any) -> Outcome:
    marks, why = load_judgments()
    return why if marks is None else _score_recall(expect, env, marks)


def check_recall_at_k(case: Case, raw: Mapping[str, Any]) -> Outcome:
    """Score the ranking against the human's marks. The marks are read first, so a
    run without them embeds nothing (each local embedding call is paid)."""
    marks, why = load_judgments()
    if marks is None:
        return why
    env, failed = _tool_envelope(raw, case.tool)
    if failed:
        return FAIL, failed
    return _score_recall(case.expect, env, marks)


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
    if _is_request(raw, case.tool):
        return FAIL, "a query would run (the filters validate)"
    return _judge_refusal(case.expect, call_tool(raw, case.tool))


def _route_step(call: ToolCall, subset: Mapping[str, Any]) -> Outcome:
    """Compare one routed call's arguments with its expected subset. As sent: a session
    argument (`mode`, `clear`), every argument of a tool with no validator (health),
    and every argument of an `update` call (a partial; the city carries over in code).
    The rest as `filters_subset` compares them (`from_input`, then accepted values)."""
    spec = TOOL_SPECS.get(call.name)
    partial = (
        spec is not None and spec.session and call.arguments.get("mode") == "update"
    )
    raw_keys = {
        k
        for k in subset
        if spec is None or partial or (spec.session and k in SESSION_ARGS)
    }
    missing = object()
    wrong = {
        k: call.arguments.get(k, "<unset>")
        for k in sorted(raw_keys)
        if call.arguments.get(k, missing) != subset[k]
    }
    if wrong:
        return FAIL, f"differs on {wrong}"
    rest = {k: v for k, v in subset.items() if k not in raw_keys}
    if not rest:
        return PASS, "arguments match"
    assert spec is not None  # a tool with no validator has no `rest`
    actual, why = _filters_or_fail(call.arguments, call.name)
    if actual is None:
        return FAIL, why
    return _match_subset({"filters": rest}, actual)


def route_options(
    expect: Mapping[str, Any],
) -> list[tuple[list[str], list[Mapping[str, Any]]]]:
    """Every route a routing case accepts, each with one argument subset per step
    ({} where none is pinned): the one `route` with its `filters`, or each
    `route_any_of` option with its item of `filters_any_of`."""
    if "route_any_of" in expect:
        options = [list(option) for option in expect["route_any_of"]]
        per_option = expect.get("filters_any_of")
        if per_option is None:
            per_option = [None] * len(options)
    else:
        options = [list(expect["route"])]
        per_option = [expect.get("filters")]
    return [
        (route, list(filters) if filters is not None else [{}] * len(route))
        for route, filters in zip(options, per_option, strict=True)
    ]


def check_route_exact(case: Case, calls: Sequence[ToolCall]) -> Outcome:
    """Pass when the tools called, in call order, equal expect.route exactly (or one
    of the expect.route_any_of options) and every non-empty argument subset of that
    route matches its step's arguments ({} skips a step). Tool names and argument
    values come from the case words, so they may be shown in the detail."""
    got = [call.name for call in calls]
    options = route_options(case.expect)
    for want, subsets in options:
        if got == want:
            return _route_steps(calls, got, subsets)
    if len(options) == 1:
        return FAIL, f"route {got}, want {options[0][0]}"
    return FAIL, f"route {got}, want any of {[want for want, _ in options]}"


def _route_steps(
    calls: Sequence[ToolCall],
    got: Sequence[str],
    subsets: Sequence[Mapping[str, Any]],
) -> Outcome:
    """Compare each routed call with its step's subset; `got`, the tool names in call
    order, already equals the expected route."""
    if not got:
        return PASS, "no tool call, as expected"
    problems, checked = [], 0
    for number, (call, subset) in enumerate(zip(calls, subsets, strict=True), 1):
        if not subset:
            continue
        checked += 1
        result, detail = _route_step(call, subset)
        if result != PASS:
            problems.append(f"step {number} {call.name}: {detail}")
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, f"route {got} in order; {checked} argument sets match"


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
    if isinstance(env.data, MarketStats):
        low = ", low sample" if env.data.low_sample else ""
        return f"market stats, {env.data.sample_count} sales{low}"
    if isinstance(env.data, SimilarResult):
        return f"similar, {len(env.data.matches)} matches"
    if isinstance(env.data, RecommendationResult):
        check = env.data.subject_check
        return (
            f"recommend, {len(env.data.recommendations)} listings, "
            f"{check.count} comps at {check.level or 'no level'}"
        )
    if isinstance(env.data, RagAnswer):
        if not env.data.found:
            return "rag, not found"
        return f"rag, {len(env.data.chunks)} chunks"
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


# A trend row in expect.stats lists exactly the MonthRow fields.
TREND_KEYS = frozenset({"month", "sample_count", "median_close_price"})


def _expect_stats_exact(expect: Mapping[str, Any]) -> str | None:
    stats = expect.get("stats")
    if not isinstance(stats, dict) or not stats:
        return "expect.stats must be a non-empty mapping"
    unknown = sorted(set(stats) - set(MarketStats.model_fields))
    if unknown:
        return f"expect.stats has keys MarketStats lacks: {unknown}"
    trend = stats.get("trend", [])
    if not isinstance(trend, list) or not all(
        isinstance(row, dict) and set(row) == TREND_KEYS for row in trend
    ):
        return f"expect.stats.trend must be a list of mappings of {sorted(TREND_KEYS)}"
    if "warning" in expect:
        return _compile_problem(expect["warning"], "expect.warning")
    return None


def _is_int(value: Any) -> bool:
    """An int that is not a bool (`true` in YAML is a mistake, not a number)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _expect_ranked_keys(expect: Mapping[str, Any]) -> str | None:
    keys = expect.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_SIMILAR_K:
        return f"expect.keys must be a list of 1 to {MAX_SIMILAR_K} listing keys"
    if not all(_is_int(k) for k in keys) or len(set(keys)) != len(keys):
        return "expect.keys must be distinct integers"
    # A case file is tracked: only the fixture's invented keys may be pinned.
    if not all(INVENTED_KEY.match(str(k)) for k in keys):
        return "expect.keys must be invented fixture keys (9 then 5-6 digits)"
    if "warning" in expect:
        return _compile_problem(expect["warning"], "expect.warning")
    return None


def _expect_recall_at_k(expect: Mapping[str, Any]) -> str | None:
    if not _nonempty_str(expect.get("query_id")):
        return "expect.query_id must be a non-empty string"
    k = expect.get("k")
    if not _is_int(k) or not 1 <= k <= MAX_SIMILAR_K:
        return f"expect.k must be an integer from 1 to {MAX_SIMILAR_K}"
    if "none_relevant" in expect and not isinstance(expect["none_relevant"], bool):
        return "expect.none_relevant must be true or false"
    return None


def _evidence_problem(value: Any, name: str) -> str | None:
    """Why `value` is not a non-empty mapping of CompEvidence fields, or None."""
    if not isinstance(value, dict) or not value:
        return f"{name} must be a non-empty mapping"
    unknown = sorted(set(value) - set(CompEvidence.model_fields))
    if unknown:
        return f"{name} has keys CompEvidence lacks: {unknown}"
    return None


def _expect_price_check_exact(expect: Mapping[str, Any]) -> str | None:
    problem = _evidence_problem(expect.get("subject"), "expect.subject")
    if problem is not None or "ranks" not in expect:
        return problem
    ranks = expect["ranks"]
    # ranks lists every recommendation (1 to n, each once); {} pins that none came.
    if not isinstance(ranks, dict) or not all(_is_int(r) for r in ranks):
        return "expect.ranks must be a mapping of rank numbers to CompEvidence fields"
    if sorted(ranks) != list(range(1, len(ranks) + 1)) or len(ranks) > RECOMMEND_MAX_K:
        return f"expect.ranks must list ranks 1 to n (n at most {RECOMMEND_MAX_K})"
    for rank, fields in sorted(ranks.items()):
        if problem := _evidence_problem(fields, f"expect.ranks.{rank}"):
            return problem
    return None


def _expect_chunks_from(expect: Mapping[str, Any]) -> str | None:
    top, sources = expect.get("top"), expect.get("sources")
    if not _is_int(top) or not 1 <= top <= RAG_TOP_K:
        return f"expect.top must be an integer from 1 to {RAG_TOP_K}"
    if not isinstance(sources, list) or not 1 <= len(sources) <= top:
        return "expect.sources must be a list of 1 to `top` chunk ids"
    if not all(isinstance(s, str) and CHUNK_ID.match(s) for s in sources):
        return "expect.sources entries must be chunk ids written doc#key"
    if len(set(sources)) != len(sources):
        return "expect.sources must be distinct"
    if "exact" in expect and not isinstance(expect["exact"], bool):
        return "expect.exact must be true or false"
    return None


def _expect_error_category(expect: Mapping[str, Any]) -> str | None:
    if expect.get("category") not in ERROR_CATEGORIES:
        return f"expect.category must be one of {sorted(ERROR_CATEGORIES)}"
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
    validator, whether valid filters make it call the tool body (a query, so a
    database, unless the tool reads none), and the judge a conversation turn uses
    on the envelope its call returned."""

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
    "stats_exact": _check(
        check_stats_exact,
        {"stats", "warning"},
        _expect_stats_exact,
        True,
        _judge_stats,
    ),
    "ranked_keys": _check(
        check_ranked_keys,
        {"keys", "warning"},
        _expect_ranked_keys,
        True,
        _judge_ranked,
    ),
    "recall_at_k": _check(
        check_recall_at_k,
        {"query_id", "k", "none_relevant"},
        _expect_recall_at_k,
        True,
        _judge_recall,
    ),
    "price_check_exact": _check(
        check_price_check_exact,
        {"subject", "ranks"},
        _expect_price_check_exact,
        True,
        _judge_price_check,
    ),
    "error_category": _check(
        check_error_category,
        {"category"},
        _expect_error_category,
        True,
        _judge_error,
    ),
    # rag_answer only; its tool reads no database (ToolSpec.database), so the flag
    # here only says that valid input makes the check call the tool body.
    "chunks_from": _check(
        check_chunks_from,
        {"sources", "top", "exact"},
        _expect_chunks_from,
        True,
        _judge_chunks,
    ),
}
# `human` is never executed: a reviewer decides, so it has no function. `turns`
# marks a conversation case; its turns use the entries above. Which checks a tool
# accepts is in TOOL_SPECS. `route_exact` (WO-013) names no tool and judges the
# model's tool calls, not a tool's result: check_route_exact, run by run_route.
KNOWN_CHECKS = frozenset(CHECKS) | {"human", "turns", ROUTE_CHECK}


# --- loading ---


def _case_problem(entry: Mapping[str, Any]) -> str | None:
    """Return why a case entry is malformed, or None when it is usable."""
    if entry.get("check") == ROUTE_CHECK:
        return _route_case_problem(entry)
    if "history" in entry:
        return f"history is only for {ROUTE_CHECK} cases"
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
    tool = entry.get("tool", DEFAULT_TOOL)
    if tool not in TOOLS:
        return f"unknown tool {entry.get('tool')!r}"
    if entry["check"] not in TOOL_SPECS[tool].checks:
        return f"check {entry['check']!r} is not available for tool {tool}"
    if entry.get("database", DEFAULT_CASE_DATABASE) not in CASE_DATABASES:
        return f"database must be one of {list(CASE_DATABASES)}"
    if "index_as_of" in entry and (problem := _index_as_of_problem(entry, tool)):
        return problem
    if is_turns:
        return _turns_problem(entry)
    return _input_problem(entry, entry["suite"]) or _expect_problem(
        entry["check"], entry["expect"]
    )


def _index_as_of_problem(entry: Mapping[str, Any], tool: str) -> str | None:
    """Why a case's `index_as_of` is unusable: it dates the CI fixture index, so only
    a ci find_similar_listings case may carry it, as a YYYY-MM-DD date."""
    if tool != SIMILAR_TOOL or entry["suite"] != "ci":
        return f"index_as_of is only for ci {SIMILAR_TOOL} cases"
    if not isinstance(entry["index_as_of"], date) or isinstance(
        entry["index_as_of"], datetime
    ):
        return "index_as_of must be a date written YYYY-MM-DD"
    return None


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
    tool = entry.get("tool", DEFAULT_TOOL)
    for number, turn in enumerate(turns, 1):
        problem = _turn_problem(turn, entry["suite"], tool)
        if problem is not None:
            return f"turn {number}: {problem}"
    return None


def _turn_problem(turn: Any, suite: str, tool: str = DEFAULT_TOOL) -> str | None:
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
    if turn["check"] not in TOOL_SPECS[tool].checks:
        return f"check {turn['check']!r} is not available for tool {tool}"
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


def _route_case_problem(entry: Mapping[str, Any]) -> str | None:
    """Why a routing case (`check: route_exact`) is malformed, or None. It names no
    tool (its route does), needs a model (never `ci`), and has `input` text."""
    if "tool" in entry:
        return f"a {ROUTE_CHECK} case has no tool key: expect.route names the tools"
    missing = [k for k in ROUTE_REQUIRED if k not in entry]
    if missing:
        return f"missing keys {missing}"
    unknown = sorted(set(entry) - ROUTE_ALLOWED)
    if unknown:
        return f"unknown keys {unknown}"
    for key in ("id", "category"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            return f"{key} must be a non-empty string"
    if entry["suite"] not in SUITES:
        return f"suite must be one of {list(SUITES)}"
    if entry["suite"] == "ci":
        return f"a {ROUTE_CHECK} case cannot be in the ci suite (it needs a model)"
    if not _nonempty_str(entry["input"]):
        return "input must be a non-empty string"
    if problem := _key_like_problem(entry["input"], "input"):
        return problem
    if "history" in entry and (problem := _history_problem(entry["history"])):
        return problem
    return _expect_route(entry["expect"])


def _key_like_problem(text: str, where: str) -> str | None:
    """Why routing words hold a number that could be a real listing key, or None.
    Every run of 6+ digits must be an invented fixture key; the number is not echoed.
    Write prices with commas ($1,080,000) or short ($1.5M)."""
    for number in LISTING_KEY_LIKE.findall(text):
        if not INVENTED_KEY.match(number):
            return (
                f"{where} holds a {len(number)}-digit number that is not an invented"
                " fixture key (9 then 5-6 digits)"
            )
    return None


def _history_problem(value: Any) -> str | None:
    """Why a routing case's `history` is unusable: a non-empty list of turns, each a
    mapping of `user` and `assistant` (non-empty strings, own words), and optionally
    `tool_calls` with `tool_result` (the calls made for that turn and the result text
    each got back), the two together or neither."""
    if not isinstance(value, list) or not value:
        return "history must be a non-empty list of {user, assistant} turns"
    for number, turn in enumerate(value, 1):
        where = f"history turn {number}"
        if (
            not isinstance(turn, dict)
            or not HISTORY_REQUIRED <= set(turn)
            or not set(turn) <= HISTORY_ALLOWED
            or not all(_nonempty_str(turn[k]) for k in HISTORY_REQUIRED)
        ):
            return (
                f"{where} must be a mapping of user and assistant, both non-empty"
                " strings, and optionally tool_calls with tool_result"
            )
        for key in ("user", "assistant"):
            if problem := _key_like_problem(turn[key], where):
                return problem
        if problem := _history_calls_problem(turn, where):
            return problem
    return None


def _history_calls_problem(turn: Mapping[str, Any], where: str) -> str | None:
    """Why a history turn's tool-call record is unusable, or None (a turn may have
    none). `tool_calls` is a list of 1 to 3 `{name, arguments}` records: a registered
    tool and a mapping of invented arguments (no `sender_id`; a `listing_key` is an
    invented fixture key). `tool_result` is the own-words text each call got back."""
    if ("tool_calls" in turn) != ("tool_result" in turn):
        return f"{where}: tool_calls and tool_result go together"
    if "tool_calls" not in turn:
        return None
    calls = turn["tool_calls"]
    if not isinstance(calls, list) or not calls or len(calls) > ROUTE_MAX_STEPS:
        return (
            f"{where}: tool_calls must be a list of 1 to {ROUTE_MAX_STEPS}"
            " {name, arguments} records"
        )
    for number, call in enumerate(calls, 1):
        at = f"{where} tool call {number}"
        if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
            return f"{at} must be a mapping of exactly name and arguments"
        name, arguments = call["name"], call["arguments"]
        if not isinstance(name, str) or name not in ROUTE_TOOLS:
            return f"{at} names unknown tool {name!r}; known: {sorted(ROUTE_TOOLS)}"
        if not isinstance(arguments, dict):
            return f"{at}: arguments must be a mapping"
        if "sender_id" in arguments:
            return f"{at}: arguments must not hold sender_id (sender-label rule)"
        key = arguments.get("listing_key")
        if key is not None and not (_is_int(key) and INVENTED_KEY.match(str(key))):
            return (
                f"{at}: listing_key must be an invented fixture key (9 then 5-6 digits)"
            )
        for value in arguments.values():
            if isinstance(value, str) and (problem := _key_like_problem(value, at)):
                return problem
    if not _nonempty_str(turn["tool_result"]):
        return f"{where}: tool_result must be a non-empty string"
    return _key_like_problem(turn["tool_result"], f"{where} tool_result")


def _expect_route(expect: Any) -> str | None:
    """Why a routing case's `expect` is unusable: `route` is a list of 0 to 3
    registered tool names and the optional `filters` is one mapping per route step;
    or, instead of both, `route_any_of` is a non-empty list of such routes (no route
    twice) and the optional `filters_any_of` holds one `filters` list per option."""
    if not isinstance(expect, dict):
        return "expect must be a mapping"
    unknown = sorted(set(expect) - ROUTE_EXPECT_KEYS)
    if unknown:
        return f"unknown expect keys {unknown} for {ROUTE_CHECK}"
    if "route_any_of" in expect:
        return _expect_route_any_of(expect)
    if "filters_any_of" in expect:
        return "expect.filters_any_of goes only with expect.route_any_of"
    if "route" not in expect:
        return "expect.route is missing ([] means no tool call)"
    if problem := _route_problem(expect["route"], "expect.route"):
        return problem
    if "filters" not in expect:
        return None
    return _route_filters_problem(
        expect["filters"], len(expect["route"]), "expect.filters"
    )


def _expect_route_any_of(expect: Mapping[str, Any]) -> str | None:
    """Why a `route_any_of` expectation is unusable, or None."""
    if "route" in expect or "filters" in expect:
        return (
            "expect has route_any_of, so no route or filters (each option's"
            " filters go in filters_any_of)"
        )
    options = expect["route_any_of"]
    if not isinstance(options, list) or not options:
        return (
            "expect.route_any_of must be a non-empty list of routes, each a list of"
            " tool names ([] means no tool call)"
        )
    for number, option in enumerate(options, 1):
        if problem := _route_problem(option, f"expect.route_any_of[{number}]"):
            return problem
    if len({tuple(option) for option in options}) != len(options):
        return "expect.route_any_of lists the same route twice"
    if "filters_any_of" not in expect:
        return None
    per_option = expect["filters_any_of"]
    if not isinstance(per_option, list) or len(per_option) != len(options):
        return (
            "expect.filters_any_of must be a list of one filters list per"
            " route_any_of option"
        )
    for number, (option, filters) in enumerate(
        zip(options, per_option, strict=True), 1
    ):
        where = f"expect.filters_any_of[{number}]"
        if problem := _route_filters_problem(filters, len(option), where):
            return problem
    return None


def _route_problem(route: Any, where: str) -> str | None:
    """Why one expected route is unusable: a list of 0 to 3 registered tool names."""
    if not isinstance(route, list):
        return f"{where} must be a list of tool names ([] means no tool call)"
    if len(route) > ROUTE_MAX_STEPS:
        return f"{where} lists at most {ROUTE_MAX_STEPS} tool calls"
    bad = [t for t in route if not isinstance(t, str) or t not in ROUTE_TOOLS]
    if bad:
        return f"{where} names unknown tools {bad}; known: {sorted(ROUTE_TOOLS)}"
    return None


def _route_filters_problem(filters: Any, steps: int, where: str) -> str | None:
    """Why one route's argument subsets are unusable: one mapping per step, with no
    `sender_id` and no `listing_key` outside the invented fixture pattern."""
    if not isinstance(filters, list) or len(filters) != steps:
        return f"{where} must be a list of one mapping per route step"
    for number, item in enumerate(filters, 1):
        if not isinstance(item, dict):
            return f"{where} item {number} must be a mapping ({{}} skips a step)"
        if "sender_id" in item:
            return SENDER_IN_FILTERS.replace("input_filters", where)
        key = item.get("listing_key")
        if key is not None and not (_is_int(key) and INVENTED_KEY.match(str(key))):
            return (
                f"{where} item {number}: listing_key must be an invented"
                " fixture key (9 then 5-6 digits)"
            )
    return None


def _history_turn(turn: Mapping[str, Any]) -> HistoryTurn:
    """A HistoryTurn from a validated `history` item."""
    calls = tuple(
        ToolCall(call["name"], dict(call["arguments"]))
        for call in turn.get("tool_calls") or ()
    )
    return HistoryTurn(
        user=turn["user"],
        assistant=turn["assistant"],
        tool_calls=calls,
        tool_result=turn.get("tool_result", ""),
    )


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
    history = tuple(_history_turn(t) for t in entry.get("history") or ())
    routed = entry["check"] == ROUTE_CHECK
    return Case(
        id=case_id,
        category=entry["category"],
        suite=entry["suite"],
        check=entry["check"],
        expect=entry.get("expect"),
        tool="" if routed else entry.get("tool", DEFAULT_TOOL),
        input=entry.get("input"),
        input_filters=entry.get("input_filters"),
        source=source,
        turns=turns,
        sender_id=entry.get("sender_id"),
        database=entry.get("database", DEFAULT_CASE_DATABASE),
        index_as_of=entry.get("index_as_of"),
        history=history,
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


def _load_semantic_fixture() -> Any:
    """Import tests/semantic_fixture.py by path (tests/ is no package)."""
    spec = importlib.util.spec_from_file_location("semantic_fixture", SEMANTIC_FIXTURE)
    if spec is None or spec.loader is None:
        raise ImportError("tests/semantic_fixture.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dated_copy(source: Path, target: Path, as_of: date) -> Path:
    """Copy a fixture index and set its meta.json active_as_of to `as_of` (the
    vector and key hashes are untouched, so it still loads)."""
    shutil.copytree(source, target)
    meta_path = target / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["active_as_of"] = as_of.isoformat()
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return target


class FixtureIndex:
    """The CI fixture index for the ci find_similar_listings and recommend cases.

    Built once per run in a temporary directory (invented rows, test:hashing, no paid
    call), a dated copy per `index_as_of`. `use` points the tool at one; `close`
    restores the settings, forgets the loaded index, and removes the directory."""

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._dirs: dict[date | None, Path] = {}
        self._saved: dict[str, str | None] = {}

    def use(self, as_of: date | None = None) -> Path:
        """Build on first use, then set the index settings for the next tool call."""
        if self._tmp is None:
            tmp = tempfile.TemporaryDirectory(prefix="idx-fixture-index-")
            try:
                base = Path(tmp.name) / "base"
                base.mkdir()
                built = Path(_load_semantic_fixture().build_fixture_index(base))
            except BaseException:
                tmp.cleanup()
                raise
            self._saved = {name: os.environ.get(name) for name in SEMANTIC_ENV}
            self._tmp, self._dirs = tmp, {None: built}
        if as_of not in self._dirs:
            target = Path(self._tmp.name) / f"as-of-{as_of}"
            self._dirs[as_of] = _dated_copy(self._dirs[None], target, as_of)
        path = self._dirs[as_of]
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        os.environ["IDX_SEMANTIC_INDEX_DIR"] = str(path)
        os.environ["IDX_EMBED_MODEL"] = FIXTURE_EMBED_MODEL
        os.environ["IDX_EMBED_DIMS"] = str(meta["dims"])
        return path

    def close(self) -> None:
        """Restore the settings, drop the tool's cached index, remove the directory."""
        if self._tmp is None:
            return
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        reset = getattr(mcp_server, "reset_semantic_for_tests", None)
        if callable(reset):
            reset()
        self._tmp.cleanup()
        self._tmp, self._dirs, self._saved = None, {}, {}


def _load_rag_fixture() -> Any:
    """Import tests/rag_fixture.py by path (tests/ is no package)."""
    spec = importlib.util.spec_from_file_location("rag_fixture", RAG_FIXTURE)
    if spec is None or spec.loader is None:
        raise ImportError("tests/rag_fixture.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RagFixtureIndex:
    """The ci rag_answer cases' document index (WO-012), built once per run in a temp
    directory from the own-words fixture corpus. `use` points the tool at it; `close`
    restores the settings, drops the cached index, and removes the directory."""

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._env: dict[str, str] = {}
        self._saved: dict[str, str | None] = {}

    def use(self) -> None:
        """Build on first use, then set the index settings for the next tool call."""
        if self._tmp is None:
            tmp = tempfile.TemporaryDirectory(prefix="idx-rag-fixture-")
            try:
                fixture = _load_rag_fixture()
                path = fixture.build_fixture_index(
                    Path(tmp.name), route=RAG_FIXTURE_ROUTE
                )
                env = dict(fixture.fixture_env(path))
            except BaseException:
                tmp.cleanup()
                raise
            self._saved = {name: os.environ.get(name) for name in env}
            self._tmp, self._env = tmp, env
        os.environ.update(self._env)

    def close(self) -> None:
        """Restore the settings, drop the tool's cached index, remove the directory."""
        if self._tmp is None:
            return
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        reset = getattr(mcp_server, "reset_rag_for_tests", None)
        if callable(reset):
            reset()
        self._tmp.cleanup()
        self._tmp, self._env, self._saved = None, {}, {}


class RunContext:
    """Per-run state: the database probe (once, on first need), whether a missing
    database fails a case, the database kind, the CI fixture indexes, and for the
    local suite `fill` (words to one tool call) and `route` (a routing case's words
    and history to its tool calls). Call close()."""

    def __init__(
        self,
        fill: Callable[..., dict[str, Any] | None] | None = None,
        require_database: bool = False,
        database_kind: str = "fixture",
        route: Callable[..., list[ToolCall]] | None = None,
    ):
        self.fill = fill
        self.route = route
        self.require_database = require_database
        self.database_kind = database_kind
        self.database: bool | None = None
        self.fixture_index = FixtureIndex()
        self.rag_index = RagFixtureIndex()

    def database_available(self) -> bool:
        """Probe db_pool.database_configured() once and remember the answer."""
        if self.database is None:
            self.database = bool(db_pool.database_configured())
        return self.database

    def close(self) -> None:
        """Release the CI fixture indexes that were built (the document index first)."""
        try:
            self.rag_index.close()
        finally:
            self.fixture_index.close()


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

    A query-running check skips with no database, or fails under require_database
    (rag_answer reads none and always runs); a fixture-only case skips on a
    real-database run. Conversations go through run_turns; an exception fails."""
    ctx = ctx or RunContext()
    if case.check == "human" or case.suite == "manual":
        return _record(case, MANUAL, "for a reviewer; not executed")
    if case.database == "fixture" and ctx.database_kind == "real":
        # Its numbers hold only for the fixture rows: not a failure, never required.
        return _record(case, SKIPPED, FIXTURE_ONLY_SKIP)
    if case.check == ROUTE_CHECK:
        # The trace (calls, model_calls, reply_preview) goes to the JSON report
        # entry only; print_table shows its fixed columns and never these.
        trace: dict[str, Any] = {}
        try:
            result, detail = run_route(case, ctx, trace)
        except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
            result, detail = FAIL, f"error {type(exc).__name__}: {exc}"[:200]
        return {**_record(case, result, detail), **trace}
    try:
        if case.check == "turns":
            result, detail = run_turns(case, ctx)
            return _record(case, result, detail)
        if case.input_filters is not None:
            raw: dict[str, Any] | None = dict(case.input_filters)
        elif ctx.fill is None:
            return _record(case, SKIPPED, "needs a model (local suite)")
        else:
            raw = ctx.fill(case.input or "", tool=case.tool)
            raw = None if raw is None else _without_sender(raw)
        if raw is None:
            # The model made no tool call: that is exactly what a refusal asks for.
            if case.check == "refusal":
                return _record(case, PASS, "declined: no tool call")
            return _record(case, FAIL, "the model made no tool call")
        spec = CHECKS[case.check]
        if spec.needs_database and _is_request(raw, case.tool):
            # A tool that reads no database (rag_answer) never probes for one.
            if TOOL_SPECS[case.tool].database and not ctx.database_available():
                if ctx.require_database:
                    return _record(case, FAIL, NO_DATABASE_REQUIRED)
                return _record(case, SKIPPED, "no database")
            # A ci similar-listings or recommend case ranks over the CI fixture
            # index, and a ci document case reads the fixture document index; a
            # local case uses the index the settings already name.
            if case.tool in INDEXED_TOOLS and case.suite == "ci":
                ctx.fixture_index.use(case.index_as_of)
            if case.tool == RAG_TOOL and case.suite == "ci":
                ctx.rag_index.use()
        result, detail = spec.run(case, raw)
    except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
        result, detail = FAIL, f"error {type(exc).__name__}: {exc}"[:200]
    return _record(case, result, detail)


def run_route(
    case: Case, ctx: RunContext, trace: dict[str, Any] | None = None
) -> Outcome:
    """Run a routing case: the model gets every skill and tool, each call is answered
    with the stub, and the calls are judged by check_route_exact. No tool body runs
    and no database is probed. Skipped without the local model. `trace` is filled
    by the driver for the report entry (see model_route)."""
    if ctx.route is None:
        return SKIPPED, "needs a model (local suite)"
    try:
        calls = ctx.route(case.input or "", case.history, trace)
    except TooManyCalls as exc:
        return FAIL, str(exc)
    return check_route_exact(case, calls)


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
    env = call_tool(raw, case.tool)
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
    database_kind: str = "fixture",
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    temperature_omitted: bool = False,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Write the JSON report (run time UTC, suite, commit, results, counts).
    `database` is the probe's answer (None when no case needed one); the other
    arguments record the run's flags: --database-kind, --skills-dir,
    --no-temperature, and --reasoning-effort (None when not given)."""
    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": suite,
        "git_commit": _git_commit(),
        "database_configured": database,
        "database_kind": database_kind,
        "require_database": require_database,
        "skills_dir": str(Path(skills_dir).resolve()),
        "temperature_omitted": temperature_omitted,
        "reasoning_effort": reasoning_effort,
        "counts": counts(records),
        "cases": list(records),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


# --- local driver (paid; urllib only; never called by the ci suite or the tests) ---


def _openai_function(tool: Any) -> dict[str, Any]:
    """One registered MCP tool as an OpenAI function definition."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }


def tool_schema(name: str = "search_listings") -> dict[str, Any]:
    """The tool as an OpenAI function definition, from the MCP server's registration."""
    tools = asyncio.run(mcp_server.server.list_tools())
    return _openai_function(next(t for t in tools if t.name == name))


def all_tool_schemas() -> list[dict[str, Any]]:
    """Every registered tool, in registration order, as OpenAI function definitions
    (the routing mode sends them all, as the gateway does)."""
    return [_openai_function(t) for t in asyncio.run(mcp_server.server.list_tools())]


def _load_merge_script() -> Any:
    """Import scripts/openclaw_merge_config.py by path, for its JSON5 reader."""
    spec = importlib.util.spec_from_file_location("openclaw_merge", MERGE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RoutingSetupError("scripts/openclaw_merge_config.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured_skills(config: Path = OPENCLAW_CONFIG) -> list[str]:
    """The idx agent's skill list, in the config's order (what the gateway shows)."""
    try:
        data = _load_merge_script().load_json5(Path(config))
        skills = data["agents"]["entries"][ROUTING_AGENT]["skills"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RoutingSetupError(f"no skill list in {config}: {exc}"[:200]) from exc
    if not isinstance(skills, list) or not all(_nonempty_str(s) for s in skills):
        raise RoutingSetupError(f"the {ROUTING_AGENT} skill list in {config} is bad")
    return list(skills)


def skill_parts(name: str, skills_dir: Path = DEFAULT_SKILLS_DIR) -> tuple[str, str]:
    """A skill's frontmatter description and its body (frontmatter stripped), read
    from <skills_dir>/<name>/SKILL.md; the frontmatter name must equal `name`."""
    path = Path(skills_dir) / name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RoutingSetupError(f"no skill file for {name!r} at {path}") from exc
    match = FRONTMATTER.match(text)
    if match is None:
        raise RoutingSetupError(f"{path}: no --- frontmatter")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise RoutingSetupError(f"{path}: the frontmatter is not YAML") from exc
    if not isinstance(meta, dict) or meta.get("name") != name:
        raise RoutingSetupError(f"{path}: the frontmatter name is not {name!r}")
    description = meta.get("description")
    if not _nonempty_str(description):
        raise RoutingSetupError(f"{path}: no frontmatter description")
    return " ".join(description.split()), match.group(2).strip()


def routing_prompt(
    skill_names: Sequence[str], skills_dir: Path = DEFAULT_SKILLS_DIR
) -> str:
    """The routing mode's system prompt: the base prompt, then the MCP server's
    `instructions` (the string the live model always sees, and the one the routing
    contract test pins), then every skill as its name and description (the list the
    gateway shows), then every skill body with its frontmatter stripped, all in the
    order given (the config's)."""
    parts = [(name, *skill_parts(name, skills_dir)) for name in skill_names]
    listed = "\n".join(f"- {name}: {description}" for name, description, _ in parts)
    bodies = "\n\n".join(f"## Skill: {name}\n\n{body}" for name, _, body in parts)
    return (
        f"{ROUTING_PROMPT}\n\n{SERVER_INSTRUCTIONS_HEADING}\n"
        f"{mcp_server.server.instructions}\n\nSkills:\n{listed}\n\n"
        f"Skill instructions, in the same order:\n\n{bodies}"
    )


def _routed_call(call: Mapping[str, Any]) -> ToolCall:
    """One tool call from a model reply: the name without the idx__ prefix, the
    arguments with nulls and sender_id dropped."""
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    name = name.removeprefix(TOOL_PREFIX)
    args = json.loads(function.get("arguments") or "{}")
    if not isinstance(args, dict):
        raise ValueError("tool-call arguments are not an object")
    kept = {k: v for k, v in args.items() if v is not None and k != "sender_id"}
    return ToolCall(name, kept)


@dataclass(frozen=True)
class RouteShape:
    """How every routing request of a run is shaped, from the flags: `--no-temperature`
    leaves `temperature` out; `--reasoning-effort` adds `reasoning_effort`."""

    omit_temperature: bool = False
    reasoning_effort: str | None = None

    def apply(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """The payload as this run sends it."""
        out = dict(payload)
        if self.omit_temperature:
            out.pop("temperature", None)
        if self.reasoning_effort is not None:
            out["reasoning_effort"] = self.reasoning_effort
        return out

    def describe(self) -> str:
        """The plan's line for the routing request shape."""
        temperature = "omitted (--no-temperature)" if self.omit_temperature else "0"
        effort = (
            f"{self.reasoning_effort!r} (--reasoning-effort)"
            if self.reasoning_effort is not None
            else "not sent"
        )
        return f"routing requests: temperature {temperature}; reasoning_effort {effort}"


# No flag given: temperature 0 and no reasoning_effort, as the single-tool path sends.
PLAIN_SHAPE = RouteShape()


def _provider_message(exc: urllib.error.HTTPError, api_key: str) -> str:
    """A short fragment of the provider's error text: its `error.message` when the body
    is JSON, else the body; whitespace collapsed; the key and key-like runs masked."""
    try:
        body = exc.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        body = ""
    try:
        text = str(json.loads(body)["error"]["message"])
    except (ValueError, KeyError, TypeError):
        text = body
    text = " ".join(text.split())
    if api_key:
        text = text.replace(api_key, "<key>")
    text = API_KEY_LIKE.sub("<key>", text)
    return text[:PROVIDER_MESSAGE_CHARS] or "(no message)"


def _post_routed(
    payload: Mapping[str, Any], api_key: str, shape: RouteShape
) -> dict[str, Any]:
    """Send one routing request, shaped by the run's flags. An HTTP 400 raises
    ProviderRejected with the provider's message fragment (never the key), which
    fails the case; nothing is resent. Any other error is raised as it came."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        return _post_json(OPENAI_URL, shape.apply(payload), headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        message = _provider_message(exc, api_key)
    raise ProviderRejected(f"HTTP 400 from the provider: {message}")


def history_call_id(turn: int, number: int) -> str:
    """The id of the `number`th tool call of history turn `turn` (both from 1): the
    same id on the assistant's call and on the tool message that answers it."""
    return f"call_history_{turn}_{number}"


def route_history_messages(history: RouteHistory) -> list[dict[str, Any]]:
    """A routing case's earlier turns as chat messages, in order. A plain turn is the
    user's words, then the reply. A turn with tool-call records is the user's words,
    one assistant message carrying the call(s) in the provider's format, one tool
    message per call holding the turn's result text in an envelope's shape,
    {"ok": true, "message": <text>} (ids matching), then the reply."""
    messages: list[dict[str, Any]] = []
    for number, turn in enumerate(history, 1):
        if not isinstance(turn, HistoryTurn):
            said, reply = turn
            turn = HistoryTurn(said, reply)
        messages.append({"role": "user", "content": turn.user})
        ids = [history_call_id(number, n) for n in range(1, len(turn.tool_calls) + 1)]
        if turn.tool_calls:
            requested = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call_id, call in zip(ids, turn.tool_calls, strict=True)
            ]
            messages.append(
                {"role": "assistant", "content": None, "tool_calls": requested}
            )
            result = json.dumps({"ok": True, "message": turn.tool_result})
            messages += [
                {"role": "tool", "tool_call_id": call_id, "content": result}
                for call_id in ids
            ]
        messages.append(
            {"role": "assistant", "content": turn.assistant or "(no reply)"}
        )
    return messages


def model_route(
    text: str,
    model: str,
    api_key: str,
    history: RouteHistory = (),
    max_calls: int = ROUTE_MAX_CALLS,
    *,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    prompt: str | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    shape: RouteShape = PLAIN_SHAPE,
    trace: dict[str, Any] | None = None,
) -> list[ToolCall]:
    """Send `text` (after `history`, see route_history_messages) with every skill and
    tool; return the tool calls in order. Each call gets ROUTE_STUB_RESULT and the
    model is called again until a reply with no call (TooManyCalls at `max_calls`).
    `shape` is the flags' request shape; `trace` (report only) gets `calls`,
    `model_calls`, `reply_preview` (final text, collapsed, 200 chars; "" on a call)."""
    if prompt is None:
        prompt = routing_prompt(configured_skills(), skills_dir)
    tools = list(all_tool_schemas() if tools is None else tools)
    messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
    messages += route_history_messages(history)
    messages.append({"role": "user", "content": text})
    calls: list[ToolCall] = []
    trace = {} if trace is None else trace
    trace.update({"calls": [], "model_calls": 0, "reply_preview": ""})
    for _ in range(max_calls):
        payload = {
            "model": model,
            "temperature": 0,
            "messages": list(messages),
            "tools": tools,
            "tool_choice": "auto",
        }
        reply = _post_routed(payload, api_key, shape)
        trace["model_calls"] += 1
        message = reply["choices"][0]["message"]
        requested = message.get("tool_calls") or []
        if not requested:
            text_reply = " ".join(str(message.get("content") or "").split())
            trace["reply_preview"] = text_reply[:REPLY_PREVIEW_CHARS]
            return calls
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": requested,
            }
        )
        for call in requested:
            calls.append(_routed_call(call))
            trace["calls"].append(
                {"name": calls[-1].name, "argument_keys": sorted(calls[-1].arguments)}
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": ROUTE_STUB_RESULT,
                }
            )
    raise TooManyCalls(calls, max_calls)


def _model_route(
    model: str,
    api_key: str,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    shape: RouteShape = PLAIN_SHAPE,
) -> Callable[..., list[ToolCall]]:
    """The local suite's router: the routing prompt and all tool schemas are built
    once, on the first routing case, then sent with every case's words, each request
    shaped by the run's flags (`shape`)."""
    built: dict[str, Any] = {}

    def route(
        text: str, history: RouteHistory = (), trace: dict[str, Any] | None = None
    ) -> list[ToolCall]:
        if not built:
            built["prompt"] = routing_prompt(configured_skills(), skills_dir)
            built["tools"] = all_tool_schemas()
        return model_route(
            text,
            model,
            api_key,
            history,
            prompt=built["prompt"],
            tools=built["tools"],
            shape=shape,
            trace=trace,
        )

    return route


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

    The system prompt is that tool's (base prompt plus its skill body). `history`
    holds earlier turns as (user words, reply text) message pairs. Arguments that
    are null are dropped, as the MCP entry point does.
    """
    prompt = system_prompt(schema["function"]["name"])
    messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
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


def _model_fill(model: str, api_key: str) -> Callable[..., dict[str, Any] | None]:
    """The local suite's fill: send only the case's own tool schema (read once per
    tool from the server's registration) and that tool's system prompt."""
    schemas: dict[str, dict[str, Any]] = {}

    def fill(
        text: str, history: History = (), tool: str = DEFAULT_TOOL
    ) -> dict[str, Any] | None:
        if tool not in schemas:
            schemas[tool] = tool_schema(tool)
        return model_tool_call(text, schemas[tool], model, api_key, history)

    return fill


def _describe(case: Case) -> str:
    """What the plan prints for a case: its words, or its turns' words in order."""
    if case.turns:
        steps = [t.input if t.input is not None else "<filters>" for t in case.turns]
        return f"{len(steps)} turns: " + " | ".join(steps)
    if case.check == ROUTE_CHECK:
        count = len(case.history)
        earlier = f"after {count} earlier turn{'s' * (count != 1)}: " if count else ""
        return f"{earlier}{case.input} (up to {ROUTE_MAX_CALLS} chat calls)"
    return case.input if case.input is not None else "input_filters (no model)"


def _chat_calls(case: Case) -> int:
    """The most chat requests a local case can send (embedding calls not counted)."""
    if case.check == ROUTE_CHECK:
        return ROUTE_MAX_CALLS
    if case.check == "human":
        return 0
    if case.turns:
        return sum(t.input is not None for t in case.turns)
    return 1 if case.input is not None else 0


def routing_problem(skills_dir: Path = DEFAULT_SKILLS_DIR) -> str | None:
    """Why the routing prompt cannot be built from `skills_dir` (files only, no
    call), or None when it can."""
    try:
        routing_prompt(configured_skills(), skills_dir)
    except RoutingSetupError as exc:
        return str(exc)
    return None


def _routing_setup(skills_dir: Path, shape: RouteShape, out: Any) -> str | None:
    """Print where the routing skills come from and the request shape; return why
    the routing prompt cannot be built from them, or None."""
    print(f"  routing skills from: {Path(skills_dir).resolve()}", file=out)
    print(f"  {shape.describe()}", file=out)
    problem = routing_problem(skills_dir)
    if problem is not None:
        print(f"  routing prompt: cannot be built ({problem})", file=out)
    return problem


def _local_plan(
    cases: Sequence[Case],
    allow_paid: bool,
    out: Any = None,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    shape: RouteShape = PLAIN_SHAPE,
) -> tuple[bool, str | None]:
    """Print what the local suite would run and what it needs (variable values never,
    only whether each is set). Returns (ready, the routing prompt's problem or None);
    the prompt is built only when routing cases are selected."""
    out = out or sys.stdout
    print(f"Local suite: {len(cases)} cases selected.", file=out)
    for case in cases:
        print(f"  {case.id} [{case.check}] {_describe(case)}", file=out)
    routed = sum(case.check == ROUTE_CHECK for case in cases)
    problem = None
    if routed:
        print(
            f"  chat calls: at most {sum(_chat_calls(c) for c in cases)} ({routed}"
            f" routing cases at up to {ROUTE_MAX_CALLS} each; a refused request"
            " fails its case and is never resent)",
            file=out,
        )
        problem = _routing_setup(skills_dir, shape, out)
    prompt_ok = problem is None
    ready = allow_paid
    for name in LOCAL_ENV:
        is_set = bool(os.environ.get(name))
        ready = ready and is_set
        print(f"  needs {name}: {'set' if is_set else 'missing'}", file=out)
    print(f"  needs --allow-paid: {'given' if allow_paid else 'missing'}", file=out)
    print(PAID_NOTICE, file=out)
    if not ready:
        print("Not running: set both variables and pass --allow-paid.", file=out)
    elif not prompt_ok:
        print("Not running: the routing prompt cannot be built (above).", file=out)
    return ready and prompt_ok, problem


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
        "--database-kind",
        choices=DATABASE_KINDS,
        default="fixture",
        help="real: skip the `database: fixture` cases (default fixture runs all)",
    )
    p.add_argument(
        "--allow-tracing",
        action="store_true",
        help="keep IDX_OTLP_ENDPOINT and IDX_LOG_FILE (both are blanked by default)",
    )
    p.add_argument(
        "--skills-dir",
        type=Path,
        default=DEFAULT_SKILLS_DIR,
        metavar="PATH",
        help=(
            "routing cases only: the skills folder the routing prompt reads (default"
            " the repo's skills/; e.g. a checkout of unchanged skills for a baseline)"
        ),
    )
    p.add_argument(
        "--no-temperature",
        action="store_true",
        help="routing cases only: leave `temperature` out of every routing request",
    )
    p.add_argument(
        "--reasoning-effort",
        default=None,
        metavar="VALUE",
        help=(
            "routing cases only: send `reasoning_effort` with this value (for example"
            " none) in every routing request"
        ),
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected cases, print the table, write the report. Exit 1 when a case
    failed, a case file is malformed, or the selection is empty or outside the suite;
    else 0. A local run without both variables and --allow-paid prints its plan only
    (exit 1 when a selected routing case's prompt cannot be built). A bad
    --skills-dir or --reasoning-effort is a usage error (exit 2)."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not Path(args.skills_dir).is_dir():
        parser.error(f"--skills-dir {args.skills_dir}: no such directory")
    effort = args.reasoning_effort
    if effort is not None and not re.fullmatch(r"[a-z]+", effort):
        parser.error("--reasoning-effort takes one lower-case word, such as none")
    shape = RouteShape(args.no_temperature, effort)
    if not args.allow_tracing:
        # A ci run calls the tool body without the root span, so it would export
        # orphan stage spans (and append eval lines to the server's log file).
        for name in TRACING_ENV:
            os.environ[name] = ""
    cases, errors = load_cases(args.cases_dir)
    chosen, missing = select_cases(cases, args.suite, args.category, args.case)
    errors += missing
    in_ci = os.environ.get("CI", "").strip().lower() == "true"
    ctx = RunContext(
        require_database=args.require_database or in_ci,
        database_kind=args.database_kind,
    )
    if args.suite == "local":
        ready, problem = _local_plan(
            chosen, args.allow_paid, skills_dir=args.skills_dir, shape=shape
        )
        if not ready:
            for err in errors:
                print(f"load error: {err.source}: {err.message}")
            return 1 if errors or problem is not None else 0
        model, api_key = os.environ["IDX_EVAL_MODEL"], os.environ["OPENAI_API_KEY"]
        ctx.fill = _model_fill(model, api_key)
        ctx.route = _model_route(model, api_key, args.skills_dir, shape)
    records = [_error_record(e) for e in errors]
    try:
        records += [run_case(case, ctx) for case in chosen]
    finally:
        ctx.close()
    print_table(records)
    write_report(
        args.out,
        args.suite,
        records,
        ctx.database,
        ctx.require_database,
        ctx.database_kind,
        args.skills_dir,
        shape.omit_temperature,
        shape.reasoning_effort,
    )
    print(f"report: {args.out}")
    return 1 if any(r["result"] == FAIL for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
