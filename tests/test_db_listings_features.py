"""Feature-scoped listing SQL (WO-021): bound keys, snapshot freshness, and no change
to searches without features. Pure builders plus fake cursors; no database."""

import pytest

from idx_agent.db import listings as db
from idx_agent.domain.models import PropertySearchFilters

WATERMARK = "2026-09-18 06:58:44"


def filters(**extra):
    value = PropertySearchFilters.from_input({"city": "Pasadena", **extra})
    assert isinstance(value, PropertySearchFilters)
    return value


def scope(*keys):
    return db.FeatureScope(keys=tuple(keys), watermark=WATERMARK)


def test_searches_without_features_build_identical_sql():
    plain = filters(min_beds=3)
    assert db.build_search_sql(plain) == db.build_search_sql(plain, None)
    assert db.build_count_sql(plain) == db.build_count_sql(plain, None)
    assert "ModificationTimestamp" not in db.build_search_sql(plain).sql


def test_scope_binds_keys_and_keeps_only_unchanged_listings():
    query = db.build_search_sql(filters(), scope("101", "102"))
    assert "L_ListingID IN (%s, %s) AND ModificationTimestamp <= %s" in query.sql
    assert query.params[-5:] == ("101", "102", WATERMARK, 5, 0)
    assert "101" not in query.sql
    assert query.sql.count("%s") == len(query.params)


def test_count_uses_the_same_scope():
    query = db.build_count_sql(filters(), scope("101"))
    assert "ModificationTimestamp <= %s" in query.sql
    assert query.params[-2:] == ("101", WATERMARK)


def test_changed_count_selects_listings_changed_after_the_snapshot():
    query = db.build_changed_count_sql(filters(), scope("101"))
    assert "ModificationTimestamp > %s" in query.sql
    assert query.sql.startswith("SELECT COUNT(*)")


def test_freshness_returns_counts_only():
    query = db.build_freshness_sql(WATERMARK)
    assert query.sql.startswith("SELECT COUNT(*) AS total, ")
    assert query.params[0] == WATERMARK
    assert "L_Remarks" not in query.sql


@pytest.mark.parametrize(
    "keys",
    [(), ("10a",), (101,), ("1",) * (db.MAX_FEATURE_KEYS + 1)],
)
def test_bad_or_oversized_scopes_are_refused(keys):
    with pytest.raises(ValueError):
        db.build_search_sql(filters(), db.FeatureScope(keys=keys, watermark=WATERMARK))


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, rows):
        self.last = Cursor(rows)

    def cursor(self):
        return self.last


def test_executors_read_counts():
    assert db.fetch_freshness(WATERMARK, Conn([{"total": 100, "changed": 4}])) == (
        100,
        4,
    )
    assert db.fetch_freshness(WATERMARK, Conn([(10, None)])) == (10, 0)
    assert (
        db.count_changed_since(filters(), scope("1"), Conn([{"total_matches": 2}])) == 2
    )
    conn = Conn([{"total_matches": 7}])
    assert db.count_active_listings(filters(), conn, scope("1")) == 7
    assert "ModificationTimestamp <= %s" in conn.last.executed[0][0]
    with pytest.raises(ValueError):
        db.fetch_freshness(WATERMARK, Conn([]))
