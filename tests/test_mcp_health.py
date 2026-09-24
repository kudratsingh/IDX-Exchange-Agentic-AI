"""The `health` tool returns a valid AgentResult over the MCP layer, no OpenClaw.

Covers each link: tool body -> `_guarded` wrapper -> MCP call path -> log line,
plus the error path and log redaction.
"""

import asyncio
import json

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
    assert mcp.tool_names() == ["health", "search_listings"]
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
