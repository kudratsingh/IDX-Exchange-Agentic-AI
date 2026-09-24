"""Integration tests for the db layer against the local MySQL (`@pytest.mark.db`).

Skipped unless MYSQL_HOST is set. Other MYSQL_* values missing from the environment
come from .env through `pool.dotenv_values`, the same path the MCP server takes; no
value is printed or logged. Run with: MYSQL_HOST=localhost pytest -q -m db
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import pymysql
import pytest

from idx_agent.db import asof
from idx_agent.db.listings import (
    MAX_ROWS,
    count_active_listings,
    search_active_listings,
)
from idx_agent.db.pool import DbConfig, connect
from idx_agent.domain.models import Listing, PropertySearchFilters
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST, check_column

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def conn() -> Iterator[Any]:
    """One reader connection for the module, closed afterwards.

    `DbConfig.from_env()` takes the environment first and fills the gaps from
    `pool.dotenv_values()`, so this test reads .env exactly as the server does.
    """
    connection = connect(DbConfig.from_env())
    try:
        yield connection
    finally:
        connection.close()


def _pasadena(**extra: Any) -> PropertySearchFilters:
    """The WO-004 example: 3+ beds in Pasadena at or under 1.5M."""
    return PropertySearchFilters(
        city="Pasadena", min_beds=3, max_price=1_500_000, **extra
    )


def test_pasadena_returns_one_to_five_listings_with_the_expected_shape(conn):
    outcome = search_active_listings(_pasadena(), conn)
    assert 1 <= len(outcome.listings) <= 5
    for item in outcome.listings:
        assert isinstance(item, Listing)
        assert item.city == "Pasadena"
        assert item.bedrooms is not None and item.bedrooms >= 3
        assert item.list_price <= 1_500_000
        assert item.status == "Active"
        keys = set(item.model_dump())
        assert not keys & (DENYLIST | AGENT_CONTACT)
    prices = [item.list_price for item in outcome.listings]
    assert prices == sorted(prices)


def test_page_two_differs_from_page_one(conn):
    first = search_active_listings(_pasadena(page=1), conn).listings
    second = search_active_listings(_pasadena(page=2), conn).listings
    assert first and second
    first_ids = {item.listing_id for item in first}
    assert first_ids.isdisjoint(item.listing_id for item in second)


def test_the_count_covers_every_page_of_the_same_search(conn):
    """WO-006: the COUNT uses the search's WHERE, so it is at least two pages here
    and matches a page of 50 when the total fits in one. Skipped rows count too:
    the COUNT sees them, the listings do not."""
    total = count_active_listings(_pasadena(), conn)
    assert total >= 6
    outcome = search_active_listings(_pasadena(limit=MAX_ROWS), conn)
    assert len(outcome.listings) + outcome.skipped_rows == min(total, MAX_ROWS)


def test_same_query_twice_returns_the_same_page(conn):
    one = search_active_listings(_pasadena(page=2), conn).listings
    two = search_active_listings(_pasadena(page=2), conn).listings
    assert [i.listing_id for i in one] == [i.listing_id for i in two]


def test_a_request_for_500_returns_50_with_a_warning(conn):
    filters = PropertySearchFilters.model_construct(city="Los Angeles", limit=500)
    outcome = search_active_listings(filters, conn)
    assert len(outcome.listings) + outcome.skipped_rows == MAX_ROWS
    assert any(str(MAX_ROWS) in warning for warning in outcome.warnings)


def _latest_modification_day(conn: Any) -> date:
    """The date of MAX(ModificationTimestamp), read with an allowlisted column."""
    column = check_column("rets_property", "ModificationTimestamp")
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT MAX({column}) AS latest FROM rets_property")
        latest = cursor.fetchone()["latest"]
    if isinstance(latest, datetime):
        return latest.date()
    return date.fromisoformat(str(latest)[:10])


def test_asof_dates_follow_the_data_not_a_fixed_day(conn):
    asof.clear_asof_cache()
    try:
        dates = asof.get_asof_dates(conn)
        assert dates.active == _latest_modification_day(conn)
        # Sold is bounded by active, so a typo year in close dates never wins.
        assert dates.sold <= dates.active
        assert asof.get_asof_dates(conn) is dates
    finally:
        asof.clear_asof_cache()


def test_the_session_refuses_writes(conn):
    # Inserts zero rows even if it were allowed; it must fail on grants or the
    # read-only session before anything runs.
    sql = (
        "INSERT INTO rets_property (L_City) "
        "SELECT L_City FROM rets_property WHERE 1 = 0"
    )
    with pytest.raises(pymysql.MySQLError), conn.cursor() as cursor:
        cursor.execute(sql)
