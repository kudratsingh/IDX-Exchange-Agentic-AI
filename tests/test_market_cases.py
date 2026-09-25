"""Checks for evals/cases/market_stats.yaml (WO-008), with no model and no database.

A Python reference applies the WO's exclusions to the fixture generator's own sold rows,
recomputing each `stats` literal via idx_agent.domain.market (median, rounding, labels);
ci cases then go through the runner and real tool body, only the SQL replaced by it.
"""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from evals import run as runner

from idx_agent.db import asof as db_asof
from idx_agent.db import market as db_market
from idx_agent.db import pool as db_pool
from idx_agent.domain import market
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import Clarification, MarketStatsRequest, StatsWindow

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals" / "cases" / "market_stats.yaml"
CATEGORY = "market_analytics"
TOOL = "get_market_stats"


def _generator() -> ModuleType:
    """Import tests/fixtures/make_synthetic.py by path (the folder is no package)."""
    path = ROOT / "tests" / "fixtures" / "make_synthetic.py"
    spec = importlib.util.spec_from_file_location("make_synthetic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _generator()


def _sold_rows() -> list[dict[str, Any]]:
    """Every sold row the generator writes, in file order (active rows draw first)."""
    make = GEN.Maker()
    GEN.active_groups(make)
    return [row for _, rows in GEN.sold_groups(make) for row in rows]


ROWS = _sold_rows()
AS_OF = AsOfDates(sold=GEN.SOLD_ASOF, active=GEN.ACTIVE_ASOF.date())


def _close(row: dict[str, Any]) -> date | None:
    """The close date as the generated close_date_d column reads it (None if bad)."""
    value = row["CloseDate"]
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


EARLIEST = min(d for r in ROWS if (d := _close(r)) is not None and d <= AS_OF.active)


def _load() -> tuple[list[runner.Case], list[runner.LoadError]]:
    """Load only market_stats.yaml, through the runner's own loader."""
    cases, errors = runner.load_cases(CASES_FILE.parent)
    mine = [c for c in cases if c.source == CASES_FILE.name]
    return mine, [e for e in errors if e.source == CASES_FILE.name]


CASES, LOAD_ERRORS = _load()
CI = [c for c in CASES if c.suite == "ci"]
LOCAL = [c for c in CASES if c.suite == "local"]
STATS = [c for c in CI if c.check == "stats_exact"]
CLARIFY = [c for c in CI if c.check == "clarification"]
BY_ID = {c.id: c for c in CASES}


# --- the Python reference ------------------------------------------------------------


def _dec(value: Any) -> Decimal:
    """A stored double as the Decimal it was written as (1040001.6, no binary noise)."""
    return Decimal(repr(value))


def _window(months: int) -> StatsWindow:
    """AsOfDates.window, or the data's coverage when it would start too early."""
    start, end = AS_OF.window(months)
    if start >= EARLIEST:
        return StatsWindow(start=start, end=end, months=months)
    used = market.coverage_months(EARLIEST, AS_OF.sold)
    return StatsWindow(start=EARLIEST, end=end, months=used)


def _in_place(row: dict[str, Any], request: MarketStatsRequest) -> bool:
    """City equality, or the five-digit prefix of the postal code (ZIP+4 kept)."""
    if request.city is not None:
        return row["City"] == request.city
    return str(row["PostalCode"] or "").startswith(str(request.postal_code))


def _sample(
    request: MarketStatsRequest, window: StatsWindow, subtype: str | None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Kept sales and per-rule counts, the WO's exclusions in order; subtype None
    keeps every subtype (the mix). Repeated keys keep the latest close, then the
    higher close price, then the higher list price."""
    counts = dict.fromkeys(market.EXCLUSION_RULES, 0)
    candidates = []
    for row in ROWS:
        if not _in_place(row, request):
            continue
        if subtype is not None and row["PropertySubType"] != subtype:
            continue
        close = _close(row)
        if close is None:
            counts["unreadable_close_date"] += 1
        elif close > AS_OF.active:
            counts["after_active_asof"] += 1
        elif not window.start <= close <= window.end:
            continue
        elif row["PurchaseContractDate"] and close < row["PurchaseContractDate"]:
            counts["close_before_contract"] += 1
        elif min(row["ClosePrice"], row["ListPrice"]) < market.PRICE_FLOOR:
            counts["price_under_floor"] += 1
        else:
            candidates.append(row)
    # A NULL ListingKey is never a repeat (as in the SQL): every keyless row is kept.
    keyless = [row for row in candidates if row["ListingKey"] is None]
    best: dict[int, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for row in candidates:
        if row["ListingKey"] is None:
            continue
        rank = (_close(row), row["ClosePrice"], row["ListPrice"])
        if row["ListingKey"] not in best or rank > best[row["ListingKey"]][0]:
            best[row["ListingKey"]] = (rank, row)
    kept = [row for _, row in best.values()] + keyless
    counts["duplicate_listing_key"] = len(candidates) - len(kept)
    counts["area_under_floor"] = sum(not _has_area(r) for r in kept)
    counts["dom_missing"] = sum(not _has_dom(r) for r in kept)
    return kept, counts


def _has_area(row: dict[str, Any]) -> bool:
    return row["LivingArea"] is not None and row["LivingArea"] >= market.AREA_FLOOR


def _has_dom(row: dict[str, Any]) -> bool:
    return row["DaysOnMarket"] is not None and row["DaysOnMarket"] >= 0


def _metrics(kept: list[dict[str, Any]]) -> dict[str, list[Decimal]]:
    """Each metric's values over the kept sales, exact in Decimal."""
    sized = [r for r in kept if _has_area(r)]
    return {
        "price": [_dec(r["ClosePrice"]) for r in kept],
        "ratio": [_dec(r["ClosePrice"]) / _dec(r["ListPrice"]) for r in kept],
        "dom": [Decimal(r["DaysOnMarket"]) for r in kept if _has_dom(r)],
        "ppsf": [_dec(r["ClosePrice"]) / _dec(r["LivingArea"]) for r in sized],
    }


def _mix(kept: list[dict[str, Any]], subtype: str) -> Counter[str | None]:
    """Sale counts of the other subtypes (None is a sale with no subtype)."""
    return Counter(
        r["PropertySubType"] for r in kept if r["PropertySubType"] != subtype
    )


def _month(row: dict[str, Any]) -> str:
    close = _close(row)
    assert close is not None
    return close.strftime("%Y-%m")


def reference_stats(request: MarketStatsRequest) -> dict[str, Any]:
    """MarketStats fields in JSON form, computed with the domain functions over the
    full value lists (not the SQL middles)."""
    window = _window(request.months)
    subtype = request.property_subtype or market.DEFAULT_SUBTYPE
    kept, counts = _sample(request, window, subtype)
    low = len(kept) < market.MIN_SAMPLE
    out: dict[str, Any] = {
        "geography": request.geography().model_dump(mode="json"),
        "property_subtype": subtype,
        "window": window.model_dump(mode="json"),
        "as_of": AS_OF.sold.isoformat(),
        "sample_count": len(kept),
        "low_sample": low,
        "exclusions_applied": [f"{k}: {counts[k]}" for k in market.EXCLUSION_RULES],
        "trend": [],
    }
    names = ("median_close_price", "median_price_per_sqft", "median_dom", "dom_band")
    out.update(dict.fromkeys(names))
    out.update(sale_to_list_ratio=None, sale_to_list_reading=None, market_lean=None)
    if low:
        return out
    values = _metrics(kept)
    ratio = market.round_ratio(market.median(values["ratio"]))
    out.update(
        median_close_price=float(market.round_dollars(market.median(values["price"]))),
        sale_to_list_ratio=float(ratio),
        sale_to_list_reading=market.sale_to_list_reading(ratio),
    )  # fmt: skip
    # Days and price per sqft need METRIC_MIN_SAMPLE usable values each.
    if len(values["ppsf"]) >= market.METRIC_MIN_SAMPLE:
        ppsf = market.round_dollars(market.median(values["ppsf"]))
        out.update(median_price_per_sqft=float(ppsf))
    if len(values["dom"]) >= market.METRIC_MIN_SAMPLE:
        days = market.median(values["dom"])
        out.update(
            median_dom=float(days),
            dom_band=market.dom_band(days),
            market_lean=market.market_lean(ratio, days),
        )
    for key in market.month_keys(window):
        prices = [_dec(r["ClosePrice"]) for r in kept if _month(r) == key]
        median = None
        if len(prices) >= market.MONTH_MIN:
            median = float(market.round_dollars(market.median(prices)))
        out["trend"].append(
            {"month": key, "sample_count": len(prices), "median_close_price": median}
        )
    return out


def _request(case: runner.Case) -> MarketStatsRequest:
    request = MarketStatsRequest.from_input(case.input_filters or {})
    assert isinstance(request, MarketStatsRequest), case.id
    return request


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# --- the case file ---------------------------------------------------------------


def test_file_loads_with_no_errors() -> None:
    assert LOAD_ERRORS == []
    assert all(c.id.startswith("market-") for c in CASES)
    assert {c.category for c in CASES} == {CATEGORY}
    assert {c.tool for c in CASES} == {TOOL}
    # About 14 ci cases and the WO's 5 phrasing cases, each with the user's words.
    assert len(CI) >= 14 and len(STATS) >= 10
    assert len(LOCAL) == 5
    assert all(c.input and c.check == "filters_exact" for c in LOCAL)


def test_fixture_bound_cases_are_marked_fixture_only() -> None:
    """Exact numbers and the count-bearing replies hold only for the fixture rows;
    validation and the absence check hold on any database."""
    fixture = {c.id for c in CASES if c.database == "fixture"}
    bound = {c.id for c in CI if c.check in ("stats_exact", "regex")}
    assert fixture == bound
    assert all(c.database == "any" for c in CLARIFY + LOCAL)
    assert BY_ID["market-ci-021"].database == "any"


def test_the_generator_holds_the_hand_valued_rows() -> None:
    # 48 through WO-010, plus WO-011's 4 Bradbury sales (appended last).
    assert len(ROWS) == 52 and EARLIEST == date(2026, 3, 18)
    keys = {r["ListingKey"] for r in ROWS}
    for group in (GEN.MONROVIA_SFR, GEN.MONROVIA_CONDO, GEN.DUARTE_SFR):
        assert {row[0] for row in group} <= keys
    # The 1-month window starts on 2026-08-18: that sale is in, the 08-17 one is out.
    start, end = AS_OF.window(1)
    closes = {r[1] for r in GEN.MONROVIA_SFR}
    assert start == date(2026, 8, 18) and {start, end} <= closes
    assert date(2026, 8, 17) in closes


@pytest.mark.parametrize("case", STATS, ids=lambda c: c.id)
def test_stats_literals_match_the_reference(case: runner.Case) -> None:
    """Requirement 11: each hand-computed literal equals the reference math."""
    derived = reference_stats(_request(case))
    for field, expected in case.expect["stats"].items():
        assert _plain(expected) == derived[field], f"{case.id}: {field}"


def test_rounding_once_at_the_end_is_what_the_cases_pin() -> None:
    """The fractional price and the condo half make rounding order visible."""
    three = _request(BY_ID["market-ci-006"])
    kept, _ = _sample(three, _window(3), market.DEFAULT_SUBTYPE)
    prices = _metrics(kept)["price"]
    assert market.round_dollars(market.median(prices)) == 1_050_001
    first = market.median([market.round_dollars(p) for p in prices])
    assert market.round_dollars(first) == 1_050_002
    condo = _request(BY_ID["market-ci-002"])
    kept, _ = _sample(condo, _window(6), "Condominium")
    middle = market.median(_metrics(kept)["price"])
    assert middle == Decimal("593750.5") and market.round_dollars(middle) == 593_750


def test_the_reference_keeps_every_keyless_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two sales with no ListingKey stay two sales (the SQL's `OR keyless`)."""
    request = MarketStatsRequest(city="Monrovia", property_subtype="Condominium")
    kept, counts = _sample(request, _window(6), "Condominium")
    copies = [dict(kept[0], ListingKey=None) for _ in range(2)]
    monkeypatch.setitem(globals(), "ROWS", ROWS + copies)
    more, more_counts = _sample(request, _window(6), "Condominium")
    assert len(more) == len(kept) + 2
    assert more_counts["duplicate_listing_key"] == counts["duplicate_listing_key"]


def test_the_default_discloses_the_other_subtypes() -> None:
    request = _request(BY_ID["market-ci-004"])
    kept, _ = _sample(request, _window(6), None)
    assert _mix(kept, market.DEFAULT_SUBTYPE) == {"Condominium": 6, None: 1}
    pattern = BY_ID["market-ci-004"].expect["pattern"]
    assert re.search(pattern, "types sold here: Condominium 6, unknown type 1")
    assert not re.search(pattern, "types sold here: Condominium 4, unknown type 1")


def test_not_enough_comps_counts() -> None:
    duarte = MarketStatsRequest(city="Duarte")
    alhambra = MarketStatsRequest(city="Alhambra")
    assert len(_sample(duarte, _window(6), market.DEFAULT_SUBTYPE)[0]) == 3
    assert len(_sample(alhambra, _window(6), None)[0]) == 0
    pattern = BY_ID["market-ci-012"].expect["pattern"]
    assert re.search(pattern, "Not enough comps in Duarte: 3 sales")
    assert not re.search(pattern, "Not enough comps in Duarte: 13 sales")


@pytest.mark.parametrize("case", CLARIFY, ids=lambda c: c.id)
def test_clarification_cases_through_from_input(case: runner.Case) -> None:
    got = MarketStatsRequest.from_input(case.input_filters or {})
    want = case.expect["clarification"]
    assert isinstance(got, Clarification), case.id
    assert (got.field, got.reason) == (want["field"], want["reason"])


@pytest.mark.parametrize("case", LOCAL, ids=lambda c: c.id)
def test_local_expectations_are_valid_requests(case: runner.Case) -> None:
    got = MarketStatsRequest.from_input(case.expect["filters"])
    assert isinstance(got, MarketStatsRequest), case.id
    assert got.model_dump(exclude_defaults=True) == case.expect["filters"]


# --- the ci cases through the runner and the real tool body ----------------------


def _middles(values: list[Decimal]) -> tuple[Decimal, ...]:
    """The one or two middle values of the ordered sample, as the SQL returns them."""
    ordered, n = sorted(values), len(values)
    if not n:
        return ()
    return (ordered[n // 2],) if n % 2 else (ordered[n // 2 - 1], ordered[n // 2])


def fake_aggregates(
    request: MarketStatsRequest, window: StatsWindow, as_of: AsOfDates, conn: Any
) -> market.MarketAggregates:
    """fetch_market_aggregates computed in Python from the generator's rows."""
    assert as_of == AS_OF
    subtype = request.property_subtype or market.DEFAULT_SUBTYPE
    kept, counts = _sample(request, window, subtype)
    values = _metrics(kept)
    months = Counter(_month(r) for r in kept)
    mix = _mix(_sample(request, window, None)[0], subtype)
    return market.MarketAggregates(
        sample_count=len(kept),
        price_middles=_middles(values["price"]),
        dom_middles=_middles(values["dom"]),
        dom_sample=len(values["dom"]),
        ratio_middles=_middles(values["ratio"]),
        ppsf_middles=_middles(values["ppsf"]),
        ppsf_sample=len(values["ppsf"]),
        months=tuple(
            market.MonthAggregate(
                key=key,
                count=count,
                price_middles=_middles(
                    [_dec(r["ClosePrice"]) for r in kept if _month(r) == key]
                ),
            )
            for key, count in sorted(months.items())
        ),
        subtype_mix=tuple(sorted(mix.items(), key=lambda i: (-i[1], i[0] or "~"))),
        exclusions=tuple((k, counts[k]) for k in market.EXCLUSION_RULES),
    )


def test_ci_cases_pass_through_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the SQL is replaced: validation, window fallback, math, labels, the card,
    and the runner's checks are the real code."""
    monkeypatch.setattr(db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(db_pool, "connect", lambda *a, **k: object())
    monkeypatch.setattr(db_asof, "get_asof_dates", lambda conn: AS_OF)
    monkeypatch.setattr(db_asof, "get_earliest_close", lambda conn: EARLIEST)
    monkeypatch.setattr(db_market, "fetch_market_aggregates", fake_aggregates)
    ctx = runner.RunContext(require_database=True)
    records = [runner.run_case(case, ctx) for case in CI]
    failed = {r["id"]: r["detail"] for r in records if r["result"] != runner.PASS}
    assert failed == {}
