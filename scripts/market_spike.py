"""WO-008 early-start spike: sample sizes, SQL medians, ZIP shape, subtype gap.

Read-only, as idx_reader through pool.connect(); prints aggregates only, never a row,
an address, a listing key, or a city name. Every column passes check_column and every
value is bound. Run: MYSQL_HOST=localhost python scripts/market_spike.py
"""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as scripts/fixture_lint.py does.
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.db.asof import read_asof_dates  # noqa: E402
from idx_agent.db.pool import connect  # noqa: E402
from idx_agent.domain.asof import AsOfDates  # noqa: E402
from idx_agent.safety.columns import check_column  # noqa: E402

Stmt = tuple[str, tuple[Any, ...]]

TABLE = "california_sold"
SINGLE_FAMILY = "SingleFamilyResidence"
PRICE_FLOOR = 25_000
WINDOWS = (1, 3, 6)
DEFAULT_MONTHS = 6
TOP_N = 20
RUNS = 3
THRESHOLDS = (5, 10)
QUANTILES = (0.25, 0.5, 0.75)
MAX_ROWS = 50
KEEP_RANK = 1
MONTH_FORMAT = "%Y-%m"
FIVE_DIGITS = "^[0-9]{5}$"
ZIP_PLUS_FOUR = "^[0-9]{5}-[0-9]{4}$"
# The one or two middle rows of an ordered sample of n (rn counts from 1).
MIDDLE = "rn IN (FLOOR((n + 1) / 2), FLOOR(n / 2) + 1)"


def _col(name: str) -> str:
    """Return the column name after the california_sold allowlist check."""
    return check_column(TABLE, name)


CITY, ZIP, KEY = _col("City"), _col("PostalCode"), _col("ListingKey")
CLOSE, LIST, DOM = _col("ClosePrice"), _col("ListPrice"), _col("DaysOnMarket")
CLOSE_D, CONTRACT_D = _col("close_date_d"), _col("purchase_contract_date_d")
SUBTYPE = _col("PropertySubType")


# ----- statement builders (pure) ----------------------------------------------------
def sample(
    name: str,
    window: tuple[date, date],
    active: date,
    city: str | None = None,
    subtype: str | None = None,
) -> Stmt:
    """CTEs `<name>_raw` (window rows after the exclusions, ranked per ListingKey) and
    `<name>` (rank 1 only: latest close, then higher close, then higher list price).
    """
    where = [
        f"{CLOSE_D} BETWEEN %s AND %s",  # also drops a NULL close date
        f"{CLOSE_D} <= %s",  # never after the active as-of date
        f"NOT ({CONTRACT_D} IS NOT NULL AND {CLOSE_D} < {CONTRACT_D})",
        f"{CLOSE} >= %s",
        f"{LIST} >= %s",
        f"{CITY} <> %s",
    ]
    params: list[Any] = [MONTH_FORMAT, *window, active, PRICE_FLOOR, PRICE_FLOOR, ""]
    if city is not None:
        where.append(f"{CITY} = %s")
        params.append(city)
    if subtype is not None:
        where.append(f"{SUBTYPE} = %s")
        params.append(subtype)
    raw = (
        f"{name}_raw AS (SELECT {CITY} AS city, {CLOSE} AS close_price, "
        f"{LIST} AS list_price, {DOM} AS dom, {SUBTYPE} AS subtype, "
        f"DATE_FORMAT({CLOSE_D}, %s) AS ym, ROW_NUMBER() OVER (PARTITION BY {KEY} "
        f"ORDER BY {CLOSE_D} DESC, {CLOSE} DESC, {LIST} DESC) AS dup "
        f"FROM {TABLE} WHERE {' AND '.join(where)})"
    )
    kept = (
        f"{name} AS (SELECT city, close_price, list_price, dom, subtype, ym "
        f"FROM {name}_raw WHERE dup = %s)"
    )
    return f"{raw}, {kept}", (*params, KEEP_RANK)


