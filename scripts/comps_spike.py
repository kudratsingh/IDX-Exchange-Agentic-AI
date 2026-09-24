"""WO-011 early-start spike: comps reach under the human's rule, timing, index use.

Read-only, as idx_reader through pool.connect(); prints aggregates only, never a row,
a listing key, an address, a remark, a ZIP, or a city name. The sample's subject
facts stay in memory. Every column passes check_column, every value is bound, and
no statement returns more than 50 rows. The comps statements reuse WO-008's sample
CTE (exclusions, floors, duplicate-key collapse) and window-function median.
Run: MYSQL_HOST=localhost python scripts/comps_spike.py
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as scripts/market_spike.py does.
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.db.asof import read_asof_dates  # noqa: E402
from idx_agent.db.market import _columns, _median, _run, _sample  # noqa: E402
from idx_agent.db.pool import connect  # noqa: E402
from idx_agent.domain.asof import AsOfDates  # noqa: E402
from idx_agent.domain.market import AREA_FLOOR, MIN_SAMPLE  # noqa: E402
from idx_agent.domain.models import StatsWindow  # noqa: E402
from idx_agent.domain.valid_values import (  # noqa: E402
    ACTIVE_STATUS_COLUMN,
    ACTIVE_STATUS_VALUES,
)
from idx_agent.safety.columns import check_column  # noqa: E402

Stmt = tuple[str, tuple[Any, ...]]

ACTIVE = "rets_property"
SOLD = "california_sold"
MONTHS = 6
TOP_CITIES = 20
PER_CITY = 10
RUNS = 3
# A full recommendation: the subject plus 5 candidates, each city then ZIP at most.
RECOMMENDATION = 6
AREA_LOW, AREA_HIGH = Decimal("0.8"), Decimal("1.2")
BED_SPAN = 1
QUANTILES = (0.25, 0.5, 0.75)
FIVE_DIGITS = re.compile(r"[0-9]{5}")
COUNTY_PATTERN = "%county%"
PROCEED_S, STOP_S = 2.0, 10.0
EMPTY = ""


def _a(name: str) -> str:
    """Return the column name after the rets_property allowlist check."""
    return check_column(ACTIVE, name)


if ACTIVE_STATUS_COLUMN is None or not ACTIVE_STATUS_VALUES:
    raise SystemExit("no active status rule in valid_values")
A_KEY, A_CITY, A_ZIP = _a("L_ListingID"), _a("L_City"), _a("L_Zip")
A_TYPE, A_AREA, A_BEDS = _a("L_Type_"), _a("LM_Int2_3"), _a("L_Keyword2")
A_STATUS = _a(ACTIVE_STATUS_COLUMN)
STATUSES = tuple(sorted(ACTIVE_STATUS_VALUES))
S_AREA = check_column(SOLD, "LivingArea")
S_BEDS = check_column(SOLD, "BedroomsTotal")


@dataclass(frozen=True)
class Subject:
    """One sampled active listing's comps facts; held in memory, never printed."""

    city: str
    zip5: str | None
    subtype: str | None
    area: int | None
    beds: int | None

    @property
    def missing(self) -> tuple[str, ...]:
        """Which facts the rule needs are absent (size under the floor counts)."""
        gaps = []
        if self.area is None or self.area < AREA_FLOOR:
            gaps.append("size")
        if self.beds is None or self.beds < 0:
            gaps.append("beds")
        if not self.subtype:
            gaps.append("type")
        return tuple(gaps)


@dataclass
class Reach:
    """Comps counts for one checkable subject: city, and ZIP when it was needed."""

    city_n: int
    zip_n: int | None  # None when the city reached the minimum or no five-digit ZIP

    @property
    def used_n(self) -> int:
        """The count at the level the rule ends on."""
        return self.city_n if self.zip_n is None else self.zip_n


# ----- statement builders (pure) ----------------------------------------------------
def _status() -> tuple[str, tuple[Any, ...]]:
    """The active-status clause with its bound values."""
    marks = ", ".join(["%s"] * len(STATUSES))
    return f"{A_STATUS} IN ({marks})", STATUSES


def county_stmt() -> Stmt:
    """Column names (only) of both tables that look like a county column."""
    sql = (
        "SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN (%s, %s) "
        "AND LOWER(COLUMN_NAME) LIKE %s ORDER BY TABLE_NAME, COLUMN_NAME"
    )
    return sql, (ACTIVE, SOLD, COUNTY_PATTERN)


