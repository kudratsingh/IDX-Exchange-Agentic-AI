"""`search_listings` with remark features (WO-021), over the MCP layer, no database.

A real effective store is written to tmp_path from invented rows; the database layer is
replaced with recording fakes. Covers unchanged searches without features, fail-closed
unavailable and stale stores, freshness, and the visible accuracy limitation.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from idx_agent.db import listings as db_listings
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import Clarification, Listing, SearchResult
from idx_agent.domain.results import AgentResult
from idx_agent.enrichment import effective_store
from idx_agent.enrichment.source_check import EXPECTED_RESULTS_DIGEST
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore

Envelope = AgentResult[SearchResult | Clarification]
ASOF = AsOfDates(sold=date(2026, 6, 30), active=date(2026, 7, 2))
WATERMARK = "2026-09-18 06:58:44"
META = {
    "source_watermark": WATERMARK,
    "policy_version": "v4",
    "rules_version": "2026-11-01.4",
    "source_rows": "6",
    # Only the meta value is checked at open; the rows here are invented.
    "results_digest": EXPECTED_RESULTS_DIGEST,
    "built_from": json.dumps({"overlay": "invented"}),
}
ROWS = [
    ("101", {"solar": "present", "walk_in_closet": "present"}),
    ("102", {"solar": "planned", "walk_in_closet": "present"}),
    ("103", {"solar": "uncertain"}),
    ("104", {"solar": "stated_absent"}),
    ("105", {"solar": "historical"}),
    ("106", {}),
]


def _listing(key):
    return Listing(
        listing_key=key,
        listing_id=f"INV{key}",
        address=f"{key} Invented Way",
        city="Pasadena",
        postal_code="91101",
        list_price=1_000_000 + key,
        bedrooms=3,
    )


class FakeConn:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A store on disk plus a fake database; returns a dict recording calls."""
    path = tmp_path / "effective.sqlite3"
    effective_store.write_store(path, ROWS, META)
    calls = {"search": [], "count": [], "changed": [], "fresh": (1000, 5), "path": path}

    def search(filters, conn, scope=None):
        calls["search"].append(scope)
        keys = [int(k) for k in scope.keys] if scope else [900, 901]
        return db_listings.SearchOutcome(listings=[_listing(k) for k in keys])

    def count(filters, conn, scope=None):
        calls["count"].append(scope)
        return 0

    def changed(filters, scope, conn):
        calls["changed"].append(scope)
        return 2

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", lambda config=None: FakeConn())
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", count)
    monkeypatch.setattr(mcp.db_listings, "count_changed_since", changed)
    monkeypatch.setattr(
        mcp.db_listings, "fetch_freshness", lambda watermark, conn: calls["fresh"]
    )
    monkeypatch.setattr(
        mcp.effective_store, "configured_store_path", lambda: calls["path"]
    )
    monkeypatch.setattr(
        mcp,
        "memory_key",
        lambda raw, secret=None: raw and hashlib.sha256(raw.encode()).hexdigest(),
    )
    mcp.reset_store_for_tests(
        InMemorySessionStore(
            timedelta(minutes=30), 10, lambda: datetime(2026, 7, 2, tzinfo=UTC)
        )
    )
    yield calls
    mcp.reset_store_for_tests()


def run(**kwargs):
    return Envelope.model_validate(mcp.search_listings(city="Pasadena", **kwargs))


def test_search_without_features_never_opens_the_store(world, monkeypatch):
    def refuse(path):
        raise AssertionError("store opened for a search without features")

    monkeypatch.setattr(mcp.effective_store, "open_store", refuse)
    result = run()
    assert result.ok and result.data.feature_filter is None
    assert world["search"] == [None]
    assert "Features matched" not in result.message
    assert "applied_filters" in result.model_dump(mode="json")["data"]
    assert result.data.applied_filters.features is None


def test_applied_feature_filter_matches_only_present_features(world):
    result = run(features=["solar"])
    scope = world["search"][0]
    assert scope.keys == ("101",)
    assert scope.watermark == WATERMARK
    feature = result.data.feature_filter
    assert feature.status == "applied"
    assert feature.features == ["solar"]
    assert feature.snapshot_watermark == WATERMARK
    assert feature.policy_version == "v4"
    assert feature.changed_since_snapshot == 2
    assert [x.listing_key for x in result.data.listings] == [101]


def test_every_requested_feature_must_be_present(world):
    run(features=["walk_in_closet", "solar"])
    assert world["search"][0].keys == ("101",)
    run(features=["walk_in_closet"])
    assert world["search"][1].keys == ("101", "102")


