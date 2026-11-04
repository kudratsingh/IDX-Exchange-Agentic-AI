"""Offline end-to-end acceptance for feature search (WO-021) via the real tool path:
validation, session memory, a real effective store built by `effective_rows` from
invented results and both overlay kinds, the real SQL run on an SQLite stand-in for
`rets_property`, paging, payload and reply. Only the connection and as-of dates are
substituted; every row is invented. Names carry the matrix row (A1-A12, WO-021)."""

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from tests.synthetic_store import write_synthetic_store

from idx_agent.alerts import server as alerts
from idx_agent.db import listings as db_listings
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.fieldmap import listing_columns
from idx_agent.domain.models import Clarification, PropertySearchFilters, SearchResult
from idx_agent.domain.results import AgentResult
from idx_agent.enrichment import effective_store
from idx_agent.enrichment.effective import ELIGIBLE_FACETS, effective_rows
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore

Envelope = AgentResult[SearchResult | Clarification]
ASOF = AsOfDates(sold=date(2026, 9, 15), active=date(2026, 9, 18))
WATERMARK = "2026-09-18 06:58:44"
BEFORE = "2026-09-01 10:00:00"
AFTER = "2026-10-01 10:00:00"
FACETS = sorted(ELIGIBLE_FACETS)

# How each status is written as extraction labels (polarity, temporality).
VARIANTS = {
    "present": [("affirmed", "current")],
    "present_unspecified": [("affirmed", "unspecified")],
    "planned": [("affirmed", "planned")],
    "uncertain": [("uncertain", "current")],
    "historical": [("affirmed", "historical")],
    "negated": [("negated", "current")],
    "contradictory": [("affirmed", "current"), ("negated", "current")],
    "unknown": [],
}
MATCHING = {"present", "present_unspecified"}


def label(value, polarity="affirmed", temporality="current"):
    return dict(group="g", value=value, polarity=polarity, temporality=temporality)


class Universe:
    """Invented listings (database rows) and extraction results (store input)."""

    def __init__(self):
        self.rows = []  # (key, city, price, beds, modified)
        self.results = []  # (sequence, key, labels)

    def add(self, key, city, labels, *, price=None, beds=3, modified=(BEFORE,)):
        price = price or 500_000 + key * 10
        for stamp in modified:
            self.rows.append((str(key), city, price, beds, stamp))
        if labels is not None:
            self.results.append((len(self.results) + 1, str(key), labels))
        return key

    def sequence(self, key):
        return next(s for s, k, _ in self.results if k == str(key))


def facet_key(facet, variant):
    return 10_000 + FACETS.index(facet) * 100 + list(VARIANTS).index(variant)


def universe():
    u = Universe()
    # A1/A2: every eligible facet in every status, in Pasadena. An "unknown" listing
    # carries an ineligible label only, so it is covered by the store but has no status.
    for facet in FACETS:
        for variant, parts in VARIANTS.items():
            labels = [label(facet, p, t) for p, t in parts] or [label("office")]
            u.add(facet_key(facet, variant), "Pasadena", labels)
    u.add(19_999, "Pasadena", None)  # active, never extracted: unknown everywhere
    # A3: ordinary filters with features, in Sierra Madre.
    both = [label("solar"), label("pool")]
    u.add(20_001, "Sierra Madre", both, price=900_000, beds=4)
    u.add(20_002, "Sierra Madre", [label("solar")], price=800_000, beds=4)
    u.add(
        20_003, "Sierra Madre", [label("solar"), label("pool", "affirmed", "planned")]
    )
    u.add(20_004, "Sierra Madre", both, price=700_000, beds=2)
    u.add(20_005, "Monrovia", both, price=650_000, beds=4)
    # A4: corrections, in Arcadia. Each one changes eligibility when applied.
    u.add(30_001, "Arcadia", [label("solar")])  # diagnostic: wrong label removed
    u.add(30_002, "Arcadia", [label("hardwood")])  # dataset: retagged uncertain
    u.add(30_003, "Arcadia", [label("hardwood", "affirmed", "planned")])  # dataset: add
    u.add(30_004, "Arcadia", [label("solar")])  # diagnostic: accepted unchanged
    u.add(30_005, "Arcadia", [label("garage")])  # no overlay at all
    # A6: freshness, in Altadena.
    u.add(40_001, "Altadena", [label("patio")])  # unchanged
    u.add(40_002, "Altadena", [label("patio")], modified=(BEFORE, AFTER))  # changed
    u.add(40_003, "Altadena", [label("patio")], modified=(None,))  # unknown time
    u.add(40_004, "Altadena", [label("patio")], modified=(BEFORE, None))
    u.add(40_005, "Altadena", [label("patio")], modified=(AFTER,))
    # A7: paging, in Glendale: seven solar listings and three without.
    for i in range(7):
        u.add(50_000 + i, "Glendale", [label("solar")])
    for i in range(3):
        u.add(50_100 + i, "Glendale", [label("garage")])
    return u


