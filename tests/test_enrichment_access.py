"""Shared enrichment access (WO-023): one rule set for every feature consumer.

Reuses the invented universe of the WO-021 acceptance tests: a real effective store,
the real SQL on an SQLite stand-in, every status for every facet. No real data."""

import os
import sqlite3

import pytest
from tests.test_feature_search_acceptance import (
    AFTER,
    BEFORE,
    FACETS,
    MATCHING,
    VARIANTS,
    Conn,
    build_store,
    engine_for,
    facet_key,
    label,
    search,
    universe,
    world,  # noqa: F401 - the shared fixture
)

from idx_agent.db import listings as db_listings
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.enrichment import access as fa
from idx_agent.enrichment import effective_store
from idx_agent.enrichment.effective import ELIGIBLE_FACETS
from idx_agent.mcp_server import server as mcp


def conn_of(world):  # noqa: F811
    return Conn(world["engine"], world["statements"])


_REAL_OPEN = effective_store.open_store


class Tracking:
    """An opener that records every store it opens and whether each was closed."""

    def __init__(self):
        self.opened = []

    def __call__(self, path):
        got = _REAL_OPEN(path)
        if isinstance(got, effective_store.FacetStore):
            real_close = got.close
            record = {"closed": False}

            def close():
                record["closed"] = True
                real_close()

            got.close = close
            self.opened.append(record)
        return got


def usable(world):  # noqa: F811
    access = fa.FeatureAccess(world["path"])
    assert access.readiness(conn_of(world)).usable
    return access


# --- Readiness: unavailable and stale fail closed ---


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda w: None, "not_configured"),
        (lambda w: w["tmp"] / "absent.sqlite3", "missing"),
    ],
)
def test_unavailable_store_needs_no_database_read(world, make, reason):  # noqa: F811
    with fa.FeatureAccess(make(world)) as access:
        ready = access.readiness(conn_of(world))
        assert (ready.status, ready.reason, ready.info) == ("unavailable", reason, None)
        bound = access.bind(["solar"], conn_of(world))
        assert (bound.status, bound.reason) == ("unavailable", reason)
        assert bound.scope is None
        assert bound.refused and not bound.matches_nothing
        with pytest.raises(RuntimeError):
            access.present_features(["10000"], conn_of(world))
    assert world["statements"] == []


def test_junk_store_is_unavailable(world):  # noqa: F811
    junk = world["tmp"] / "junk.sqlite3"
    junk.write_text("not a database")
    with fa.FeatureAccess(junk) as access:
        assert access.readiness(conn_of(world)).status == "unavailable"


def test_stale_snapshot_blocks_every_read(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fa.db_listings, "fetch_freshness", lambda w, c: (100, 11))
    with fa.FeatureAccess(world["path"]) as access:
        ready = access.readiness(conn_of(world))
        assert ready.status == "stale" and ready.info is not None
        assert (ready.active, ready.changed) == (100, 11)
        bound = access.bind(["solar"], conn_of(world))
        assert (bound.status, bound.scope, bound.info) == ("stale", None, ready.info)
        assert bound.refused
        with pytest.raises(RuntimeError):
            access.present_features(["10000"], conn_of(world))


def test_exactly_the_threshold_is_still_usable(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fa.db_listings, "fetch_freshness", lambda w, c: (100, 10))
    with fa.FeatureAccess(world["path"]) as access:
        assert access.readiness(conn_of(world)).usable


def test_no_active_listings_is_stale(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fa.db_listings, "fetch_freshness", lambda w, c: (0, 0))
    with fa.FeatureAccess(world["path"]) as access:
        assert access.readiness(conn_of(world)).status == "stale"


def test_reads_need_a_checked_snapshot_first(world):  # noqa: F811
    with fa.FeatureAccess(world["path"]) as access:
        assert access.open().usable  # opened, but freshness not checked yet
        with pytest.raises(RuntimeError):
            access.lookup(["10000"], conn_of(world))


def test_readiness_is_checked_once_per_access(world, monkeypatch):  # noqa: F811
    reads = []
    monkeypatch.setattr(
        fa.db_listings, "fetch_freshness", lambda w, c: reads.append(w) or (100, 0)
    )
    fa.reset_for_tests()
    with fa.FeatureAccess(world["path"]) as access:
        first = access.readiness(conn_of(world))
        assert access.readiness(conn_of(world)) is first
    assert len(reads) == 1


# --- Present-only semantics, identical across consumers ---


