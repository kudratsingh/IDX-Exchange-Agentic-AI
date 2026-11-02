"""Answer facts for measurement cases, from hand-written SQL (WO-020 requirement 2).

Written from the documented definitions (CONTRACTS.md search filters and MarketStats,
DECISIONS.md time windows and exclusions, WO-008's duplicate rule), never by calling or
copying `idx_agent.db`. The only `idx_agent` import is the column allowlist. Every value
is bound; statements return counts or median middle rows only (at most 2 rows), and the
SQL runs unchanged on MySQL 8 and on SQLite (window functions, `%s` or `?` marks), so
goldens can be recomputed from the committed fixture without a server.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from idx_agent.safety.columns import check_column

__all__ = ["FACT_KINDS", "Truth", "months_back"]

ACTIVE = "rets_property"
SOLD = "california_sold"
DEFAULT_SUBTYPE = "SingleFamilyResidence"
PRICE_FLOOR = 25_000  # DECISIONS.md: close or list price under 25,000 is excluded
AREA_FLOOR = 200  # price per sqft counts only living areas of 200 sqft or more
MIN_SAMPLE = 5  # below this, no figure is given
METRIC_MIN = 10  # median DOM and price per sqft each need 10 usable values
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
            f"ROW_NUMBER() OVER (PARTITION BY {_s('ListingKey')} "
            f"ORDER BY {close} DESC, "
            f"{_s('ClosePrice')} DESC, {_s('ListPrice')} DESC) AS copy "
            f"FROM {SOLD} WHERE {place_sql} AND {_s('PropertySubType')} = %s "
            f"AND {close} IS NOT NULL AND {close} >= %s AND {close} <= %s "
            f"AND {close} <= %s AND ({contract} IS NULL OR {close} >= {contract}) "
            f"AND {_s('ClosePrice')} >= %s AND {_s('ListPrice')} >= %s), "
            "kept AS (SELECT close_price, list_price, area, dom FROM base "
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
            "SELECT * FROM ranked WHERE rn * 2 >= n AND rn * 2 <= n + 2 ORDER BY rn"
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
        usable, mids = self._middles(cte, params, "dom", "dom", "dom IS NOT NULL")
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
