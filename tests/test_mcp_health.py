"""The `health` tool returns a valid AgentResult over the MCP layer, no OpenClaw."""

import asyncio
import json

from idx_agent import __version__
from idx_agent.domain.results import AgentResult, HealthData
from idx_agent.mcp_server import server as mcp
from idx_agent.observability import logging as obs


def test_health_result_is_a_valid_agent_result():
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
    assert mcp.tool_names() == ["health"]
    payload = mcp.health()
    envelope = AgentResult[HealthData].model_validate(payload)
    assert envelope.ok and envelope.data.version == __version__
    json.dumps(payload)  # serializable as-is


def test_health_over_the_mcp_call_path():
    result = asyncio.run(mcp.server.call_tool("health", {}))
    content = result.structured_content or json.loads(result.content[0].text)
    envelope = AgentResult[HealthData].model_validate(content)
    assert envelope.ok and envelope.provenance.tool == "health"


def test_a_failing_tool_body_becomes_an_error_result(capsys):
    def boom(trace_id):
        raise RuntimeError("secret " + "sk-" + "abcdefghijklmnop" + " leaked?")

    payload = mcp._guarded("health", boom)
    envelope = AgentResult[HealthData].model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "internal"
    assert envelope.error.trace_id == envelope.provenance.trace_id
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["event"] == "tool_call" and line["ok"] is False
    assert line["error"] == "internal" and line["trace_id"] == envelope.error.trace_id


def test_log_lines_are_redacted(capsys):
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