@pytest.mark.parametrize("facet", FACETS)
def test_present_features_match_feature_search_for_every_status(world, facet):  # noqa: F811
    """The keys badges/explanations may use for a facet are exactly the keys feature
    search returns for it: present only, never-extracted and unknown excluded."""
    found = search(city="Pasadena", features=[facet], limit=50)
    matched = {str(x.listing_key) for x in found.data.listings}
    candidates = [facet_key(facet, v) for v in VARIANTS] + [19_999]
    with usable(world) as access:
        present = access.present_features(candidates, conn_of(world))
    with_facet = {k for k, feats in present.items() if facet in feats}
    assert with_facet == matched == {str(facet_key(facet, v)) for v in MATCHING}
    # A listing whose only label is ineligible, and one never extracted, have none.
    assert str(facet_key(facet, "unknown")) not in present
    assert "19999" not in present


def test_only_eligible_present_facets_are_returned(world):  # noqa: F811
    keys = [facet_key(f, v) for f in FACETS for v in VARIANTS][:50]
    with usable(world) as access:
        present = access.present_features(keys, conn_of(world))
        store_statuses = {str(k): access._store.statuses(str(k)) for k in keys}
    for key, feats in present.items():
        assert feats <= ELIGIBLE_FACETS
        assert all(store_statuses[key][f] == "present" for f in feats)


def test_area_facets_can_be_left_out_by_a_consumer(world):  # noqa: F811
    keys = [facet_key(f, "present") for f in sorted(fa.AREA_FACETS)]
    home_only = ELIGIBLE_FACETS - fa.AREA_FACETS
    with usable(world) as access:
        assert set(access.present_features(keys, conn_of(world))) == {
            str(k) for k in keys
        }
        assert access.present_features(keys, conn_of(world), home_only) == {}


# --- Freshness per listing: changed, undated and duplicate rows ---


def test_changed_and_undated_listings_have_no_features(world):  # noqa: F811
    altadena = [40_001, 40_002, 40_003, 40_004, 40_005]
    with usable(world) as access:
        present = access.present_features(altadena, conn_of(world))
        moved = access.changed_keys(altadena, conn_of(world))
    assert set(present) == {"40001"}
    assert moved == {"40002", "40003", "40004", "40005"}
    # Feature search agrees: only the unchanged listing matches.
    found = search(city="Altadena", features=["patio"])
    assert [x.listing_key for x in found.data.listings] == [40_001]
    assert found.data.feature_filter.changed_since_snapshot == 4


def test_duplicate_rows_count_once_and_any_newer_row_excludes(world, monkeypatch):  # noqa: F811
    u = universe()
    u.add(60_001, "Duarte", [label("pool")], modified=(BEFORE, BEFORE))
    u.add(60_002, "Duarte", [label("pool")], modified=(BEFORE, AFTER, BEFORE))
    world["engine"] = engine_for(u)
    world["path"] = build_store(world["tmp"] / "dupes.sqlite3", u)
    with usable(world) as access:
        present = access.present_features(["60001", 60_001, "60002"], conn_of(world))
    assert present == {"60001": frozenset({"pool"})}
    found = search(city="Duarte", features=["pool"])
    # Only the unchanged listing matches. Its two identical rows are each returned
    # and counted, exactly as an ordinary search returns them (pre-existing rule).
    assert {x.listing_key for x in found.data.listings} == {60_001}
    plain = search(city="Duarte")
    assert [x.listing_key for x in plain.data.listings].count(60_001) == 2


def test_more_than_fifty_keys_are_refused(world):  # noqa: F811
    with usable(world) as access, pytest.raises(ValueError):
        access.present_features([str(n) for n in range(10_000, 10_051)], conn_of(world))


def test_no_keys_reads_nothing(world):  # noqa: F811
    with usable(world) as access:
        before = len(world["statements"])
        assert access.present_features([], conn_of(world)) == {}
        assert access.changed_keys([], conn_of(world)) == set()
        assert len(world["statements"]) == before


# --- Binding: too broad never falls open ---


def test_too_broad_scope_is_refused_not_bound(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fa.db_listings, "MAX_FEATURE_KEYS", 3)
    with usable(world) as access:
        bound = access.bind(["solar"], conn_of(world))
    assert (bound.status, bound.reason) == ("unavailable", "too_broad")
    assert bound.scope is None
    assert bound.refused and not bound.matches_nothing and bound.matched > 3
    result = search(city="Glendale", features=["solar"])
    assert result.data.feature_filter.status == "unavailable"
    assert result.data.listings == [] and result.data.total_matches is None


def test_scope_is_present_only(world):  # noqa: F811
    with usable(world) as access:
        keys = set(access.bind(["pool"], conn_of(world)).scope.keys)
    assert {str(facet_key("pool", v)) for v in MATCHING} <= keys
    for variant in set(VARIANTS) - MATCHING:
        assert str(facet_key("pool", variant)) not in keys