def median_stmt(
    cte: Stmt, value: str, keep: str = "", keep_params: tuple[Any, ...] = ()
) -> Stmt:
    """Order-statistics median over CTE `d`: n and the one or two middle values."""
    where = f" WHERE {keep}" if keep else ""
    sql = (
        f"WITH {cte[0]}, o AS (SELECT {value} AS v, ROW_NUMBER() OVER "
        f"(ORDER BY {value}) AS rn, COUNT(*) OVER () AS n FROM d{where}) "
        f"SELECT MAX(n) AS n, MIN(v) AS lo, MAX(v) AS hi FROM o WHERE {MIDDLE}"
    )
    return sql, (*cte[1], *keep_params)


def offset_stmt(cte: Stmt, offset: int) -> Stmt:
    """The close price at a bound OFFSET of the ordered sample in CTE `d`."""
    sql = (
        f"WITH {cte[0]} SELECT close_price AS v FROM d "
        "ORDER BY close_price LIMIT 1 OFFSET %s"
    )
    return sql, (*cte[1], offset)


def exclusions_stmt(
    window: tuple[date, date], active: date, city: str, subtype: str | None
) -> Stmt:
    """Per-request exclusion counts for one city (and subtype); one row."""
    in_window = f"{CLOSE_D} BETWEEN %s AND %s"
    before = f"({CONTRACT_D} IS NOT NULL AND {CLOSE_D} < {CONTRACT_D})"
    sql = (
        f"SELECT SUM({CLOSE_D} > %s) AS after_active, "
        f"SUM({CLOSE_D} IS NULL) AS null_close, "
        f"SUM({in_window} AND {before}) AS before_contract, "
        f"SUM({in_window} AND NOT {before} AND ({CLOSE} < %s OR {LIST} < %s)) "
        f"AS under_floor FROM {TABLE} WHERE {CITY} = %s"
    )
    params: list[Any] = [active, *window, *window, PRICE_FLOOR, PRICE_FLOOR, city]
    if subtype is not None:
        sql += f" AND {SUBTYPE} = %s"
        params.append(subtype)
    return sql, tuple(params)


def city_statement_set(
    window: tuple[date, date], active: date, city: str, subtype: str | None
) -> list[tuple[str, Stmt]]:
    """The statements one market request would run: exclusions through subtype mix."""
    d = sample("d", window, active, city, subtype)
    mix = sample("m", window, active, city)
    months = (
        f"WITH {d[0]}, o AS (SELECT ym, close_price AS v, ROW_NUMBER() OVER "
        "(PARTITION BY ym ORDER BY close_price) AS rn, COUNT(*) OVER "
        "(PARTITION BY ym) AS n FROM d) SELECT ym, MAX(n) AS n, MIN(v) AS lo, "
        f"MAX(v) AS hi FROM o WHERE {MIDDLE} GROUP BY ym ORDER BY ym"
    )
    return [
        ("exclusions", exclusions_stmt(window, active, city, subtype)),
        (
            "count",
            (
                f"WITH {d[0]} SELECT COUNT(*) AS valid, SUM(dup = %s) AS kept "
                "FROM d_raw",
                (*d[1], KEEP_RANK),
            ),
        ),
        ("median close price", median_stmt(d, "close_price")),
        ("median DOM", median_stmt(d, "dom", "dom IS NOT NULL AND dom >= %s", (0,))),
        ("median sale-to-list", median_stmt(d, "close_price / list_price")),
        ("month buckets", (months, d[1])),
        (
            "subtype mix",
            (
                f"WITH {mix[0]} SELECT subtype, COUNT(*) AS n FROM m "
                "GROUP BY subtype ORDER BY n DESC LIMIT %s",
                (*mix[1], TOP_N),
            ),
        ),
    ]


def distribution_stmt(cte: Stmt) -> Stmt:
    """Per-city counts over CTE `d`, reduced to lower-rank quantiles and shares."""
    picks = ", ".join(
        f"MAX(CASE WHEN rn = FLOOR(%s * (k - 1)) + 1 THEN n END) AS q{int(q * 100)}"
        for q in QUANTILES
    )
    unders = ", ".join(f"SUM(n < %s) AS under_{t}" for t in THRESHOLDS)
    sql = (
        f"WITH {cte[0]}, c AS (SELECT city, COUNT(*) AS n FROM d GROUP BY city), "
        "r AS (SELECT n, ROW_NUMBER() OVER (ORDER BY n) AS rn, COUNT(*) OVER () "
        f"AS k FROM c) SELECT MAX(k) AS cities, MIN(n) AS q0, {picks}, "
        f"MAX(n) AS q100, {unders} FROM r"
    )
    return sql, (*cte[1], *QUANTILES, *THRESHOLDS)


