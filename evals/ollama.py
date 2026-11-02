"""Local-model adapter for the eval driver (WO-020 requirement 6): Ollama's chat API.

`IDX_EVAL_PROVIDER=ollama` with `IDX_EVAL_MODEL` and a loopback `IDX_EVAL_BASE_URL`.
No key is read or sent. A free local model is not a paid call (human rule 2026-10-28),
but in this phase it may only ever see synthetic data: `synthetic_problem` refuses the
run before the first request unless the database is the fixture and no real index or
embedding key is configured. Replies map to the driver's OpenAI-style shape; anything
else aborts the run.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

__all__ = [
    "FIXTURE_MAX_ROWS",
    "LocalBudget",
    "LocalModelRefused",
    "base_url",
    "chat",
    "from_ollama",
    "probe_problem",
    "synthetic_problem",
    "to_ollama",
]

BASE_URL_ENV = "IDX_EVAL_BASE_URL"
# The fixture has under 200 rows per table; a real snapshot has tens of thousands.
FIXTURE_MAX_ROWS = 1_000
# Settings that would bring real data or a paid embedder into a local-model run.
REAL_DATA_SETTINGS = ("OPENAI_API_KEY", "IDX_SEMANTIC_INDEX_DIR", "IDX_RAG_INDEX_DIR")
_INVENTED = "^9[0-9]{5,6}$"  # the fixture lint's invented-key pattern


class LocalModelRefused(ValueError):
    """The local-model run is refused before any request; `reason` says why."""


class LocalBudget:
    """The call ceiling for a local run: no token, but never more than planned."""

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.calls_made = 0

    def spend(self) -> None:
        if self.calls_made >= self.max_calls:
            raise LocalModelRefused("the local run reached its call ceiling")
        self.calls_made += 1


def base_url(environ: Mapping[str, str]) -> str:
    """The configured base URL, only when it is http(s) on a loopback address."""
    raw = environ.get(BASE_URL_ENV, "").strip()
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LocalModelRefused(f"{BASE_URL_ENV} must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LocalModelRefused(f"{BASE_URL_ENV} takes no credentials or query")
    host = parsed.hostname
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        raise LocalModelRefused(f"{BASE_URL_ENV} must be a loopback address")
    return raw.rstrip("/")


def synthetic_problem(
    database_kind: str, setting: Callable[[str], str | None]
) -> str | None:
    """Why this run could see real data, or None (checked before any request)."""
    if database_kind != "fixture":
        return "a local-model run needs --database-kind fixture"
    present = [name for name in REAL_DATA_SETTINGS if (setting(name) or "").strip()]
    if present:
        return (
            f"unset {', '.join(present)} for a local-model run (e.g. "
            f"{'= '.join(present)}= on the command line); it is refused, not ignored"
        )
    return None


def probe_problem(conn: Any) -> str | None:
    """The configured database must look like the fixture: few rows, invented keys."""
    checks = (
        ("rets_property", "L_ListingID"),
        ("california_sold", "ListingKey"),
    )
    with conn.cursor() as cursor:
        for table, key in checks:
            cursor.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN {key} REGEXP %s "
                f"THEN 0 ELSE 1 END), 0) AS real_like FROM {table}",
                (_INVENTED,),
            )
            row = cursor.fetchall()[0]
            n, real_like = (
                (row["n"], row["real_like"]) if isinstance(row, dict) else row
            )
            if int(n) > FIXTURE_MAX_ROWS:
                return f"{table} is larger than the synthetic fixture"
            if int(real_like):
                return f"{table} holds keys that are not invented fixture keys"
    return None


def to_ollama(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The driver's OpenAI-style chat payload as an Ollama /api/chat body."""
    messages = []
    for message in payload.get("messages", ()):
        converted = {k: v for k, v in message.items() if k != "tool_call_id"}
        calls = message.get("tool_calls")
        if calls:
            converted["tool_calls"] = [
                {
                    "function": {
                        "name": c["function"]["name"],
                        "arguments": json.loads(c["function"].get("arguments") or "{}"),
                    }
                }
                for c in calls
            ]
        messages.append(converted)
    body: dict[str, Any] = {
        "model": payload["model"],
        "messages": messages,
        "stream": False,
    }
    if payload.get("tools"):
        body["tools"] = list(payload["tools"])
    if "temperature" in payload:
        body["options"] = {"temperature": payload["temperature"]}
    return body


def from_ollama(reply: Any) -> dict[str, Any]:
    """An Ollama reply as {"choices": [{"message": ...}]}; any other shape raises."""
    if not isinstance(reply, dict) or not isinstance(reply.get("message"), dict):
        raise LocalModelRefused("unsupported reply shape from the local model")
    message = reply["message"]
    if message.get("role") != "assistant":
        raise LocalModelRefused("unsupported reply shape from the local model")
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise LocalModelRefused("unsupported reply shape from the local model")
    out: dict[str, Any] = {"role": "assistant", "content": content}
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list):
        raise LocalModelRefused("unsupported reply shape from the local model")
    if calls:
        mapped = []
        for number, call in enumerate(calls, 1):
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or not isinstance(
                function.get("name"), str
            ):
                raise LocalModelRefused("unsupported tool call from the local model")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise LocalModelRefused("unsupported tool call from the local model")
            mapped.append(
                {
                    "id": f"local-{number}",
                    "type": "function",
                    "function": {
                        "name": function["name"],
                        "arguments": json.dumps(arguments),
                    },
                }
            )
        out["tool_calls"] = mapped
    return {"choices": [{"index": 0, "message": out}]}


def _post(url: str, body: Mapping[str, Any]) -> Any:
    """POST JSON with no credentials of any kind; the only network call here."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def chat(
    payload: Mapping[str, Any],
    environ: Mapping[str, str],
    budget: LocalBudget,
    post: Callable[[str, Mapping[str, Any]], Any] = _post,
) -> dict[str, Any]:
    """One chat request to the loopback model, within the run's call ceiling."""
    url = base_url(environ) + "/api/chat"
    budget.spend()
    return from_ollama(post(url, to_ollama(payload)))