def test_binding_carries_the_snapshot_and_matches_search(world):  # noqa: F811
    """A consumer that writes its own listing SQL (saved-search alerts) gets the same
    scope as feature search: snapshot watermark included, changed listings left out."""
    with usable(world) as access:
        bound = access.bind(["patio"], conn_of(world))
    assert bound.status == "applied" and not bound.refused
    assert isinstance(bound.scope, db_listings.FeatureScope)
    assert bound.scope.watermark == bound.info.source_watermark
    assert bound.matched == len(bound.scope.keys)
    filters = PropertySearchFilters.from_input({"city": "Altadena"})
    own = db_listings.search_active_listings(filters, conn_of(world), bound.scope)
    found = search(city="Altadena", features=["patio"])
    assert [x.listing_key for x in own.listings] == [40_001]
    assert [x.listing_key for x in found.data.listings] == [40_001]


def test_no_match_is_applied_and_distinct_from_a_refusal(world):  # noqa: F811
    with usable(world) as access:
        bound = access.bind(["adu", "solar", "pool", "garage"], conn_of(world))
    assert (bound.status, bound.scope, bound.reason) == ("applied", None, None)
    assert bound.matches_nothing and not bound.refused


def test_a_store_with_repeated_facet_rows_is_unavailable(world):  # noqa: F811
    """Review of #142: rows, not facets, were counted, so a store built without the
    primary key could match a solar-only listing for solar + pool."""
    u = universe()
    u.add(61_001, "Duarte", [label("solar")])
    world["engine"] = engine_for(u)
    path = build_store(world["tmp"] / "nopk.sqlite3", u)
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE loose (listing_key TEXT NOT NULL, facet TEXT NOT NULL,"
        " status TEXT NOT NULL);"
        "INSERT INTO loose SELECT * FROM facets; DROP TABLE facets;"
        "ALTER TABLE loose RENAME TO facets;"
        "INSERT INTO facets VALUES ('61001', 'solar', 'present');"
    )
    db.commit()
    with fa.FeatureAccess(path) as access:
        ready = access.readiness(conn_of(world))
    assert (ready.status, ready.reason) == ("unavailable", "malformed")
    # Matching itself counts distinct facets, independent of validation.
    raw = effective_store.FacetStore(db, ready.info)
    assert "61001" in raw.keys_with_all(["solar"])
    assert "61001" not in raw.keys_with_all(["solar", "pool"])
    raw.close()


def test_server_keeps_no_dead_copies_of_the_thresholds(world, monkeypatch):  # noqa: F811
    """Review of #142: patching the server's old names did nothing; the only knobs
    are in enrichment.access, and patching them there takes effect."""
    assert not hasattr(mcp, "FEATURE_STALE_SHARE")
    assert not hasattr(mcp, "FRESHNESS_TTL_SECONDS")
    monkeypatch.setattr(fa.db_listings, "fetch_freshness", lambda w, c: (100, 5))
    fa.reset_for_tests()
    assert search(city="Glendale", features=["solar"]).data.feature_filter.status == (
        "applied"
    )
    monkeypatch.setattr(fa, "STALE_SHARE", 0.01)
    fa.reset_for_tests()
    assert search(city="Glendale", features=["solar"]).data.feature_filter.status == (
        "stale"
    )


def test_lookup_reports_changed_keys_with_present_features(world):  # noqa: F811
    altadena = [40_001, 40_002, 40_003, 40_004, 40_005, 19_999]
    with usable(world) as access:
        found = access.lookup(altadena, conn_of(world))
        assert found.present == access.present_features(altadena, conn_of(world))
    assert set(found.present) == {"40001"}
    assert found.changed == {"40002", "40003", "40004", "40005"}


def test_badge_log_counts_cards_left_out_as_changed(world, monkeypatch):  # noqa: F811
    """Review of #142: the refactor dropped `badges_left_out` from the search log."""
    monkeypatch.setenv("IDX_FEATURE_BADGES", "1")
    seen = []
    real = mcp._card_badges

    def spy(listings, checked, access, conn, log):
        out = real(listings, checked, access, conn, log)
        seen.append((list(listings), dict(log)))
        return out

    monkeypatch.setattr(mcp, "_card_badges", spy)
    search(city="Altadena")
    ((listings, log),) = seen
    with usable(world) as access:
        moved = access.changed_keys([x.listing_key for x in listings], conn_of(world))
    assert moved and log["badges_left_out"] == len(moved)


