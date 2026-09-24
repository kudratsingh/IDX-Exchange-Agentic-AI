"""Domain models from docs/CONTRACTS.md: the only shapes that cross a boundary.

Value-set checks (city, subtype) apply to PropertySearchFilters, the user input;
`PropertySearchFilters.from_input` turns a failed check into a Clarification.
Listing and SoldComp hold data as stored and refuse deny-listed or agent-contact keys.
All models forbid unknown fields and hide input in errors; all but UserSession are
frozen (shallowly: a list field's contents can still be changed in place).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from idx_agent.domain.results import AgentResult, PendingAction, ToolError
from idx_agent.domain.valid_values import SUBTYPES, stored_city
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

__all__ = [
    "AgentResult",
    "Clarification",
    "CompEvidence",
    "Geography",
    "Listing",
    "MIN_YEAR_BUILT",
    "MarketStats",
    "MonthRow",
    "PendingAction",
    "PropertySearchFilters",
    "Recommendation",
    "RetrievedChunk",
    "SCORE_COMPONENTS",
    "SoftPreferences",
    "SoldComp",
    "StatsWindow",
    "ToolError",
    "UserSession",
    "safe_errors",
    "to_channel",
]

# Five ASCII digits; [0-9] rather than \d so non-ASCII digits are refused.
_ZIP = r"^[0-9]{5}$"
# A soft-preference term: surrounding whitespace trimmed, empty refused.
_Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Earliest year_built accepted; fieldmap turns anything older (e.g. 0) into None.
MIN_YEAR_BUILT = 1800
# The parts a Recommendation score may be built from (docs/CONTRACTS.md).
SCORE_COMPONENTS: frozenset[str] = frozenset(
    {"price", "beds", "city", "sqft", "semantic"}
)


class _Frozen(BaseModel):
    """Shared config: immutable, unknown fields refused, input kept out of errors.

    Hiding input keeps remarks or a stray contact value out of a logged error.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


def _reject_forbidden_keys(data: Any, model: str) -> Any:
    """Raise if a raw input mapping has a deny-listed or agent-contact key.

    Runs before field validation so the error names the reason, not just
    "extra field". Non-mapping input is returned unchanged.
    """
    if isinstance(data, Mapping):
        for key in data:
            if key in DENYLIST:
                raise ValueError(
                    f"field {key!r} is deny-listed; not allowed in {model}"
                )
            if key in AGENT_CONTACT:
                raise ValueError(
                    f"field {key!r} is an agent contact field; not allowed in {model}"
                )
    return data


class Clarification(_Frozen):
    """A follow-up question returned instead of a search when a filter is unusable.

    `field` names the filter, `reason` is a stable code (e.g. "unknown_city"),
    `question` never repeats the user's value, `options` lists a small allowed set.
    """

    field: str
    reason: str
    question: str
    options: list[str] | None = None


