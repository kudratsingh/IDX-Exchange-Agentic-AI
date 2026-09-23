"""The envelope every tool returns (docs/CONTRACTS.md: AgentResult, ToolError, ...).

Flow: tool body -> AgentResult -> `model_dump()` -> MCP boundary -> runtime.
Only these models cross that boundary. A tool never raises across it: failures
become `AgentResult(ok=False, error=...)`. Every model forbids unknown fields.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# The payload model a tool puts in `AgentResult.data` (for example HealthData).
T = TypeVar("T")

# Fixed set of failure kinds; callers branch on the category, not on message text.
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
    """A safe, user-facing failure carried in `AgentResult.error`.

    `category` says what kind of failure; `message` is safe to show the user.
    `detail` is internal and never sent to the channel. `trace_id` links the
    failure to its log line.
    """

    model_config = ConfigDict(extra="forbid")

    category: ErrorCategory
    message: str
    detail: str | None = None
    trace_id: str


class AsOf(BaseModel):
    """The data's own as-of dates: the date each table's data runs to.

    `sold` is for california_sold, `active` for rets_property; None when unknown.
    Time windows count back from these, never from today.
    """

    model_config = ConfigDict(extra="forbid")

    sold: date | None = None
    active: date | None = None


class Provenance(BaseModel):
    """Where a result came from: tables read, their as-of dates, tool, trace id.

    Lets a reply cite its source and lets a log line be matched to the result.
    """

    model_config = ConfigDict(extra="forbid")

    tables: list[str] = Field(default_factory=list)
    as_of: AsOf = Field(default_factory=AsOf)
    tool: str
    trace_id: str


class PendingAction(BaseModel):
    """An email draft waiting for explicit human approval.

    Flow: draft -> this stored record (state "pending") -> human approves ->
    send. Approval binds to this exact record (by `id`), so an edited draft
    needs a new approval. `state` tracks where the record is in that flow.
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
    """The envelope every tool returns, generic over the payload type T.

    `ok` is True on success with `data` set; on failure `ok` is False and
    `error` is set. `provenance` is always present. `pending_action` is set
    only when the tool produced something that needs human approval.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: T | list[T] | None = None
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance
    pending_action: PendingAction | None = None
    error: ToolError | None = None


class HealthData(BaseModel):
    """What the `health` tool reports in `AgentResult.data`.

    Server time (UTC), package version, and database state. No database yet
    (WO-001), so `database` stays "not_configured".
    """

    model_config = ConfigDict(extra="forbid")

    server_time: datetime
    version: str
    database: Literal["not_configured", "reachable", "unreachable"] = "not_configured"
