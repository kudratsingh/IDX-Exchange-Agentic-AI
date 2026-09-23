"""The IDX MCP server: typed tools over the data layer.

See docs/ARCHITECTURE.md, section 2.

WO-001 exposes one tool, `health`, with no database. Every tool returns an `AgentResult`
serialized with `model_dump()` and never raises across the MCP boundary. Each call logs
one structured line with a trace id to stderr; stdout belongs to the stdio transport.

Run:  python -m idx_agent.mcp_server.server
(stdio; logs its tool list to stderr on start)
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

SERVER_NAME = "idx"

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
    return Provenance(tables=tables or [], as_of=AsOf(), tool=tool, trace_id=trace_id)


def health_result(trace_id: str | None = None) -> AgentResult[HealthData]:
    """Server time, package version, and database state (not configured in WO-001)."""
    trace_id = trace_id or new_trace_id()
    data = HealthData(server_time=datetime.now(UTC), version=__version__)
    return AgentResult[HealthData](
        ok=True,
        data=data,
        message=f"idx_agent {__version__} is up",
        provenance=_provenance("health", trace_id),
    )


def _guarded(tool: str, fn: Any, **kwargs: Any) -> dict[str, Any]:
    """Run a tool body, log one line, and turn any exception into ok=False."""
    trace_id = new_trace_id()
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
    log_event(
        "tool_call",
        trace_id,
        tool=tool,
        ok=result.ok,
        ms=timer.ms,
        error=result.error.category if result.error else None,
    )
    return result.model_dump(mode="json")


@server.tool(
    name="health",
    description=(
        "Health check: server time, idx_agent version, and whether the database is "
        "configured. Takes no arguments. Returns an AgentResult envelope."
    ),
)
def health() -> dict[str, Any]:
    return _guarded("health", health_result)


def tool_names() -> list[str]:
    return sorted(t.name for t in asyncio.run(server.list_tools()))


def main() -> None:
    log_event("server_start", new_trace_id(), server=SERVER_NAME, tools=tool_names())
    server.run(transport="stdio")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
