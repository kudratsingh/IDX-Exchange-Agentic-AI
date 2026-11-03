"""Refresh preflight classification (WO-021): every class, fail-closed ambiguity, and
the bounded keyset pages on an SQLite stand-in. Synthetic keys only; no database."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from idx_agent.db import refresh_pages as pages
from idx_agent.enrichment import refresh_preflight as rp

WATERMARK = datetime(2026, 9, 18, 6, 58, 44)
AS_OF = datetime(2026, 10, 1, 0, 0, 0)
BEFORE = datetime(2026, 9, 1, 0, 0, 0)
AFTER = datetime(2026, 9, 20, 0, 0, 0)


def row(modified=BEFORE, active=True):
    return rp.ListingRow(modified=modified, active=active)


def classify(store, rows, watermark=WATERMARK, as_of=AS_OF):
    return rp.classify_inventory(store, watermark, rows, as_of)


def test_every_class_and_exactly_one_entry_per_in_scope_id():
    store = ["100", "101", "102", "103", "104"]
    rows = {
        "100": [row()],  # unchanged
        "101": [row(AFTER)],  # changed
        "102": [row(active=False)],  # no longer active
        # "103" is a store key absent from the source: no longer active
        "104": [row(None)],  # ambiguous: unknown change time
        "200": [row(AFTER)],  # new
        "201": [row()],  # never extracted
        "202": [row(active=False)],  # inactive and never stored: out of scope
    }
    inv = classify(store, rows)
    got = {key: (e.cls, e.reason) for key, e in inv.entries.items()}
    assert got == {
        "100": ("unchanged", None),
        "101": ("changed", None),
        "102": ("no_longer_active", None),
        "103": ("no_longer_active", rp.ABSENT),
        "104": ("ambiguous", rp.UNKNOWN_TIMESTAMP),
        "200": ("new", None),
        "201": ("never_extracted", None),
    }
    assert inv.out_of_scope == 1
    summary = rp.summarize(inv)
    assert summary["classes"] == {c: 1 for c in rp.CLASSES} | {"no_longer_active": 2}
    assert summary["usable"] == 1 == summary["classes"]["unchanged"]
    assert summary["classified"] == 7
    assert summary["reasons"] == {rp.ABSENT: 1, rp.UNKNOWN_TIMESTAMP: 1}


def test_only_unchanged_is_usable():
    assert rp.USABLE == {"unchanged"}


def test_a_row_exactly_at_the_watermark_is_unchanged():
    inv = classify(["100"], {"100": [row(WATERMARK)]})
    assert inv.entries["100"].cls == "unchanged"


def test_multiple_versions_of_one_listing():
    rows = {
        "100": [row(BEFORE), row(datetime(2026, 9, 10))],  # ordered, both old
        "101": [row(BEFORE), row(AFTER)],  # an older row cannot hide a change
        "200": [row(BEFORE), row(AFTER)],  # unstored, newest row after: new
    }
    inv = classify(["100", "101"], rows)
    assert inv.entries["100"].cls == "unchanged"
    assert inv.entries["101"].cls == "changed"
    assert inv.entries["200"].cls == "new"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([row(BEFORE), row(None)], rp.UNKNOWN_TIMESTAMP),
        ([row(datetime(2026, 10, 2))], rp.AFTER_AS_OF),
        ([row(active=None)], rp.UNKNOWN_STATUS),
        ([row(BEFORE, True), row(AFTER, False)], rp.CONFLICTING_STATUS),
        ([row(BEFORE), row(BEFORE)], rp.UNORDERED_DUPLICATE),
    ],
)
@pytest.mark.parametrize("in_store", [True, False])
def test_uncertain_rows_are_ambiguous_never_unchanged(rows, reason, in_store):
    inv = classify(["100"] if in_store else [], {"100": rows})
    assert (inv.entries["100"].cls, inv.entries["100"].reason) == ("ambiguous", reason)


def test_deactivated_listings():
    rows = {"100": [row(BEFORE, False), row(AFTER, False)], "101": [row(AFTER, False)]}
    inv = classify(["100", "101"], rows)
    assert {e.cls for e in inv.entries.values()} == {"no_longer_active"}


@pytest.mark.parametrize("key", ["12a", " 12", "", "١٢"])
def test_keys_that_are_not_digit_strings_are_ambiguous(key):
    inv = classify([key], {key: [row()]})
    assert inv.entries[key] == rp.Entry("ambiguous", rp.KEY_NOT_DIGITS)


def test_a_duplicated_store_key_is_ambiguous():
    inv = classify(["100", "100"], {"100": [row()]})
    assert inv.entries["100"] == rp.Entry("ambiguous", rp.DUPLICATE_STORE_KEY)


def test_a_watermark_after_the_data_as_of_is_refused():
    with pytest.raises(ValueError):
        classify(["100"], {"100": [row()]}, watermark=AS_OF, as_of=WATERMARK)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (BEFORE, BEFORE),
        ("2026-09-01 00:00:00", BEFORE),
        ("0000-00-00 00:00:00", None),
        ("yesterday", None),
        (None, None),
        (20260901, None),
    ],
)
def test_timestamps_parse_or_are_unknown(value, expected):
    assert rp.parse_timestamp(value) == expected


@pytest.mark.parametrize(
    ("status", "active"),
    [("Active", True), (" Active ", True), ("Closed", False), ("", None), (None, None)],
)
def test_status_mapping(status, active):
    assert rp.to_row(BEFORE, status).active is active


# --- bounded keyset pages on an SQLite stand-in for rets_property -----------------


class SqliteConn:
    """A pool-like connection: %s -> ?, dict rows, every statement recorded."""

    def __init__(self, engine):
        self.engine = engine
        self.statements = []

    def cursor(self):
        return _Cursor(self)


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.conn.statements.append((sql, params))
        result = self.conn.engine.execute(sql.replace("%s", "?"), params)
        self.rows = [dict(r) for r in result.fetchall()]

    def fetchall(self):
        return self.rows


def engine(rows):
    """rets_property with the three read columns plus a remark column never read."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE rets_property (L_ListingID TEXT, ModificationTimestamp TEXT, "
        "StandardStatus TEXT, L_Remarks TEXT)"
    )
    db.executemany(
        "INSERT INTO rets_property VALUES (?, ?, ?, 'synthetic remark')", rows
    )
    return db


