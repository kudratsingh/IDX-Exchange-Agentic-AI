"""Layer 2 of the relay fix (owner decision 2026-11-05): one copy of each card.

The card tools return integral numbers as integers, so OpenClaw 2026.9.5 drops the SDK
text block (mcp-content-Dj8o6nFL.mjs:113; evals.routing_fixtures.openclaw_projection).
Synthetic fixtures only; no database, model or network. The node check needs node."""

from __future__ import annotations

import asyncio
import json
import math
import random
import shutil
import struct
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
from idx_agent.mcp_server.wire import javascript_json, one_copy

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


# JavaScript's own spellings (node: JSON.stringify(JSON.parse(wire), null, 2)), so the
# check below needs no node; the node-backed test further down covers many more.
JAVASCRIPT_SPELLINGS = [
    (1e-6, "0.000001"),
    (-1e-6, "-0.000001"),
    (9.999e-7, "9.999e-7"),
    (1.5e-7, "1.5e-7"),
    (1e-5, "0.00001"),
    (0.000123, "0.000123"),
    (1e16, "10000000000000000"),
    (1.5e17, "150000000000000000"),
    (2.0**60, "1152921504606847000"),
    (2**60, "1152921504606847000"),
    (2**53 + 1, "9007199254740992"),
    (1e21, "1e+21"),
    (123e18, "123000000000000000000"),
    (5e-324, "5e-324"),
    (-0.0, "0"),
    (2.5, "2.5"),
    (2.0, "2"),
    ('a \x7f\x01"\\\n\t\ud800é', '"a \x7f\\u0001\\"\\\\\\n\\t\\ud800é"'),
]


@pytest.mark.parametrize(("value", "spelled"), JAVASCRIPT_SPELLINGS)
def test_javascript_json_spells_numbers_and_strings_as_javascript(value, spelled):
    assert javascript_json(value) == spelled


def test_javascript_json_indents_and_orders_as_javascript():
    value = {"10": [], "b": [1, {"2": None}], "1": True, "01": {}, "a": ""}
    assert javascript_json(value) == (
        '{\n  "1": true,\n  "10": [],\n  "b": [\n    1,\n    {\n      "2": null\n'
        '    }\n  ],\n  "01": {},\n  "a": ""\n}'
    )


def _market_with(monkeypatch, ratio):
    """The real get_market_stats call path with sale_to_list_ratio set to `ratio`."""
    envelope = RoutingFixtures().result("get_market_stats", {"city": "Pasadena"})
    envelope = envelope.model_copy(
        update={"data": envelope.data.model_copy(update={"sale_to_list_ratio": ratio})}
    )
    monkeypatch.setattr(mcp, "market_result", lambda **_: envelope)
    result = asyncio.run(mcp.server.call_tool("get_market_stats", {"city": "Pasadena"}))
    return envelope, [b.text for b in result.content], result.structured_content


@pytest.mark.parametrize("ratio", [1e-6, 1.5e-7, 9.9e-6, 1.0, 1.0123])
def test_a_number_python_spells_differently_still_reaches_the_model_once(
    monkeypatch, ratio
):
    """Regression (review of #172): 1e-6 is `1e-6` to the SDK's pydantic_core and
    `0.000001` to JavaScript, so the SDK text block never mirrored and the card went to
    the model twice. The card tools now write that block in JavaScript's spelling."""
    envelope, texts, structured = _market_with(monkeypatch, ratio)
    assert structured["data"]["sale_to_list_ratio"] == ratio  # value unchanged
    assert structured == one_copy(envelope.model_dump(mode="json"))
    assert len(texts) == 1
    assert len(openclaw_projection(texts, structured)) == 1
    sdk_text = pydantic_core.to_json(structured, indent=2).decode()
    if ratio in (1e-6, 9.9e-6):  # pydantic_core `1e-6`, JavaScript `0.000001`
        assert len(openclaw_projection([sdk_text], structured)) == 2  # the old miss


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on the PATH")
def test_javascript_itself_agrees_with_javascript_json_and_the_1e_6_card(monkeypatch):
    """node's JSON.stringify(JSON.parse(wire), null, 2) equals javascript_json for a
    spread of values, and the 1e-6 market card's text block is its mirror."""
    rng = random.Random(7)
    values = [v for v, _ in JAVASCRIPT_SPELLINGS]
    values += [rng.uniform(-1, 1) * 10.0 ** rng.randint(-30, 30) for _ in range(2000)]
    values += [struct.unpack("d", struct.pack("Q", rng.getrandbits(64)))[0]]
    values = [v for v in values if not isinstance(v, float) or math.isfinite(v)]
    _, texts, structured = _market_with(monkeypatch, 1e-6)
    rows = [[json.dumps(v), javascript_json(v)] for v in values]
    rows.append([json.dumps(structured), texts[0]])
    script = (
        "const rows = JSON.parse(require('fs').readFileSync(0));"
        "const js = (w) => JSON.stringify(JSON.parse(w), null, 2);"
        "const bad = rows.filter(([w, t]) => js(w) !== t);"
        "process.stdout.write(JSON.stringify(bad.length));"
    )
    done = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(rows),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(done.stdout) == 0