def test_reply_shows_features_freshness_and_limitation(world):
    message = run(features=["solar"]).message
    assert (
        "Features matched from listing descriptions as of 2026-09-18: solar." in message
    )
    assert "2 matching listing(s) changed since then" in message
    assert mcp.FEATURE_LIMITATION in message
    assert "features solar" in message


def test_no_listing_with_every_feature_is_a_match_not_an_outage(world):
    result = run(features=["garage"])
    assert result.ok
    assert result.data.feature_filter.status == "applied"
    assert result.data.listings == []
    assert world["search"] == []
    assert mcp.FEATURE_LIMITATION in result.message


@pytest.mark.parametrize("reason", ["not_configured", "missing", "incomplete"])
def test_unavailable_store_fails_closed_without_querying(world, monkeypatch, reason):
    monkeypatch.setattr(
        mcp.effective_store,
        "open_store",
        lambda path: effective_store.StoreUnavailable(reason),
    )
    result = run(features=["solar"])
    assert result.ok
    assert result.data.listings == []
    assert result.data.feature_filter.status == "unavailable"
    assert result.data.feature_filter.limitation == mcp.FEATURE_LIMITATION
    assert result.message == mcp.FEATURE_UNAVAILABLE_MESSAGE
    assert world["search"] == []


def test_a_real_missing_store_is_unavailable(world, tmp_path):
    world["path"] = tmp_path / "absent.sqlite3"
    result = run(features=["solar"])
    assert result.data.feature_filter.status == "unavailable"


def test_stale_snapshot_fails_closed(world):
    world["fresh"] = (1000, 101)
    result = run(features=["solar"])
    assert result.data.listings == []
    assert result.data.feature_filter.status == "stale"
    assert result.data.feature_filter.snapshot_watermark == WATERMARK
    assert result.message == mcp.FEATURE_STALE_MESSAGE
    assert world["search"] == []


def test_snapshot_at_the_stale_threshold_is_still_used(world):
    world["fresh"] = (1000, 100)
    assert run(features=["solar"]).data.feature_filter.status == "applied"


def test_empty_listing_table_counts_as_stale(world):
    world["fresh"] = (0, 0)
    assert run(features=["solar"]).data.feature_filter.status == "stale"


def test_unknown_feature_is_a_clarification(world):
    result = run(features=["jacuzzi"])
    assert isinstance(result.data, Clarification)
    assert result.data.reason == "unknown_feature"
    assert "solar" in result.data.options
    assert world["search"] == []


def test_a_follow_up_keeps_and_can_clear_features(world):
    mcp.search_listings(city="Pasadena", features=["solar"], sender_id="invented-1")
    updated = Envelope.model_validate(
        mcp.search_listings(min_beds=3, sender_id="invented-1", mode="update")
    )
    assert updated.data.applied_filters.features == ("solar",)
    cleared = Envelope.model_validate(
        mcp.search_listings(sender_id="invented-1", mode="update", clear=["features"])
    )
    assert cleared.data.applied_filters.features is None
    assert cleared.data.feature_filter is None


def test_the_tool_lists_the_eligible_features():
    import asyncio

    tool = next(
        t for t in asyncio.run(mcp.server.list_tools()) if t.name == "search_listings"
    )
    description = tool.input_schema["properties"]["features"]["description"]
    assert "walk_in_closet" in description and "office" not in description


def test_page_past_one_with_no_feature_match_counts_zero(world):
    result = run(features=["garage"], page=2)
    assert result.data.total_matches == 0
    assert world["count"] == []
    assert world["search"] == []


def test_paging_a_feature_search_keeps_its_scope(world):
    mcp.search_listings(city="Pasadena", features=["solar"], sender_id="invented-2")
    more = Envelope.model_validate(
        mcp.search_listings(sender_id="invented-2", mode="more")
    )
    assert more.data.applied_filters.page == 2
    assert [s.keys for s in world["search"]] == [("101",), ("101",)]
    assert all(scope is not None for scope in world["count"])


