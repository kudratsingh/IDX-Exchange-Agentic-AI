"""Fixture-backed SQL checks, run by existing CI with the SELECT-only reader."""

from datetime import timedelta

import pytest

from idx_agent.alerts.query import fetch_new
from idx_agent.db import asof, pool
from idx_agent.db.analytics import fetch_analytics
from idx_agent.domain.alerts import SavedSearch
from idx_agent.domain.analytics import build_analytics
from idx_agent.domain.models import (
    MarketStatsRequest,
    PropertySearchFilters,
    StatsWindow,
)

pytestmark = pytest.mark.db


def test_hand_valued_fixture_means_and_usable_counts():
    from tests.test_db_integration import _require_fixture

    conn = pool.connect()
    try:
        _require_fixture(conn)
        dates = asof.get_asof_dates(conn)
        window = StatsWindow(start=dates.window(6)[0], end=dates.sold, months=6)
        values = fetch_analytics(
            MarketStatsRequest(city="Monrovia"), window, dates, conn
        )
        result = build_analytics(*values, window, dates)
        # Independent arithmetic over the seven hand-valued sales documented in
        # tests/fixtures/make_synthetic.py, excluding the old duplicate and bad rows.
        assert result.sold_count == 7
        assert result.mean_close_price == 1_037_143.23
        assert values[0]["dom_n"] == 6 and values[0]["ppsf_n"] == 6
        assert result.mean_dom is None and result.mean_price_per_sqft is None
        august = next(m for m in result.months if m.month == "2026-08")
        assert august.mean_close_price == 1_011_667.2
        assert result.active_count == 5
    finally:
        conn.close()


def test_extended_aggregates_use_bounded_reader_queries():
    conn = pool.connect()
    try:
        dates = asof.get_asof_dates(conn)
        window = StatsWindow(start=dates.window(6)[0], end=dates.sold, months=6)
        values = fetch_analytics(
            MarketStatsRequest(city="Pasadena"), window, dates, conn
        )
        result = build_analytics(*values, window, dates)
        assert result.sold_count >= 0 and result.active_count >= 0
        assert sum(m.sample_count for m in result.months) == result.sold_count
        assert len(result.months) <= 25
    finally:
        conn.close()


def test_new_listing_query_returns_distinct_public_cards_within_cap():
    from datetime import UTC, datetime

    conn = pool.connect()
    try:
        dates = asof.get_asof_dates(conn)
        saved = SavedSearch(
            id="a" * 32,
            sender_key="b" * 64,
            filters=PropertySearchFilters(city="Pasadena"),
            created_at=datetime.now(UTC),
            checked_as_of=dates.active - timedelta(days=30),
        )
        count, listings = fetch_new(saved, dates.active, conn)
        assert count >= len(listings) and len(listings) <= 10
        assert len({item.listing_key for item in listings}) == len(listings)
        assert all(
            item.city == "Pasadena" and item.remarks is None for item in listings
        )
    finally:
        conn.close()