def test_page_sql_names_allowlisted_columns_and_binds_everything():
    query = pages.build_key_page_sql("100")
    assert query.sql.startswith(
        "SELECT L_ListingID, ModificationTimestamp, StandardStatus\n"
    )
    assert "*" not in query.sql and "L_Remarks" not in query.sql
    assert "WHERE L_ListingID > %s\nORDER BY L_ListingID\nLIMIT %s" in query.sql
    assert query.params == ("100", 50)
    for bad in [("100", 51), ("100", 0), (100, 10)]:
        with pytest.raises(ValueError):
            pages.build_key_page_sql(*bad)


def test_count_sql_returns_numbers_only():
    query = pages.build_inventory_counts_sql()
    assert query.sql.startswith("SELECT COUNT(*) AS total_rows")
    assert "*" not in query.sql.replace("COUNT(*)", "")
    assert query.params == ("Active",)


def test_counts_on_the_stand_in():
    conn = SqliteConn(
        engine(
            [
                ("1", "2026-09-01 00:00:00", "Active"),
                ("1", "2026-09-02 00:00:00", "Active"),
                ("2", None, "Closed"),
                (None, "2026-09-03 00:00:00", "Active"),
            ]
        )
    )
    assert pages.fetch_inventory_counts(conn) == {
        "total_rows": 4,
        "listing_ids": 2,
        "rows_without_key": 1,
        "rows_without_timestamp": 1,
        "active_ids": 1,
        "max_modified": "2026-09-03 00:00:00",
    }


def test_120_keys_page_across_three_pages():
    keys = [f"{n:04d}" for n in range(1, 121)]
    conn = SqliteConn(engine([(k, "2026-09-01 00:00:00", "Active") for k in keys]))
    got = [r[0] for r in pages.iter_listing_rows(conn)]
    assert got == keys
    assert len(conn.statements) == 3
    assert all(sql.startswith("SELECT ") for sql, _ in conn.statements)
    assert all(params[-1] == 50 for _, params in conn.statements)


def test_a_listing_split_across_a_page_boundary_is_read_whole():
    keys = [f"{n:04d}" for n in range(1, 50)]  # 49 single-row keys, then ...
    rows = [(k, "2026-09-01 00:00:00", "Active") for k in keys]
    rows += [("0050", "2026-09-01 00:00:00", "Active")] * 2  # rows 50 and 51
    rows += [("0051", "2026-09-01 00:00:00", "Active")]
    conn = SqliteConn(engine(rows))
    got = [r[0] for r in pages.iter_listing_rows(conn)]
    assert got == [*keys, "0050", "0050", "0051"]


def test_an_empty_table_needs_one_page():
    conn = SqliteConn(engine([]))
    assert list(pages.iter_listing_rows(conn)) == []
    assert len(conn.statements) == 1


def test_a_listing_filling_a_page_is_refused():
    conn = SqliteConn(engine([("7", "2026-09-01 00:00:00", "Active")] * 3))
    with pytest.raises(ValueError, match="fills a whole page"):
        list(pages.iter_listing_rows(conn, limit=3))


class FakeConn:
    def __init__(self, pages_):
        self.pages = list(pages_)

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.current = self.pages.pop(0)

    def fetchall(self):
        return self.current


@pytest.mark.parametrize(
    "page",
    [
        [("2", None, "Active"), ("1", None, "Active")],  # descending in a page
        [("", None, "Active")],  # not after the cursor
        [(5, None, "Active")],  # not text
    ],
)
def test_keys_out_of_order_are_refused(page):
    with pytest.raises(ValueError, match="out of order"):
        list(pages.iter_listing_rows(FakeConn([page])))


def test_a_page_over_the_limit_is_refused():
    page = [(str(n), None, "Active") for n in range(4)]
    with pytest.raises(ValueError, match="more than"):
        list(pages.iter_listing_rows(FakeConn([page]), limit=3))