def test_a_refused_search_keeps_its_features_until_explicitly_cleared(
    world, monkeypatch
):
    mcp.search_listings(city="Pasadena", sender_id="invented-3")
    monkeypatch.setattr(
        mcp.effective_store,
        "open_store",
        lambda path: effective_store.StoreUnavailable("missing"),
    )
    refused = Envelope.model_validate(
        mcp.search_listings(city="Irvine", features=["solar"], sender_id="invented-3")
    )
    assert refused.data.feature_filter.status == "unavailable"
    # A refinement never drops the features the user asked for.
    refined = Envelope.model_validate(
        mcp.search_listings(max_price=1_000_000, sender_id="invented-3", mode="update")
    )
    assert refined.data.applied_filters.city == "Irvine"
    assert refined.data.applied_filters.features == ("solar",)
    assert refined.data.feature_filter.status == "unavailable"
    assert world["search"] == [None]
    # Only an explicit clear broadens it, in the area the user asked about.
    plain = Envelope.model_validate(
        mcp.search_listings(sender_id="invented-3", mode="update", clear=["features"])
    )
    assert plain.data.applied_filters.city == "Irvine"
    assert plain.data.applied_filters.max_price == 1_000_000
    assert plain.data.applied_filters.features is None
    assert world["search"] == [None, None]


def test_store_is_closed_when_the_database_connection_fails(world, monkeypatch):
    closed = []
    real_open = effective_store.open_store

    def tracking_open(path):
        store = real_open(path)
        original = store.close
        store.close = lambda: (closed.append(True), original())
        return store

    def broken_connect(config=None):
        raise OSError("database down")

    monkeypatch.setattr(mcp.effective_store, "open_store", tracking_open)
    monkeypatch.setattr(mcp.db_pool, "connect", broken_connect)
    result = run(features=["solar"])
    assert not result.ok and result.error.category == "db"
    assert closed == [True]


def test_an_oversized_feature_scope_fails_closed(world, monkeypatch):
    monkeypatch.setattr(mcp.db_listings, "MAX_FEATURE_KEYS", 0)
    result = run(features=["solar"])
    assert result.data.feature_filter.status == "unavailable"
    assert result.message == mcp.FEATURE_UNAVAILABLE_MESSAGE
    assert world["search"] == []


def test_a_search_without_features_keeps_its_earlier_payload_shape(world):
    data = mcp.search_listings(city="Pasadena")["data"]
    assert set(data) == {
        "listings",
        "applied_filters",
        "total_matches",
        "narrowing_question",
    }
    assert "features" not in data["applied_filters"]


def test_an_empty_features_list_never_clears_refused_features(world, monkeypatch):
    monkeypatch.setattr(
        mcp.effective_store,
        "open_store",
        lambda path: effective_store.StoreUnavailable("missing"),
    )
    mcp.search_listings(city="Irvine", features=["solar"], sender_id="invented-4")
    again = Envelope.model_validate(
        mcp.search_listings(
            max_price=1_000_000, features=[], sender_id="invented-4", mode="update"
        )
    )
    assert again.data.applied_filters.features == ("solar",)
    assert again.data.feature_filter.status == "unavailable"
    assert world["search"] == []


def test_a_refused_later_page_is_not_stored(world, monkeypatch):
    real_open = effective_store.open_store
    available = {"store": True}

    def switchable_open(path):
        if available["store"]:
            return real_open(path)
        return effective_store.StoreUnavailable("missing")

    monkeypatch.setattr(mcp.effective_store, "open_store", switchable_open)
    mcp.search_listings(city="Pasadena", features=["solar"], sender_id="invented-5")
    available["store"] = False
    refused = Envelope.model_validate(
        mcp.search_listings(sender_id="invented-5", mode="more")
    )
    assert refused.data.feature_filter.status == "unavailable"
    assert refused.data.applied_filters.page == 2
    available["store"] = True
    back = Envelope.model_validate(
        mcp.search_listings(sender_id="invented-5", mode="more")
    )
    # Page 2 is shown next, not page 3: the refused page was never stored.
    assert back.data.applied_filters.page == 2
    assert back.data.feature_filter.status == "applied"


def test_freshness_counts_are_reused_briefly_then_read_again(world, monkeypatch):
    """The full-scan freshness counts are cached per snapshot for a short time only."""
    reads = []
    monkeypatch.setattr(
        mcp.db_listings,
        "fetch_freshness",
        lambda watermark, conn: reads.append(watermark) or world["fresh"],
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(mcp.feature_access.time, "monotonic", lambda: clock["now"])
    run(features=["solar"])
    world["fresh"] = (1000, 500)
    # Within the window the earlier counts stand; the per-listing test is unaffected.
    assert run(features=["solar"]).data.feature_filter.status == "applied"
    clock["now"] += mcp.FRESHNESS_TTL_SECONDS
    assert run(features=["solar"]).data.feature_filter.status == "stale"
    assert reads == [WATERMARK, WATERMARK]