def short_single_family_stmt(window: tuple[date, date], active: date) -> Stmt:
    """Cities with at least t sales in total, and how many of them have under t SF."""
    a = sample("a", window, active)
    f = sample("f", window, active, subtype=SINGLE_FAMILY)
    sums = ", ".join(
        f"SUM(ca.n >= %s) AS enough_{t}, "
        f"SUM(ca.n >= %s AND COALESCE(cf.n, 0) < %s) AS short_{t}"
        for t in THRESHOLDS
    )
    sql = (
        f"WITH {a[0]}, {f[0]}, "
        "ca AS (SELECT city, COUNT(*) AS n FROM a GROUP BY city), "
        "cf AS (SELECT city, COUNT(*) AS n FROM f GROUP BY city) "
        f"SELECT {sums} FROM ca LEFT JOIN cf ON cf.city = ca.city"
    )
    return sql, (*a[1], *f[1], *(t for t in THRESHOLDS for _ in range(3)))


def postal_stmt() -> Stmt:
    """Shape of every sold PostalCode: null, empty, five digits, ZIP+4; one row."""
    sql = (
        f"SELECT COUNT(*) AS total, SUM({ZIP} IS NULL) AS nulls, "
        f"SUM({ZIP} = %s) AS empties, SUM({ZIP} REGEXP %s) AS five, "
        f"SUM({ZIP} REGEXP %s) AS zip4 FROM {TABLE}"
    )
    return sql, ("", FIVE_DIGITS, ZIP_PLUS_FOUR)


# ----- execution helpers ------------------------------------------------------------
def run(conn: Any, stmt: Stmt) -> list[dict[str, Any]]:
    """Execute one statement; raise if it returns more than MAX_ROWS rows."""
    with conn.cursor() as cursor:
        cursor.execute(stmt[0], stmt[1])
        rows = list(cursor.fetchall())
    if len(rows) > MAX_ROWS:
        raise RuntimeError(f"statement returned {len(rows)} rows (cap {MAX_ROWS})")
    return rows


def explain_keys(conn: Any, stmt: Stmt) -> str:
    """Index names (and access type) EXPLAIN reports on the base table, no values."""
    # This server defaults explain_format to TREE; ask for the tabular form.
    rows = run(conn, ("EXPLAIN FORMAT=TRADITIONAL " + stmt[0], stmt[1]))
    seen = []
    for row in rows:
        if row.get("table") == TABLE:
            key = row.get("key") or "none"
            seen.append(f"{key} ({row.get('type')})")
    return ", ".join(dict.fromkeys(seen)) or "no base-table access"


def middle(row: dict[str, Any]) -> Decimal | None:
    """Median from the one or two middle values, averaged in Decimal."""
    if row.get("n") is None:
        return None
    return (Decimal(str(row["lo"])) + Decimal(str(row["hi"]))) / 2


def lower_rank(values: Sequence[float]) -> list[float]:
    """min, 25%, median, 75%, max by lower nearest rank (same rule as the SQL)."""
    ordered = sorted(values)
    k = len(ordered)
    picks = [ordered[int(q * (k - 1))] for q in QUANTILES]
    return [ordered[0], *picks, ordered[-1]]


def pct(part: float, whole: float) -> str:
    """Share as a percentage with one decimal; '-' when the whole is zero."""
    return f"{100 * part / whole:.1f}%" if whole else "-"


# ----- sections -----------------------------------------------------------------------
def section_a(conn: Any, as_of: AsOfDates) -> dict[str, Any]:
    """(a) per-city sample sizes by window and subtype mode; returns 6-month SF row."""
    print("\n(a) per-city sample sizes after exclusions (cities with >= 1 sale)")
    print("window | mode | start | cities | min | p25 | p50 | p75 | max | <5 | <10")
    keep: dict[str, Any] = {}
    for months in WINDOWS:
        window = as_of.window(months)
        for mode, subtype in (("single-family", SINGLE_FAMILY), ("all", None)):
            row = run(
                conn,
                distribution_stmt(sample("d", window, as_of.active, subtype=subtype)),
            )[0]
            k = row["cities"] or 0
            print(
                f"{months} mo | {mode} | {window[0]} | {k} | {row['q0']} | "
                f"{row['q25']} | {row['q50']} | {row['q75']} | {row['q100']} | "
                f"{pct(row['under_5'] or 0, k)} | {pct(row['under_10'] or 0, k)}"
            )
            if months == DEFAULT_MONTHS and subtype == SINGLE_FAMILY:
                keep = row
    return keep


