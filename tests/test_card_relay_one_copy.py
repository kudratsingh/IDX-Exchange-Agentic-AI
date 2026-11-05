"""Layer 2 of the relay fix (owner decision 2026-11-05): one copy of each card.

The card tools return integral numbers as integers, so OpenClaw 2026.9.5 drops the SDK
text block (mcp-content-Dj8o6nFL.mjs:113; evals.routing_fixtures.openclaw_projection).
Synthetic fixtures only; no database, model or network. The node check needs node."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess

import pydantic_core
import pytest
from evals.routing_fixtures import (
    STRUCTURED_PREFIX,
    RoutingFixtures,
    openclaw_blocks,
    openclaw_projection,
)

from idx_agent.mcp_server import server as mcp
from idx_agent.mcp_server.wire import one_copy

# (tool, the body `_guarded` runs, the arguments the call sends): synthetic fixtures.
CARD_CALLS = [
    ("search_listings", "search_result", {"city": "Pasadena", "min_baths": 2}),
    ("get_market_stats", "market_result", {"city": "Pasadena"}),
    (
        "find_similar_listings",
        "similar_result",
        {"text": "a three bedroom house with a large backyard and a modern kitchen"},
    ),
    ("recommend", "recommend_result", {"listing_key": 9190001}),
]


def _sdk_call(monkeypatch, tool, body, args):
    """The real MCP call path with the tool body replaced by a fixture envelope.
    Returns (fixture envelope, SDK text blocks, SDK structuredContent)."""
    envelope = RoutingFixtures().result(tool, args)
    assert envelope.ok, envelope.message
    monkeypatch.setattr(mcp, body, lambda **_: envelope)
    result = asyncio.run(mcp.server.call_tool(tool, args))
    texts = [block.text for block in result.content]
    return envelope, texts, result.structured_content


def test_the_card_tools_are_the_one_copy_tools():
    assert mcp.ONE_COPY_TOOLS == {
        "search_listings",
        "get_market_stats",
        mcp.SIMILAR_TOOL,
        mcp.RECOMMEND_TOOL,
    }


@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_each_card_tool_reaches_the_model_once(monkeypatch, tool, body, args):
    """Before Layer 2 the same envelope reached the model twice (two text blocks);
    now the SDK text mirrors the structured content and only one block is left."""
    envelope, texts, structured = _sdk_call(monkeypatch, tool, body, args)
    before = openclaw_blocks(envelope)  # the pre-Layer-2 payload, same projection
    after = openclaw_projection(texts, structured)
    assert len(before) == 2, "the fixture must carry a whole float (the P1-4 shape)"
    assert len(after) == 1
    assert after[0]["text"].startswith(STRUCTURED_PREFIX)
    assert after == before[:1]  # the copy kept is the same text as before
    chars_before = sum(len(b["text"]) for b in before)
    chars_after = len(after[0]["text"])
    assert chars_after < 0.6 * chars_before


@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_one_copy_keeps_every_value(monkeypatch, tool, body, args):
    """Same JSON values (2 == 2.0), same keys; the message text is untouched."""
    envelope, texts, structured = _sdk_call(monkeypatch, tool, body, args)
    legacy = envelope.model_dump(mode="json")
    assert structured == legacy
    assert json.loads(texts[0]) == legacy
    assert structured["message"] == envelope.message


def test_other_tools_are_unchanged(monkeypatch):
    """health keeps the old payload (not a card tool): no change outside Layer 2."""
    envelope = RoutingFixtures().result("health", {})
    monkeypatch.setattr(mcp, "health_result", lambda **_: envelope)
    result = asyncio.run(mcp.server.call_tool("health", {}))
    assert result.structured_content == envelope.model_dump(mode="json")


def test_one_copy_values():
    value = {
        "b": [2.0, 2.5, -0.0, True, None, "4.0", 1e300, float(2**53)],
        "10": 1.0,
        "a": {"2": 1, "1": 2, "01": 3, "x": 4.0},
        "0": 0.0,
    }
    out = one_copy(value)
    assert out == value
    assert list(out) == ["0", "10", "b", "a"]
    assert list(out["a"]) == ["1", "2", "01", "x"]
    assert [type(v).__name__ for v in out["b"]] == [
        "int",
        "float",
        "int",
        "bool",
        "NoneType",
        "str",
        "float",
        "float",
    ]
    assert out["a"]["x"] == 4 and isinstance(out["a"]["x"], int)


def test_integer_like_keys_follow_javascript_order():
    """A dict keyed by listing keys (card badges) out of order still mirrors."""
    structured = one_copy({"badges": {"9190002": ["pool"], "9190001": ["solar"]}})
    text = pydantic_core.to_json(structured, indent=2).decode()
    assert len(openclaw_projection([text], structured)) == 1
    raw = {"badges": {"9190002": ["pool"], "9190001": ["solar"]}}
    text = pydantic_core.to_json(raw, indent=2).decode()
    assert len(openclaw_projection([text], raw)) == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on the PATH")
@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_javascript_itself_finds_the_sdk_text_a_mirror(monkeypatch, tool, body, args):
    """JavaScript's JSON.parse and JSON.stringify(x, null, 2), the two calls of the
    line-113 rule, agree with the SDK text now and disagree with the old payload."""
    envelope, texts, structured = _sdk_call(monkeypatch, tool, body, args)
    legacy = envelope.model_dump(mode="json")
    old_text = pydantic_core.to_json(legacy, indent=2).decode()
    script = (
        "const [now, wire, old, oldWire] = JSON.parse(require('fs').readFileSync(0));"
        "const m = (w) => JSON.stringify(JSON.parse(w), null, 2);"
        "process.stdout.write(JSON.stringify([now === m(wire), old === m(oldWire)]));"
    )
    stdin = json.dumps([texts[0], json.dumps(structured), old_text, json.dumps(legacy)])
    done = subprocess.run(
        ["node", "-e", script],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(done.stdout) == [True, False]
