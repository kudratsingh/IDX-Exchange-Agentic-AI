"""Host-emulation tests for the card delivery boundary (WO-036 "Architectural blocker").

The `test_host_blocker_*` tests ASSERT THE CURRENT OUTCOME where our handler cannot
run: the model's malformed reply is delivered unchanged. They document the gap; they
are not a guarantee. Synthetic data only; no host, gateway or network."""

# The emulation models OpenClaw 2026.9.5's documented reply_payload_sending semantics,
# read from the installed dist (deliver-prepare-BRk062mg.mjs:26-39, 121-141, sha256
# 03f60ee0178f; hooks-Jjh3afyP.mjs:441, 780-788, 94e01df2379f;
# hook-runner-global-CN2-D2Rq.mjs:94-99, 8a9a236d7874). It is our own code; no vendor
# source is copied. Rewrite these tests when the send path is owned (Path A or B).
# What does hold is asserted too: with the plugin absent, before_tool_call never binds
# a card call, so under IDX_CARD_DELIVERY=1 the server refuses it and the model is
# never given a card value or a token.

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from evals.routing_fixtures import RoutingFixtures
from tests import card_delivery_vectors as vectors

from idx_agent.channels import card_delivery as cd
from idx_agent.mcp_server import server as mcp

VECTORS = json.loads(vectors.PATH.read_text(encoding="utf-8"))
MALFORMED = [c for c in VECTORS["malformed_replies"] if c["name"].endswith("_card_run")]
UNMATCHED = [c for c in VECTORS["cases"] if c["name"].startswith("unmatched_")]
# The host default for reply_payload_sending (15 s); scaled down for the test.
HOST_TIMEOUT_S = 0.05

Handler = Callable[[dict[str, Any]], Any]


async def _run_one(handler: Handler, event: dict[str, Any], timeout_s: float) -> Any:
    result = handler(event)
    if asyncio.iscoroutine(result):
        result = await asyncio.wait_for(result, timeout_s)
    return result


def host_send(
    payload: Any, handlers: list[Handler], *, timeout_s: float = HOST_TIMEOUT_S
) -> Any:
    """What OpenClaw 2026.9.5 delivers for one reply payload (None: withheld). No
    handler: unchanged. A throw or timeout: logged and skipped (fail-open). Only
    {cancel: True} withholds and only {payload: <object>} replaces."""
    current = payload
    for handler in handlers:
        event = {"channel": "whatsapp", "payload": current}
        try:
            result = asyncio.run(_run_one(handler, event, timeout_s))
        except Exception:  # noqa: BLE001 - the host logs and skips the handler
            continue
        if not isinstance(result, dict):
            continue
        if result.get("cancel") is True:
            return None
        if isinstance(result.get("payload"), dict):
            current = result["payload"]
    return current


def _release_handler(case: dict[str, Any]) -> Handler:
    """Our release decision (the Python mirror of plugin.mjs) as a host handler."""
    records = {}
    for name in case["records"]:
        record = cd.parse_record(VECTORS["records"][name])
        if record is not None:
            records[record.ref] = record
    context = case["context"]

    def handler(event: dict[str, Any]) -> dict[str, Any] | None:
        decision = cd.release(
            event["payload"],
            channel=context["channel"],
            session=context["session"],
            run=context["run"],
            now_ms=context["now_ms"],
            records=records,
            bound_calls=context["bound_calls"],
            known_runs=context["known_runs"],
            run_state=context["run_state"],
        )
        if decision.action == "drop":
            return {"cancel": True}
        if decision.action in ("withhold", "substitute"):
            return {"payload": {"text": decision.text}}
        return None

    return handler


def _payload(case: dict[str, Any]) -> Any:
    return case["payload"] if "payload" in case else {"text": case["text"]}


def _cases() -> list[dict[str, Any]]:
    return MALFORMED + UNMATCHED


IDS = [c["name"] for c in _cases()]


# --- control: while our handler runs, nothing the model wrote gets through ---


@pytest.mark.parametrize("case", _cases(), ids=IDS)
def test_while_the_release_handler_runs_the_model_text_is_withheld(case):
    sent = host_send(_payload(case), [_release_handler(case)])
    assert sent in (None, {"text": cd.CARD_NOT_DELIVERED_LINE})


@pytest.mark.parametrize("case", MALFORMED, ids=[c["name"] for c in MALFORMED])
def test_a_throw_inside_the_handler_is_caught_and_cancels(case):
    def failing(event):
        decision = cd.release(event["payload"], verify=_boom)
        assert (decision.action, decision.reason) == ("drop", "release_error")
        return {"cancel": True}

    assert host_send(_payload(case), [failing]) is None


def _boom(*_args, **_kwargs):
    raise RuntimeError("synthetic release failure")


SUBSTITUTED = [c for c in VECTORS["cases"] if c["expect"]["action"] == "substitute"]
MODEL_EXTRAS = {
    "mediaUrl": "https://example.invalid/invented-1250000.png",
    "mediaUrls": ["https://example.invalid/invented-1250000.png"],
    "presentation": {"blocks": [{"type": "text", "text": "Lists at $1,250,000"}]},
    "fallbackText": {"text": "Lists at $1,250,000"},
    "spokenText": "one point two five million",
    "channelData": {"whatsapp": {"caption": "$1,250,000"}},
}


