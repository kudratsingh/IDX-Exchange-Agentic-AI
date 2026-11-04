"""Answer facts for measurement cases, from hand-written SQL (WO-020 requirement 2;
extended for set version 2 by WO-028: card readings, the monthly trend, opt-in
extended figures, and the comparable-sales price check).

Written from the documented definitions (CONTRACTS.md search filters, MarketStats and
CompEvidence, DECISIONS.md time windows and exclusions, WO-008's duplicate rule and
labels, ADDITIONAL_CAPABILITIES.md extended figures), never by calling or copying
`idx_agent.db`. The only `idx_agent` import is the column allowlist. Every value
is bound; statements return counts, per-month aggregates or median middle rows only
(at most 50 rows), and the SQL runs unchanged on MySQL 8 and on SQLite (window
functions, `%s` or `?` marks), so goldens can be recomputed from the committed fixture
without a server.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from idx_agent.safety.columns import check_column

__all__ = [
    "ANALYTICS_KINDS",
    "CARD_KINDS",
    "COMP_KINDS",
    "FACT_KINDS",
    "STOPPED_KINDS",
    "Truth",
    "dom_band",
    "market_lean",
    "month_keys",
    "months_back",
    "sale_to_list_reading",
]

ACTIVE = "rets_property"
SOLD = "california_sold"
DEFAULT_SUBTYPE = "SingleFamilyResidence"
PRICE_FLOOR = 25_000  # DECISIONS.md: close or list price under 25,000 is excluded
AREA_FLOOR = 200  # price per sqft counts only living areas of 200 sqft or more
MIN_SAMPLE = 5  # below this, no figure is given
METRIC_MIN = 10  # median DOM and price per sqft each need 10 usable values
MONTH_MIN = 3  # a month's median or mean price needs 3 sales
COMP_MIN = 5  # a price check is sufficient from 5 comparable sales
COMP_WINDOW = 6  # comparable sales come from the six-month window
FACT_KINDS = frozenset(
    {
        "total_matches",
        "sample_count",
        "median_close_price",
        "median_dom",
        "sale_to_list_ratio",
        "median_price_per_sqft",
    }
)
# Set version 2 (WO-028). Card readings and the monthly trend (WO-008 labels).
CARD_KINDS = frozenset({"dom_band", "market_lean", "sale_to_list_reading", "trend"})
# Opt-in extended figures (`include_extended`, ADDITIONAL_CAPABILITIES.md).
ANALYTICS_KINDS = frozenset(
    {
        "analytics_active_count",
        "analytics_sold_count",
        "analytics_mean_close_price",
        "analytics_mean_dom",
        "analytics_months",
    }
)
# The comparable-sales price check (`recommend`, CONTRACTS.md CompEvidence).
COMP_KINDS = frozenset(
    {
        "comp_verdict",
        "comp_level",
        "comp_count",
        "comp_median_ppsf",
        "comp_range_low_ppsf",
        "comp_range_high_ppsf",
        "comp_delta_pct",
    }
)
# Figures with no truth: the documents leave them ambiguous or disagree with the
# tool, so WO-028 stopped and recorded why instead of choosing a side.
STOPPED_KINDS = {
    "analytics_mean_price_per_sqft": "mean of per-sale ratios or total price over "
    "total area is not documented",
    "analytics_month_median_price_per_sqft": "CONTRACTS.md rounds price-per-sqft "
    "medians to whole dollars; the extended monthly rows carry two decimals",
    "exclusions_applied": "the rule a sale failing several exclusions is counted "
    "under is not documented",
    "subtype_mix": "the other subtypes' counts are only in the card text, not a "
    "structured field",
}


def _a(name: str) -> str:
    return check_column(ACTIVE, name)


def _s(name: str) -> str:
    return check_column(SOLD, name)


def months_back(day: date, months: int) -> date:
    """The same day `months` calendar months earlier, clamped to the month's end."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _half_even(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_EVEN)


