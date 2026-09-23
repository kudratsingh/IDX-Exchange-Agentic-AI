"""The envelope every tool returns.

See docs/CONTRACTS.md: AgentResult, ToolError, PendingAction.

Nothing crosses the MCP boundary except these models, serialized with `model_dump()`.
A tool never raises across the boundary: failures become
`AgentResult(ok=False, error=...)`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

ErrorCategory = Literal[
    "validation",
    "not_found",
    "db",
    "provider",
    "timeout",
    "rate_limit",
    "safety_refusal",
    "internal",
]


class ToolError(BaseModel):
    """A safe, user-facing failure.

    `detail` is internal and never sent to the channel.
    """

    model_config = ConfigDict(extra="forbid")

    category: ErrorCategory
    message: str
    detail: str | None = None
    trace_id: str


class AsOf(BaseModel):
    """The data's own as-of dates.

    Time windows count back from these, never from today.
    """

    model_config = ConfigDict(extra="forbid")

    sold: date | None = None
    active: date | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: list[str] = Field(default_factory=list)
    as_of: AsOf = Field(default_factory=AsOf)
    tool: str
    trace_id: str


class PendingAction(BaseModel):
    """An email draft waiting for explicit human approval.

    Approval binds to this exact record.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["email"] = "email"
    recipient: str
    subject: str
    body: str
    created_at: datetime
    state: Literal["pending", "approved", "sent", "rejected", "expired"] = "pending"


class AgentResult(BaseModel, Generic[T]):
    """The envelope every tool returns."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: T | list[T] | None = None
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance
    pending_action: PendingAction | None = None
    error: ToolError | None = None


class HealthData(BaseModel):
    """What the `health` tool reports. No database yet (WO-001)."""

    model_config = ConfigDict(extra="forbid")

    server_time: datetime
    version: str
    database: Literal["not_configured", "reachable", "unreachable"] = "not_configured"
