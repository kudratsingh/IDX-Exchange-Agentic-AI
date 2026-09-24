"""The `health` tool returns a valid AgentResult over the MCP layer, no OpenClaw.

Covers each link: tool body -> `_guarded` wrapper -> MCP call path -> log line,
plus the error path and log redaction.
"""

import asyncio
import json
import os

from mcp import Client

from idx_agent import __version__
from idx_agent.domain.results import AgentResult, HealthData
from idx_agent.mcp_server import server as mcp
from idx_agent.observability import logging as obs


def test_health_result_is_a_valid_agent_result():
    """The tool body alone: ok envelope, version, trace id kept, as-of dates empty."""
    result = mcp.health_result(trace_id="abc123")
    assert result.ok is True and result.error is None
    assert isinstance(result.data, HealthData)
    assert result.data.version == __version__
    assert result.data.database == "not_configured"
    assert result.provenance.tool == "health"
    assert result.provenance.trace_id == "abc123"
    assert (
        result.provenance.as_of.sold is None and result.provenance.as_of.active is None
    )


def test_health_tool_is_registered_and_returns_the_envelope_as_json():
    """`health` is the only registered tool; its dict parses back as an envelope."""
    assert mcp.tool_names() == ["get_market_stats", "health", "search_listings"]
    payload = mcp.health()
    envelope = AgentResult[HealthData].model_validate(payload)
    assert envelope.ok and envelope.data.version == __version__
    json.dumps(payload)  # serializable as-is


def test_health_over_the_mcp_call_path():
    """Call through the MCP server's own `call_tool`, as the runtime would."""
    result = asyncio.run(mcp.server.call_tool("health", {}))
    # Read structured content if the server returns it, else parse the text block.
    content = result.structured_content or json.loads(result.content[0].text)
    envelope = AgentResult[HealthData].model_validate(content)
    assert envelope.ok and envelope.provenance.tool == "health"


def test_a_failing_tool_body_becomes_an_error_result(capsys):
    """A raising body yields ok=False with an "internal" error and one log line.

    The error, provenance, and log line all carry the same trace id.
    """

    # A tool body that always raises, with a secret-shaped value in the message.
    def boom(trace_id):
        raise RuntimeError("secret " + "sk-" + "abcdefghijklmnop" + " leaked?")

    payload = mcp._guarded("health", boom)
    envelope = AgentResult[HealthData].model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "internal"
    assert envelope.error.trace_id == envelope.provenance.trace_id
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["event"] == "tool_call" and line["ok"] is False
    assert line["error"] == "internal" and line["trace_id"] == envelope.error.trace_id


