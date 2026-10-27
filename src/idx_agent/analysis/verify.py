"""WO-017 trusted figure checks: recompute each claim from the sample's rows.

The worker's number is only compared, never adopted. Values come from
field_values with missing entries dropped (pairwise for two-variable kinds).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from idx_agent.analysis import stats
from idx_agent.analysis.fields import field_values
from idx_agent.domain.analysis import ANALYSIS_MIN_ROWS, AnalysisSample
from idx_agent.domain.analysis_output import (
    TWO_VARIABLE_KINDS,
    Figure,
    FigureCheck,
    WorkerOutput,
)

RELATIVE_TOLERANCE = 1e-6

_ONE: dict[str, Callable[[Sequence[float]], float]] = {
    "count": lambda values: float(len(values)),
    "mean": stats.mean,
    "median": stats.median,
    "min": stats.minimum,
    "max": stats.maximum,
    "stdev": stats.stdev,
}
_TWO: dict[str, Callable[[Sequence[float], Sequence[float]], float]] = {
    "pearson": stats.pearson,
    "spearman": stats.spearman,
    "slope": stats.slope,
    "intercept": stats.intercept,
}


def matches(kind: str, reported: float, trusted: float) -> bool:
    """Counts match exactly; other kinds within 1e-6 relative (absolute below 1)."""
    if kind == "count":
        return reported == trusted
    return abs(reported - trusted) <= RELATIVE_TOLERANCE * max(1.0, abs(trusted))


class _Unavailable(Exception):
    def __init__(self, n: int, reason: str) -> None:
        super().__init__(reason)
        self.n = n
        self.reason = reason


def _check(figure: Figure, **fields) -> FigureCheck:
    return FigureCheck(
        label=figure.label,
        kind=figure.kind,
        x=figure.x,
        y=figure.y,
        reported=figure.value,
        **fields,
    )


def _trusted(sample: AnalysisSample, figure: Figure) -> tuple[int, float]:
    xs = field_values(sample, figure.x)
    if figure.kind not in TWO_VARIABLE_KINDS:
        values = [v for v in xs if v is not None]
        if not values:
            raise _Unavailable(0, "no_values")
        try:
            return len(values), _ONE[figure.kind](values)
        except stats.StatUnavailable as caught:
            raise _Unavailable(len(values), caught.reason) from None
    pairs = [
        (x, y)
        for x, y in zip(xs, field_values(sample, figure.y), strict=True)
        if x is not None and y is not None
    ]
    if len(pairs) < ANALYSIS_MIN_ROWS:
        raise _Unavailable(len(pairs), "too_few_pairs")
    try:
        value = _TWO[figure.kind]([p[0] for p in pairs], [p[1] for p in pairs])
    except stats.StatUnavailable as caught:
        raise _Unavailable(len(pairs), caught.reason) from None
    return len(pairs), value


def verify_figure(sample: AnalysisSample, figure: Figure) -> FigureCheck:
    if figure.kind == "other":
        return _check(
            figure, trusted=None, n=0, status="unverified", reason="unsupported_kind"
        )
    try:
        n, trusted = _trusted(sample, figure)
    except _Unavailable as caught:
        return _check(
            figure, trusted=None, n=caught.n, status="unavailable", reason=caught.reason
        )
    if figure.value is None:
        return _check(
            figure, trusted=trusted, n=n, status="mismatch", reason="missing_value"
        )
    if matches(figure.kind, figure.value, trusted):
        return _check(figure, trusted=trusted, n=n, status="verified", reason=None)
    return _check(
        figure, trusted=trusted, n=n, status="mismatch", reason="value_differs"
    )


def verify_figures(
    sample: AnalysisSample, output: WorkerOutput
) -> tuple[FigureCheck, ...]:
    """One check per claimed figure, in the worker's order."""
    return tuple(verify_figure(sample, figure) for figure in output.figures)