# Plain-language names for filter fields, used in follow-up questions.
_LABELS: dict[str, str] = {
    "city": "city",
    "postal_code": "ZIP code",
    "min_price": "minimum price",
    "max_price": "maximum price",
    "min_beds": "minimum number of bedrooms",
    "min_baths": "minimum number of bathrooms",
    "min_sqft": "minimum living area in square feet",
    "property_subtype": "property type",
    "pool": "pool preference",
    "view": "view preference",
    "max_hoa_monthly": "maximum monthly HOA fee",
    "page": "page number",
    "limit": "number of results",
}
# Pydantic error types mapped to stable reason codes; anything else is "invalid_value".
# The filter validators raise their own codes (unknown_city, min_above_max, ...).
_REASONS: dict[str, str] = {
    "extra_forbidden": "unsupported_filter",
    "greater_than_equal": "below_minimum",
    "greater_than": "below_minimum",
    "less_than_equal": "above_maximum",
    "less_than": "above_maximum",
    "string_pattern_mismatch": "invalid_format",
}
# Fixed questions per reason; range and fallback questions are built from the label.
_QUESTIONS: dict[str, str] = {
    "missing_location": "Which city or ZIP code should I search in?",
    "unknown_city": (
        "I could not match that city to one in the listings. "
        "Which city should I search in?"
    ),
    "unknown_subtype": (
        "Which property type do you mean? Please pick one of the options."
    ),
    "min_above_max": (
        "The minimum price is above the maximum price. What price range should I use?"
    ),
    "not_half_step": (
        "Bathrooms count in whole or half steps. "
        "What minimum number of bathrooms should I use?"
    ),
    "unsupported_filter": (
        "I cannot search on that filter. "
        "Which of the supported filters should I use instead?"
    ),
}
# A filter key safe to repeat back as `field`: a short snake_case name, never free text.
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _clarify(error: Mapping[str, Any], filter_names: list[str]) -> Clarification:
    """Turn one pydantic error (input already stripped) into a Clarification.

    Uses only the error's location, type, and bound; never the rejected value.
    """
    loc = error.get("loc") or ()
    key = loc[0] if loc else None
    kind = str(error.get("type", ""))
    reason = _REASONS.get(kind, kind if kind in _QUESTIONS else "invalid_value")
    if reason == "min_above_max":
        key = "min_price"
    field = key if isinstance(key, str) and _FIELD_NAME.match(key) else "unknown"
    label = _LABELS.get(field, "that filter")
    ctx = error.get("ctx") or {}
    if reason in _QUESTIONS:
        question = _QUESTIONS[reason]
    elif reason == "below_minimum":
        bound = ctx.get("ge", ctx.get("gt"))
        question = f"The {label} must be at least {bound}. What {label} should I use?"
    elif reason == "above_maximum":
        bound = ctx.get("le", ctx.get("lt"))
        question = f"The {label} can be at most {bound}. What {label} should I use?"
    elif reason == "invalid_format" and field == "postal_code":
        question = "ZIP codes have five digits. Which ZIP code should I search in?"
    elif field not in _LABELS:
        question = (
            "I could not use one of the search filters. What are you looking for?"
        )
    else:
        question = f"I could not use the {label} given. What {label} should I use?"
    options = None
    if reason == "unknown_subtype":
        options = sorted(SUBTYPES)
    elif reason == "unsupported_filter":
        options = filter_names
    return Clarification(field=field, reason=reason, question=question, options=options)


class PropertySearchFilters(_Frozen):
    """Hard constraints parsed from user language; every value checked, never guessed.

    Every field is optional. City is normalized and must be a known city; subtype
    must be a known subtype. Prices >= 0 with min <= max, beds 0-20, baths 0-20 in
    half steps, limit 1-50. `from_input` returns a Clarification instead of raising.
    """

    city: str | None = None
    postal_code: str | None = Field(default=None, pattern=_ZIP)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    min_beds: int | None = Field(default=None, ge=0, le=20)
    min_baths: float | None = Field(default=None, ge=0, le=20)
    min_sqft: int | None = Field(default=None, ge=0)
    property_subtype: str | None = None
    pool: bool | None = None
    view: bool | None = None
    max_hoa_monthly: int | None = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=5, ge=1, le=50)

    @field_validator("city")
    @classmethod
    def _city_known(cls, value: str | None) -> str | None:
        """Match any casing or spacing to a known city; keep its stored spelling."""
        if value is None:
            return None
        city = stored_city(value)
        if city is None:
            raise PydanticCustomError("unknown_city", "unknown city")
        return city

    @field_validator("property_subtype")
    @classmethod
    def _subtype_known(cls, value: str | None) -> str | None:
        """Require the subtype to be one of SUBTYPES (exact RESO spelling)."""
        if value is not None and value not in SUBTYPES:
            raise PydanticCustomError("unknown_subtype", "unknown property subtype")
        return value

    @field_validator("min_baths")
    @classmethod
    def _half_steps(cls, value: float | None) -> float | None:
        """Require bathrooms in half steps (2, 2.5, 3), refusing values like 2.3."""
        if value is not None and (value * 2) % 1 != 0:
            raise PydanticCustomError(
                "not_half_step", "min_baths must be a whole or half number"
            )
        return value

    @model_validator(mode="after")
    def _price_order(self) -> PropertySearchFilters:
        """Require min_price <= max_price when both are set."""
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise PydanticCustomError(
                "min_above_max", "min_price is greater than max_price"
            )
        return self

    @classmethod
    def from_input(
        cls, raw: Mapping[str, object]
    ) -> PropertySearchFilters | Clarification:
        """Validate a tool-call mapping; return the filters or one Clarification.

        The first validation error becomes the Clarification; with no city and no
        postal code the reason is "missing_location". Bad user data never raises;
        a non-mapping `raw` is a programmer error and raises TypeError.
        """
        if not isinstance(raw, Mapping):
            raise TypeError("from_input expects a mapping of filter names to values")
        try:
            filters = cls.model_validate(dict(raw))
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            return _clarify(errors[0], sorted(cls.model_fields))
        if filters.city is None and filters.postal_code is None:
            return Clarification(
                field="city",
                reason="missing_location",
                question=_QUESTIONS["missing_location"],
            )
        return filters