def overlays(u):
    """One diagnostic and one dataset overlay of each kind, keyed by sequence."""

    def disposition(key, status, changes):
        return dict(listing_key=str(key), status=status, changes=changes)

    diagnostic = {
        u.sequence(30_001): disposition(
            30_001,
            "corrected",
            [dict(operation="remove", original=label("solar"))],
        ),
        u.sequence(30_004): disposition(30_004, "accepted_unchanged", []),
    }
    dataset = {
        u.sequence(30_002): disposition(
            30_002,
            "corrected",
            [
                dict(operation="remove", original=label("hardwood")),
                dict(
                    operation="add",
                    corrected_annotation=label("hardwood", "uncertain", "current"),
                ),
            ],
        ),
        u.sequence(30_003): disposition(
            30_003,
            "corrected",
            [dict(operation="add", corrected_annotation=label("hardwood"))],
        ),
    }
    return diagnostic, dataset


META = {
    "source_watermark": WATERMARK,
    "policy_version": "v4",
    "rules_version": "2026-11-01.4",
    # The digest and source count are a synthetic pair (tests/synthetic_store.py).
    "built_from": json.dumps({"overlay": "invented"}),
}


def build_store(path, u, with_overlays=True):
    diagnostic, dataset = overlays(u) if with_overlays else ({}, {})
    rows = list(effective_rows(u.results, diagnostic, dataset))
    write_synthetic_store(path, rows, META)
    return path


# --- The SQLite stand-in for the listings database ---


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.conn.statements.append((sql, tuple(params)))
        cursor = self.conn.engine.execute(sql.replace("%s", "?"), params)
        self.rows = [dict(row) for row in cursor.fetchall()]

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, engine, statements):
        self.engine = engine
        self.statements = statements

    def cursor(self):
        return Cursor(self)

    def close(self):
        pass


def engine_for(u):
    engine = sqlite3.connect(":memory:", check_same_thread=False)
    engine.row_factory = sqlite3.Row
    columns = list(dict.fromkeys([*listing_columns(), "ModificationTimestamp"]))
    engine.execute(f"CREATE TABLE rets_property ({', '.join(columns)})")
    marks = ", ".join("?" * len(columns))
    for n, (key, city, price, beds, modified) in enumerate(u.rows):
        values = dict.fromkeys(columns)
        values.update(
            L_ListingID=key,
            L_DisplayId=f"D{key}-{n}",
            L_Address=f"{key} Invented Way",
            L_City=city,
            L_Zip="91000",
            L_SystemPrice=price,
            L_Keyword2=beds,
            StandardStatus="Active",
            ModificationTimestamp=modified,
        )
        engine.execute(
            f"INSERT INTO rets_property VALUES ({marks})", [values[c] for c in columns]
        )
    return engine


@pytest.fixture
def world(monkeypatch, tmp_path):
    u = universe()
    statements = []
    state = {
        "universe": u,
        "engine": engine_for(u),
        "statements": statements,
        "path": build_store(tmp_path / "effective.sqlite3", u),
        "tmp": tmp_path,
    }
    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(
        mcp.db_pool, "connect", lambda config=None: Conn(state["engine"], statements)
    )
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(
        mcp.effective_store, "configured_store_path", lambda: state["path"]
    )
    monkeypatch.setattr(
        mcp,
        "memory_key",
        lambda raw, secret=None: raw and hashlib.sha256(raw.encode()).hexdigest(),
    )
    mcp.reset_store_for_tests(
        InMemorySessionStore(
            timedelta(minutes=30), 10, lambda: datetime(2026, 9, 18, tzinfo=UTC)
        )
    )
    yield state
    mcp.reset_store_for_tests()


def search(**kwargs):
    return Envelope.model_validate(mcp.search_listings(**kwargs))


def keys(result):
    return [x.listing_key for x in result.data.listings]


# --- A1/A2: every eligible facet, every status ---


