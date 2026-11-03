"""Card badges (WO-021 increment 2): present remark features on search cards, off by
default. Same harness as the feature-search acceptance: the real tool path over an
SQLite stand-in and a real store from invented rows; nothing here is real data."""

from datetime import date

import pytest
from tests.test_feature_search_acceptance import (
    AFTER,
    FACETS,
    MATCHING,
    VARIANTS,
    build_store,
    facet_key,
    keys,
    search,
    world,  # noqa: F401 - the shared fixture
)

from idx_agent.channels.format import (
    BADGE_PREFIX,
    format_listing_card,
    format_search_reply,
)
from idx_agent.domain.models import Listing
from idx_agent.mcp_server import server as mcp

LISTING = Listing(
    listing_key=7,
    listing_id="INV7",
    address="7 Invented Way",
    city="Pasadena",
    postal_code="91101",
    list_price=1_000_000,
    bedrooms=3,
    pool=True,
)


@pytest.fixture
def badges_on(monkeypatch):
    monkeypatch.setenv(mcp.BADGES_SETTING, "1")


def badge_lines(message):
    return [line for line in message.splitlines() if line.startswith(BADGE_PREFIX)]


def card_badges(result):
    found = result.data.card_badges
    return found.badges if found else {}


# --- Off by default: nothing changes ---


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", " 2 "])
def test_badges_are_off_unless_the_setting_is_one(world, monkeypatch, value):  # noqa: F811
    if value is None:
        monkeypatch.delenv(mcp.BADGES_SETTING, raising=False)
    else:
        monkeypatch.setenv(mcp.BADGES_SETTING, value)

    def refuse(path):
        raise AssertionError("store opened for a search without features")

    monkeypatch.setattr(mcp.effective_store, "open_store", refuse)
    result = search(city="Pasadena", limit=50)
    assert result.ok and result.data.card_badges is None
    assert "card_badges" not in result.model_dump(mode="json")["data"]
    assert badge_lines(result.message) == []
    assert all("ModificationTimestamp" not in sql for sql, _ in world["statements"])


def test_off_by_default_a_feature_search_is_unchanged(world, monkeypatch):  # noqa: F811
    monkeypatch.delenv(mcp.BADGES_SETTING, raising=False)
    result = search(city="Sierra Madre", features=["solar"])
    assert result.data.card_badges is None and badge_lines(result.message) == []


def test_cards_render_exactly_as_before_without_badges():
    assert format_listing_card(LISTING, date(2026, 9, 18)) == format_listing_card(
        LISTING, date(2026, 9, 18), None
    )
    assert format_listing_card(LISTING, date(2026, 9, 18), []) == format_listing_card(
        LISTING, date(2026, 9, 18)
    )
    plain = format_search_reply([LISTING], date(2026, 9, 18), "Filters: city Pasadena")
    assert plain == format_search_reply(
        [LISTING], date(2026, 9, 18), "Filters: city Pasadena", badges={}
    )


def test_the_badge_line_follows_the_flags_and_keeps_every_card_fact():
    plain = format_listing_card(LISTING, date(2026, 9, 18)).splitlines()
    badged = format_listing_card(
        LISTING, date(2026, 9, 18), ["walk_in_closet", "adu"]
    ).splitlines()
    flags = plain.index("pool")
    assert badged[: flags + 1] == plain[: flags + 1]
    assert badged[flags + 1] == f"{BADGE_PREFIX} walk-in closet, ADU"
    assert badged[flags + 2 :] == plain[flags + 1 :]


# --- On: present only, same status and freshness rules as feature search ---


def price_of(key):
    return 500_000 + key * 10


@pytest.mark.parametrize("facet", FACETS)
def test_only_present_statuses_get_a_badge(world, badges_on, facet):  # noqa: F811
    low = price_of(facet_key(facet, "present"))
    high = price_of(facet_key(facet, "unknown"))
    result = search(city="Pasadena", min_price=low, max_price=high, limit=50)
    assert sorted(keys(result)) == sorted(facet_key(facet, v) for v in VARIANTS)
    expected = {facet_key(facet, v): [facet] for v in MATCHING}
    assert card_badges(result) == expected


def test_a_listing_never_extracted_has_no_badge(world, badges_on):  # noqa: F811
    result = search(city="Pasadena", min_price=price_of(19_999), limit=5)
    assert 19_999 in keys(result) and 19_999 not in card_badges(result)


def test_requested_features_first_then_alphabetical_at_most_three(world, badges_on):  # noqa: F811
    plain = search(city="Sierra Madre", limit=50)
    assert card_badges(plain)[20_001] == ["pool", "solar"]
    assert card_badges(plain)[20_003] == ["solar"]  # pool planned: no badge
    asked = search(city="Sierra Madre", features=["solar"], limit=50)
    assert card_badges(asked)[20_001] == ["solar", "pool"]
    assert all(len(v) <= mcp.MAX_BADGES for v in card_badges(asked).values())