class SoftPreferences(_Frozen):
    """Free-text descriptors ("quiet street") used only for semantic ranking.

    Never placed in SQL. Each term is trimmed and must be non-empty.
    """

    terms: list[_Term] = Field(default_factory=list)


class Listing(_Frozen):
    """One active listing in RESO-style names; built from a row by fieldmap.to_listing.

    Deny-listed and agent-contact keys are refused with a named reason.
    `remarks` is untrusted text: hidden from repr and dropped by `for_log()`.
    """

    listing_key: int
    listing_id: str
    address: str | None = None
    city: str | None = None
    postal_code: str | None = Field(default=None, pattern=_ZIP)
    list_price: int = Field(ge=0)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: float | None = Field(default=None, ge=0)
    living_area: int | None = Field(default=None, ge=0)
    property_subtype: str | None = None
    status: str | None = None
    year_built: int | None = Field(default=None, ge=MIN_YEAR_BUILT)
    hoa_fee_monthly: int | None = Field(default=None, ge=0)
    days_on_market: int | None = Field(default=None, ge=0)
    photo_count: int = Field(default=0, ge=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    pool: bool | None = None
    view: bool | None = None
    fireplace: bool | None = None
    remarks: str | None = Field(default=None, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _no_forbidden_keys(cls, data: Any) -> Any:
        """Refuse deny-listed and agent-contact keys before extra="forbid" runs."""
        return _reject_forbidden_keys(data, "Listing")

    def for_log(self) -> dict[str, Any]:
        """Return a JSON-ready dict without `remarks`, for log lines."""
        return self.model_dump(mode="json", exclude={"remarks"})


class SoldComp(_Frozen):
    """One closed sale used as a comparable; built from a row by fieldmap.to_sold_comp.

    Refuses deny-listed and agent-contact keys the same way Listing does.
    """

    listing_key: int
    address: str | None = None
    city: str | None = None
    postal_code: str | None = Field(default=None, pattern=_ZIP)
    close_date: date
    close_price: int = Field(ge=0)
    list_price: int | None = Field(default=None, ge=0)
    original_list_price: int | None = Field(default=None, ge=0)
    days_on_market: int | None = Field(default=None, ge=0)
    bedrooms: int | None = Field(default=None, ge=0)
    living_area: int | None = Field(default=None, ge=0)
    property_subtype: str | None = None
    year_built: int | None = Field(default=None, ge=MIN_YEAR_BUILT)

    @model_validator(mode="before")
    @classmethod
    def _no_forbidden_keys(cls, data: Any) -> Any:
        """Refuse deny-listed and agent-contact keys before extra="forbid" runs."""
        return _reject_forbidden_keys(data, "SoldComp")


class MonthRow(_Frozen):
    """One month of a MarketStats trend: month ("YYYY-MM"), count, median price."""

    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    sample_count: int = Field(ge=0)
    median_close_price: float | None = Field(default=None, ge=0)


class Geography(_Frozen):
    """Where MarketStats applies: exactly one of city or postal_code."""

    city: str | None = None
    postal_code: str | None = Field(default=None, pattern=_ZIP)

    @model_validator(mode="after")
    def _exactly_one(self) -> Geography:
        """Require exactly one of city and postal_code to be set."""
        if (self.city is None) == (self.postal_code is None):
            raise ValueError("set exactly one of city or postal_code")
        return self


class StatsWindow(_Frozen):
    """The date range MarketStats covers: start <= end, counted back `months` months."""

    start: date
    end: date
    months: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> StatsWindow:
        """Require start on or before end."""
        if self.start > self.end:
            raise ValueError("window start is after its end")
        return self


class MarketStats(_Frozen):
    """Closed-sale statistics for one geography, subtype, and window.

    The window must end on or before `as_of` (count back from the data, never
    today). The four readings (dom_band, ratio, reading, lean) may be None only
    when sample_count is 0; figures are None when there is nothing to compute.
    """

    geography: Geography
    property_subtype: str | None = None
    window: StatsWindow
    as_of: date
    sample_count: int = Field(ge=0)
    low_sample: bool
    median_close_price: float | None = Field(default=None, ge=0)
    mean_close_price: float | None = Field(default=None, ge=0)
    median_price_per_sqft: float | None = Field(default=None, ge=0)
    median_dom: float | None = Field(default=None, ge=0)
    dom_band: Literal["very_low", "low", "average", "high"] | None = None
    sale_to_list_ratio: float | None = Field(default=None, gt=0)
    sale_to_list_reading: str | None = None
    market_lean: Literal["seller", "buyer", "balanced"] | None = None
    trend: list[MonthRow] = Field(default_factory=list)
    exclusions_applied: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _window_and_readings(self) -> MarketStats:
        """Require the window to end by `as_of`, and readings when there are sales."""
        if self.window.end > self.as_of:
            raise ValueError("window ends after the as-of date")
        readings = (
            self.dom_band,
            self.sale_to_list_ratio,
            self.sale_to_list_reading,
            self.market_lean,
        )
        if self.sample_count > 0 and any(r is None for r in readings):
            raise ValueError("dom_band, sale_to_list_*, market_lean need a value")
        return self


class CompEvidence(_Frozen):
    """How a Recommendation's price was checked against comparable sales.

    `sufficient` is False when too few comps back the estimate.
    """

    count: int = Field(ge=0)
    window_months: int = Field(ge=1)
    subtype: str | None = None
    comp_price_estimate: int | None = Field(default=None, ge=0)
    delta_pct: float | None = None
    sufficient: bool


class Recommendation(_Frozen):
    """A ranked listing with its score parts, comp evidence, and a short explanation.

    `score_components` keys must come from SCORE_COMPONENTS.
    """

    listing: Listing
    score_total: float
    score_components: dict[str, float] = Field(default_factory=dict)
    comp_evidence: CompEvidence
    explanation: str

    @field_validator("score_components")
    @classmethod
    def _known_components(cls, value: dict[str, float]) -> dict[str, float]:
        """Refuse score parts outside SCORE_COMPONENTS."""
        unknown = set(value) - SCORE_COMPONENTS
        if unknown:
            raise ValueError(f"unknown score components {sorted(unknown)}")
        return value


class RetrievedChunk(_Frozen):
    """One passage returned by retrieval; `text` is data, never instructions."""

    text: str
    source_doc: str
    section_or_field: str
    page: int | None = Field(default=None, ge=1)
    score: float


class UserSession(BaseModel):
    """Per-sender conversation state; the one mutable model (assignments validated).

    `sender_id` must be a lowercase hex hash (16-128 chars), so a raw phone
    number cannot be stored as the key.
    """

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, hide_input_in_errors=True
    )

    sender_id: str = Field(pattern=r"^[0-9a-f]{16,128}$")
    filters: PropertySearchFilters | None = None
    last_result_keys: list[int] = Field(default_factory=list)
    step: int = Field(default=0, ge=0)
    pending_approval_id: str | None = None
    updated_at: datetime


# SavedSearch (sender_id, filters, email, last_alert_at) is deferred until the Week 4
# decision; no class until then (docs/CONTRACTS.md).


def to_channel(obj: ToolError | AgentResult) -> dict[str, Any]:
    """Serialize a ToolError or an AgentResult to a JSON-ready dict for a channel.

    Thin wrapper: `ToolError.detail` is declared `exclude=True`, so no dump of
    either model ever contains it.
    """
    return obj.model_dump(mode="json")


def safe_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Return a validation error's details without input values or doc URLs.

    Safe to log: no remarks, contact values, or user text are echoed back.
    """
    return exc.errors(include_input=False, include_url=False)