def _keys(value):
    """Return every dict key found anywhere inside a JSON-like value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_failure_payload_has_no_detail_anywhere():
    """ToolError.detail never crosses the MCP boundary, nor does the exception text."""

    # A tool body that always raises with a recognizable message.
    def boom(trace_id):
        raise RuntimeError("internal-only-text")

    payload = mcp._guarded("health", boom)
    assert payload["ok"] is False and payload["error"]["category"] == "internal"
    assert "detail" not in _keys(payload)
    assert "internal-only-text" not in json.dumps(payload)


def test_log_lines_are_redacted(capsys):
    """Email, phone, key, and a `password` field are scrubbed in return and stderr."""
    record = obs.log_event(
        "t",
        "id1",
        # Built at runtime so this file never holds a literal address, number, or key.
        note=" ".join(
            [
                "mail",
                "agent" + "@" + "brokerage.com",
                "phone",
                "310" + "-555-" + "0100",
                "key",
                "sk-" + "abcdefghijklmnop",
            ]
        ),
        password="hunter2",
    )
    assert "[email]" in record["note"] and "[phone]" in record["note"]
    assert "sk-abc" not in record["note"] and record["password"] == "[redacted]"
    err = capsys.readouterr().err
    assert "brokerage" not in err and "hunter2" not in err


def test_health_reports_the_process_start_time_and_pid():
    """Two calls in one process report the same start time and pid (WO-006 spike)."""
    first = mcp.health_result().data
    second = mcp.health_result().data
    assert first.pid == second.pid == os.getpid()
    assert first.process_started_at == second.process_started_at
    assert first.process_started_at <= first.server_time


def test_a_direct_call_logs_empty_meta(capsys):
    """Without a request context the log line still has both meta fields, empty."""
    mcp.health()
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["meta_keys"] == [] and line["meta_shape"] == {}


def test_request_meta_is_logged_as_key_names_and_shape_only(capsys):
    """Over a real in-process MCP session, the tool sees the request `_meta`; the
    log line names its keys and describes each string value, never the value."""
    # Built at runtime so this file never holds a number-shaped literal.
    phone_shaped = "peer:+1" + "2" * 10
    meta = {"sessionKey": phone_shaped, "outer": {"inner": "abc"}}

    async def call():
        async with Client(mcp.server) as client:
            await client.call_tool("health", {}, meta=meta)

    asyncio.run(call())
    err = capsys.readouterr().err
    line = json.loads(err.strip().splitlines()[-1])
    assert {"sessionKey", "outer.inner"} <= set(line["meta_keys"])
    assert line["meta_keys"] == sorted(line["meta_keys"])
    assert line["meta_shape"]["sessionKey"] == {
        "len": len(phone_shaped),
        "phone_like": True,
    }
    assert line["meta_shape"]["outer.inner"] == {"len": 3, "phone_like": False}
    assert phone_shaped not in err and "2" * 10 not in err


def test_phone_shaped_meta_keys_are_logged_as_placeholders(capsys):
    """A key segment with a digit run (top level or nested) is logged as `key#N`
    with its length and phone_like flag; its digits never reach stderr."""
    # Built at runtime from parts so this file never holds a number-shaped literal.
    digits = "".join(["1", "555", "010", "4", "3", "2", "1"])
    top_key = "+" + digits
    dashed = "-".join([digits[1:4], digits[4:7], digits[7:]])
    meta = {top_key: "x", "sender": {digits: "abc", "ok_key": "y"}, "s": {dashed: 1}}

    async def call():
        async with Client(mcp.server) as client:
            await client.call_tool("health", {}, meta=meta)

    asyncio.run(call())
    err = capsys.readouterr().err
    line = json.loads(err.strip().splitlines()[-1])
    assert {"key#0", "sender.key#0", "sender.ok_key", "s.key#0"} <= set(
        line["meta_keys"]
    )
    assert line["meta_shape"]["key#0"] == {
        "key_len": len(top_key),
        "key_phone_like": True,
        "len": 1,
        "phone_like": False,
    }
    assert line["meta_shape"]["sender.key#0"] == {
        "key_len": len(digits),
        "key_phone_like": True,
        "len": 3,
        "phone_like": False,
    }
    assert line["meta_shape"]["s.key#0"]["key_len"] == len(dashed)
    for part in (digits, digits[1:], dashed, digits[4:]):
        assert part not in err


def test_meta_key_rule_keeps_safe_keys_and_replaces_the_rest():
    """The key rule directly: allowed shape and no 7-digit run, else a placeholder."""
    shape: dict = {}
    assert mcp._meta_key_name("sessionKey", 0, "", shape) == "sessionKey"
    assert mcp._meta_key_name("a.b/c-d_1", 1, "", shape) == "a.b/c-d_1"
    assert mcp._meta_key_name("x" + "1" * 6, 2, "", shape) == "x" + "1" * 6
    assert mcp._meta_key_name("x" + "1" * 7, 3, "", shape) == "key#3"
    assert mcp._meta_key_name("9lead", 4, "p.", shape) == "p.key#4"
    assert mcp._meta_key_name("a" * 65, 5, "", shape) == "key#5"
    assert mcp._meta_key_name("has space", 6, "", shape) == "key#6"
    assert set(shape) == {"key#3", "p.key#4", "key#5", "key#6"}
    assert shape["key#5"] == {"key_len": 65, "key_phone_like": False}
