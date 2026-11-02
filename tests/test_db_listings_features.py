"""Feature-scoped listing SQL (WO-021): bound keys, snapshot freshness, and no change
to searches without features. Pure builders plus fake cursors; no database."""

import sqlite3

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
    assert (
        "L_ListingID IN (%s, %s) AND NOT EXISTS (SELECT 1 FROM rets_property"
        in query.sql
    )
    assert "newer.ModificationTimestamp > %s" in query.sql
    assert query.params[-5:] == ("101", "102", WATERMARK, 5, 0)
    assert "101" not in query.sql
    assert query.sql.count("%s") == len(query.params)


def test_count_uses_the_same_scope():
    query = db.build_count_sql(filters(), scope("101"))
    assert "NOT EXISTS" in query.sql
    assert query.params[-2:] == ("101", WATERMARK)


def test_changed_count_selects_listings_changed_after_the_snapshot():
    query = db.build_changed_count_sql(filters(), scope("101"))
    assert "AND EXISTS (SELECT 1" in query.sql and "NOT EXISTS" not in query.sql
    assert query.sql.startswith("SELECT COUNT(DISTINCT L_ListingID)")


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
    assert "NOT EXISTS" in conn.last.executed[0][0]
    with pytest.raises(ValueError):
        db.fetch_freshness(WATERMARK, Conn([]))


# The built statements, run on a real SQL engine (SQLite) with every listing column.
def _engine(rows):
    from idx_agent.domain.fieldmap import listing_columns

    engine = sqlite3.connect(":memory:")
    engine.row_factory = sqlite3.Row
    columns = [*listing_columns(), "ModificationTimestamp"]
    engine.execute(f"CREATE TABLE rets_property ({', '.join(columns)})")
    marks = ", ".join("?" * len(columns))
    for key, modified in rows:
        values = dict.fromkeys(columns)
        values.update(
            L_ListingID=key,
            L_DisplayId=f"D{key}",
            L_City="Pasadena",
            L_SystemPrice=1_000_000,
            StandardStatus="Active",
            ModificationTimestamp=modified,
        )
        engine.execute(
            f"INSERT INTO rets_property VALUES ({marks})", [values[c] for c in columns]
        )
    return engine


def _run(engine, query):
    return engine.execute(query.sql.replace("%s", "?"), query.params).fetchall()


def test_an_older_row_of_a_changed_listing_never_matches():
    engine = _engine(
        [
            ("101", "2026-09-01 00:00:00"),  # unchanged listing
            ("102", "2026-09-01 00:00:00"),  # older row of a listing ...
            ("102", "2026-10-01 00:00:00"),  # ... that changed after the snapshot
            ("103", "2026-10-01 00:00:00"),  # changed, one row
        ]
    )
    feature_scope = scope("101", "102", "103")
    rows = _run(engine, db.build_search_sql(filters(), feature_scope))
    assert [r["L_ListingID"] for r in rows] == ["101"]
    assert _run(engine, db.build_count_sql(filters(), feature_scope))[0][0] == 1
    changed = _run(engine, db.build_changed_count_sql(filters(), feature_scope))
    assert changed[0][0] == 2


def test_listings_outside_the_scope_are_never_matched():
    engine = _engine([("101", "2026-09-01 00:00:00"), ("104", "2026-09-01 00:00:00")])
    rows = _run(engine, db.build_search_sql(filters(), scope("101")))
    assert [r["L_ListingID"] for r in rows] == ["101"]
    plain = _run(engine, db.build_search_sql(filters()))
    assert sorted(r["L_ListingID"] for r in plain) == ["101", "104"]


def test_a_listing_with_an_unknown_change_time_never_matches():
    """A NULL timestamp is unknown, so the listing counts as changed (fail closed)."""
    engine = _engine(
        [
            ("101", "2026-09-01 00:00:00"),
            ("105", None),  # only row has no change time
            ("106", "2026-09-01 00:00:00"),  # an older row ...
            ("106", None),  # ... and a row with no change time
        ]
    )
    feature_scope = scope("101", "105", "106")
    rows = _run(engine, db.build_search_sql(filters(), feature_scope))
    assert [r["L_ListingID"] for r in rows] == ["101"]
    assert _run(engine, db.build_count_sql(filters(), feature_scope))[0][0] == 1
    changed = _run(engine, db.build_changed_count_sql(filters(), feature_scope))
    assert changed[0][0] == 2
