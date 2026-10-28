"""WO-017 step 6 outcome (host-side: checks with worker numbers, checked PNG bytes).

`view()` is all the model sees: codes, scope, counts, caveats and trusted values.
No worker number, label, code or row value is in it; the PNG is never dumped.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from idx_agent.analysis.fields import Field as AnalysisField
from idx_agent.analysis.png import check_png
from idx_agent.domain.analysis_chart import CHART_MIN_GROUP, ChartData, ChartKind
from idx_agent.domain.analysis_output import (
    CheckReason,
    CheckStatus,
    FigureCheck,
    FigureKind,
)
from idx_agent.domain.analysis_worker import AnalysisReason
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, StatsWindow

OutcomeStatus = Literal[
    "ok",
    "no_sales",
    "unavailable",
    "busy",
    "timeout",
    "output_too_large",
    "failed",
    "invalid_code",
    "invalid_output",
    "db_error",
    "db_timeout",
]
ChartStatus = Literal[
    "not_requested",
    "rendered",
    "refused",
    "invalid_png",
    "timeout",
    "output_too_large",
    "failed",
    "unavailable",
    "busy",
]
# Said whenever no sample was read, so the bounded-sample limit is never left out.
DEFAULT_CAVEATS: tuple[str, ...] = (
    "Bounded input of at most 50 sales; not a representative area sample.",
)

# A min or max is always one sale's value, and a mean, median or stdev over fewer
# than CHART_MIN_GROUP values is (nearly) one sale's value; the model sees the
# check status but not the number, the same rule as a suppressed bin median.
SINGLE_SALE_KINDS = frozenset({"min", "max"})
FIGURE_MIN_GROUP = CHART_MIN_GROUP


def withholds_value(kind: str, n: int) -> bool:
    """True when the trusted value could be one sale's own value."""
    if kind in SINGLE_SALE_KINDS:
        return True
    return kind not in ("count", "other") and n < FIGURE_MIN_GROUP


_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
_Count = Annotated[int, Field(strict=True, ge=0)]
_Finite = Annotated[float, Field(allow_inf_nan=False)]


class FigureView(BaseModel):
    """One checked figure by position; `trusted` is the host's number or None.

    `withheld` marks a computed value kept from the model (see `withholds_value`).
    """

    model_config = _FROZEN

    index: Annotated[int, Field(ge=1)]
    kind: FigureKind
    x: AnalysisField | None
    y: AnalysisField | None
    status: CheckStatus
    reason: CheckReason | None
    trusted: _Finite | None
    n: _Count
    withheld: bool = False

    @model_validator(mode="after")
    def _no_withheld_value(self) -> FigureView:
        if self.withheld and self.trusted is not None:
            raise ValueError("a withheld figure carries no value")
        return self


def _figure_view(index: int, check: FigureCheck) -> FigureView:
    hide = check.trusted is not None and withholds_value(check.kind, check.n)
    return FigureView(
        index=index,
        kind=check.kind,
        x=check.x,
        y=check.y,
        status=check.status,
        reason=check.reason,
        trusted=None if hide else check.trusted,
        n=check.n,
        withheld=hide,
    )


class ChartView(BaseModel):
    """Chart status and the trusted chart's fixed wording and counts; no points."""

    model_config = _FROZEN

    status: ChartStatus
    image_attached: bool = False
    kind: ChartKind | None = None
    title: str | None = None
    x_label: str | None = None
    x_unit: str | None = None
    y_label: str | None = None
    y_unit: str | None = None
    n_rows: _Count | None = None
    n_used: _Count | None = None
    n_missing: _Count | None = None
    outside: _Count | None = None
    caption: tuple[str, ...] = ()


class AnalysisView(BaseModel):
    """What the model sees in `AgentResult.data`."""

    model_config = _FROZEN

    status: OutcomeStatus
    reason: AnalysisReason | None = None
    city: str | None = None
    postal_code: str | None = None
    property_subtype: str | None = None
    months: int | None = None
    window_start: date | None = None
    window_end: date | None = None
    sold_as_of: date | None = None
    active_as_of: date | None = None
    n: _Count = 0
    eligible: _Count | None = None
    caveats: tuple[str, ...]
    figures: tuple[FigureView, ...] = ()
    chart: ChartView


class AnalysisOutcome(BaseModel):
    """Host-side result of one bounded analysis; see `view()` for the public part."""

    model_config = _FROZEN

    trace_id: str
    status: OutcomeStatus
    reason: AnalysisReason | None = None
    scope: MarketStatsRequest | None = None
    window: StatsWindow | None = None
    as_of: AsOfDates | None = None
    n: _Count = 0
    eligible: _Count | None = None
    caveats: tuple[str, ...] = Field(min_length=1)
    checks: tuple[FigureCheck, ...] = ()
    chart_status: ChartStatus = "not_requested"
    chart: ChartData | None = None
    png: bytes | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def _consistent(self) -> AnalysisOutcome:
        if self.status != "ok" and (self.checks or self.chart is not None):
            raise ValueError("only an ok outcome carries figures or a chart")
        if self.status != "ok" and self.chart_status != "not_requested":
            raise ValueError("only an ok outcome has a chart status")
        if (self.png is not None) != (self.chart_status == "rendered"):
            raise ValueError("an image is present exactly when the chart rendered")
        if self.png is not None and not check_png(self.png):
            raise ValueError("the image did not pass the PNG check")
        if self.chart_status in ("not_requested", "refused") and self.chart:
            raise ValueError("no chart data without a chart to draw")
        if self.chart_status == "rendered" and self.chart is None:
            raise ValueError("a rendered chart needs its chart data")
        return self

    def view(self) -> AnalysisView:
        """Codes, scope, counts, caveats and trusted values; nothing from the worker."""
        scope = self.scope
        chart = ChartView(status=self.chart_status, image_attached=self.png is not None)
        if self.chart is not None:
            data = self.chart
            chart = chart.model_copy(
                update=dict(
                    kind=data.kind,
                    title=data.title,
                    x_label=data.x_label,
                    x_unit=data.x_unit,
                    y_label=data.y_label,
                    y_unit=data.y_unit,
                    n_rows=data.n_rows,
                    n_used=data.n_used,
                    n_missing=data.n_missing,
                    outside=data.outside,
                    caption=data.caption,
                )
            )
        return AnalysisView(
            status=self.status,
            reason=self.reason,
            city=None if scope is None else scope.city,
            postal_code=None if scope is None else scope.postal_code,
            property_subtype=None if scope is None else scope.property_subtype,
            months=None if scope is None else scope.months,
            window_start=None if self.window is None else self.window.start,
            window_end=None if self.window is None else self.window.end,
            sold_as_of=None if self.as_of is None else self.as_of.sold,
            active_as_of=None if self.as_of is None else self.as_of.active,
            n=self.n,
            eligible=self.eligible,
            caveats=self.caveats,
            figures=tuple(
                _figure_view(index, check)
                for index, check in enumerate(self.checks, start=1)
            ),
            chart=chart,
        )