def top_cities_stmt() -> Stmt:
    """The TOP_CITIES cities by active rows (20 rows)."""
    status, params = _status()
    sql = (
        f"SELECT {A_CITY} AS city, COUNT(*) AS n FROM {ACTIVE} WHERE {status} "
        f"AND {A_CITY} IS NOT NULL AND {A_CITY} <> %s GROUP BY {A_CITY} "
        f"ORDER BY n DESC, {A_CITY} LIMIT %s"
    )
    return sql, (*params, EMPTY, TOP_CITIES)


def city_subjects_stmt(city: str) -> Stmt:
    """The PER_CITY active rows with the lowest listing ids in one city (10 rows)."""
    status, params = _status()
    sql = (
        f"SELECT {A_ZIP} AS zip, {A_TYPE} AS subtype, {A_AREA} AS area, "
        f"{A_BEDS} AS beds FROM {ACTIVE} WHERE {status} AND {A_CITY} = %s "
        f"ORDER BY CAST({A_KEY} AS UNSIGNED), {A_KEY} LIMIT %s"
    )
    return sql, (*params, city, PER_CITY)


def comps_stmt(
    subject: Subject, level: str, window: StatsWindow, as_of: AsOfDates
) -> Stmt:
    """One summary row: comps count n and the middle close_price / area values.

    WO-008's sample CTE with the geography for the level plus the area and bed
    bands (the subtype through the CTE's own subtype predicate), then WO-008's
    median over close_price / area with the area floor.
    """
    if subject.missing:
        raise ValueError("subject cannot be checked")
    c = _columns()
    if level == "city":
        geo_sql, geo_params = f"{c['city']} = %s", (subject.city,)
    elif level == "zip" and subject.zip5 is not None:
        geo_sql, geo_params = f"{c['zip']} LIKE %s", (f"{subject.zip5}%",)
    else:
        raise ValueError("unknown level or no five-digit ZIP")
    area = Decimal(int(subject.area or 0))
    beds = int(subject.beds or 0)
    geo = (
        f"{geo_sql} AND {S_AREA} BETWEEN %s AND %s AND {S_BEDS} BETWEEN %s AND %s",
        (
            *geo_params,
            area * AREA_LOW,
            area * AREA_HIGH,
            max(beds - BED_SPAN, 0),
            beds + BED_SPAN,
        ),
    )
    d = _sample("d", c, geo, window, as_of, subject.subtype)
    return _median(
        d, "close_price / area", ("close_price", "area"), ("area >= %s", (AREA_FLOOR,))
    )


# ----- execution helpers ------------------------------------------------------------
def count_of(conn: Any, stmt: Stmt) -> int:
    """Run one comps statement and return its count (0 for an empty sample)."""
    rows = _run(conn, "comps", stmt)
    return int(rows[0]["n"] or 0) if rows else 0


def best_of(fn: Callable[[], Any]) -> float:
    """Best wall time of RUNS calls, in seconds."""
    times = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


def explain(conn: Any, stmt: Stmt) -> str:
    """Index use EXPLAIN reports on the sold table: key (type) [possible]; no values."""
    rows = _run(conn, "explain", ("EXPLAIN FORMAT=TRADITIONAL " + stmt[0], stmt[1]))
    seen = []
    for row in rows:
        if row.get("table") == SOLD:
            seen.append(
                f"{row.get('key') or 'none'} ({row.get('type')}) "
                f"[possible: {row.get('possible_keys') or 'none'}]"
            )
    return "; ".join(dict.fromkeys(seen)) or "no base-table access"


def to_int(value: Any) -> int | None:
    """An int from a driver value; None for NULL."""
    return None if value is None else int(value)


def zip5(value: Any) -> str | None:
    """The five-digit prefix of a ZIP value, or None when it has none."""
    text = str(value or "").strip()
    return text[:5] if FIVE_DIGITS.fullmatch(text[:5]) else None


def lower_rank(values: Sequence[int]) -> str:
    """min | p25 | p50 | p75 | max by lower nearest rank; '-' when empty."""
    if not values:
        return "- | - | - | - | -"
    ordered = sorted(values)
    k = len(ordered)
    picks = [ordered[int(q * (k - 1))] for q in QUANTILES]
    return " | ".join(str(v) for v in (ordered[0], *picks, ordered[-1]))


def pct(part: int, whole: int) -> str:
    """Share as a percentage with one decimal; '-' when the whole is zero."""
    return f"{100 * part / whole:.1f}%" if whole else "-"


# ----- sections -----------------------------------------------------------------------
def section_county(conn: Any) -> None:
    """(a) county-like column names per table (names are schema, not data)."""
    found: dict[str, list[str]] = {ACTIVE: [], SOLD: []}
    for row in _run(conn, "county", county_stmt()):
        found[row["t"]].append(row["c"])
    print("\n(a) county-like columns (information_schema, names only)")
    for table, names in found.items():
        print(f"{table}: {', '.join(names) if names else 'none'}")


