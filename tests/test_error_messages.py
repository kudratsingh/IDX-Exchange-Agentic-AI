"""WO-014 R5: every error message the six tools can return is one plain sentence.

Messages are collected by an AST walk of src/idx_agent (ToolError, the `_*_error`
helpers, `_with_ref`) and from real error envelopes; `to_channel` never carries
`detail`. The five retry messages end with a six-character reference. No database.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import socket
from pathlib import Path
from types import SimpleNamespace
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
# The five messages said through `_with_ref` (the human, 2026-09-25): each must end
# with " (ref <6 hex>)." and no other message may carry a reference.
REF_MESSAGES = {
    server.SEARCH_DB_MESSAGE,
    server.MARKET_DB_MESSAGE,
    server.PROVIDER_MESSAGE,
    server.SIMILAR_DB_MESSAGE,
    server.RECOMMEND_DB_MESSAGE,
}
# Planted in every `detail` and every raised exception; it must never reach a channel.
SENTINEL = "SENTINEL-detail-7f3a /srv/idx/data/index.npy OperationalError"

_TRACE_ID = re.compile(r"[0-9a-fA-F]{16,}")
# The one allowed reference: six lowercase hex characters, just before the period.
_REF_TAIL = re.compile(r" \(ref ([0-9a-f]{6})\)(?=\.$)")
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
    core = _REF_TAIL.sub("", text)
    if re.search(r"\bref\b", core, re.IGNORECASE):
        problems.append("malformed reference")
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


def _unwrap_ref(arg: ast.expr) -> tuple[ast.expr, bool]:
    """A `_with_ref(<message>, ...)` argument as its message, and whether it was one."""
    if (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Name)
        and arg.func.id == "_with_ref"
        and arg.args
    ):
        return arg.args[0], True
    return arg, False


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


def collect_error_messages() -> tuple[dict[str, str], list[str], set[str]]:
    """Walk src/idx_agent: ({message: where}, [unresolvable sites], {ref messages})."""
    messages: dict[str, str] = {}
    unresolved: list[str] = []
    with_ref: set[str] = set()
    for path in sorted((SRC / "idx_agent").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        args = _message_args(tree)
        module = _module_for(path) if args else None
        for wrapped in args:
            arg, referenced = _unwrap_ref(wrapped)
            where = f"{path.relative_to(ROOT)}:{arg.lineno}"
            text = None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.Name) and isinstance(
                getattr(module, arg.id, None), str
            ):
                text = getattr(module, arg.id)
            elif not (isinstance(arg, ast.Name) and arg.id == "message"):
                unresolved.append(where)  # an f-string or expression: uncheckable
            if text is not None:
                messages.setdefault(text, where)
                if referenced:
                    with_ref.add(text)
    return messages, unresolved, with_ref


MESSAGES, UNRESOLVED, WITH_REF = collect_error_messages()


def _base(message: str) -> str:
    """A channel message without its reference, as the walk records it."""
    return _REF_TAIL.sub("", message)


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
    if message in WITH_REF:
        referenced = server._with_ref(message, new_trace_id())
        assert message_problems(referenced) == [], MESSAGES[message]


def test_exactly_the_five_retry_messages_carry_a_reference():
    """The walk finds `_with_ref` around the five, and around nothing else."""
    assert WITH_REF == REF_MESSAGES
    for message in MESSAGES:
        assert not _REF_TAIL.search(message) and "(ref" not in message


def test_with_ref_puts_six_hex_before_the_period():
    trace_id = "a1b2c3d4e5f60718"
    assert server._with_ref(server.SEARCH_DB_MESSAGE, trace_id) == (
        "The listing search isn't available right now; "
        "try again in a minute (ref a1b2c3)."
    )


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
    assert _base(payload["error"]["message"]) in MESSAGES
    assert message_problems(payload["error"]["message"]) == []
    if reachable:
        _assert_ref_from_trace_id(payload)


def _assert_ref_from_trace_id(payload: dict[str, Any]) -> None:
    """The message is one of the five and ends with the trace id's first six hex."""
    message = payload["error"]["message"]
    assert _base(message) in REF_MESSAGES
    match = _REF_TAIL.search(message)
    assert match is not None, message
    assert match.group(1) == payload["provenance"]["trace_id"][:6]
    assert len(match.group(1)) == 6


class _Conn:
    """A connection stub that only closes."""

    def close(self) -> None:
        return None


@pytest.mark.parametrize("failure", ["provider", "db"])
def test_real_similar_retry_envelopes_carry_the_reference(monkeypatch, failure):
    """Past the index check (stubbed), a provider or database failure is a retry
    message with the trace id's six-character reference, and no detail."""
    from idx_agent.semantic import query as semantic_query
    from idx_agent.semantic.embedder import ProviderError

    def no_provider(*_args: Any, **_kwargs: Any) -> Any:
        raise ProviderError("failed")

    embedder = SimpleNamespace(name="m", dims=8)
    monkeypatch.setattr(server, "_semantic", lambda: (object(), embedder, "m", 8))
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: True)
    if failure == "db":
        monkeypatch.setattr(server.db_pool, "connect", _raise_db)
    else:
        monkeypatch.setattr(server.db_pool, "connect", lambda: _Conn())
        monkeypatch.setattr(server.db_asof, "get_asof_dates", lambda conn: None)
        monkeypatch.setattr(semantic_query, "find_similar", no_provider)
    raw = {"text": "a quiet craftsman with a big yard"}
    payload = to_channel(server.similar_result(raw, trace_id=new_trace_id()))
    assert payload["ok"] is False and payload["error"]["category"] == failure
    assert detail_leaks(payload) == [] and SENTINEL not in json.dumps(payload)
    assert message_problems(payload["error"]["message"]) == []
    _assert_ref_from_trace_id(payload)


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
        ("The search failed (ref a1b2c).", "malformed reference"),
        ("The search failed (ref a1b2c3d).", "malformed reference"),
        ("The search failed (ref A1B2C3).", "malformed reference"),
        ("The search failed (ref a1b2c3) today.", "malformed reference"),
        ("The search failed; ref a1b2c3.", "malformed reference"),
        ("The search failed (ref 0123456789abcdef).", "trace id pattern"),
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
