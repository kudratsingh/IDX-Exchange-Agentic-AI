"""WO-017 numeric handoff only: no execution, SQL, filesystem or provider access.

The sample stays in trusted host code. Only worker_rows() is intended for the
future isolated worker. Nothing registers a tool or runs model-generated Python.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.market import AREA_FLOOR, DEFAULT_SUBTYPE, PRICE_FLOOR
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow

ANALYSIS_MAX_ROWS = 50
ANALYSIS_MIN_ROWS = 10
_PositivePrice = Annotated[int, Field(strict=True, ge=PRICE_FLOOR)]
_Area = Annotated[int, Field(strict=True, ge=AREA_FLOOR)]
_Dom = Annotated[int, Field(strict=True, ge=0)]


class AnalysisRow(BaseModel):
    """Fixed numeric projection; extra fields (including identifiers) fail closed."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    close_price: _PositivePrice
    list_price: _PositivePrice
    original_list_price: _PositivePrice | None = None
    living_area: _Area | None = None
    days_on_market: _Dom | None = None


class AnalysisSample(BaseModel):
    """Host-side provenance and immutable rows, never a city population estimate."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    dataset: Literal["sold_price_dom_v1"] = "sold_price_dom_v1"
    scope: MarketStatsRequest
    window: StatsWindow
    as_of: AsOfDates
    rows: tuple[AnalysisRow, ...] = Field(max_length=ANALYSIS_MAX_ROWS)
    sampling: Literal["bounded_input_not_representative"] = (
        "bounded_input_not_representative"
    )
    # Kept sales before the 50-row cap, when the reader counted them (WO-017 step 1).
    eligible: int | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode="after")
    def _provenance(self) -> AnalysisSample:
        expected = self.as_of.window(self.scope.months)
        if (
            (self.window.start, self.window.end) != expected
            or self.window.months != self.scope.months
            or self.as_of.sold > self.as_of.active
        ):
            raise ValueError("analysis window does not match the requested snapshot")
        if self.eligible is not None and self.eligible < len(self.rows):
            raise ValueError("eligible count is below the number of rows")
        return self

    def worker_rows(self) -> list[dict[str, int | None]]:
        """Fresh numeric dictionaries only; no keys, addresses, scope or text."""
        return [row.model_dump() for row in self.rows]

    def caveats(self) -> tuple[str, ...]:
        notes = [
            "Bounded input of at most 50 sales; not a representative area sample.",
            "Original and final list prices do not give the timing or number of cuts.",
            "A relationship in this sample does not establish causation.",
            "Missing values remain unavailable; stored days on market are used.",
        ]
        if len(self.rows) < ANALYSIS_MIN_ROWS:
            notes.append("Fewer than 10 sales: relationship estimates are unavailable.")
        if self.eligible is not None and self.eligible > len(self.rows):
            notes.append(
                f"Uses the {len(self.rows)} most recent of {self.eligible} eligible "
                "sales; older eligible sales are left out."
            )
        return tuple(notes)


def make_analysis_sample(
    rows: Sequence[SoldComp],
    scope: MarketStatsRequest,
    window: StatsWindow,
    as_of: AsOfDates,
    *,
    eligible: int | None = None,
) -> AnalysisSample:
    """Validate a bounded, cleaned batch and project numeric fields only.

    Refuse duplicates, scope mismatches and oversize input; never fetch or truncate.
    Errors omit values; unknown original price/area/DOM is None; `eligible` is kept.
    """
    if len(rows) > ANALYSIS_MAX_ROWS:
        raise ValueError("analysis source exceeds the 50-row ceiling")
    subtype = scope.property_subtype or DEFAULT_SUBTYPE
    seen = set()
    projected = []
    for row in rows:
        if row.listing_key in seen:
            raise ValueError("analysis source contains duplicate sale keys")
        seen.add(row.listing_key)
        if (
            (scope.city is not None and row.city != scope.city)
            or (scope.postal_code is not None and row.postal_code != scope.postal_code)
            or row.property_subtype != subtype
        ):
            raise ValueError("analysis source does not match the requested scope")
        if (
            not window.start
            <= row.close_date
            <= min(window.end, as_of.sold, as_of.active)
        ):
            raise ValueError("analysis source is outside the snapshot window")
        if (
            row.close_price < PRICE_FLOOR
            or row.list_price is None
            or row.list_price < PRICE_FLOOR
        ):
            raise ValueError("analysis source has an unusable sale or list price")
        projected.append(
            AnalysisRow(
                close_price=row.close_price,
                list_price=row.list_price,
                original_list_price=(
                    row.original_list_price
                    if row.original_list_price is not None
                    and row.original_list_price >= PRICE_FLOOR
                    else None
                ),
                living_area=(
                    row.living_area
                    if row.living_area is not None and row.living_area >= AREA_FLOOR
                    else None
                ),
                days_on_market=row.days_on_market,
            )
        )
    return AnalysisSample(
        scope=scope,
        window=window,
        as_of=as_of,
        rows=tuple(projected),
        eligible=eligible,
    )
