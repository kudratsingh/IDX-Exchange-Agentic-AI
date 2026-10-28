"""WO-017 trusted field values: the eight analysable numbers per sale.

Host code derives these from an AnalysisSample; the worker never supplies them.
A missing input gives None. Units are display labels only.
"""

from __future__ import annotations

from typing import Literal

from idx_agent.domain.analysis import AnalysisRow, AnalysisSample

Field = Literal[
    "close_price",
    "list_price",
    "original_list_price",
    "living_area",
    "days_on_market",
    "price_per_sqft",
    "sale_to_list",
    "list_change_pct",
]

UNITS: dict[str, str] = {
    "close_price": "USD",
    "list_price": "USD",
    "original_list_price": "USD",
    "living_area": "sqft",
    "days_on_market": "days",
    "price_per_sqft": "USD per sqft",
    "sale_to_list": "ratio",
    "list_change_pct": "percent",
}


def _value(row: AnalysisRow, field: str) -> float | None:
    if field == "price_per_sqft":
        return None if row.living_area is None else row.close_price / row.living_area
    if field == "sale_to_list":
        return row.close_price / row.list_price
    if field == "list_change_pct":
        original = row.original_list_price
        if original is None:
            return None
        return (row.list_price - original) / original * 100
    if field not in UNITS:
        raise ValueError("unknown analysis field")
    value = getattr(row, field)
    return None if value is None else float(value)


def field_values(sample: AnalysisSample, field: str) -> list[float | None]:
    """One trusted value per row, in row order; None where an input is missing."""
    return [_value(row, field) for row in sample.rows]