def test_a_closed_access_reports_closed_and_reads_nothing(world):  # noqa: F811
    """Review of #142: after close, readiness still said usable."""
    access = fa.FeatureAccess(world["path"])
    with access:
        info = access.readiness(conn_of(world)).info
    before = len(world["statements"])
    ready = access.readiness(conn_of(world))
    assert (ready.status, ready.reason, ready.info) == ("unavailable", "closed", info)
    assert access.open() == ready
    bound = access.bind(["solar"], conn_of(world))
    assert (bound.status, bound.reason, bound.scope) == ("unavailable", "closed", None)
    with pytest.raises(RuntimeError, match="closed"):
        access.present_features(["10000"], conn_of(world))
    with pytest.raises(RuntimeError, match="closed"):
        access.changed_keys(["10000"], conn_of(world))
    assert len(world["statements"]) == before
    access.close()  # closing twice is harmless and keeps the provenance
    assert access.open().info == info


# --- Store replacement and resource cleanup ---


def test_replacing_the_store_takes_effect_for_the_next_access(world):  # noqa: F811
    u = universe()
    with usable(world) as old:
        assert "50000" in old.present_features(["50000"], conn_of(world))
        # Replace the file atomically with a store where 50000 has no label at all.
        u.results = [r for r in u.results if r[1] != "50000"]
        replacement = world["tmp"] / "next.sqlite3"
        build_store(replacement, u)
        os.replace(replacement, world["path"])
        # The open access keeps reading the store it validated; it does not crash.
        assert "50000" in old.present_features(["50000"], conn_of(world))
    with usable(world) as new:
        assert new.present_features(["50000"], conn_of(world)) == {}


def test_a_replacement_that_fails_validation_is_unavailable(world):  # noqa: F811
    with usable(world):
        pass
    db = sqlite3.connect(world["path"])
    db.execute("UPDATE meta SET value = 'other' WHERE name = 'results_digest'")
    db.commit()
    db.close()
    with fa.FeatureAccess(world["path"]) as access:
        ready = access.readiness(conn_of(world))
    assert (ready.status, ready.reason) == ("unavailable", "source_mismatch")


def test_store_is_closed_on_exit_and_on_error(world):  # noqa: F811
    tracking = Tracking()
    with fa.FeatureAccess(world["path"], opener=tracking) as access:
        access.readiness(conn_of(world))
    with pytest.raises(ZeroDivisionError):
        with fa.FeatureAccess(world["path"], opener=tracking) as access:
            access.readiness(conn_of(world))
            raise ZeroDivisionError
    assert [r["closed"] for r in tracking.opened] == [True, True]


def test_search_opens_the_store_once_and_closes_it(world, monkeypatch):  # noqa: F811
    tracking = Tracking()
    monkeypatch.setattr(mcp.effective_store, "open_store", tracking)
    monkeypatch.setenv("IDX_FEATURE_BADGES", "1")
    result = search(city="Glendale", features=["solar"])
    assert result.data.feature_filter.status == "applied"
    assert result.data.card_badges is not None
    assert [r["closed"] for r in tracking.opened] == [True]


def test_badges_alone_open_and_close_their_own_store(world, monkeypatch):  # noqa: F811
    tracking = Tracking()
    monkeypatch.setattr(mcp.effective_store, "open_store", tracking)
    monkeypatch.setenv("IDX_FEATURE_BADGES", "1")
    result = search(city="Glendale")
    assert result.data.card_badges is not None
    assert [r["closed"] for r in tracking.opened] == [True]


def test_a_failed_connection_still_closes_the_store(world, monkeypatch):  # noqa: F811
    tracking = Tracking()
    monkeypatch.setattr(mcp.effective_store, "open_store", tracking)

    def broken(config=None):
        raise OSError("down")

    monkeypatch.setattr(mcp.db_pool, "connect", broken)
    result = mcp.search_listings(city="Glendale", features=["solar"])
    assert result["ok"] is False
    assert [r["closed"] for r in tracking.opened] == [True]


def test_ordinary_search_never_opens_the_store(world, monkeypatch):  # noqa: F811
    tracking = Tracking()
    monkeypatch.setattr(mcp.effective_store, "open_store", tracking)
    monkeypatch.delenv("IDX_FEATURE_BADGES", raising=False)
    result = search(city="Glendale")
    assert result.ok and result.data.feature_filter is None
    assert tracking.opened == []
    assert not any("ModificationTimestamp" in sql for sql, _ in world["statements"])


# --- Ordering helper ---


def test_ordered_puts_requested_first_then_a_to_z():
    feats = {"solar", "pool", "garage", "patio"}
    assert fa.ordered(feats, ["pool", "adu", "pool", "solar"]) == [
        "pool",
        "solar",
        "garage",
        "patio",
    ]
    assert fa.ordered(feats) == ["garage", "patio", "pool", "solar"]
    assert fa.ordered(set(), ["solar"]) == []