def draw_sample(conn: Any) -> list[list[Subject]]:
    """The 200 subjects, grouped by city in active-row order; kept in memory."""
    cities = [row["city"] for row in _run(conn, "top", top_cities_stmt())]
    groups = []
    for city in cities:
        rows = _run(conn, "subjects", city_subjects_stmt(city))
        groups.append(
            [
                Subject(
                    city=city,
                    zip5=zip5(row["zip"]),
                    subtype=(row["subtype"] or None),
                    area=to_int(row["area"]),
                    beds=to_int(row["beds"]),
                )
                for row in rows
            ]
        )
    return groups


def section_reach(
    conn: Any, groups: list[list[Subject]], window: StatsWindow, as_of: AsOfDates
) -> tuple[int, int, int, int]:
    """(b) comps reach at city and ZIP; returns (checkable, city, zip, short)."""
    subjects = [s for group in groups for s in group]
    total = len(subjects)
    gaps = {
        name: sum(name in s.missing for s in subjects)
        for name in ("size", "beds", "type")
    }
    uncheckable = sum(bool(s.missing) for s in subjects)
    no_zip = sum(s.zip5 is None for s in subjects)
    reaches: list[Reach] = []
    # Subtype vocabulary (RESO names, not row data) -> [checkable, still short].
    by_type: dict[str, list[int]] = {}
    t0 = time.perf_counter()
    for s in subjects:
        if s.missing:
            continue
        city_n = count_of(conn, comps_stmt(s, "city", window, as_of))
        zip_n = None
        if city_n < MIN_SAMPLE and s.zip5 is not None:
            zip_n = count_of(conn, comps_stmt(s, "zip", window, as_of))
        reach = Reach(city_n=city_n, zip_n=zip_n)
        reaches.append(reach)
        tally = by_type.setdefault(str(s.subtype), [0, 0])
        tally[0] += 1
        tally[1] += reach.used_n < MIN_SAMPLE
    elapsed = time.perf_counter() - t0
    checkable = len(reaches)
    at_city = sum(r.city_n >= MIN_SAMPLE for r in reaches)
    widened = [r for r in reaches if r.city_n < MIN_SAMPLE]
    at_zip = sum(r.zip_n is not None and r.zip_n >= MIN_SAMPLE for r in widened)
    short = len(widened) - at_zip
    short_no_zip = sum(r.zip_n is None for r in widened)
    zip_below_city = sum(r.zip_n is not None and r.zip_n < r.city_n for r in widened)
    print(f"\n(b) comps reach, {total} subjects ({len(groups)} cities x {PER_CITY})")
    print(
        f"cities sampled {len(groups)}; subjects per city min "
        f"{min(map(len, groups), default=0)} max {max(map(len, groups), default=0)}"
    )
    print("missing fact (cannot be checked) | subjects | share of all")
    for name, n in gaps.items():
        print(f"{name} | {n} | {pct(n, total)}")
    print(f"any of the three | {uncheckable} | {pct(uncheckable, total)}")
    print(f"no five-digit ZIP (any subject) | {no_zip} | {pct(no_zip, total)}")
    print("outcome | subjects | share of checkable | share of all")
    for label, n in (
        ("checkable", checkable),
        (f">= {MIN_SAMPLE} comps in the city", at_city),
        (f"needed the ZIP (city < {MIN_SAMPLE})", len(widened)),
        (f"  reached {MIN_SAMPLE} at the ZIP", at_zip),
        ("  still short after the ZIP", short),
        ("    of which no five-digit ZIP", short_no_zip),
        ("  ZIP count below the city count", zip_below_city),
    ):
        print(f"{label} | {n} | {pct(n, checkable)} | {pct(n, total)}")
    print("comps count | n | min | p25 | p50 | p75 | max")
    city_counts = [r.city_n for r in reaches]
    zip_counts = [r.zip_n for r in widened if r.zip_n is not None]
    used_counts = [r.used_n for r in reaches]
    print(
        f"city level (all checkable) | {len(city_counts)} | {lower_rank(city_counts)}"
    )
    print(f"ZIP level (widened only) | {len(zip_counts)} | {lower_rank(zip_counts)}")
    print(f"level used | {len(used_counts)} | {lower_rank(used_counts)}")
    zero = sum(n == 0 for n in city_counts)
    print(f"city count 0: {zero}; reach statements took {elapsed:.1f} s in total")
    print("subtype | checkable | still short after the ZIP")
    for name, (n, s_n) in sorted(by_type.items(), key=lambda kv: -kv[1][0]):
        print(f"{name} | {n} | {s_n}")
    return checkable, at_city, at_zip, short


