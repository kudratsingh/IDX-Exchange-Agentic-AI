"""WO-014 R5: every error message the six tools can return is one plain sentence.

Messages are collected by an AST walk of src/idx_agent (ToolError and the `_*_error`
helpers) and from real error envelopes; `to_channel` must never carry `detail`.
No database, no network, no model.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import socket
from pathlib import Path
from typing import Any, get_args

import pymysql
import pytest

from idx_agent.domain.models import to_channel
from idx_agent.domain.results import (
    AgentResult,
    ErrorCategory,
    Provenance,
    ToolError,
)
from idx_agent.mcp_server import server
from idx_agent.observability.logging import new_trace_id

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Two retry tails five db and provider messages end with. Tolerated here only while a
# human decision is pending (WO-014 requirement 4, Status Pending 3); not an accepted
# form. The text before a tail must itself be one sentence. Empty this once decided.
RETRY_HINTS = ("Please try again later.", "Please try again.")
# Planted in every `detail` and every raised exception; it must never reach a channel.
SENTINEL = "SENTINEL-detail-7f3a /srv/idx/data/index.npy OperationalError"

_TRACE_ID = re.compile(r"[0-9a-fA-F]{16,}")
_PATH = re.compile(
    r"(?:^|[\s'\"(=])(?:~|\.{1,2})?/\w"  # /abs, ~/home, ./rel, ../up
    r"|[A-Za-z]:\\"  # C:\ drive paths
    r"|\b\w[\w.-]*/[\w.-]+"  # dir/file
    r"|\.(?:py|pyc|env|json5?|ya?ml|log|npy|npz|sql|sock|txt|pkl)\b"
)
_EXCEPTION = re.compile(r"\b\w*(?:Error|Exception)\b")
_HOST = re.compile(
    r"\blocalhost\b|\b\d{1,3}(?:\.\d{1,3}){3}\b|::1\b|\b[\w.-]+:\d{2,5}\b"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|local|internal|lan|example)\b",
    re.IGNORECASE,
)


def message_problems(text: str) -> list[str]:
    """Every rule `text` breaks as a user-facing error message (empty when clean)."""
    problems: list[str] = []
    if "\n" in text or "\r" in text:
        problems.append("newline")
    core = text
    for hint in RETRY_HINTS:
        if text.endswith(" " + hint):
            core = text[: -len(hint) - 1]
            break
    if not core.strip() or core.rstrip()[-1] not in ".?":
        problems.append("no terminal period or question mark")
    elif len(re.findall(r"[.?!](?=\s|$)", core)) != 1:
        problems.append("more than one sentence")
    if _TRACE_ID.search(text):
        problems.append("trace id pattern")
    if _PATH.search(text):
        problems.append("filesystem path")
    if _EXCEPTION.search(text):
        problems.append("exception class name")
    if "Traceback" in text:
        problems.append("traceback")
    host = socket.gethostname().split(".")[0].lower()
    if _HOST.search(text) or (len(host) > 3 and host in text.lower()):
        problems.append("server host name")
    return problems


def detail_leaks(payload: Any, where: str = "$") -> list[str]:
    """Paths of every `detail` key, or planted sentinel, in a channel payload."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "detail":
                found.append(f"{where}.detail")
            found += detail_leaks(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for i, value in enumerate(payload):
            found += detail_leaks(value, f"{where}[{i}]")
    elif isinstance(payload, str) and "SENTINEL" in payload:
        found.append(where)
    return found


def _module_for(path: Path) -> Any:
    """Import the module at a path under src/ by its dotted name."""
    dotted = ".".join(path.relative_to(SRC).with_suffix("").parts)
    return importlib.import_module(dotted)


def _message_args(tree: ast.Module) -> list[ast.expr]:
    """The `message` argument of every ToolError(...) or `_*_error(...)` call."""
    helpers: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and re.fullmatch(r"_\w+_error", node.name):
            params = [a.arg for a in node.args.args]
            if "message" in params:
                helpers[node.name] = params
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "ToolError" and name not in helpers:
            continue
        found += [kw.value for kw in node.keywords if kw.arg == "message"]
        if name in helpers and len(node.args) > helpers[name].index("message"):
            found.append(node.args[helpers[name].index("message")])
    return found


def collect_error_messages() -> tuple[dict[str, str], list[str]]:
    """Walk src/idx_agent; returns ({message: where}, [unresolvable sites])."""
    messages: dict[str, str] = {}
    unresolved: list[str] = []
    for path in sorted((SRC / "idx_agent").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        args = _message_args(tree)
        module = _module_for(path) if args else None
        for arg in args:
            where = f"{path.relative_to(ROOT)}:{arg.lineno}"
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                messages.setdefault(arg.value, where)
            elif isinstance(arg, ast.Name) and isinstance(
                getattr(module, arg.id, None), str
            ):
                messages.setdefault(getattr(module, arg.id), where)
            elif not (isinstance(arg, ast.Name) and arg.id == "message"):
                unresolved.append(where)  # an f-string or expression: uncheckable
    return messages, unresolved


MESSAGES, UNRESOLVED = collect_error_messages()


def test_the_walk_finds_the_known_messages_and_nothing_dynamic():
    """The walk sees every named constant and no message it cannot check."""
    assert UNRESOLVED == []
    for known in (
        server.NOT_SET_UP_MESSAGE,
        server.PROVIDER_MESSAGE,
        server.NOT_ACTIVE_MESSAGE,
        server.RAG_NOT_SET_UP_MESSAGE,
        server.RAG_INTERNAL_MESSAGE,
        "The tool failed; the trace id was logged.",
    ):
        assert known in MESSAGES
    assert len(MESSAGES) >= 12


@pytest.mark.parametrize("message", sorted(MESSAGES))
def test_each_error_message_is_one_plain_sentence(message):
    assert message_problems(message) == [], MESSAGES[message]


def test_to_channel_of_every_category_drops_detail():
    """Each category, as a bare ToolError and inside an AgentResult."""
    categories = get_args(ErrorCategory)
    assert len(categories) == 8
    for category in categories:
        for message in MESSAGES:
            trace_id = new_trace_id()
            error = ToolError(
                category=category, message=message, detail=SENTINEL, trace_id=trace_id
            )
            envelope = AgentResult[Any](
                ok=False,
                provenance=Provenance(tool="health", trace_id=trace_id),
                error=error,
            )
            for payload in (to_channel(error), to_channel(envelope)):
                assert detail_leaks(payload) == []
                assert SENTINEL not in json.dumps(payload)
            assert message_problems(to_channel(envelope)["error"]["message"]) == []


def _raise_db(*_args: Any, **_kwargs: Any) -> Any:
    raise pymysql.err.OperationalError(2003, f"no route to db.internal:3306 {SENTINEL}")


BODIES = {
    "search_listings": (server.search_result, {"city": "Pasadena"}),
    "get_market_stats": (server.market_result, {"city": "Pasadena"}),
    "recommend": (server.recommend_result, {"listing_key": 9130002, "k": 0}),
}


@pytest.mark.parametrize("reachable", [False, True], ids=["unset", "failing"])
@pytest.mark.parametrize("tool", sorted(BODIES))
def test_real_db_error_envelopes_are_clean(monkeypatch, tool, reachable):
    """A database that is not configured, or raises, gives a clean `db` error."""
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: reachable)
    monkeypatch.setattr(server.db_pool, "connect", _raise_db)
    body, raw = BODIES[tool]
    payload = to_channel(body(raw, trace_id=new_trace_id()))
    assert payload["ok"] is False and payload["error"]["category"] == "db"
    assert detail_leaks(payload) == []
    assert payload["error"]["message"] in MESSAGES
    assert message_problems(payload["error"]["message"]) == []


@pytest.mark.parametrize(
    ("body", "raw"),
    [
        (server.similar_result, {"text": "a quiet craftsman with a big yard"}),
        (server.rag_result, {"question": "what does DOM mean?"}),
    ],
    ids=["find_similar_listings", "rag_answer"],
)
def test_not_set_up_envelopes_are_clean(monkeypatch, body, raw):
    """No index configured: the not-set-up sentence, and nothing else."""
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", "")
    monkeypatch.setenv("IDX_RAG_INDEX_DIR", "")
    server.reset_semantic_for_tests()
    server.reset_rag_for_tests()
    payload = to_channel(body(raw, trace_id=new_trace_id()))
    assert payload["error"]["category"] == "not_found"
    assert detail_leaks(payload) == []
    assert payload["error"]["message"] in MESSAGES
    assert message_problems(payload["error"]["message"]) == []


def test_a_raising_body_becomes_the_clean_internal_error():
    """`_guarded` turns an exception into the fixed internal sentence."""

    def body(trace_id: str) -> Any:
        raise RuntimeError(SENTINEL)

    payload = server._guarded("health", body)
    assert payload["error"]["category"] == "internal"
    assert detail_leaks(payload) == [] and SENTINEL not in json.dumps(payload)
    assert message_problems(payload["error"]["message"]) == []


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        ("The search failed. The index is gone.", "more than one sentence"),
        ("The search failed", "no terminal period or question mark"),
        ("The search failed.\nTry again.", "newline"),
        ("The search failed (trace 0123456789abcdef).", "trace id pattern"),
        ("The index at /srv/idx/data is missing.", "filesystem path"),
        ("The index in data/indexes is missing.", "filesystem path"),
        ("The file settings.env is unreadable.", "filesystem path"),
        ("The search raised OperationalError.", "exception class name"),
        ("The search raised a KeyError.", "exception class name"),
        ("Traceback follows for the failed search.", "traceback"),
        ("The search could not reach localhost.", "server host name"),
        ("The search could not reach 10.0.0.12.", "server host name"),
        ("The search could not reach db.internal.", "server host name"),
        ("The search could not reach mysql:3306.", "server host name"),
    ],
)
def test_the_checks_bite_on_a_bad_message(bad, problem):
    assert problem in message_problems(bad)


def test_the_detail_check_bites_on_a_leaking_payload():
    leaking = {"ok": False, "error": {"message": "It failed.", "detail": "x"}}
    assert detail_leaks(leaking) == ["$.error.detail"]
    assert detail_leaks({"warnings": [SENTINEL]}) == ["$.warnings[0]"]


def test_error_helpers_keep_message_as_a_parameter():
    """The walk reads `message` by name; a renamed parameter would hide messages."""
    helpers = [
        server._search_error,
        server._market_error,
        server._similar_error,
        server._recommend_error,
        server._rag_error,
    ]
    for helper in helpers:
        assert "message" in inspect.signature(helper).parameters