@pytest.mark.parametrize("facet", FACETS)
def test_a1_a2_each_facet_matches_only_present_statuses(world, facet):
    result = search(city="Pasadena", features=[facet], limit=50)
    assert result.ok and result.data.feature_filter.status == "applied"
    expected = sorted(facet_key(facet, v) for v in MATCHING)
    assert sorted(keys(result)) == expected
    assert result.data.total_matches == 2
    # planned, uncertain, historical, negated, contradictory and unknown never match,
    # and nor does a listing that was never extracted.
    excluded = {facet_key(facet, v) for v in VARIANTS if v not in MATCHING}
    assert not excluded & set(keys(result)) and 19_999 not in keys(result)


def test_a2_the_store_records_each_status_and_never_records_unknown(world):
    store = effective_store.open_store(world["path"])
    try:
        for facet in FACETS:
            got = {
                v: store.statuses(str(facet_key(facet, v))).get(facet) for v in VARIANTS
            }
            assert got == {
                "present": "present",
                "present_unspecified": "present",
                "planned": "planned",
                "uncertain": "uncertain",
                "historical": "historical",
                "negated": "stated_absent",
                "contradictory": "contradictory",
                "unknown": None,
            }
        assert store.statuses("19999") == {}
    finally:
        store.close()


# --- A3: features with ordinary filters, and several features ---


def test_a3_every_requested_feature_must_be_present(world):
    assert sorted(keys(search(city="Sierra Madre", features=["solar"]))) == [
        20_001,
        20_002,
        20_003,
        20_004,
    ]
    # Pool planned (20_003) is not pool present.
    both = search(city="Sierra Madre", features=["pool", "solar"])
    assert sorted(keys(both)) == [20_001, 20_004]


def test_a3_features_combine_with_ordinary_filters(world):
    assert keys(
        search(city="Sierra Madre", features=["solar", "pool"], min_beds=3)
    ) == [20_001]
    assert keys(
        search(city="Sierra Madre", features=["solar", "pool"], max_price=750_000)
    ) == [20_004]
    # The city still applies: 20_005 has both features but is in Monrovia.
    assert keys(search(city="Monrovia", features=["solar", "pool"])) == [20_005]
    none = search(city="Sierra Madre", features=["solar", "pool"], min_price=2_000_000)
    assert none.data.listings == [] and none.data.total_matches == 0


def test_a3_five_features_at_once(world):
    five = ["solar", "pool", "garage", "patio", "hardwood"]
    result = search(city="Pasadena", features=five)
    assert result.ok and result.data.listings == []
    assert result.data.feature_filter.status == "applied"
    six = search(city="Pasadena", features=[*five, "adu"])
    assert isinstance(six.data, Clarification)
    assert six.data.reason == "too_many_features"


# --- A4: both correction overlays change what is matched ---


def test_a4_both_overlays_change_search_outcomes(world, tmp_path):
    corrected = {
        f: sorted(keys(search(city="Arcadia", features=[f])))
        for f in ("solar", "hardwood", "garage")
    }
    assert corrected == {
        "solar": [30_004],  # diagnostic removal drops 30_001; accepted keeps 30_004
        "hardwood": [30_003],  # retag drops 30_002; an added label brings in 30_003
        "garage": [30_005],
    }
    world["path"] = build_store(
        tmp_path / "uncorrected.sqlite3", world["universe"], with_overlays=False
    )
    original = {
        f: sorted(keys(search(city="Arcadia", features=[f])))
        for f in ("solar", "hardwood", "garage")
    }
    assert original == {
        "solar": [30_001, 30_004],
        "hardwood": [30_002],
        "garage": [30_005],
    }


# --- A5: missing, malformed, wrong-source and incomplete stores fail closed ---


def _store_variant(world, name, edit):
    path = world["tmp"] / f"{name}.sqlite3"
    build_store(path, world["universe"])
    with sqlite3.connect(path) as db:
        edit(db)
    return path


