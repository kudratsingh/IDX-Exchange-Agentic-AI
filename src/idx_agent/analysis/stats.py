"""WO-017 trusted statistics on plain finite floats; pure, no I/O.

Each function raises StatUnavailable with a stable reason code instead of
guessing when its input cannot support the statistic.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


class StatUnavailable(ValueError):
    """The input cannot support the statistic; `reason` is a stable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _need(values: Sequence[float], minimum: int) -> None:
    if len(values) == 0:
        raise StatUnavailable("no_values")
    if len(values) < minimum:
        raise StatUnavailable("too_few_values")


def _paired(xs: Sequence[float], ys: Sequence[float]) -> None:
    if len(xs) != len(ys):
        raise ValueError("paired inputs differ in length")
    if len(xs) < 2:
        raise StatUnavailable("too_few_values")
    if min(xs) == max(xs) or min(ys) == max(ys):
        raise StatUnavailable("constant_input")


def mean(values: Sequence[float]) -> float:
    _need(values, 1)
    return math.fsum(values) / len(values)


def median(values: Sequence[float]) -> float:
    """Middle value; the mean of the two middle values for an even count."""
    _need(values, 1)
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def minimum(values: Sequence[float]) -> float:
    _need(values, 1)
    return float(min(values))


def maximum(values: Sequence[float]) -> float:
    _need(values, 1)
    return float(max(values))


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (divides by n - 1); needs two values."""
    _need(values, 2)
    centre = mean(values)
    return math.sqrt(math.fsum((v - centre) ** 2 for v in values) / (len(values) - 1))


def _moments(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float]:
    mx, my = mean(xs), mean(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    syy = math.fsum((y - my) ** 2 for y in ys)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxx, syy, sxy


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    _paired(xs, ys)
    sxx, syy, sxy = _moments(xs, ys)
    return sxy / (math.sqrt(sxx) * math.sqrt(syy))


def ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks in input order; tied values share their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            result[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return result


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    _paired(xs, ys)
    return pearson(ranks(xs), ranks(ys))


def slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Ordinary least-squares slope of y on x."""
    _paired(xs, ys)
    sxx, _, sxy = _moments(xs, ys)
    return sxy / sxx


def intercept(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Ordinary least-squares intercept of y on x."""
    return mean(ys) - slope(xs, ys) * mean(xs)
