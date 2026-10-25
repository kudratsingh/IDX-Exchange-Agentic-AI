"""Mean and change metrics, sample floors and comparable-calendar-month rules."""

import calendar
from datetime import date
from decimal import Decimal

from idx_agent.domain.market import METRIC_MIN_SAMPLE, MIN_SAMPLE, MONTH_MIN, month_keys
from idx_agent.domain.models import MarketAnalytics, MonthAnalytics


def _raw_number(row, field, count, floor):
    value = row.get(field)
    if value is None or int(row.get(count) or 0) < floor:
        return None
    return Decimal(str(value))


def _number(row, field, count, floor):
    number = _raw_number(row, field, count, floor)
    return float(number.quantize(Decimal("0.01"))) if number is not None else None


def _change(current, previous):
    if current is None or previous is None or previous <= 0:
        return None
    return float(
        ((Decimal(str(current)) / Decimal(str(previous)) - 1) * 100).quantize(
            Decimal("0.1")
        )
    )


def build_analytics(totals, rows, active, window, dates):
    by_month = {str(r["ym"]): r for r in rows}
    keys = month_keys(window)
    if len(by_month) != len(rows) or set(by_month) - set(keys):
        raise ValueError("invalid monthly analytics")
    if sum(int(r["n"] or 0) for r in rows) != int(totals["n"]):
        raise ValueError("monthly counts differ from totals")
    months = []
    prices = {}
    ppsfs = {}
    for key in keys:
        row = by_month.get(key, {})
        if int(totals["n"]) < MIN_SAMPLE:
            row = {"n": row.get("n", 0)}
        year, month = map(int, key.split("-"))
        first, last = (
            date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]),
        )
        partial = window.start > first or window.end < last
        price = _number(row, "mean_price", "n", MONTH_MIN)
        ppsf = _number(row, "median_ppsf", "ppsf_n", METRIC_MIN_SAMPLE)
        # MoM/YoY price changes use monthly means, and PPSF changes use medians.
        index = year * 12 + month - 2
        previous = f"{index // 12:04d}-{index % 12 + 1:02d}"
        prior_year = f"{year - 1:04d}-{month:02d}"
        changes = {}
        if not partial:
            changes = {
                "price_mom_pct": _change(
                    _raw_number(row, "mean_price", "n", MONTH_MIN), prices.get(previous)
                ),
                "price_yoy_pct": _change(
                    _raw_number(row, "mean_price", "n", MONTH_MIN),
                    prices.get(prior_year),
                ),
                "ppsf_mom_pct": _change(
                    _raw_number(row, "median_ppsf", "ppsf_n", METRIC_MIN_SAMPLE),
                    ppsfs.get(previous),
                ),
                "ppsf_yoy_pct": _change(
                    _raw_number(row, "median_ppsf", "ppsf_n", METRIC_MIN_SAMPLE),
                    ppsfs.get(prior_year),
                ),
            }
            prices[key] = _raw_number(row, "mean_price", "n", MONTH_MIN)
            ppsfs[key] = _raw_number(row, "median_ppsf", "ppsf_n", METRIC_MIN_SAMPLE)
        months.append(
            MonthAnalytics(
                month=key,
                sample_count=int(row.get("n") or 0),
                partial=partial,
                mean_close_price=price,
                mean_dom=_number(row, "mean_dom", "dom_n", METRIC_MIN_SAMPLE),
                median_price_per_sqft=ppsf,
                **changes,
            )
        )
    notes = [
        "Inventory is the current active snapshot; sales are the selected "
        "historical window.",
        "Monthly price changes use mean sale price; PPSF changes use median sale PPSF. "
        "Only complete calendar months are compared; "
        "changes in the mix of homes sold can affect them.",
    ]
    if not any(m.price_yoy_pct is not None for m in months):
        notes.append(
            "Year-over-year comparison unavailable: no pair of complete months "
            "with sufficient sales one year apart."
        )
    return MarketAnalytics(
        active_count=active,
        active_as_of=dates.active,
        sold_count=int(totals["n"]),
        mean_close_price=_number(totals, "mean_price", "n", MIN_SAMPLE),
        mean_dom=_number(totals, "mean_dom", "dom_n", METRIC_MIN_SAMPLE),
        mean_price_per_sqft=_number(totals, "mean_ppsf", "ppsf_n", METRIC_MIN_SAMPLE),
        months=months,
        notes=notes,
    )


def format_analytics(stats):
    a = stats.analytics
    if a is None:
        return ""

    def value(number, money=False):
        return (
            "unavailable"
            if number is None
            else (f"${number:,.2f}" if money else f"{number:g}")
        )

    lines = [
        "Additional market figures",
        f"Active inventory: {a.active_count} as of {a.active_as_of}; "
        f"{a.sold_count} closed sales in the selected window.",
        f"Mean sale price {value(a.mean_close_price, True)}",
        f"Mean sale price per sqft {value(a.mean_price_per_sqft, True)}",
        f"Mean days on market {value(a.mean_dom)}",
        "Monthly means and median sale price per sqft:",
    ]
    for row in a.months:
        line = f"{row.month}" + (" (partial)" if row.partial else "")
        line += (
            f": {row.sample_count} sales; "
            f"mean price {value(row.mean_close_price, True)}; "
            f"mean DOM {value(row.mean_dom)}; "
            f"median PPSF {value(row.median_price_per_sqft, True)}"
        )
        for field, label in (
            ("price_mom_pct", "mean price MoM"),
            ("price_yoy_pct", "mean price YoY"),
            ("ppsf_mom_pct", "PPSF MoM"),
            ("ppsf_yoy_pct", "PPSF YoY"),
        ):
            number = getattr(row, field)
            if number is not None:
                line += f"; {label} {number:+g}%"
        lines.append(line)
    return "\n".join(lines) + "\n" + "\n".join(a.notes)