@pytest.mark.parametrize(
    "variant",
    [
        "unconfigured",
        "missing",
        "junk",
        "schema",
        "source_digest",
        "no_digest",
        "incomplete",
        "bad_status",
    ],
)
def test_a5_unusable_stores_fail_closed_without_a_listing_query(world, variant):
    edits = {
        "schema": "UPDATE meta SET value = '0' WHERE name = 'schema_version'",
        "source_digest": "UPDATE meta SET value = 'f00d' WHERE name = 'results_digest'",
        "no_digest": "DELETE FROM meta WHERE name = 'results_digest'",
        "incomplete": "DELETE FROM listings WHERE listing_key = '30005'",
        "bad_status": "UPDATE facets SET status = 'maybe' WHERE listing_key = '30005'",
    }
    if variant == "unconfigured":
        world["path"] = None
    elif variant == "missing":
        world["path"] = world["tmp"] / "absent.sqlite3"
    elif variant == "junk":
        world["path"] = world["tmp"] / "junk.sqlite3"
        world["path"].write_text("not a database")
    else:
        world["path"] = _store_variant(
            world, variant, lambda db: db.execute(edits[variant])
        )
    result = search(city="Pasadena", features=["solar"], sender_id="a5")
    assert result.ok and result.data.listings == []
    assert result.data.feature_filter.status == "unavailable"
    assert result.data.feature_filter.limitation == mcp.FEATURE_LIMITATION
    assert result.message == mcp.FEATURE_UNAVAILABLE_MESSAGE
    assert world["statements"] == []


# --- A6: changed listings, several versions, unknown change times ---


def test_a6_only_listings_unchanged_since_the_snapshot_match(world):
    result = search(city="Altadena", features=["patio"])
    assert keys(result) == [40_001]
    feature = result.data.feature_filter
    # 40_002 (a newer version), 40_003 and 40_004 (no change time), 40_005 (changed).
    assert feature.changed_since_snapshot == 4
    assert "4 matching listing(s) changed since then" in result.message
    assert result.data.total_matches == 1


