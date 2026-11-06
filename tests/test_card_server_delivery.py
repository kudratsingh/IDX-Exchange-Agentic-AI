"""The server side of code-controlled card delivery (WO-036 prototype, ADR-0015).

Off (IDX_CARD_DELIVERY unset or anything but "1") the card tools are unchanged. On,
a card reaches the model only as a token, and only for a WhatsApp binding from the
gateway hook. The real MCP call path with synthetic fixture envelopes; no database.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest
from evals.routing_fixtures import RoutingFixtures, openclaw_projection
from mcp.server.mcpserver import MCPServer

from idx_agent.channels import card_delivery as cd
from idx_agent.channels import card_store as cs
from idx_agent.mcp_server import server as mcp
from idx_agent.mcp_server.wire import javascript_json, one_copy

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
# Figures the synthetic fixture cards show; none may reach the model under the switch.
CARD_FIGURES = ("900,000", "1,500 sqft", "$400/month", "$600", "9190001")
SESSION = cd.session_digest("agent:idx:whatsapp:direct:synthetic-peer-alpha")


def wa_binding(call="call-one", run="run-current-turn"):
    return {"v": 1, "channel": "wa", "session": SESSION, "run": run, "call": call}


@pytest.fixture
def card_dir(tmp_path, monkeypatch):
    directory = tmp_path / "idx-cards"
    monkeypatch.setenv("IDX_CARD_DIR", str(directory))
    mcp.reset_card_delivery_for_tests()
    yield directory
    mcp.reset_card_delivery_for_tests()


@pytest.fixture
def switch_on(monkeypatch, card_dir):
    monkeypatch.setenv(mcp.CARD_DELIVERY_SETTING, "1")
    return card_dir


def _fixture(monkeypatch, tool, body, args):
    envelope = RoutingFixtures().result(tool, args)
    monkeypatch.setattr(mcp, body, lambda **_: envelope)
    return envelope


def _call(tool, args):
    result = asyncio.run(mcp.server.call_tool(tool, args))
    return result, [block.text for block in result.content]


def _store_files(directory):
    return sorted(directory.glob("card-*.json")) if directory.exists() else []


# --- off: byte-identical to main ---


@pytest.mark.parametrize("value", [None, "", "0", "true", " 1", "1 ", "yes"])
@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_switch_off_leaves_every_card_result_unchanged(
    monkeypatch, card_dir, value, tool, body, args
):
    if value is None:
        monkeypatch.delenv(mcp.CARD_DELIVERY_SETTING, raising=False)
    else:
        monkeypatch.setenv(mcp.CARD_DELIVERY_SETTING, value)
    envelope = _fixture(monkeypatch, tool, body, args)
    expected = one_copy(envelope.model_dump(mode="json"))
    for call_args in (args, {**args, cd.BINDING_ARG: wa_binding()}):
        result, texts = _call(tool, call_args)
        assert result.structured_content == expected
        assert texts == [javascript_json(expected)]
        assert result.structured_content["message"] == envelope.message
    assert not card_dir.exists()


def _surface():
    tools = asyncio.run(mcp.server.list_tools())
    listed = [t.model_dump(mode="json", exclude_none=True) for t in tools]
    return json.dumps(listed, sort_keys=True), mcp.server._lowlevel_server.instructions


def test_the_switch_changes_no_tool_schema_description_or_instruction(monkeypatch):
    """The Layer 2 surface digests (tests/test_phase_integration*.py) hold either way:
    the switch adds no argument, tool or instruction."""
    monkeypatch.delenv(mcp.CARD_DELIVERY_SETTING, raising=False)
    off = _surface()
    monkeypatch.setenv(mcp.CARD_DELIVERY_SETTING, "1")
    assert _surface() == off
    assert cd.BINDING_ARG not in off[0]


# --- on: refusals without a WhatsApp binding ---


@pytest.mark.parametrize(
    "binding",
    [
        None,
        {"v": 1, "channel": "none"},
        {"v": 1, "channel": "webchat"},
        {**wa_binding(), "channel": "whatsapp"},
        {**wa_binding(), "session": "not-a-digest"},
        {**wa_binding(), "extra": True},
        "wa",
    ],
)
@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_no_whatsapp_binding_is_a_refusal_with_nothing_stored(
    monkeypatch, switch_on, binding, tool, body, args
):
    called = []
    monkeypatch.setattr(mcp, body, lambda **_: called.append(1))
    call_args = dict(args) if binding is None else {**args, cd.BINDING_ARG: binding}
    result, texts = _call(tool, call_args)
    payload = result.structured_content
    assert payload["ok"] is False and payload["data"] is None
    assert payload["message"] == cd.CHANNEL_REFUSAL
    assert payload["error"]["category"] == "safety_refusal"
    assert not re.search(r"[0-9]", payload["message"])
    assert cd.MARKER not in texts[0]
    assert texts == [javascript_json(payload)]
    assert not called and _store_files(switch_on) == []


# --- on: a WhatsApp binding stores the card and hands the model a token ---


@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_a_whatsapp_binding_stores_the_card_and_returns_only_a_token(
    monkeypatch, switch_on, tool, body, args
):
    envelope = _fixture(monkeypatch, tool, body, args)
    # Under the switch a raw listing key is no handle; recommend goes by position.
    asked = {"sender_id": "s", "position": 1} if tool == "recommend" else args
    result, texts = _call(tool, {**asked, cd.BINDING_ARG: wa_binding()})
    payload = result.structured_content
    tokens, outside = cd.parse_tokens(payload["message"])
    assert len(tokens) == 1 and outside == ""
    files = _store_files(switch_on)
    assert len(files) == 1
    record = cs.CardStore(switch_on).read(tokens[0][0])
    assert record is not None
    assert record.message == envelope.message  # the exact card, byte for byte
    assert (record.session, record.run, record.call) == (
        SESSION,
        "run-current-turn",
        "call-one",
    )
    assert cd.mint_token(record) == payload["message"]
    assert texts == [javascript_json(payload)]
    assert len(openclaw_projection(texts, payload)) == 1  # still one copy
    model_view = texts[0] + json.dumps(payload)
    for figure in CARD_FIGURES:
        if figure in envelope.message or figure == "9190001":
            assert figure not in model_view, figure
    assert payload["data"]["delivery_note"] == cd.DELIVERY_NOTE


def test_the_released_card_is_the_stored_bytes(monkeypatch, switch_on):
    tool, body, args = CARD_CALLS[0]
    envelope = _fixture(monkeypatch, tool, body, args)
    result, _ = _call(tool, {**args, cd.BINDING_ARG: wa_binding()})
    token = result.structured_content["message"]
    (ref, _tag), *_ = cd.parse_tokens(token)[0]
    record = cs.CardStore(switch_on).read(ref)
    decision = cd.verify_and_substitute(
        token,
        channel="whatsapp",
        session=SESSION,
        run="run-current-turn",
        now_ms=record.created_ms + 1,
        records={ref: record},
        bound_calls=["call-one"],
    )
    assert (decision.action, decision.text) == ("substitute", envelope.message)


def test_a_model_supplied_binding_never_reaches_the_tool(monkeypatch, switch_on):
    seen = []
    original = MCPServer.call_tool

    async def spy(self, name, arguments, context=None):
        seen.append(dict(arguments))
        return await original(self, name, arguments, context)

    monkeypatch.setattr(MCPServer, "call_tool", spy)
    tool, body, args = CARD_CALLS[0]
    _fixture(monkeypatch, tool, body, args)
    _call(tool, {**args, cd.BINDING_ARG: wa_binding()})
    assert seen == [args]


# --- handles in place of listing keys ---


def _search_handles(monkeypatch):
    tool, body, args = CARD_CALLS[0]
    envelope = _fixture(monkeypatch, tool, body, args)
    result, _ = _call(tool, {**args, cd.BINDING_ARG: wa_binding()})
    real = [x["listing_key"] for x in envelope.model_dump()["data"]["listings"]]
    shown = result.structured_content["data"]["listings"]
    assert [x["position"] for x in shown] == list(range(1, len(real) + 1))
    handles = [x["listing_key"] for x in shown]
    assert not set(handles) & set(real)
    return real, handles


def test_a_handle_round_trips_to_its_listing_key(monkeypatch, switch_on):
    real, handles = _search_handles(monkeypatch)
    raws = []
    envelope = RoutingFixtures().result("recommend", {"listing_key": real[1]})

    def body(**kwargs):
        raws.append(kwargs["raw"])
        return envelope

    monkeypatch.setattr(mcp, "recommend_result", body)
    result, _ = _call(
        "recommend",
        {"listing_key": handles[1], cd.BINDING_ARG: wa_binding(call="call-two")},
    )
    assert raws == [{"listing_key": real[1]}]
    assert cd.parse_tokens(result.structured_content["message"])[0]


def test_an_unknown_handle_is_refused_before_the_tool_runs(monkeypatch, switch_on):
    called = []
    monkeypatch.setattr(mcp, "recommend_result", lambda **_: called.append(1))
    result, _ = _call(
        "recommend", {"listing_key": 123456789, cd.BINDING_ARG: wa_binding()}
    )
    assert result.structured_content["message"] == cd.HANDLE_REFUSAL
    assert not called and _store_files(switch_on) == []


def test_position_follow_ups_are_unchanged(monkeypatch, switch_on):
    raws = []
    envelope = RoutingFixtures().result("recommend", {"listing_key": 9190001})
    monkeypatch.setattr(
        mcp, "recommend_result", lambda **kw: raws.append(kw["raw"]) or envelope
    )
    _call(
        "recommend",
        {"sender_id": "s", "position": 2, cd.BINDING_ARG: wa_binding()},
    )
    assert raws == [{"sender_id": "s", "position": 2}]


def test_draft_email_takes_handles_and_keeps_its_own_output(monkeypatch, switch_on):
    real, handles = _search_handles(monkeypatch)
    raws = []
    preview = {"ok": True, "data": None, "message": "preview", "warnings": []}

    def draft(raw, trace_id=None, log_fields=None):
        raws.append(raw)
        return mcp.AgentResult[dict](
            ok=True, message="preview", provenance=mcp._provenance("draft_email", "t")
        )

    monkeypatch.setattr(mcp, "draft_result", draft)
    result, _ = _call(
        "draft_email", {"source": "listings", "listing_keys": handles[:2]}
    )
    assert raws == [{"source": "listings", "listing_keys": real[:2]}]
    assert result.structured_content["message"] == preview["message"]
    refused, _ = _call("draft_email", {"source": "listings", "listing_keys": [7]})
    assert refused.structured_content["message"] == cd.HANDLE_REFUSAL
    assert len(raws) == 1


# --- store problems are refusals, never a token without a durable record ---


def test_an_unusable_store_directory_is_a_refusal(monkeypatch, switch_on):
    monkeypatch.setenv("IDX_CARD_DIR", cs.WORKSPACE + "/idx-cards")
    tool, body, args = CARD_CALLS[0]
    _fixture(monkeypatch, tool, body, args)
    result, _ = _call(tool, {**args, cd.BINDING_ARG: wa_binding()})
    assert result.structured_content["message"] == cd.STORE_REFUSAL


def test_a_failed_write_is_a_refusal(monkeypatch, tmp_path, switch_on):
    monkeypatch.setenv("IDX_CARD_DIR", str(tmp_path / "missing" / "idx-cards"))
    tool, body, args = CARD_CALLS[0]
    _fixture(monkeypatch, tool, body, args)
    result, texts = _call(tool, {**args, cd.BINDING_ARG: wa_binding()})
    assert result.structured_content["message"] == cd.STORE_REFUSAL
    assert cd.MARKER not in texts[0]


def test_a_failed_tool_body_is_a_refusal(monkeypatch, switch_on):
    def boom(**_):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(mcp, "search_result", boom)
    result, _ = _call(
        "search_listings", {"city": "Pasadena", cd.BINDING_ARG: wa_binding()}
    )
    assert result.structured_content["message"] == cd.STORE_REFUSAL
    assert _store_files(switch_on) == []
