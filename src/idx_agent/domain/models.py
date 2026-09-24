"""Domain models from docs/CONTRACTS.md: the only shapes that cross a boundary.

User input models check city and subtype; `from_input` turns a failed check into a
Clarification. Listing and SoldComp refuse deny-listed or agent-contact keys. All forbid
unknown fields and hide input in errors; all but UserSession are (shallowly) frozen."""

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
    "KEY_WINS_WARNING",
    "Listing",
    "MIN_YEAR_BUILT",
    "MarketStats",
    "MarketStatsRequest",
    "MonthRow",
    "PendingAction",
    "PropertySearchFilters",
    "RECOMMEND_MAX_K",
    "RECOMMEND_QUESTIONS",
    "RecommendRequest",
    "Recommendation",
    "RecommendationResult",
    "RetrievedChunk",
    "SCORE_COMPONENTS",
    "SearchResult",
    "SimilarListingsRequest",
    "SimilarMatch",
    "SimilarResult",
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
    "months": "number of months",
    "k": "number of matches",
    "listing_key": "listing number",
    "position": "position in the last result",
    "sender_id": "sender id",
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
# Market figures cover one place: asked when both a city and a ZIP code are given.
_BOTH_LOCATIONS_QUESTION = (
    "I can look at a city or a ZIP code, not both. Which one should I use?"
)
# The market tool's own wording for the location reasons (same reason codes).
_MARKET_QUESTIONS: dict[str, str] = {
    "missing_location": "Which city or ZIP code should I report the market for?",
    "unknown_city": (
        "I could not match that city to one in the sales data. "
        "Which city should I report on?"
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


def _known_city(value: str | None) -> str | None:
    """Return a known city's stored spelling (any casing or spacing), else raise."""
    if value is None:
        return None
    city = stored_city(value)
    if city is None:
        raise PydanticCustomError("unknown_city", "unknown city")
    return city


def _known_subtype(value: str | None) -> str | None:
    """Return the subtype if it is one of SUBTYPES (exact RESO spelling), else raise."""
    if value is not None and value not in SUBTYPES:
        raise PydanticCustomError("unknown_subtype", "unknown property subtype")
    return value


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
    page: int = Field(default=1, ge=1, le=1000)
    limit: int = Field(default=5, ge=1, le=50)

    @field_validator("city")
    @classmethod
    def _city_known(cls, value: str | None) -> str | None:
        """Match any casing or spacing to a known city; keep its stored spelling."""
        return _known_city(value)

    @field_validator("property_subtype")
    @classmethod
    def _subtype_known(cls, value: str | None) -> str | None:
        """Require the subtype to be one of SUBTYPES (exact RESO spelling)."""
        return _known_subtype(value)

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


class SearchResult(_Frozen):
    """What `search_listings` returns in `AgentResult.data` when a search ran.

    `listings` are the page (at most 50); `applied_filters` is the validated (and,
    in a follow-up, merged) filter object the query used, not the raw input.
    `total_matches` counts every match; above 50, `narrowing_question` asks the
    user for a budget or a home type (WO-006).
    """

    listings: list[Listing] = Field(default_factory=list, max_length=50)
    applied_filters: PropertySearchFilters
    total_matches: int | None = Field(default=None, ge=0)
    narrowing_question: str | None = None


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


class MarketStatsRequest(_Frozen):
    """What get_market_stats is asked for: one place, an optional subtype, a window.

    Exactly one of city (stored spelling) and a five-digit postal_code; subtype
    from SUBTYPES, None meaning the single-family default; months 1-24, default 6.
    `from_input` returns a Clarification instead of raising.
    """

    city: str | None = None
    postal_code: str | None = Field(default=None, pattern=_ZIP)
    property_subtype: str | None = None
    months: int = Field(default=6, ge=1, le=24)

    @field_validator("city")
    @classmethod
    def _city_known(cls, value: str | None) -> str | None:
        """Match any casing or spacing to a known city; keep its stored spelling."""
        return _known_city(value)

    @field_validator("property_subtype")
    @classmethod
    def _subtype_known(cls, value: str | None) -> str | None:
        """Require the subtype to be one of SUBTYPES (exact RESO spelling)."""
        return _known_subtype(value)

    @field_validator("months", mode="before")
    @classmethod
    def _months_not_bool(cls, value: Any) -> Any:
        """Refuse True/False, which pydantic would otherwise read as 1 and 0."""
        if isinstance(value, bool):
            raise PydanticCustomError("invalid_value", "months must be a number")
        return value

    @model_validator(mode="after")
    def _one_location(self) -> MarketStatsRequest:
        """Require exactly one of city and postal_code."""
        if self.city is None and self.postal_code is None:
            raise PydanticCustomError("missing_location", "no city or postal code")
        if self.city is not None and self.postal_code is not None:
            raise PydanticCustomError("both_locations", "both city and postal code")
        return self

    @classmethod
    def from_input(
        cls, raw: Mapping[str, object]
    ) -> MarketStatsRequest | Clarification:
        """Validate a tool-call mapping; return the request or one Clarification.

        None values count as unset (months falls back to 6). Field errors come
        first, then the location rule; a non-mapping `raw` raises TypeError.
        """
        if not isinstance(raw, Mapping):
            raise TypeError("from_input expects a mapping of argument names to values")
        given = {key: value for key, value in raw.items() if value is not None}
        try:
            return cls.model_validate(given)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
        kind = str(errors[0].get("type", ""))
        if kind in _MARKET_QUESTIONS:
            return Clarification(
                field="city", reason=kind, question=_MARKET_QUESTIONS[kind]
            )
        if kind == "both_locations":
            return Clarification(
                field="city", reason="invalid_value", question=_BOTH_LOCATIONS_QUESTION
            )
        return _clarify(errors[0], sorted(cls.model_fields))

    def geography(self) -> Geography:
        """Return the request's place as a Geography (exactly one of city, ZIP)."""
        return Geography(city=self.city, postal_code=self.postal_code)


# Similar-listing search (WO-010): bounds on the description and the match count.
SIMILAR_MAX_K = 10
SIMILAR_TEXT_MAX_CHARS = 500
_SIMILAR_MIN_WORDS = 2
_SIMILAR_MIN_LETTERS = 8
# Fixed questions for an unusable description; neither repeats the user's text.
_TEXT_QUESTIONS: dict[str, str] = {
    "below_minimum": (
        "Could you describe the home you have in mind in a few more words, "
        "such as its style, its setting, or the features you want?"
    ),
    "above_maximum": (
        f"That description is longer than I can use "
        f"({SIMILAR_TEXT_MAX_CHARS} characters at most). "
        "Could you say it more briefly?"
    ),
}


class SimilarListingsRequest(_Frozen):
    """What find_similar_listings is asked for: a description plus hard filters.

    `text` is whitespace-collapsed, with at least 2 words and 8 letters and at most
    500 characters; k is 1-10 (default 5). The filters are checked as search checks
    them, and no location is required. `from_input` returns a Clarification.
    """

    text: str
    k: int = Field(default=5, ge=1, le=SIMILAR_MAX_K)
    city: str | None = None
    max_price: int | None = Field(default=None, ge=0)
    min_beds: int | None = Field(default=None, ge=0, le=20)
    property_subtype: str | None = None

    @field_validator("text")
    @classmethod
    def _usable_text(cls, value: str) -> str:
        """Collapse whitespace, then require enough words and letters, within 500."""
        text = " ".join(value.split())
        letters = sum(ch.isalpha() for ch in text)
        if len(text.split()) < _SIMILAR_MIN_WORDS or letters < _SIMILAR_MIN_LETTERS:
            raise PydanticCustomError("text_too_short", "description too short")
        if len(text) > SIMILAR_TEXT_MAX_CHARS:
            raise PydanticCustomError("text_too_long", "description too long")
        return text

    @field_validator("k", mode="before")
    @classmethod
    def _k_not_bool(cls, value: Any) -> Any:
        """Refuse True/False, which pydantic would otherwise read as 1 and 0."""
        if isinstance(value, bool):
            raise PydanticCustomError("invalid_value", "k must be a number")
        return value

    @field_validator("city")
    @classmethod
    def _city_known(cls, value: str | None) -> str | None:
        """Match any casing or spacing to a known city; keep its stored spelling."""
        return _known_city(value)

    @field_validator("property_subtype")
    @classmethod
    def _subtype_known(cls, value: str | None) -> str | None:
        """Require the subtype to be one of SUBTYPES (exact RESO spelling)."""
        return _known_subtype(value)

    @classmethod
    def from_input(
        cls, raw: Mapping[str, object]
    ) -> SimilarListingsRequest | Clarification:
        """Validate a tool-call mapping; return the request or one Clarification.

        None values count as unset (k falls back to 5). The first error decides; a
        text error asks for a better description without quoting it. A non-mapping
        `raw` is a programmer error and raises TypeError.
        """
        if not isinstance(raw, Mapping):
            raise TypeError("from_input expects a mapping of argument names to values")
        given = {key: value for key, value in raw.items() if value is not None}
        try:
            return cls.model_validate(given)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
        first = errors[0]
        if tuple(first.get("loc") or ())[:1] == ("text",):
            # Missing, empty, short, or not a string all ask for more words.
            too_long = first.get("type") == "text_too_long"
            reason = "above_maximum" if too_long else "below_minimum"
            return Clarification(
                field="text", reason=reason, question=_TEXT_QUESTIONS[reason]
            )
        return _clarify(first, sorted(cls.model_fields))

    def hard_filters(self) -> PropertySearchFilters:
        """Return only the four hard filters as search filters (page, limit default)."""
        return PropertySearchFilters(
            city=self.city,
            max_price=self.max_price,
            min_beds=self.min_beds,
            property_subtype=self.property_subtype,
        )


class SimilarMatch(_Frozen):
    """One ranked listing: 1-based rank, cosine score (4 decimals), the listing.

    The listing never carries remarks: any remarks value is dropped on construction,
    so no match can return the text it was ranked by.
    """

    rank: int = Field(ge=1, le=SIMILAR_MAX_K)
    score: float = Field(ge=-1, le=1, allow_inf_nan=False)
    listing: Listing

    @field_validator("score", mode="before")
    @classmethod
    def _four_decimals(cls, value: Any) -> Any:
        """Round a number (NumPy floats included) to 4 decimals; refuse text, bools."""
        if isinstance(value, bool | str):
            raise PydanticCustomError("invalid_value", "score must be a number")
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return value

    @field_validator("listing")
    @classmethod
    def _without_remarks(cls, value: Listing) -> Listing:
        """Return the listing with remarks set to None."""
        if value.remarks is None:
            return value
        return value.model_copy(update={"remarks": None})


class SimilarResult(_Frozen):
    """What find_similar_listings returns in `AgentResult.data` when a ranking ran.

    `matches` hold at most k (at most 10), ranked 1..n in order. `applied_filters`
    are the hard filters, never the text; `rows_ranked` counts index rows left after
    the in-memory mask; `index_as_of` is the index's active as-of date.
    """

    matches: list[SimilarMatch] = Field(default_factory=list, max_length=SIMILAR_MAX_K)
    applied_filters: PropertySearchFilters
    k: int = Field(ge=1, le=SIMILAR_MAX_K)
    rows_ranked: int = Field(ge=0)
    index_as_of: date
    model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ranked_within_k(self) -> SimilarResult:
        """Require at most k matches, ranked 1, 2, ... in list order."""
        if len(self.matches) > self.k:
            raise ValueError("more matches than k")
        if [m.rank for m in self.matches] != list(range(1, len(self.matches) + 1)):
            raise ValueError("match ranks must run 1..n in list order")
        return self


class MarketStats(_Frozen):
    """Closed-sale statistics for one geography, subtype, and window.

    The window must end on or before `as_of` (never counted from today). With
    low_sample or no sales, figures and readings may be None. Otherwise the price,
    ratio and reading are required, and dom_band and market_lean whenever
    median_dom is set (under 10 usable days-on-market values leaves all three None).
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
        """Require the window to end by `as_of`, and figures unless low_sample."""
        if self.window.end > self.as_of:
            raise ValueError("window ends after the as-of date")
        if self.low_sample or self.sample_count == 0:
            return self
        required = [
            self.median_close_price,
            self.sale_to_list_ratio,
            self.sale_to_list_reading,
        ]
        dom_readings = (self.dom_band, self.market_lean)
        if self.median_dom is not None:
            required.extend(dom_readings)
        elif any(r is not None for r in dom_readings):
            raise ValueError("dom_band and market_lean need median_dom")
        if any(r is None for r in required):
            raise ValueError(
                "median_close_price, sale_to_list_*, dom_band, market_lean need a value"
            )
        return self


class CompEvidence(_Frozen):
    """A listing's price check against comparable closed sales (WO-011).

    `level` None: the listing cannot be checked. Figures are set only when
    `sufficient`; `comp_price_estimate` is always None (no valuation). `sentence`
    is the fixed-shape fact, written only by domain/comps.price_check_sentence.
    """

    count: int = Field(ge=0)
    window_months: int = Field(ge=1)
    subtype: str | None = None
    comp_price_estimate: int | None = Field(default=None, ge=0)
    delta_pct: float | None = Field(default=None, allow_inf_nan=False)
    sufficient: bool
    level: Literal["city", "postal_code"] | None = None
    area: str | None = None
    widened_from: str | None = None
    median_price_per_sqft: int | None = Field(default=None, ge=0)
    sentence: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> CompEvidence:
        """Figures only when sufficient; a level names its area; ZIP names its city."""
        if self.comp_price_estimate is not None:
            raise ValueError("comp_price_estimate stays None: no valuation")
        figures = (self.delta_pct, self.median_price_per_sqft)
        if self.sufficient and (self.level is None or None in figures):
            raise ValueError("a sufficient check needs a level, delta, and median")
        if not self.sufficient and figures != (None, None):
            raise ValueError("an insufficient check carries no figures")
        if self.delta_pct is not None and self.delta_pct != int(self.delta_pct):
            raise ValueError("delta_pct is a whole percent")
        if (self.level is None) != (self.area is None):
            raise ValueError("a level and its area come together")
        if (self.level == "postal_code") != (self.widened_from is not None):
            raise ValueError("widened_from is set exactly at the postal_code level")
        return self


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


# Recommendations (WO-011): at most 5; 0 asks for the subject's price check alone.
RECOMMEND_MAX_K = 5
# Fixed questions for the two recommend-only reasons; neither repeats a value.
RECOMMEND_QUESTIONS: dict[str, str] = {
    "missing_listing": (
        "Which listing do you mean? Send its listing number or pick one from a search."
    ),
    "no_session": "I no longer have that result. Which listing do you mean?",
}
# The warning when both a listing key and a position arrive: the key is used.
KEY_WINS_WARNING = (
    "Both a listing number and a position were given; the listing number was used."
)
_RECOMMEND_FIELDS: dict[str, str] = {
    "missing_listing": "listing_key",
    "no_session": "position",
}


class RecommendRequest(_Frozen):
    """What `recommend` is asked for: a subject listing and how many similar ones.

    The subject is `listing_key` (>= 1), else `position` (1-based) into the
    sender's last result, which needs `sender_id`. k is 0-5 (default 5); 0 is
    the price check alone. `from_input` returns a Clarification instead of raising.
    """

    listing_key: int | None = Field(default=None, ge=1)
    k: int = Field(default=5, ge=0, le=RECOMMEND_MAX_K)
    sender_id: str | None = Field(default=None, min_length=1)
    position: int | None = Field(default=None, ge=1)

    @field_validator("listing_key", "k", "position", mode="before")
    @classmethod
    def _not_bool(cls, value: Any) -> Any:
        """Refuse True/False, which pydantic would otherwise read as 1 and 0."""
        if isinstance(value, bool):
            raise PydanticCustomError("invalid_value", "a whole number is needed")
        return value

    @model_validator(mode="after")
    def _has_subject(self) -> RecommendRequest:
        """Require a key, or a position together with a sender id."""
        if self.listing_key is None and self.position is None:
            raise PydanticCustomError("missing_listing", "no listing key or position")
        if self.listing_key is None and self.sender_id is None:
            raise PydanticCustomError("no_session", "a position needs a sender id")
        return self

    @property
    def resolved_by(self) -> Literal["key", "position"]:
        """How the subject is named: "key" whenever a key is given (it wins)."""
        return "key" if self.listing_key is not None else "position"

    def input_warnings(self) -> list[str]:
        """KEY_WINS_WARNING when both a key and a position were given, else []."""
        both = self.listing_key is not None and self.position is not None
        return [KEY_WINS_WARNING] if both else []

    @staticmethod
    def clarification(
        reason: Literal["missing_listing", "no_session"],
    ) -> Clarification:
        """The fixed Clarification for a recommend-only reason (the server uses it)."""
        return Clarification(
            field=_RECOMMEND_FIELDS[reason],
            reason=reason,
            question=RECOMMEND_QUESTIONS[reason],
        )

    @classmethod
    def from_input(cls, raw: Mapping[str, object]) -> RecommendRequest | Clarification:
        """Validate a tool-call mapping; return the request or one Clarification.

        None values count as unset (k falls back to 5). Field errors come first,
        then the subject rule; a non-mapping `raw` raises TypeError.
        """
        if not isinstance(raw, Mapping):
            raise TypeError("from_input expects a mapping of argument names to values")
        given = {key: value for key, value in raw.items() if value is not None}
        try:
            return cls.model_validate(given)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
        kind = str(errors[0].get("type", ""))
        if kind in RECOMMEND_QUESTIONS:
            return cls.clarification(kind)  # type: ignore[arg-type]
        return _clarify(errors[0], sorted(cls.model_fields))


class RecommendationResult(_Frozen):
    """What `recommend` returns in `AgentResult.data` when the subject was found.

    `subject_check` is the subject's own price check; `recommendations` hold at
    most k (so at most 5). No listing carries remarks: they are dropped here.
    `index_as_of` is None when k is 0; `comps_window` is the six-month window.
    """

    subject: Listing
    subject_check: CompEvidence
    recommendations: list[Recommendation] = Field(
        default_factory=list, max_length=RECOMMEND_MAX_K
    )
    k: int = Field(ge=0, le=RECOMMEND_MAX_K)
    index_as_of: date | None = None
    comps_window: StatsWindow

    @field_validator("subject")
    @classmethod
    def _subject_without_remarks(cls, value: Listing) -> Listing:
        """Return the subject with remarks set to None."""
        return (
            value
            if value.remarks is None
            else value.model_copy(update={"remarks": None})
        )

    @field_validator("recommendations")
    @classmethod
    def _listings_without_remarks(
        cls, value: list[Recommendation]
    ) -> list[Recommendation]:
        """Return each recommendation with its listing's remarks set to None."""
        return [
            rec
            if rec.listing.remarks is None
            else rec.model_copy(
                update={"listing": rec.listing.model_copy(update={"remarks": None})}
            )
            for rec in value
        ]

    @model_validator(mode="after")
    def _within_k(self) -> RecommendationResult:
        """At most k recommendations; k 0 has no index date; one window length."""
        if len(self.recommendations) > self.k:
            raise ValueError("more recommendations than k")
        if self.k == 0 and self.index_as_of is not None:
            raise ValueError("index_as_of is None when k is 0")
        checks = [self.subject_check, *(r.comp_evidence for r in self.recommendations)]
        if any(c.window_months != self.comps_window.months for c in checks):
            raise ValueError("every price check uses the comps window")
        return self


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