def test_a6_a_widely_changed_table_is_stale(world):
    engine = world["engine"]
    rows = engine.execute("SELECT COUNT(*) FROM rets_property").fetchone()[0]
    engine.execute(
        "UPDATE rets_property SET ModificationTimestamp = ? WHERE rowid <= ?",
        (AFTER, rows // 10 + 1),
    )
    result = search(city="Pasadena", features=["solar"])
    assert result.data.feature_filter.status == "stale"
    assert result.message == mcp.FEATURE_STALE_MESSAGE
    assert result.data.listings == []


def test_a6_missing_change_times_count_toward_staleness(world):
    engine = world["engine"]
    rows = engine.execute("SELECT COUNT(*) FROM rets_property").fetchone()[0]
    engine.execute(
        "UPDATE rets_property SET ModificationTimestamp = NULL WHERE rowid <= ?",
        (rows // 10 + 1,),
    )
    assert search(city="Pasadena", features=["solar"]).data.feature_filter.status == (
        "stale"
    )


# --- A7: no matches, later pages, "more", and the over-cap count ---


def test_a7_paging_a_feature_search_with_more(world):
    first = search(city="Glendale", features=["solar"], limit=3, sender_id="a7")
    assert len(first.data.listings) == 3
    assert first.data.total_matches == 7  # the scoped count, not all 10 in Glendale
    seen = keys(first)
    second = search(sender_id="a7", mode="more")
    third = search(sender_id="a7", mode="more")
    assert second.data.applied_filters.page == 2 and len(second.data.listings) == 3
    assert third.data.applied_filters.page == 3 and len(third.data.listings) == 1
    seen += keys(second) + keys(third)
    assert sorted(seen) == list(range(50_000, 50_007))
    assert all(r.data.applied_filters.features == ("solar",) for r in (second, third))
    last = search(sender_id="a7", mode="more")
    assert last.data is None and last.message == mcp.LAST_PAGE_MESSAGE


def test_a7_a_feature_with_no_match_is_empty_on_every_page(world):
    first = search(city="Glendale", features=["adu"], sender_id="a7b")
    assert first.ok and first.data.listings == [] and first.data.total_matches == 0
    assert "No active listings matched on page 1" in first.message
    assert mcp.FEATURE_LIMITATION in first.message
    later = search(city="Glendale", features=["adu"], page=4)
    assert later.data.total_matches == 0
    # The count never ran without the feature scope.
    counts = [
        sql for sql, _ in world["statements"] if "COUNT(*) AS total_matches" in sql
    ]
    assert all("L_ListingID IN" in sql for sql in counts)


# --- A8: recovery after a refusal ---


def test_a8_recovery_after_an_unavailable_store(world):
    good = world["path"]
    world["path"] = world["tmp"] / "absent.sqlite3"
    refused = search(city="Glendale", features=["solar"], limit=3, sender_id="a8")
    assert refused.data.feature_filter.status == "unavailable"
    # "more" while still refused: page 1 again, refused again.
    again = search(sender_id="a8", mode="more")
    assert again.data.applied_filters.page == 1
    assert again.data.feature_filter.status == "unavailable"
    world["path"] = good
    # The store is back: "more" shows page 1, which the user never saw, not page 2.
    back = search(sender_id="a8", mode="more")
    assert back.data.applied_filters.page == 1
    assert back.data.feature_filter.status == "applied"
    assert len(back.data.listings) == 3
    assert search(sender_id="a8", mode="more").data.applied_filters.page == 2


def test_a8_accepting_the_offer_searches_the_same_area_without_features(world):
    world["path"] = world["tmp"] / "absent.sqlite3"
    search(city="Glendale", features=["solar"], max_price=1_500_000, sender_id="a8b")
    plain = search(sender_id="a8b", mode="update", clear=["features"])
    assert plain.data.feature_filter is None
    assert plain.data.applied_filters.city == "Glendale"
    assert plain.data.applied_filters.max_price == 1_500_000
    assert plain.data.total_matches == 10


# --- A9: refinements keep features until they are cleared ---


def test_a9_refinements_keep_features_until_cleared(world):
    search(city="Sierra Madre", features=["solar"], sender_id="a9")
    refined = search(min_beds=4, sender_id="a9", mode="update")
    assert refined.data.applied_filters.features == ("solar",)
    assert sorted(keys(refined)) == [20_001, 20_002]
    empty_list = search(features=[], sender_id="a9", mode="update")
    assert empty_list.data.applied_filters.features == ("solar",)
    replaced = search(features=["pool"], sender_id="a9", mode="update")
    assert replaced.data.applied_filters.features == ("pool",)
    assert keys(replaced) == [20_001]
    cleared = search(sender_id="a9", mode="update", clear=["features"])
    assert cleared.data.applied_filters.features is None
    assert cleared.data.feature_filter is None
    assert sorted(keys(cleared)) == [20_001, 20_002]
    reset = search(sender_id="a9", mode="reset")
    assert reset.data is None


# --- A10: a saved search never silently drops features ---


def test_a10_saving_a_feature_search_is_refused_not_narrowed(monkeypatch):
    class Store:
        added = []

        def add(self, *args):
            self.added.append(args)
            raise AssertionError("a feature search was saved")

    monkeypatch.setattr(alerts, "configured_store", lambda: Store())
    monkeypatch.setattr(
        alerts, "memory_key", lambda raw, secret=None: "ab" * 32 if raw else None
    )
    refused = alerts.save_search(sender_id="a10", city="Pasadena", features=["solar"])
    assert refused["ok"] and refused["data"]["field"] == "features"
    assert refused["message"] == alerts.SAVED_FEATURES_QUESTION
    assert Store.added == []


# --- A11: searches without features are unchanged ---


def test_a11_a_plain_search_runs_the_earlier_sql_and_never_opens_the_store(
    world, monkeypatch
):
    def refuse(path):
        raise AssertionError("store opened for a search without features")

    monkeypatch.setattr(mcp.effective_store, "open_store", refuse)
    result = search(city="Glendale", limit=3)
    filters = PropertySearchFilters.from_input({"city": "Glendale", "limit": 3})
    expected = db_listings.build_search_sql(filters)
    assert world["statements"][0] == (expected.sql, expected.params)
    assert all("ModificationTimestamp" not in sql for sql, _ in world["statements"])
    data = result.model_dump(mode="json")["data"]
    assert set(data) == {
        "listings",
        "applied_filters",
        "total_matches",
        "narrowing_question",
    }
    assert "features" not in data["applied_filters"]
    assert "Features matched" not in result.message
    assert mcp.FEATURE_LIMITATION not in result.message


def test_a11_a_plain_search_is_identical_with_or_without_a_store(world):
    with_store = mcp.search_listings(city="Glendale", limit=3)
    world["path"] = None
    without = mcp.search_listings(city="Glendale", limit=3)
    for payload in (with_store, without):
        payload["provenance"].pop("trace_id")
    assert with_store == without


# --- A12: the rendered reply keeps the snapshot and the limitation ---


def test_a12_reply_names_features_snapshot_and_limitation(world):
    result = search(city="Sierra Madre", features=["walk_in_closet", "solar"])
    assert result.data.listings == []
    message = search(city="Sierra Madre", features=["solar"]).message
    assert "Features matched from listing descriptions as of 2026-09-18: solar." in (
        message
    )
    assert message.rstrip().endswith(mcp.FEATURE_LIMITATION)
    assert "features solar" in message
    words = search(city="Pasadena", features=["near_transit_mentioned"]).message
    assert "transit nearby (as stated)" in words
