"""Pydantic models: the only shapes that cross a boundary.

Modules: `models` (the docs/CONTRACTS.md models), `results` (the AgentResult
envelope), `fieldmap` (source column -> model), `asof` (as-of dates and windows),
`valid_values` (value sets user input is checked against).
"""

from idx_agent.domain import asof, fieldmap, models
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import (
    AgentResult,
    Clarification,
    CompEvidence,
    Geography,
    Listing,
    MarketStats,
    MonthRow,
    PendingAction,
    PropertySearchFilters,
    Recommendation,
    RetrievedChunk,
    SoftPreferences,
    SoldComp,
    StatsWindow,
    ToolError,
    UserSession,
)

__all__ = [
    "AgentResult",
    "AsOfDates",
    "Clarification",
    "CompEvidence",
    "Geography",
    "Listing",
    "MarketStats",
    "MonthRow",
    "PendingAction",
    "PropertySearchFilters",
    "Recommendation",
    "RetrievedChunk",
    "SoftPreferences",
    "SoldComp",
    "StatsWindow",
    "ToolError",
    "UserSession",
    "asof",
    "fieldmap",
    "models",
]
