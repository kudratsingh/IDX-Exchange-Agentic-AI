"""Saved-search boundary contracts; no recipient address crosses a tool."""

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from idx_agent.domain.models import PropertySearchFilters


class SavedSearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sender_key: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False, exclude=True)
    filters: PropertySearchFilters
    created_at: datetime
    checked_as_of: date
    last_alert_as_of: date | None = None
    alerted_keys: list[int] = Field(default_factory=list, max_length=500)
    recipient_label: Literal["owner"] = "owner"

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(days=180)


class SavedSearchView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    filters: PropertySearchFilters
    checked_as_of: date
    last_alert_as_of: date | None = None
    expires_at: datetime
    recipient_label: Literal["owner"] = "owner"
