"""Structured email request; addresses, subjects and bodies are never model inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from idx_agent.domain.models import Clarification, MarketStatsRequest, RagRequest


class DraftEmailRequest(BaseModel):
    """A known data source and owner label, with at most ten listing identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    source: Literal["listings", "market", "document"]
    listing_keys: list[int] | None = Field(default=None, min_length=1, max_length=10)
    sender_id: str | None = None
    city: str | None = None
    postal_code: str | None = None
    property_subtype: str | None = None
    months: int | None = None
    question: str | None = None
    to: Literal["owner"] = "owner"

    @classmethod
    def from_input(cls, raw: Mapping[str, object]) -> DraftEmailRequest | Clarification:
        if set(raw) - cls.model_fields.keys():
            return Clarification(
                field="unknown",
                reason="unsupported_filter",
                question="Please use the supported email draft fields.",
            )
        if raw.get("to", "owner") != "owner":
            return Clarification(
                field="to",
                reason="recipient_not_allowed",
                question="Email drafts are available for the owner only.",
            )
        try:
            request = cls.model_validate(
                {k: v for k, v in raw.items() if v is not None}
            )
        except ValidationError:
            return Clarification(
                field="source",
                reason="invalid_value",
                question="Should I draft listings, market figures, or reference notes?",
            )
        if request.listing_keys and any(
            type(k) is not int or k < 1 for k in raw["listing_keys"]
        ):
            return Clarification(
                field="listing_keys",
                reason="invalid_value",
                question="Which displayed listings should I include?",
            )
        groups = {
            "listings": {"listing_keys", "sender_id"},
            "market": {"city", "postal_code", "property_subtype", "months"},
            "document": {"question"},
        }
        extra = (
            {k for k, v in raw.items() if v is not None}
            - groups[request.source]
            - {"source", "to"}
        )
        if extra:
            return Clarification(
                field="source",
                reason="unsupported_filter",
                question="Please draft one source at a time.",
            )
        if request.source == "market":
            checked = MarketStatsRequest.from_input(
                {k: raw[k] for k in groups["market"] if k in raw}
            )
            if isinstance(checked, Clarification):
                return checked
        if request.source == "document":
            checked = RagRequest.from_input({"question": request.question})
            if isinstance(checked, Clarification):
                return checked
        return request
