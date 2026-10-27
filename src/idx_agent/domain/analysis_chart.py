"""WO-017 trusted chart data: numbers and fixed wording only, never an image.

Host code builds ChartData from an AnalysisSample (analysis/chart.py). Labels, units,
title and caption come from fixed mappings; no worker or user text reaches them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from idx_agent.analysis.fields import Field as AnalysisField
from idx_agent.domain.analysis import ANALYSIS_MAX_ROWS

CHART_MAX_BARS = 12
CHART_MIN_GROUP = 3  # binned medians over fewer sales than this are suppressed
CHART_MAX_CAPTION = 8

ChartKind = Literal["scatter", "binned_median", "histogram"]
_Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_Count = Annotated[int, Field(strict=True, ge=0, le=ANALYSIS_MAX_ROWS)]
_Text = Annotated[str, Field(min_length=1, max_length=120)]
_Point = tuple[_Finite, _Finite]


class _Frozen(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, hide_input_in_errors=True
    )


class Bar(_Frozen):
    """One bin [lower, upper); value is a median or a count, None when suppressed."""

    lower: _Finite
    upper: _Finite
    n: _Count
    value: _Finite | None
    suppressed: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Bar:
        if not self.lower < self.upper:
            raise ValueError("bar edges are not increasing")
        if self.suppressed and self.value is not None:
            raise ValueError("a suppressed bar carries no value")
        return self


class ChartData(_Frozen):
    """Typed chart content: bounded points or bars, counts, labels and caption.

    Invariant: n_used + n_missing + outside == n_rows. Scatter has points only;
    the binned kinds have bars only; a histogram has no y axis.
    """

    kind: ChartKind
    title: _Text
    x_field: AnalysisField
    x_label: _Text
    x_unit: _Text
    y_field: AnalysisField | None = None
    y_label: _Text | None = None
    y_unit: _Text | None = None
    points: tuple[_Point, ...] = Field(default=(), max_length=ANALYSIS_MAX_ROWS)
    bars: tuple[Bar, ...] = Field(default=(), max_length=CHART_MAX_BARS)
    n_rows: _Count
    n_used: _Count
    n_missing: _Count
    outside: _Count = 0
    caption: tuple[_Text, ...] = Field(min_length=1, max_length=CHART_MAX_CAPTION)

    @model_validator(mode="after")
    def _consistent(self) -> ChartData:
        y_parts = (self.y_field, self.y_label, self.y_unit)
        if self.kind == "histogram":
            if any(part is not None for part in y_parts):
                raise ValueError("a histogram has no y axis")
        elif any(part is None for part in y_parts) or self.y_field == self.x_field:
            raise ValueError("chart needs two different fields")
        if self.n_used + self.n_missing + self.outside != self.n_rows:
            raise ValueError("chart counts do not add up")
        if self.kind == "scatter":
            if self.bars or self.outside or len(self.points) != self.n_used:
                raise ValueError("scatter data is inconsistent")
        else:
            if self.points or not self.bars:
                raise ValueError("binned chart data is inconsistent")
            if sum(bar.n for bar in self.bars) != self.n_used:
                raise ValueError("bar counts do not add up")
            if any(
                left.upper != right.lower
                for left, right in zip(self.bars, self.bars[1:], strict=False)
            ):
                raise ValueError("bars are not contiguous")
        return self