def section_timing(
    conn: Any, subjects: list[Subject], window: StatsWindow, as_of: AsOfDates
) -> tuple[float, float]:
    """(c) best-of-RUNS per statement for the largest city's subjects, a measured
    full recommendation, and the 12-statement bound; returns (measured, bound).
    """
    checkable = [s for s in subjects if not s.missing]
    city_best: list[float] = []
    zip_best: list[float] = []
    set_best: list[float] = []
    needs_zip = 0
    for s in checkable:
        city = comps_stmt(s, "city", window, as_of)
        tc = best_of(lambda stmt=city: count_of(conn, stmt))
        city_best.append(tc)
        tz = 0.0
        if s.zip5 is not None:
            zstmt = comps_stmt(s, "zip", window, as_of)
            tz = best_of(lambda stmt=zstmt: count_of(conn, stmt))
            zip_best.append(tz)
        widen = count_of(conn, city) < MIN_SAMPLE and s.zip5 is not None
        needs_zip += widen
        set_best.append(tc + (tz if widen else 0.0))

    def rec() -> None:
        for s in checkable[:RECOMMENDATION]:
            if count_of(conn, comps_stmt(s, "city", window, as_of)) < MIN_SAMPLE:
                if s.zip5 is not None:
                    count_of(conn, comps_stmt(s, "zip", window, as_of))

    measured = best_of(rec)
    bound = RECOMMENDATION * (max(city_best, default=0.0) + max(zip_best, default=0.0))

    def ms(values: list[float]) -> str:
        if not values:
            return "- | - | -"
        ordered = sorted(values)
        return " | ".join(
            f"{1000 * v:.0f}"
            for v in (ordered[0], ordered[len(ordered) // 2], ordered[-1])
        )

    print(f"\n(c) timing, largest city, best of {RUNS} per statement (ms)")
    print(f"checkable subjects {len(checkable)}; needing the ZIP {needs_zip}")
    print("statement | n | min | median | max")
    print(f"city comps (count + ppsf middles) | {len(city_best)} | {ms(city_best)}")
    print(f"ZIP comps (count + ppsf middles) | {len(zip_best)} | {ms(zip_best)}")
    print(f"one subject's set (city, ZIP if needed) | {len(set_best)} | {ms(set_best)}")
    print(
        f"full recommendation, measured ({min(RECOMMENDATION, len(checkable))} "
        f"subjects, as the tool would run them): best {measured:.3f} s"
    )
    print(
        f"full recommendation, bound ({2 * RECOMMENDATION} statements at the "
        f"slowest city and ZIP times): {bound:.3f} s"
    )
    if checkable:
        s = checkable[0]
        print(f"EXPLAIN city: {explain(conn, comps_stmt(s, 'city', window, as_of))}")
        zs = next((x for x in checkable if x.zip5 is not None), None)
        if zs is not None:
            print(f"EXPLAIN ZIP: {explain(conn, comps_stmt(zs, 'zip', window, as_of))}")
    return measured, bound


def decide(checkable: int, short: int, measured: float, bound: float) -> None:
    """Apply the WO-011 decision rules to the numbers and print each outcome."""
    print("\nDecisions")
    worst = max(measured, bound)
    if worst > STOP_S:
        verdict = "stop condition (over 10 s)"
    elif worst >= PROCEED_S:
        verdict = "stop and ask (2-10 s; a composite index is a migration)"
    else:
        verdict = "proceed (under 2 s)"
    print(
        f"Timing: measured {measured:.3f} s, 12-statement bound {bound:.3f} s -> "
        f"{verdict}"
    )
    share = 100 * short / checkable if checkable else 0.0
    reach = "stop condition" if share > 50 else "proceed; not-enough sentence"
    print(
        f"Reach: still short after the ZIP {short}/{checkable} = {share:.1f}% of "
        f"checkable subjects -> {reach}"
    )


def main() -> int:
    """Connect as the reader; print the sections, the decisions, the wall time."""
    started = time.perf_counter()
    conn = connect()
    try:
        as_of = read_asof_dates(conn)
        start, end = as_of.window(MONTHS)
        window = StatsWindow(start=start, end=end, months=MONTHS)
        version = _run(conn, "version", ("SELECT VERSION() AS v", ()))[0]["v"]
        print(f"MySQL {version}; sold as-of {as_of.sold}; active as-of {as_of.active}")
        print(f"window {MONTHS} mo: {start} to {end}; minimum {MIN_SAMPLE} comps")
        section_county(conn)
        groups = draw_sample(conn)
        checkable, _city, _zip, short = section_reach(conn, groups, window, as_of)
        measured, bound = section_timing(conn, groups[0], window, as_of)
        decide(checkable, short, measured, bound)
    finally:
        conn.close()
    print(f"\nspike wall time {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