def test_at_most_three_badges_per_card(world, badges_on):  # noqa: F811
    extra = [
        dict(group="g", value=v, polarity="affirmed", temporality="current")
        for v in ("adu", "patio", "pool", "solar")
    ]
    universe = world["universe"]
    universe.results = [
        (s, k, [*labels, *extra] if k == "30005" else labels)
        for s, k, labels in universe.results
    ]
    world["path"] = build_store(world["tmp"] / "many.sqlite3", universe)
    price = price_of(30_005)
    result = search(city="Arcadia", min_price=price, max_price=price)
    assert keys(result) == [30_005]
    # garage, adu, patio, pool, solar are present: the first three A-Z are shown.
    assert card_badges(result)[30_005] == ["adu", "garage", "patio"]


def test_changed_listings_show_no_badge_but_still_show(world, badges_on):  # noqa: F811
    result = search(city="Altadena", limit=50)
    assert sorted(keys(result)) == [
        40_001,
        40_002,
        40_002,
        40_003,
        40_004,
        40_004,
        40_005,
    ]
    assert card_badges(result) == {40_001: ["patio"]}
    assert result.data.card_badges.snapshot_watermark.startswith("2026-09-18")


def test_a_stale_store_shows_no_badges_and_the_search_stands(world, badges_on):  # noqa: F811
    engine = world["engine"]
    rows = engine.execute("SELECT COUNT(*) FROM rets_property").fetchone()[0]
    engine.execute(
        "UPDATE rets_property SET ModificationTimestamp = ? WHERE rowid <= ?",
        (AFTER, rows // 10 + 1),
    )
    result = search(city="Glendale", limit=50)
    assert result.ok and len(result.data.listings) == 10
    assert result.data.card_badges is None and badge_lines(result.message) == []


@pytest.mark.parametrize("variant", ["unconfigured", "missing", "junk"])
def test_an_unusable_store_shows_no_badges_and_the_search_stands(
    world,  # noqa: F811
    badges_on,
    variant,
):
    if variant == "unconfigured":
        world["path"] = None
    elif variant == "missing":
        world["path"] = world["tmp"] / "absent.sqlite3"
    else:
        world["path"] = world["tmp"] / "junk.sqlite3"
        world["path"].write_text("not a database")
    result = search(city="Glendale", limit=50)
    assert result.ok and len(result.data.listings) == 10
    assert result.data.card_badges is None
    assert mcp.FEATURE_LIMITATION not in result.message


def test_a_badge_failure_never_fails_the_search(world, badges_on, monkeypatch):  # noqa: F811
    def broken(keys, watermark, conn):
        raise RuntimeError("invented failure")

    monkeypatch.setattr(mcp.db_listings, "fetch_changed_keys", broken)
    result = search(city="Glendale", limit=50)
    assert result.ok and len(result.data.listings) == 10
    assert result.data.card_badges is None


def test_a_refused_feature_search_has_no_badges(world, badges_on):  # noqa: F811
    world["path"] = world["tmp"] / "absent.sqlite3"
    result = search(city="Glendale", features=["solar"])
    assert result.data.feature_filter.status == "unavailable"
    assert result.data.card_badges is None
    assert result.message == mcp.FEATURE_UNAVAILABLE_MESSAGE


# --- Snapshot attribution and the limitation ---


def test_badged_reply_names_the_snapshot_and_shows_the_limitation_once(
    world,  # noqa: F811
    badges_on,
):
    plain = search(city="Glendale", limit=50)
    assert len(badge_lines(plain.message)) == 10  # 7 solar, 3 garage
    assert "descriptions as of 2026-09-18." in plain.message
    assert plain.message.count(mcp.FEATURE_LIMITATION) == 1
    assert plain.data.card_badges.limitation == mcp.FEATURE_LIMITATION
    asked = search(city="Glendale", features=["solar"], limit=50)
    assert asked.message.count(mcp.FEATURE_LIMITATION) == 1
    assert "Features matched from listing descriptions as of 2026-09-18" in (
        asked.message
    )


def test_badges_on_a_later_page_and_with_more(world, badges_on):  # noqa: F811
    search(city="Glendale", limit=3, sender_id="badges")
    more = search(sender_id="badges", mode="more")
    assert more.data.applied_filters.page == 2
    shown = set(keys(more))
    assert set(card_badges(more)) == shown & set(range(50_000, 50_007))


def test_no_results_with_badges_on_has_no_badges_note_or_limitation(world, badges_on):  # noqa: F811
    """Review for WO-024: an empty search shows no badge note and no limitation."""
    result = search(city="Pasadena", min_price=99_000_000)
    assert result.ok and result.data.listings == []
    assert result.data.card_badges is None
    assert "card_badges" not in result.model_dump(mode="json")["data"]
    assert badge_lines(result.message) == []
    assert mcp.FEATURE_LIMITATION not in result.message
    assert "descriptions as of" not in result.message


def test_explanations_switch_never_turns_badges_on(world, monkeypatch):  # noqa: F811
    """WO-024's switch is independent of IDX_FEATURE_BADGES: search stays unbadged."""
    monkeypatch.delenv(mcp.BADGES_SETTING, raising=False)
    monkeypatch.setenv(mcp.EXPLANATIONS_SETTING, "1")
    result = search(city="Glendale", limit=50)
    assert result.data.card_badges is None and badge_lines(result.message) == []
