"""The IDX MCP server: typed tools over the data layer (docs/ARCHITECTURE.md, sec. 2).

Flow: runtime -> `@server.tool` fn -> `_guarded` -> body -> AgentResult -> JSON dict.
WO-001 exposes one tool, `health`, with no database. No tool raises across the MCP
boundary. Each call logs one line with a trace id to stderr; stdout is the transport.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import MCPServer

from idx_agent import __version__
from idx_agent.domain.results import (
    AgentResult,
    AsOf,
    HealthData,
    Provenance,
    ToolError,
)
from idx_agent.observability.logging import Timer, log_event, new_trace_id

# Matches the `idx` server entry in config/openclaw.idx.json5 (tools allowed: idx__*).
SERVER_NAME = "idx"

# The one server instance; `@server.tool` registers tools on it. `instructions` tell
# the model what shape every tool returns.
server = MCPServer(
    name=SERVER_NAME,
    version=__version__,
    instructions=(
        "Tools over the IDX Exchange MLS data. Every tool returns an AgentResult "
        "envelope: ok, data, message, warnings, provenance, pending_action, error."
    ),
)


def _provenance(
    tool: str, trace_id: str, tables: list[str] | None = None
) -> Provenance:
    """Build the Provenance for one call: tool name, trace id, tables read.

    As-of dates stay empty until the database is wired in.
    """
    return Provenance(tables=tables or [], as_of=AsOf(), tool=tool, trace_id=trace_id)


def health_result(trace_id: str | None = None) -> AgentResult[HealthData]:
    """Body of the `health` tool: server time, version, and database state.

    Takes an optional trace id (a new one is made if absent). Returns an ok
    AgentResult[HealthData]; database is "not_configured" in WO-001.
    """
    trace_id = trace_id or new_trace_id()
    data = HealthData(server_time=datetime.now(UTC), version=__version__)
    return AgentResult[HealthData](
        ok=True,
        data=data,
        message=f"idx_agent {__version__} is up",
        provenance=_provenance("health", trace_id),
    )


def _guarded(tool: str, fn: Any, **kwargs: Any) -> dict[str, Any]:
    """Run a tool body, log one line, and turn any exception into ok=False.

    Input: tool name, body `fn(trace_id=..., **kwargs)`, and its arguments.
    Output: the AgentResult as a JSON-ready dict. Steps are numbered below.
    """
    # 1. New trace id for this call; it goes into the result and the log line.
    trace_id = new_trace_id()
    # 2. Run the body under a timer; any exception becomes an "internal" error
    #    result (detail kept short and internal) instead of propagating.
    with Timer() as timer:
        try:
            result = fn(trace_id=trace_id, **kwargs)
        except Exception as exc:  # noqa: BLE001 - never raise across the MCP boundary
            result = AgentResult[HealthData](
                ok=False,
                provenance=_provenance(tool, trace_id),
                error=ToolError(
                    category="internal",
                    message="The tool failed; the trace id was logged.",
                    detail=repr(exc)[:300],
                    trace_id=trace_id,
                ),
            )
    # 3. One redacted log line: tool, ok, duration, error category (no payload).
    log_event(
        "tool_call",
        trace_id,
        tool=tool,
        ok=result.ok,
        ms=timer.ms,
        error=result.error.category if result.error else None,
    )
    # 4. Serialize to plain JSON types; this dict is what crosses the MCP boundary.
    return result.model_dump(mode="json")


@server.tool(
    name="health",
    description=(
        "Health check: server time, idx_agent version, and whether the database is "
        "configured. Takes no arguments. Returns an AgentResult envelope."
    ),
)
def health() -> dict[str, Any]:
    """MCP entry point for `health`: runs `health_result` through `_guarded`."""
    return _guarded("health", health_result)


def tool_names() -> list[str]:
    """Return the sorted names of all registered tools (used at start and in tests)."""
    return sorted(t.name for t in asyncio.run(server.list_tools()))


def main() -> None:
    """Start the server: `python -m idx_agent.mcp_server.server`.

    1. Log a `server_start` line with the tool list to stderr.
    2. Serve over stdio; this call blocks until the transport closes.
    """
    log_event("server_start", new_trace_id(), server=SERVER_NAME, tools=tool_names())
    server.run(transport="stdio")


# Ctrl-C exits with status 0 instead of printing a traceback.
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