@pytest.mark.parametrize("case", SUBSTITUTED, ids=[c["name"] for c in SUBSTITUTED])
def test_a_substituted_card_drops_every_other_field_the_model_sent(case):
    """The verifier reads only `text`, so a substitute replaces the whole payload:
    model media, presentation and the rest never ship beside the stored card. The
    plugin.mjs twin is the "replaces the whole payload" test in delivery.test.mjs."""
    payload = {**_payload(case), **MODEL_EXTRAS}
    sent = host_send(payload, [_release_handler(case)])
    assert sent == {"text": case["expect"]["text"]}


# --- blockers: our code cannot run, and the host sends the model's text ---


@pytest.mark.parametrize("case", _cases(), ids=IDS)
def test_host_blocker_release_hook_absent_delivers_model_text(case):
    """BLOCKER (WO-036 "Architectural blocker"): with no reply_payload_sending handler
    registered (plugin missing, failed at startup, disabled, or not allowed
    conversation access), OpenClaw delivers the payload unchanged
    (deliver-prepare-BRk062mg.mjs:27). This asserts today's outcome, not a goal."""
    payload = _payload(case)
    assert host_send(payload, []) == payload


@pytest.mark.parametrize("case", _cases(), ids=IDS)
def test_host_blocker_release_hook_timeout_delivers_model_text(case):
    """BLOCKER (WO-036 "Architectural blocker"): a reply_payload_sending handler that
    times out (default 15 s; 1 to 600000 ms) is skipped like a throw, and the payload
    is delivered unchanged (hooks-Jjh3afyP.mjs:382-392, 780-788). A longer timeout
    only delays the send. This asserts today's outcome, not a goal."""
    ours = _release_handler(case)

    async def slow(event):
        await asyncio.sleep(HOST_TIMEOUT_S * 4)
        return ours(event)

    payload = _payload(case)
    assert host_send(payload, [slow]) == payload


@pytest.mark.parametrize("case", MALFORMED, ids=[c["name"] for c in MALFORMED])
def test_host_blocker_release_hook_throw_that_escapes_delivers_model_text(case):
    """BLOCKER (WO-036 "Architectural blocker"): our handler catches its own errors,
    but a failure the catch cannot cover (the module failing mid-load, a host-side
    error around the call) is logged and skipped by the fail-open runner, and the
    payload is delivered unchanged (hook-runner-global-CN2-D2Rq.mjs:94-99)."""

    def escapes(_event):
        raise RecursionError("synthetic failure outside the handler's catch")

    payload = _payload(case)
    assert host_send(payload, [escapes]) == payload


@pytest.mark.parametrize(
    "result",
    [{"cancel": "yes"}, {"payload": None}, "cancel", ["cancel"], {"withhold": True}],
)
def test_host_blocker_a_result_shape_the_host_rejects_delivers_model_text(result):
    """BLOCKER (WO-036 "Architectural blocker"): only cancel === true or a payload
    object is honoured; any other result leaves the payload unchanged
    (hooks-Jjh3afyP.mjs:479, 492-500; deliver-prepare-BRk062mg.mjs:133-140)."""
    payload = {"text": vectors.INVENTED}
    assert host_send(payload, [lambda _event: result]) == payload


# --- the mitigation that does hold with the plugin absent ---

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


@pytest.fixture
def switch_on(tmp_path, monkeypatch):
    directory = tmp_path / "idx-cards"
    monkeypatch.setenv("IDX_CARD_DIR", str(directory))
    monkeypatch.setenv(mcp.CARD_DELIVERY_SETTING, "1")
    mcp.reset_card_delivery_for_tests()
    yield directory
    mcp.reset_card_delivery_for_tests()


@pytest.mark.parametrize(("tool", "body", "args"), CARD_CALLS)
def test_with_the_plugin_absent_no_card_value_or_token_reaches_the_model(
    monkeypatch, switch_on, tool, body, args
):
    """With the plugin absent before_tool_call never bound the call, so the server
    (IDX_CARD_DELIVERY=1) refuses it: no card text, no figure and no token is issued,
    and nothing is stored. What the model then writes is still delivered unchecked
    (the blocker above); it just holds no card value we gave it."""
    envelope = RoutingFixtures().result(tool, args)
    monkeypatch.setattr(mcp, body, lambda **_: envelope)
    result = asyncio.run(mcp.server.call_tool(tool, dict(args)))  # no idx_delivery
    payload = result.structured_content
    model_view = json.dumps(payload) + "".join(b.text for b in result.content)
    assert payload["ok"] is False and payload["data"] is None
    assert payload["message"] == cd.CHANNEL_REFUSAL
    assert cd.MARKER not in model_view
    assert not re.search(r"[0-9]", payload["message"])
    if envelope.message:
        assert envelope.message not in model_view
    assert not (switch_on.exists() and list(switch_on.glob("card-*.json")))