def top_cities(conn: Any, as_of: AsOfDates) -> list[str]:
    """The TOP_N cities by all-subtype sales at 6 months; held in memory, not shown."""
    cte = sample("d", as_of.window(DEFAULT_MONTHS), as_of.active)
    stmt = (
        f"WITH {cte[0]} SELECT city, COUNT(*) AS n FROM d GROUP BY city "
        "ORDER BY n DESC, city LIMIT %s",
        (*cte[1], TOP_N),
    )
    return [row["city"] for row in run(conn, stmt)]


def section_b_medians(
    conn: Any, as_of: AsOfDates, cities: list[str]
) -> tuple[bool, list[float]]:
    """(b) window vs offset medians of ClosePrice in the top cities, both modes.

    Returns (all agree, SF-vs-all relative differences in percent for (d)).
    """
    window = as_of.window(DEFAULT_MONTHS)
    checked = agreed = 0
    time_window = time_offset = 0.0
    diffs: list[float] = []
    for city in cities:
        medians: dict[str | None, Decimal | None] = {}
        for subtype in (SINGLE_FAMILY, None):
            cte = sample("d", window, as_of.active, city, subtype)
            t0 = time.perf_counter()
            row = run(conn, median_stmt(cte, "close_price"))[0]
            t1 = time.perf_counter()
            n = int(row["n"] or 0)
            offsets = sorted({(n - 1) // 2, n // 2}) if n else []
            values = [run(conn, offset_stmt(cte, k))[0]["v"] for k in offsets]
            time_window += t1 - t0
            time_offset += time.perf_counter() - t1
            checked += 1
            # An empty sample has no middle, so nothing can disagree.
            if not n or (values[0] == row["lo"] and values[-1] == row["hi"]):
                agreed += 1
            medians[subtype] = middle(row)
        sf, total = medians[SINGLE_FAMILY], medians[None]
        if sf is not None and total:
            diffs.append(float((sf - total) / total * 100))
    print(f"\n(b) median methods, ClosePrice, top {len(cities)} cities, 6 months")
    print(f"samples checked (cities x SF/all): {checked}; both methods agree: {agreed}")
    print(
        f"total time: window-function method {time_window:.3f} s, "
        f"bound-offset method (2 statements, after count) {time_offset:.3f} s"
    )
    return checked == agreed, diffs


def section_b_timing(conn: Any, as_of: AsOfDates, city: str) -> float:
    """(b) best-of-RUNS time of the full statement set for the largest city."""
    window = as_of.window(DEFAULT_MONTHS)
    worst_best = 0.0
    print("\n(b) full statement set, largest city, 6 months (best of 3 runs)")
    for label, subtype in (
        ("subtype = SingleFamilyResidence", SINGLE_FAMILY),
        ("no subtype (all)", None),
    ):
        stmts = city_statement_set(window, as_of.active, city, subtype)
        times = []
        for _ in range(RUNS):
            t0 = time.perf_counter()
            for _name, stmt in stmts:
                run(conn, stmt)
            times.append(time.perf_counter() - t0)
        best = min(times)
        worst_best = max(worst_best, best)
        n = run(conn, stmts[1][1])[0]["kept"]
        print(
            f"{label}: sample {n}; best {best:.3f} s; runs "
            + ", ".join(f"{t:.3f}" for t in times)
        )
        for name, stmt in stmts:
            print(f"  EXPLAIN {name}: {explain_keys(conn, stmt)}")
    return worst_best


def section_c(conn: Any) -> int:
    """(c) sold PostalCode values that are not exactly five digits."""
    row = run(conn, postal_stmt())[0]
    total, five = int(row["total"]), int(row["five"] or 0)
    nulls, empties, zip4 = (int(row[k] or 0) for k in ("nulls", "empties", "zip4"))
    bad = total - five
    other = bad - nulls - empties - zip4
    print("\n(c) sold PostalCode shape (whole table)")
    print(
        f"rows {total}; not exactly five digits {bad} ({pct(bad, total)}): "
        f"NULL {nulls}, empty {empties}, ZIP+4 {zip4}, other {other}"
    )
    return bad


def section_d(conn: Any, as_of: AsOfDates, diffs: list[float]) -> dict[str, Any]:
    """(d) SF vs all-subtype median gap, and cities short of SF comps at 6 months."""
    print(f"\n(d) single-family median vs all-subtype median, top {TOP_N} cities")
    if diffs:
        q = lower_rank(diffs)
        print("relative difference (SF - all) / all: min | p25 | p50 | p75 | max")
        print(" | ".join(f"{v:+.1f}%" for v in q))
        print(
            f"cities with an SF median: {len(diffs)}; SF above all: "
            f"{sum(v > 0 for v in diffs)}; |diff| over 10%: "
            f"{sum(abs(v) > 10 for v in diffs)}"
        )
    row = run(
        conn, short_single_family_stmt(as_of.window(DEFAULT_MONTHS), as_of.active)
    )[0]
    for t in THRESHOLDS:
        enough, short = int(row[f"enough_{t}"] or 0), int(row[f"short_{t}"] or 0)
        print(
            f"threshold {t}: cities with >= {t} sales in total {enough}; of those "
            f"under {t} single-family {short} ({pct(short, enough)})"
        )
    return row


def decide(
    dist: dict[str, Any], short: dict[str, Any], agree: bool, best: float, bad_zip: int
) -> None:
    """Apply the WO-008 decision rules to the numbers and print each outcome."""
    k = dist["cities"] or 0
    reach5 = 100 * (k - (dist["under_5"] or 0)) / k if k else 0.0
    reach10 = 100 * (k - (dist["under_10"] or 0)) / k if k else 0.0
    min_sample = 10 if reach5 - reach10 <= 5 else 5
    print("\nDecisions")
    print(
        f"MIN_SAMPLE: SF 6 mo, cities reaching 5 {reach5:.1f}%, reaching 10 "
        f"{reach10:.1f}% (gap {reach5 - reach10:.1f} pts) -> MIN_SAMPLE {min_sample}"
    )
    enough = int(short[f"enough_{min_sample}"] or 0)
    short_n = int(short[f"short_{min_sample}"] or 0)
    share = 100 * short_n / enough if enough else 0.0
    verdict = "stop and ask" if share > 25 else "single-family default stands"
    print(
        f"No-subtype default: {short_n}/{enough} = {share:.1f}% of cities with "
        f"enough total sales lack SF comps -> {verdict}"
    )
    if not agree or best > 10:
        sql_verdict = "stop condition (methods disagree or over 10 s)"
    elif best >= 2:
        sql_verdict = "stop and ask (2-10 s)"
    else:
        sql_verdict = "accepted: medians from SQL order statistics"
    print(
        f"Median in SQL: agree={agree}, slowest best set {best:.3f} s -> {sql_verdict}"
    )
    form = "PostalCode = %s" if bad_zip == 0 else "five-digit prefix LIKE, as search"
    print(f"Postal code: {bad_zip} not five digits -> {form}")


def main() -> int:
    """Connect as the reader; print sections (a)-(d), the decisions, the wall time."""
    started = time.perf_counter()
    conn = connect()
    try:
        as_of = read_asof_dates(conn)
        version = run(conn, ("SELECT VERSION() AS v", ()))[0]["v"]
        print(f"MySQL {version}; sold as-of {as_of.sold}; active as-of {as_of.active}")
        for months in WINDOWS:
            start, end = as_of.window(months)
            print(f"window {months} mo: {start} to {end}")
        dist = section_a(conn, as_of)
        cities = top_cities(conn, as_of)
        agree, diffs = section_b_medians(conn, as_of, cities)
        best = section_b_timing(conn, as_of, cities[0])
        bad_zip = section_c(conn)
        short = section_d(conn, as_of, diffs)
        decide(dist, short, agree, best, bad_zip)
    finally:
        conn.close()
    print(f"\nspike wall time {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
