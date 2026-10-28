"""WO-017 worker output and trusted figure checks: numbers and fixed codes only.

WorkerOutput is the untrusted shape a future worker may print; it carries no free
text. FigureCheck is produced by host code and never copies a worker value into
`trusted`. Nothing here executes code or registers a tool.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from idx_agent.analysis.fields import Field as AnalysisField

OUTPUT_VERSION = 1
MAX_FIGURES = 12
LABEL_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"

OneVariableKind = Literal["count", "mean", "median", "min", "max", "stdev"]
TwoVariableKind = Literal["pearson", "spearman", "slope", "intercept"]
FigureKind = Literal[
    "count",
    "mean",
    "median",
    "min",
    "max",
    "stdev",
    "pearson",
    "spearman",
    "slope",
    "intercept",
    "other",
]
ONE_VARIABLE_KINDS: frozenset[str] = frozenset(OneVariableKind.__args__)
TWO_VARIABLE_KINDS: frozenset[str] = frozenset(TwoVariableKind.__args__)

_STRICT = ConfigDict(
    strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
)
_Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_Label = Annotated[str, Field(strict=True, pattern=LABEL_PATTERN)]


class Figure(BaseModel):
    """One claimed headline number; x/y name trusted fields, never columns."""

    model_config = _STRICT

    label: _Label
    kind: FigureKind
    x: AnalysisField | None
    y: AnalysisField | None
    value: _Number | None

    @model_validator(mode="after")
    def _variables(self) -> Figure:
        if self.kind in ONE_VARIABLE_KINDS and (self.x is None or self.y is not None):
            raise ValueError("one-variable figure needs x only")
        if self.kind in TWO_VARIABLE_KINDS and (
            self.x is None or self.y is None or self.x == self.y
        ):
            raise ValueError("two-variable figure needs two different fields")
        return self


def _strictly_increasing(bins: tuple[float, ...]) -> tuple[float, ...]:
    if any(low >= high for low, high in zip(bins, bins[1:], strict=False)):
        raise ValueError("bin edges must be strictly increasing")
    return bins


class ScatterChart(BaseModel):
    model_config = _STRICT

    kind: Literal["scatter"]
    x: AnalysisField
    y: AnalysisField

    @model_validator(mode="after")
    def _distinct(self) -> ScatterChart:
        if self.x == self.y:
            raise ValueError("chart axes must differ")
        return self


class BinnedMedianChart(BaseModel):
    model_config = _STRICT

    kind: Literal["binned_median"]
    x: AnalysisField
    y: AnalysisField
    bins: tuple[_Number, ...] = Field(min_length=2, max_length=9)

    _increasing = field_validator("bins")(_strictly_increasing)

    @model_validator(mode="after")
    def _distinct(self) -> BinnedMedianChart:
        if self.x == self.y:
            raise ValueError("chart axes must differ")
        return self


class HistogramChart(BaseModel):
    model_config = _STRICT

    kind: Literal["histogram"]
    x: AnalysisField
    bins: tuple[_Number, ...] = Field(min_length=2, max_length=13)

    _increasing = field_validator("bins")(_strictly_increasing)


ChartRequest = Annotated[
    ScatterChart | BinnedMedianChart | HistogramChart, Field(discriminator="kind")
]


class WorkerOutput(BaseModel):
    """Every key is required; labels are unique so a check maps to one claim."""

    model_config = _STRICT

    version: Annotated[int, Field(strict=True, ge=OUTPUT_VERSION, le=OUTPUT_VERSION)]
    figures: tuple[Figure, ...] = Field(max_length=MAX_FIGURES)
    chart: ChartRequest | None

    @model_validator(mode="after")
    def _unique_labels(self) -> WorkerOutput:
        labels = [figure.label for figure in self.figures]
        if len(set(labels)) != len(labels):
            raise ValueError("figure labels must be unique")
        return self


CheckStatus = Literal["verified", "mismatch", "unavailable", "unverified"]
CheckReason = Literal[
    "value_differs",
    "missing_value",
    "no_values",
    "too_few_values",
    "too_few_pairs",
    "constant_input",
    "unsupported_kind",
]


class FigureCheck(BaseModel):
    """Host recomputation of one figure; `trusted` comes from code, not the worker."""

    model_config = _STRICT

    label: _Label
    kind: FigureKind
    x: AnalysisField | None
    y: AnalysisField | None
    reported: _Number | None
    trusted: _Number | None
    n: Annotated[int, Field(strict=True, ge=0)]
    status: CheckStatus
    reason: CheckReason | None

    @model_validator(mode="after")
    def _consistent(self) -> FigureCheck:
        computed = self.status in ("verified", "mismatch")
        if computed != (self.trusted is not None):
            raise ValueError("trusted value must match the check status")
        if (self.status == "verified") != (self.reason is None):
            raise ValueError("only a verified figure has no reason")
        return self
