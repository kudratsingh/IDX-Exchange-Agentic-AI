"""WO-017 trusted chart data from an AnalysisSample: no rendering, no image bytes.

`build_chart` validates primitive arguments itself, reads only trusted field values
and returns ChartData with fixed labels, units, title and caption. Errors are
generic and never echo the arguments.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections.abc import Sequence

from idx_agent.analysis.fields import UNITS, field_values
from idx_agent.domain.analysis import AnalysisSample
from idx_agent.domain.analysis_chart import (
    CHART_MIN_GROUP,
    Bar,
    ChartData,
)
from idx_agent.domain.market import DEFAULT_SUBTYPE

# Edge counts per binned kind: (fewest, most); edges n give n - 1 bars.
BIN_EDGES: dict[str, tuple[int, int]] = {"binned_median": (2, 9), "histogram": (2, 13)}
LABELS: dict[str, str] = {
    "close_price": "Sale price",
    "list_price": "Final list price",
    "original_list_price": "Original list price",
    "living_area": "Living area",
    "days_on_market": "Days on market",
    "price_per_sqft": "Price per sqft",
    "sale_to_list": "Sale-to-list ratio",
    "list_change_pct": "List price change",
}
_KINDS = ("scatter", "binned_median", "histogram")
_SNAPSHOT_FIELDS = ("original_list_price", "list_change_pct")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


class ChartSpecError(ValueError):
    """A chart request outside the supported kinds, fields or bins."""


def _field(value: object) -> str:
    if not isinstance(value, str) or value not in UNITS:
        raise ChartSpecError("unsupported chart field")
    return value


def _edges(kind: str, bins: object) -> tuple[float, ...]:
    fewest, most = BIN_EDGES[kind]
    if not isinstance(bins, tuple | list) or not fewest <= len(bins) <= most:
        raise ChartSpecError("chart bins have the wrong shape")
    edges = []
    for edge in bins:
        if isinstance(edge, bool) or not isinstance(edge, int | float):
            raise ChartSpecError("chart bins must be numbers")
        try:
            number = float(edge)
        except OverflowError:
            raise ChartSpecError("chart bins must be finite") from None
        if not math.isfinite(number):
            raise ChartSpecError("chart bins must be finite")
        edges.append(number)
    if any(left >= right for left, right in zip(edges, edges[1:], strict=False)):
        raise ChartSpecError("chart bins must strictly increase")
    return tuple(edges)


def _bin(value: float, edges: tuple[float, ...]) -> int | None:
    """Index of [lower, upper) holding value; the last bin keeps its upper edge."""
    if value == edges[-1]:
        return len(edges) - 2
    index = bisect_right(edges, value) - 1
    return index if 0 <= index < len(edges) - 1 else None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _lower_first(label: str) -> str:
    return label[0].lower() + label[1:]


def _caption(
    sample: AnalysisSample,
    kind: str,
    fields: tuple[str, ...],
    counts: tuple[int, int, int],
    suppressed: bool,
) -> tuple[str, ...]:
    used, missing, outside = counts
    first = f"{used} of {len(sample.rows)} sales used; {missing} missing a value"
    first += "." if kind == "scatter" else f"; {outside} outside the bins."
    scope = sample.scope
    place = scope.city if scope.city is not None else f"ZIP {scope.postal_code}"
    subtype = _CAMEL.sub(" ", scope.property_subtype or DEFAULT_SUBTYPE)
    lines = [
        first,
        f"Place: {place}; type: {subtype}.",
        f"Closed {sample.window.start.isoformat()} to "
        f"{sample.window.end.isoformat()}; sold data as of "
        f"{sample.as_of.sold.isoformat()}.",
        "Bounded sample; not representative of the area.",
    ]
    if kind == "scatter":
        lines.append("Each point is one sale; association is not causation.")
    if suppressed:
        lines.append(f"Bins with fewer than {CHART_MIN_GROUP} sales show no median.")
    if any(name in _SNAPSHOT_FIELDS for name in fields):
        lines.append("Original list price is a snapshot, not a history of cuts.")
    return tuple(lines)


def _title(kind: str, x: str, y: str | None) -> str:
    if kind == "histogram":
        return f"Distribution of {_lower_first(LABELS[x])}"
    if kind == "binned_median":
        return f"Median {_lower_first(LABELS[y])} by {_lower_first(LABELS[x])}"
    return f"{LABELS[y]} vs. {LABELS[x]}"


def build_chart(
    sample: AnalysisSample,
    kind: str,
    x: str,
    y: str | None = None,
    bins: Sequence[float] | None = None,
) -> ChartData:
    """Trusted points or bars for one supported chart; refuse anything else.

    Rows missing a needed value are dropped and counted; binned values outside the
    edges are counted, never plotted. Medians over fewer than three are suppressed.
    """
    if not isinstance(sample, AnalysisSample):
        raise ChartSpecError("chart needs an analysis sample")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ChartSpecError("unsupported chart kind")
    x = _field(x)
    if kind == "histogram":
        if y is not None:
            raise ChartSpecError("a histogram takes one field")
    else:
        y = _field(y)
        if x == y:
            raise ChartSpecError("chart fields must differ")
    if kind == "scatter":
        if bins is not None:
            raise ChartSpecError("a scatter chart takes no bins")
        edges: tuple[float, ...] = ()
    else:
        edges = _edges(kind, bins)

    xs = field_values(sample, x)
    ys = field_values(sample, y) if y is not None else [0.0] * len(xs)
    pairs = [
        (a, b) for a, b in zip(xs, ys, strict=True) if a is not None and b is not None
    ]
    missing = len(xs) - len(pairs)
    points: tuple[tuple[float, float], ...] = ()
    bars: list[Bar] = []
    outside = 0
    if kind == "scatter":
        points = tuple(pairs)
    else:
        groups: list[list[float]] = [[] for _ in edges[1:]]
        for a, b in pairs:
            index = _bin(a, edges)
            if index is None:
                outside += 1
            else:
                groups[index].append(b)
        for index, group in enumerate(groups):
            n = len(group)
            hidden = kind == "binned_median" and n < CHART_MIN_GROUP
            if kind == "histogram":
                value: float | None = float(n)
            else:
                value = None if hidden else _median(group)
            bars.append(
                Bar(
                    lower=edges[index],
                    upper=edges[index + 1],
                    n=n,
                    value=value,
                    suppressed=hidden,
                )
            )
    used = len(pairs) - outside
    fields = (x,) if y is None else (x, y)
    return ChartData(
        kind=kind,
        title=_title(kind, x, y),
        x_field=x,
        x_label=LABELS[x],
        x_unit=UNITS[x],
        y_field=y,
        y_label=None if y is None else LABELS[y],
        y_unit=None if y is None else UNITS[y],
        points=points,
        bars=tuple(bars),
        n_rows=len(xs),
        n_used=used,
        n_missing=missing,
        outside=outside,
        caption=_caption(
            sample,
            kind,
            fields,
            (used, missing, outside),
            any(bar.suppressed for bar in bars),
        ),
    )