class Truth:
    """Facts over one SELECT-only connection (pymysql dict rows or sqlite3 rows)."""

    def __init__(self, conn: Any, mark: str = "%s") -> None:
        self.conn = conn
        self.mark = mark

    def _rows(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        sql = sql.replace("%s", self.mark)
        if hasattr(self.conn, "cursor") and self.mark == "%s":
            with self.conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        else:
            cursor = self.conn.execute(sql, tuple(params))
            names = [d[0] for d in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        if len(rows) > 50:
            raise ValueError("a truth statement returned more than 50 rows")
        return [dict(row) for row in rows]

    # --- as-of dates (DECISIONS.md "Time windows"), recomputed here ---

    def as_of(self) -> tuple[date, date]:
        """(active, sold): the latest active modification date, and the latest close
        date not after it (which drops typo years)."""
        modified = _a("ModificationTimestamp")
        (row,) = self._rows(
            f"SELECT CAST(MAX({modified}) AS CHAR) AS m FROM {ACTIVE}", ()
        )
        active = date.fromisoformat(str(row["m"])[:10])
        (row,) = self._rows(
            f"SELECT CAST(MAX({_s('close_date_d')}) AS CHAR) AS m FROM {SOLD} "
            f"WHERE {_s('close_date_d')} <= %s",
            (active.isoformat(),),
        )
        return active, date.fromisoformat(str(row["m"])[:10])

    def window(self, months: int) -> tuple[date, date]:
        """Inclusive window of `months` months ending at the sold as-of date."""
        _, sold = self.as_of()
        return months_back(sold, months) + timedelta(days=1), sold

    # --- search counts (CONTRACTS.md PropertySearchFilters) ---

    def total_matches(self, filters: Mapping[str, Any]) -> int:
        """Active rows matching the filters: the search's total_matches."""
        where = [f"{_a('StandardStatus')} = %s"]
        params: list[Any] = ["Active"]
        simple = {
            "city": ("L_City", "="),
            "min_price": ("L_SystemPrice", ">="),
            "max_price": ("L_SystemPrice", "<="),
            "min_beds": ("L_Keyword2", ">="),
            "min_baths": ("LM_Dec_3", ">="),
            "min_sqft": ("LM_Int2_3", ">="),
            "property_subtype": ("L_Type_", "="),
        }
        for name, value in filters.items():
            if name in simple:
                column, op = simple[name]
                where.append(f"{_a(column)} {op} %s")
                params.append(value)
            elif name == "postal_code":
                where.append(f"{_a('L_Zip')} LIKE %s")
                params.append(f"{value}%")
            elif name in ("pool", "view"):
                column = _a("PoolPrivateYN" if name == "pool" else "ViewYN")
                if value:
                    where.append(f"{column} = %s")
                else:
                    where.append(f"COALESCE({column}, '') <> %s")
                params.append("1")
            else:
                raise ValueError(f"no truth definition for search filter {name!r}")
        sql = f"SELECT COUNT(*) AS n FROM {ACTIVE} WHERE " + " AND ".join(where)
        return int(self._rows(sql, params)[0]["n"])

    # --- market figures (CONTRACTS.md MarketStats, WO-008 exclusions) ---

    def _sample(self, place: Mapping[str, str], subtype: str | None, months: int):
        """The FROM-clause CTE text and params for the cleaned, collapsed sample."""
        start, end = self.window(months)
        active, _ = self.as_of()
        close, contract = _s("close_date_d"), _s("purchase_contract_date_d")
        if "city" in place:
            place_sql, place_value = f"{_s('City')} = %s", place["city"]
        else:
            place_sql, place_value = (
                f"{_s('PostalCode')} LIKE %s",
                f"{place['postal_code']}%",
            )
        cte = (
            "WITH base AS (SELECT "
            f"{_s('ClosePrice')} AS close_price, {_s('ListPrice')} AS list_price, "
            f"{_s('LivingArea')} AS area, {_s('DaysOnMarket')} AS dom, "
            f"{_s('BedroomsTotal')} AS beds, "
            f"SUBSTR(CAST({close} AS CHAR), 1, 7) AS ym, "
            f"ROW_NUMBER() OVER (PARTITION BY {_s('ListingKey')} "
            f"ORDER BY {close} DESC, "
            f"{_s('ClosePrice')} DESC, {_s('ListPrice')} DESC) AS copy "
            f"FROM {SOLD} WHERE {place_sql} AND {_s('PropertySubType')} = %s "
            f"AND {close} IS NOT NULL AND {close} >= %s AND {close} <= %s "
            f"AND {close} <= %s AND ({contract} IS NULL OR {close} >= {contract}) "
            f"AND {_s('ClosePrice')} >= %s AND {_s('ListPrice')} >= %s), "
            "kept AS (SELECT close_price, list_price, area, dom, beds, ym FROM base "
            "WHERE copy = 1)"
        )
        params = [
            place_value,
            subtype or DEFAULT_SUBTYPE,
            start.isoformat(),
            end.isoformat(),
            active.isoformat(),
            PRICE_FLOOR,
            PRICE_FLOOR,
        ]
        return cte, params

    def _middles(
        self,
        cte: str,
        params: list[Any],
        value: str,
        columns: str,
        where: str,
        extra: Sequence[Any] = (),
    ) -> tuple[int, list[dict[str, Any]]]:
        """(usable count, the one or two middle rows ordered by `value`)."""
        sql = (
            f"{cte}, ranked AS (SELECT {columns}, ROW_NUMBER() OVER (ORDER BY {value}) "
            f"AS rn, COUNT(*) OVER () AS n FROM kept WHERE {where}) "
            f"SELECT {columns}, rn, n FROM ranked "
            "WHERE rn * 2 >= n AND rn * 2 <= n + 2 ORDER BY rn"
        )
        rows = self._rows(sql, [*params, *extra])
        return (int(rows[0]["n"]) if rows else 0), rows

    def market(
        self, place: Mapping[str, str], subtype: str | None = None, months: int = 6
    ) -> dict[str, Any]:
        """The five card facts; None where the sample or usable values are too few."""
        cte, params = self._sample(place, subtype, months)
        (row,) = self._rows(f"{cte} SELECT COUNT(*) AS n FROM kept", params)
        count = int(row["n"])
        facts: dict[str, Any] = {
            "sample_count": count,
            "median_close_price": None,
            "median_dom": None,
            "sale_to_list_ratio": None,
            "median_price_per_sqft": None,
        }
        if count < MIN_SAMPLE:
            return facts
        _, mids = self._middles(cte, params, "close_price", "close_price", "1 = 1")
        price = sum(Decimal(str(r["close_price"])) for r in mids) / len(mids)
        facts["median_close_price"] = int(_half_even(price, "1"))
        _, mids = self._middles(
            cte,
            params,
            "close_price * 1.0 / list_price",
            "close_price, list_price",
            "list_price > 0",
        )
        ratios = [
            Decimal(str(r["close_price"])) / Decimal(str(r["list_price"])) for r in mids
        ]
        facts["sale_to_list_ratio"] = float(
            _half_even(sum(ratios) / len(ratios), "0.001")
        )
        usable, mids = self._middles(
            cte, params, "dom", "dom", "dom IS NOT NULL AND dom >= 0"
        )
        if usable >= METRIC_MIN:
            facts["median_dom"] = float(
                sum(Decimal(str(r["dom"])) for r in mids) / len(mids)
            )
        usable, mids = self._middles(
            cte,
            params,
            "close_price * 1.0 / area",
            "close_price, area",
            "area IS NOT NULL AND area >= %s",
            (AREA_FLOOR,),
        )
        if usable >= METRIC_MIN:
            ppsf = [
                Decimal(str(r["close_price"])) / Decimal(str(r["area"])) for r in mids
            ]
            facts["median_price_per_sqft"] = int(_half_even(sum(ppsf) / len(ppsf), "1"))
        return facts

    # --- set version 2 (WO-028): card readings, the monthly trend, extended analytics
    # and the comparable-sales price check, each from its documented definition ---

    def market_card(
        self, place: Mapping[str, str], subtype: str | None = None, months: int = 6
    ) -> dict[str, Any]:
        """The five card facts plus the WO-008 readings and the monthly trend."""
        facts = self.market(place, subtype, months)
        facts["dom_band"] = dom_band(facts["median_dom"])
        facts["market_lean"] = market_lean(
            facts["sale_to_list_ratio"], facts["median_dom"]
        )
        facts["sale_to_list_reading"] = sale_to_list_reading(
            facts["sale_to_list_ratio"]
        )
        facts["trend"] = []
        if facts["sample_count"] >= MIN_SAMPLE:
            cte, params = self._sample(place, subtype, months)
            counts = self._month_counts(cte, params)
            mids = self._month_middles(
                cte, params, "close_price", "close_price", "1 = 1"
            )
            for key in month_keys(*self.window(months)):
                n = counts.get(key, {}).get("n", 0)
                median = None
                if n >= MONTH_MIN:
                    rows = mids[key]
                    value = sum(Decimal(str(r["close_price"])) for r in rows) / len(
                        rows
                    )
                    median = int(_half_even(value, "1"))
                facts["trend"].append(
                    {"month": key, "sample_count": n, "median_close_price": median}
                )
        return facts

    def analytics(
        self, place: Mapping[str, str], subtype: str | None = None, months: int = 6
    ) -> dict[str, Any]:
        """The opt-in extended figures (ADDITIONAL_CAPABILITIES.md): current active
        inventory for the place and subtype, the sold count, the mean price (5 sales)
        and mean DOM (10 usable values), and the per-month rows with their changes.
        The mean price per sqft is not here: its definition is ambiguous (WO-028)."""
        cte, params = self._sample(place, subtype, months)
        (total,) = self._rows(
            f"{cte} SELECT COUNT(*) AS n, ROUND(SUM(close_price), 2) AS price_sum, "
            "SUM(CASE WHEN dom >= 0 THEN dom END) AS dom_sum, "
            "SUM(CASE WHEN dom >= 0 THEN 1 ELSE 0 END) AS dom_n FROM kept",
            params,
        )
        count = int(total["n"])
        inventory = {k: v for k, v in place.items()}
        inventory["property_subtype"] = subtype or DEFAULT_SUBTYPE
        facts: dict[str, Any] = {
            "analytics_active_count": self.total_matches(inventory),
            "analytics_sold_count": count,
            "analytics_mean_close_price": _mean(
                total["price_sum"], count, count >= MIN_SAMPLE
            ),
            "analytics_mean_dom": _mean(
                total["dom_sum"],
                int(total["dom_n"] or 0),
                int(total["dom_n"] or 0) >= METRIC_MIN,
            ),
        }
        counts = self._month_counts(cte, params)
        ppsf = self._month_middles(
            cte,
            params,
            "close_price * 1.0 / area",
            "close_price, area",
            "area IS NOT NULL AND area >= %s",
            (AREA_FLOOR,),
        )
        start, end = self.window(months)
        rows: list[dict[str, Any]] = []
        prices: dict[str, Decimal | None] = {}
        medians: dict[str, Decimal | None] = {}
        for key in month_keys(start, end):
            cell = counts.get(key, {})
            n = int(cell.get("n", 0))
            year, month = int(key[:4]), int(key[5:])
            first = date(year, month, 1)
            last = date(year, month, calendar.monthrange(year, month)[1])
            partial = start > first or end < last
            enough = count >= MIN_SAMPLE
            price = _raw_mean(cell.get("price_sum"), n, enough and n >= MONTH_MIN)
            dom_n = int(cell.get("dom_n") or 0)
            mean_dom = _raw_mean(
                cell.get("dom_sum"), dom_n, enough and dom_n >= METRIC_MIN
            )
            middle = ppsf.get(key, [])
            median = None
            if enough and middle and int(middle[0]["n"]) >= METRIC_MIN:
                median = sum(
                    Decimal(str(r["close_price"])) / Decimal(str(r["area"]))
                    for r in middle
                ) / len(middle)
            previous = months_back(first, 1).strftime("%Y-%m")
            prior_year = f"{year - 1:04d}-{month:02d}"
            row = {
                "month": key,
                "sample_count": n,
                "partial": partial,
                "mean_close_price": _round_money(price),
                "mean_dom": _round_money(mean_dom),
                "price_mom_pct": None,
                "price_yoy_pct": None,
                "ppsf_mom_pct": None,
                "ppsf_yoy_pct": None,
            }
            if not partial:
                # Only complete months are compared; a gap is not the previous month.
                row["price_mom_pct"] = _change(price, prices.get(previous))
                row["price_yoy_pct"] = _change(price, prices.get(prior_year))
                row["ppsf_mom_pct"] = _change(median, medians.get(previous))
                row["ppsf_yoy_pct"] = _change(median, medians.get(prior_year))
                prices[key], medians[key] = price, median
            rows.append(row)
        facts["analytics_months"] = rows
        return facts

    def _month_counts(self, cte: str, params: list[Any]) -> dict[str, dict[str, Any]]:
        """Per calendar month of the sample: sales, the price sum, usable DOM."""
        rows = self._rows(
            f"{cte} SELECT ym, COUNT(*) AS n, ROUND(SUM(close_price), 2) AS price_sum, "
            "SUM(CASE WHEN dom >= 0 THEN dom END) AS dom_sum, "
            "SUM(CASE WHEN dom >= 0 THEN 1 ELSE 0 END) AS dom_n "
            "FROM kept GROUP BY ym ORDER BY ym",
            params,
        )
        return {str(r["ym"]): r for r in rows}

    def _month_middles(
        self,
        cte: str,
        params: list[Any],
        value: str,
        columns: str,
        where: str,
        extra: Sequence[Any] = (),
    ) -> dict[str, list[dict[str, Any]]]:
        """Per month, the one or two middle rows ordered by `value` (at most 50)."""
        sql = (
            f"{cte}, ranked AS (SELECT ym, {columns}, ROW_NUMBER() OVER "
            f"(PARTITION BY ym ORDER BY {value}) AS rn, "
            "COUNT(*) OVER (PARTITION BY ym) AS n FROM kept "
            f"WHERE {where}) SELECT ym, {columns}, rn, n FROM ranked "
            "WHERE rn * 2 >= n AND rn * 2 <= n + 2 ORDER BY ym, rn"
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows(sql, [*params, *extra]):
            out.setdefault(str(row["ym"]), []).append(row)
        return out

    # --- the comparable-sales price check (CONTRACTS.md CompEvidence) ---

    def comps(self, listing_key: int) -> dict[str, Any]:
        """The subject's price check: level, comp count, median and middle-half price
        per sqft, the signed whole-percent delta, and the verdict band."""
        facts: dict[str, Any] = {
            "comp_verdict": "not_checkable",
            "comp_level": None,
            "comp_count": 0,
            "comp_median_ppsf": None,
            "comp_range_low_ppsf": None,
            "comp_range_high_ppsf": None,
            "comp_delta_pct": None,
        }
        found = self._rows(
            f"SELECT {_a('L_City')} AS city, {_a('L_Zip')} AS zip, "
            f"{_a('L_Type_')} AS subtype, {_a('LM_Int2_3')} AS area, "
            f"{_a('L_Keyword2')} AS beds, {_a('L_SystemPrice')} AS price "
            f"FROM {ACTIVE} WHERE {_a('L_ListingID')} = %s LIMIT 2",
            (str(listing_key),),
        )
        if len(found) != 1:
            raise ValueError("a comps case needs exactly one subject row")
        subject = found[0]
        zip5 = str(subject["zip"] or "")[:5]
        checkable = (
            bool(subject["city"])
            and len(zip5) == 5
            and zip5.isdigit()
            and bool(subject["subtype"])
            and subject["area"] is not None
            and int(subject["area"]) >= AREA_FLOOR
            and subject["beds"] is not None
            and subject["price"] is not None
            and Decimal(str(subject["price"])) >= PRICE_FLOOR
        )
        if not checkable:
            return facts
        area, beds = int(subject["area"]), int(subject["beds"])
        band = (
            "area * 10 >= %s AND area * 10 <= %s AND beds >= %s AND beds <= %s",
            (area * 8, area * 12, max(0, beds - 1), beds + 1),
        )
        level, place = "postal_code", {"postal_code": zip5}
        count = self._comp_count(place, str(subject["subtype"]), band)
        if count < COMP_MIN:
            level, place = "city", {"city": str(subject["city"])}
            count = self._comp_count(place, str(subject["subtype"]), band)
        facts.update(comp_level=level, comp_count=count)
        if count < COMP_MIN:
            facts["comp_verdict"] = "insufficient"
            return facts
        cte, params = self._sample(place, str(subject["subtype"]), COMP_WINDOW)
        where, extra = band
        _, mids = self._middles(
            cte,
            params,
            "close_price * 1.0 / area",
            "close_price, area",
            where,
            extra,
        )
        median = sum(
            Decimal(str(r["close_price"])) / Decimal(str(r["area"])) for r in mids
        ) / len(mids)
        low_rank, high_rank = count // 4 + 1, count - count // 4
        ends = self._rows(
            f"{cte}, ranked AS (SELECT close_price, area, ROW_NUMBER() OVER "
            "(ORDER BY close_price * 1.0 / area) AS rn FROM kept "
            f"WHERE {where}) SELECT close_price, area, rn FROM ranked "
            "WHERE rn = %s OR rn = %s ORDER BY rn",
            [*params, *extra, low_rank, high_rank],
        )
        by_rank = {
            int(r["rn"]): Decimal(str(r["close_price"])) / Decimal(str(r["area"]))
            for r in ends
        }
        delta = (Decimal(str(subject["price"])) / Decimal(area) / median - 1) * 100
        delta_pct = int(_half_even(delta, "1"))
        facts.update(
            comp_median_ppsf=int(_half_even(median, "1")),
            comp_range_low_ppsf=int(_half_even(by_rank[low_rank], "1")),
            comp_range_high_ppsf=int(_half_even(by_rank[high_rank], "1")),
            comp_delta_pct=delta_pct,
            comp_verdict="above"
            if delta_pct > 0
            else "below"
            if delta_pct < 0
            else "at",
        )
        return facts

    def _comp_count(
        self, place: Mapping[str, str], subtype: str, band: tuple[str, Sequence[Any]]
    ) -> int:
        cte, params = self._sample(place, subtype, COMP_WINDOW)
        where, extra = band
        (row,) = self._rows(
            f"{cte} SELECT COUNT(*) AS n FROM kept WHERE {where}", [*params, *extra]
        )
        return int(row["n"])


# --- the WO-008 readings, from the thresholds the work order fixes ---


def dom_band(median_dom: float | None) -> str | None:
    """very_low under 15, low under 30, average under 60, high from 60."""
    if median_dom is None:
        return None
    if median_dom < 15:
        return "very_low"
    if median_dom < 30:
        return "low"
    return "average" if median_dom < 60 else "high"


def market_lean(ratio: float | None, median_dom: float | None) -> str | None:
    """seller (ratio at least 1.000 and under 30 days), else buyer (ratio under 0.980
    or 60 days or more), else balanced; None without a median DOM."""
    if ratio is None or median_dom is None:
        return None
    rounded = Decimal(str(ratio))
    if rounded >= Decimal("1.000") and median_dom < 30:
        return "seller"
    if rounded < Decimal("0.980") or median_dom >= 60:
        return "buyer"
    return "balanced"


def sale_to_list_reading(ratio: float | None) -> str | None:
    """The rounded ratio's distance from 1 in whole percent, half-even."""
    if ratio is None:
        return None
    pct = int(_half_even((Decimal(str(ratio)) - 1) * 100, "1"))
    if pct == 0:
        return "at asking"
    return f"{pct}% over asking" if pct > 0 else f"{-pct}% under asking"


def month_keys(start: date, end: date) -> list[str]:
    """Every calendar month the window touches, oldest first ("YYYY-MM")."""
    keys = []
    index, last = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    while index <= last:
        keys.append(f"{index // 12:04d}-{index % 12 + 1:02d}")
        index += 1
    return keys


def _raw_mean(total: Any, count: int, enough: bool) -> Decimal | None:
    if not enough or total is None or count <= 0:
        return None
    return Decimal(str(total)) / count


def _mean(total: Any, count: int, enough: bool) -> float | None:
    return _round_money(_raw_mean(total, count, enough))


def _round_money(value: Decimal | None) -> float | None:
    """Two decimal places, half-even (means and monthly medians in analytics)."""
    return None if value is None else float(_half_even(value, "0.01"))


def _change(current: Decimal | None, previous: Decimal | None) -> float | None:
    """Percent change to one decimal, half-even, before any display rounding."""
    if current is None or previous is None or previous <= 0:
        return None
    return float(_half_even((current / previous - 1) * 100, "0.1"))
