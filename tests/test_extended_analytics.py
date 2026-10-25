"""Means, sample floors, calendar comparisons and the actual extended MCP path."""

from datetime import date
from decimal import Decimal

import pytest
from tests.test_mcp_market import fake_db as fake_db

from idx_agent.db import analytics as db
from idx_agent.db.market import RowCapExceeded
from idx_agent.domain.analytics import build_analytics, format_analytics
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, StatsWindow
from idx_agent.mcp_server import server

DATES = AsOfDates(active=date(2026, 4, 1), sold=date(2026, 3, 31))
WINDOW = StatsWindow(start=date(2026, 1, 1), end=date(2026, 3, 31), months=3)


def row(month, price=100_000, ppsf=500, n=10):
    return dict(
        ym=month,
        n=n,
        mean_price=Decimal(price),
        dom_n=n,
        mean_dom=Decimal("21.25"),
        ppsf_n=n,
        median_ppsf=Decimal(ppsf),
        mean_ppsf=Decimal(ppsf),
    )


def totals(n=30):
    return dict(
        n=n,
        mean_price=Decimal(150_000),
        dom_n=n,
        mean_dom=Decimal("21.25"),
        ppsf_n=n,
        mean_ppsf=Decimal("551.67"),
    )


def test_means_and_monthly_changes_are_deterministic():
    rows = [
        row("2026-01", 100_000, 500),
        row("2026-02", 200_000, 550),
        row("2026-03", 150_000, 605),
    ]
    a = build_analytics(totals(), rows, 42, WINDOW, DATES)
    assert a.mean_close_price == 150_000 and a.mean_dom == 21.25
    assert a.active_count == 42 and a.sold_count == 30
    assert [m.price_mom_pct for m in a.months] == [None, 100, -25]
    assert [m.ppsf_mom_pct for m in a.months] == [None, 10, 10]
    assert all(m.price_yoy_pct is None for m in a.months)
    assert "Year-over-year comparison unavailable" in " ".join(a.notes)


def test_partial_months_never_compare_to_complete_months():
    window = WINDOW.model_copy(
        update={"start": date(2026, 1, 18), "end": date(2026, 3, 17)}
    )
    a = build_analytics(
        totals(), [row("2026-01"), row("2026-02"), row("2026-03")], 1, window, DATES
    )
    assert [m.partial for m in a.months] == [True, False, True]
    assert all(m.price_mom_pct is None and m.ppsf_mom_pct is None for m in a.months)


def test_missing_month_is_zero_and_cannot_be_compared():
    a = build_analytics(totals(20), [row("2026-01"), row("2026-03")], 0, WINDOW, DATES)
    assert a.months[1].sample_count == 0 and a.months[1].mean_close_price is None
    assert a.months[2].price_mom_pct is None


def test_yoy_only_when_both_full_months_and_sufficient_history():
    dates = AsOfDates(active=date(2026, 3, 1), sold=date(2026, 2, 28))
    window = StatsWindow(start=date(2025, 2, 1), end=dates.sold, months=13)
    a = build_analytics(
        totals(20),
        [row("2025-02", 100_000, 500), row("2026-02", 110_000, 600)],
        0,
        window,
        dates,
    )
    assert a.months[-1].price_yoy_pct == 10 and a.months[-1].ppsf_yoy_pct == 20
    assert a.months[-1].price_mom_pct is None


@pytest.mark.parametrize("n", [0, 2, 4, 5, 9])
def test_sample_floors(n):
    a = build_analytics(totals(n), [row("2026-01", n=n)], 5, WINDOW, DATES)
    assert a.mean_close_price is None if n < 5 else a.mean_close_price is not None
    assert a.mean_dom is None and a.mean_price_per_sqft is None
    assert all(m.median_price_per_sqft is None for m in a.months)
    if n < 5:
        assert all(m.mean_close_price is None for m in a.months)


def test_duplicate_outside_and_inconsistent_months_refused():
    for rows in ([row("2026-01"), row("2026-01")], [row("2025-12")], [row("2026-01")]):
        with pytest.raises(ValueError):
            build_analytics(totals(), rows, 1, WINDOW, DATES)


def test_sql_bound_safe_deduplicated_and_bounded():
    request = MarketStatsRequest(city="Pasadena", include_extended=True)
    queries = db.build_analytics_sql(request, WINDOW, DATES)
    assert len(queries) == 3
    for sql, params in queries:
        assert sql.count("%s") == len(params)
        assert "Pasadena" not in sql and "SELECT *" not in sql
        assert "L_Remarks" not in sql and "UnparsedAddress" not in sql
    assert "ROW_NUMBER()" in queries[0][0]
    assert "COUNT(DISTINCT L_ListingID)" in queries[2][0]
    assert queries[1][1][-1] == 25
    with pytest.raises(ValueError):
        db.build_analytics_sql(
            request, WINDOW.model_copy(update={"end": date(2026, 4, 2)}), DATES
        )


def test_aggregate_executor_refuses_unbounded_result():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, *_):
            pass

        def fetchall(self):
            return [{}] * 51

    class Conn:
        def cursor(self):
            return Cursor()

    with pytest.raises(RowCapExceeded):
        db.fetch_analytics(MarketStatsRequest(city="Pasadena"), WINDOW, DATES, Conn())


def test_extended_mcp_uses_same_sample_and_public_snapshot(fake_db, monkeypatch):
    def fetch(request, window, dates, conn):
        return totals(11), [row("2026-04", n=11)], 42

    monkeypatch.setattr(db, "fetch_analytics", fetch)
    payload = server.get_market_stats(city="Pasadena", include_extended=True)
    assert payload["ok"], payload
    a = payload["data"]["analytics"]
    assert a["active_count"] == 42 and a["sold_count"] == 11
    assert (
        "Mean sale price" in payload["message"]
        and "Year-over-year comparison unavailable" in payload["message"]
    )
    assert payload["provenance"]["tables"] == ["california_sold", "rets_property"]
    assert payload["data"]["median_close_price"] == 1_050_000


def test_standard_mcp_never_fetches_extra_queries(fake_db, monkeypatch):
    def fail(*_):
        raise AssertionError("unexpected extra queries")

    monkeypatch.setattr(db, "fetch_analytics", fail)
    assert server.get_market_stats(city="Pasadena")["ok"]


def test_formatter_has_counts_and_no_forecast():
    a = build_analytics(
        totals(), [row("2026-01"), row("2026-02"), row("2026-03")], 5, WINDOW, DATES
    )
    from types import SimpleNamespace

    text = format_analytics(SimpleNamespace(analytics=a))
    assert "Active inventory: 5 as of 2026-04-01" in text
    assert "30 closed sales" in text and "mean DOM 21.25" in text
    assert "will" not in text
