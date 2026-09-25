"""The `recommend` tool (WO-011) over the MCP layer, with no database and no provider.

A tiny `test:hashing` index of invented remarks (IDX_SEMANTIC_INDEX_DIR); the fetches,
comps aggregate, and as-of dates are faked. Covers the four outcomes, k 0, the session
path, the log line, spans, payload, and no-embedder imports. No key, network, MySQL."""

import asyncio
import json
import os
import pathlib
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pymysql
import pytest

from idx_agent.channels.format import (
    NO_SIMILAR_LINE,
    RECOMMEND_EXPLANATION,
    format_recommendations,
)
from idx_agent.db import comps as db_comps
from idx_agent.db import listings as db_listings
from idx_agent.db import market as db_market
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.comps import (
    CompsAggregate,
    contains_forbidden,
    price_band,
    sentence_shape,
)
from idx_agent.domain.models import (
    KEY_WINS_WARNING,
    RECOMMEND_QUESTIONS,
    Clarification,
    Listing,
    PropertySearchFilters,
    RecommendationResult,
    RecommendRequest,
    SearchResult,
)
from idx_agent.domain.results import AgentResult
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST
from idx_agent.semantic import embedder as semantic_embedder
from idx_agent.semantic.embedder import HashingEmbedder
from idx_agent.semantic.index import IndexAttrs, load_index, write_index
from idx_agent.semantic.neighbors import rank_neighbors

Envelope = AgentResult[RecommendationResult | Clarification]
DIMS = 64
INDEX_ASOF = date(2026, 9, 18)
ASOF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SFR, CONDO = "SingleFamilyResidence", "Condominium"
# A marker that must never leave the server in a log line, a span, or the payload.
REMARK_MARKER = "REMARK-MARKER-RQ7"
SRC = str(pathlib.Path(mcp.__file__).resolve().parents[2])

# Invented listings: key -> (city, subtype, price, living area, remarks). Every row has
# 3 beds and ZIP 91101. The subject 9870001 lists at 1,000,000: band 750,000-1,250,000.
SUBJECT = 9870001
ROWS = {
    9870001: ("Pasadena", SFR, 1_000_000, 2000, "craftsman bungalow with oak floors"),
    9870002: ("Pasadena", SFR, 950_000, 1900, "craftsman home with oak trim and porch"),
    9870003: ("Pasadena", SFR, 1_200_000, 2400, "spanish revival with tile roof"),
    9870004: ("Pasadena", SFR, 800_000, 1600, "bungalow with a porch and oak floors"),
    9870005: (
        "Pasadena",
        CONDO,
        900_000,
        1200,
        "craftsman style condo with oak floors",
    ),
    9870006: ("Monrovia", SFR, 1_000_000, 2000, "craftsman bungalow with oak floors"),
    9870007: ("Pasadena", SFR, 1_300_000, 2600, "craftsman bungalow above the band"),
    9870008: ("Pasadena", SFR, 760_000, None, "small bungalow with oak floors"),
    9870009: ("Pasadena", SFR, 1_100_000, 2200, "ranch home with a craftsman porch"),
}
# Active in the database but never indexed (its vector is missing).
NOT_INDEXED = 9870010
ALL_ROWS = {NOT_INDEXED: ("Pasadena", SFR, 1_000_000, 2000, "not in the index"), **ROWS}
CANDIDATES = {9870002, 9870003, 9870004, 9870008, 9870009}


def _listing(key: int) -> Listing:
    """The invented listing for `key`, carrying a remark that must never leave."""
    city, subtype, price, area, remarks = ALL_ROWS[key]
    return Listing(
        listing_key=key,
        listing_id=str(key + 400000),
        address=f"{key % 1000} Invented Way",
        city=city,
        postal_code="91101",
        list_price=price,
        bedrooms=3,
        bathrooms=2.0,
        living_area=area,
        property_subtype=subtype,
        status="Active",
        days_on_market=9,
        photo_count=4,
        remarks=f"{remarks} {REMARK_MARKER}",
    )


def _write_index(path: pathlib.Path, as_of: date = INDEX_ASOF) -> pathlib.Path:
    """Embed the invented remarks with the hashing embedder and write the index."""
    keys = sorted(ROWS)
    write_index(
        path,
        vectors=HashingEmbedder(DIMS).embed([ROWS[k][4] for k in keys]),
        keys=keys,
        attrs=IndexAttrs.from_values(
            city=[ROWS[k][0] for k in keys],
            list_price=[ROWS[k][2] for k in keys],
            bedrooms=[3] * len(keys),
            property_subtype=[ROWS[k][1] for k in keys],
        ),
        model="test:hashing",
        active_as_of=as_of,
    )
    return path


# The index directory of the running test (set by the `served` fixture).
INDEX_DIR: list[pathlib.Path] = []


def _expected(subject: int = SUBJECT, top: int = 200) -> list[tuple[int, float]]:
    """The neighbours the tool must rank, recomputed with rank_neighbors itself."""
    index = load_index(INDEX_DIR[0], "test:hashing", DIMS)
    city, subtype, price, _, _ = ALL_ROWS[subject]
    low, high = price_band(price)
    return rank_neighbors(index, subject, city, subtype, low, high, top)


def _settings(path: pathlib.Path) -> dict[str, str]:
    return {
        "IDX_SEMANTIC_INDEX_DIR": str(path),
        "IDX_EMBED_MODEL": "test:hashing",
        "IDX_EMBED_DIMS": str(DIMS),
    }


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Serve a fresh hashing index through the settings; forget it afterwards."""
    path = _write_index(tmp_path / "index")
    for name, value in _settings(path).items():
        monkeypatch.setenv(name, value)
    mcp.reset_semantic_for_tests()
    INDEX_DIR[:] = [path]
    yield path
    mcp.reset_semantic_for_tests()
    INDEX_DIR.clear()


class FakeConn:
    """Stands in for a database connection; records whether it was closed."""

    closed = False

    def close(self):
        self.closed = True


def _passes(key: int, f: PropertySearchFilters) -> bool:
    city, subtype, price, _, _ = ALL_ROWS[key]
    return (
        (f.city is None or f.city == city)
        and (f.property_subtype is None or f.property_subtype == subtype)
        and (f.min_price is None or price >= f.min_price)
        and (f.max_price is None or price <= f.max_price)
    )


@pytest.fixture
def fake_db(monkeypatch, served):
    """Patch pool, as-of, the listing fetch, and the comps statement set.

    The fetch returns every asked key that exists and passes the filters, in the
    asked order, minus calls["drop"]. Comps: 7 sales in the subject's ZIP, median
    $500 per sqft, middle half $450 to $560, unless calls["aggregate"] makes another.
    """
    calls = {
        "connect": 0,
        "fetch": [],
        "comps": [],
        "drop": set(),
        "asof": ASOF,
        "conns": [],
        "aggregate": None,
    }

    def connect(config=None):
        calls["connect"] += 1
        conn = FakeConn()
        calls["conns"].append(conn)
        return conn

    def fetch(filters, keys, conn):
        calls["fetch"].append((filters, list(keys)))
        found = [
            _listing(k)
            for k in keys
            if k in ALL_ROWS and k not in calls["drop"] and _passes(k, filters)
        ]
        return db_listings.SearchOutcome(listings=found)

    def comps(subject, window, as_of, conn):
        calls["comps"].append(subject.list_price)
        assert window.months == 6 and window.end == as_of.sold
        make = calls["aggregate"]
        if make is not None:
            return make(subject)
        return CompsAggregate(
            "postal_code",
            f"ZIP {subject.postal_code}",
            7,
            (Decimal("500"),),
            None,
            (Decimal("450"), Decimal("560")),
        )

    def search(filters, conn):
        return db_listings.SearchOutcome(listings=[_listing(SUBJECT)])

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", connect)
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: calls["asof"])
    monkeypatch.setattr(db_listings, "fetch_candidates", fetch)
    monkeypatch.setattr(db_comps, "fetch_comps", comps)
    monkeypatch.setattr(db_listings, "search_active_listings", search)
    return calls


def _recommend(**kwargs):
    """Call the MCP entry point and parse the envelope."""
    return Envelope.model_validate(mcp.recommend(**kwargs))


def _keys(value):
    """Every dict key found anywhere inside a JSON-like value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _log_lines(capsys):
    """The JSON log lines written to stderr since the last read, and the raw text."""
    err = capsys.readouterr().err
    return [json.loads(x) for x in err.strip().splitlines()], err


def _no_index(monkeypatch):
    """Make any index load fail the test."""

    def boom(*args, **kwargs):
        raise AssertionError("the index must not be loaded here")

    monkeypatch.setattr(mcp, "_semantic_index", boom)
    monkeypatch.setattr(mcp, "_semantic", boom)


# --- registration ---


def test_the_tool_is_registered_with_four_flat_arguments():
    assert "recommend" in mcp.tool_names()
    tool = next(
        t for t in asyncio.run(mcp.server.list_tools()) if t.name == "recommend"
    )
    props = set(tool.input_schema["properties"])
    assert props == set(RecommendRequest.model_fields)
    assert props == {"listing_key", "k", "sender_id", "position"}
    assert "recommend" in mcp.server.instructions


# --- recommendations ---


def test_recommendations_come_in_rank_order_with_checks_card_and_provenance(fake_db):
    envelope = _recommend(listing_key=SUBJECT)
    assert envelope.ok is True and envelope.error is None
    result = envelope.data
    assert isinstance(result, RecommendationResult)
    expected = _expected()[:5]
    assert [r.listing.listing_key for r in result.recommendations] == [
        k for k, _ in expected
    ]
    assert {k for k, _ in _expected()} == CANDIDATES
    assert result.k == 5 and result.index_as_of == INDEX_ASOF
    assert result.comps_window.months == 6 and result.comps_window.end == ASOF.sold
    assert result.subject.listing_key == SUBJECT and result.subject.remarks is None
    for rec, (_, score) in zip(result.recommendations, expected, strict=True):
        assert rec.listing.remarks is None
        assert rec.score_total == round(score, 4)
        assert rec.score_components == {"semantic": rec.score_total}
        assert rec.explanation == RECOMMEND_EXPLANATION
        assert rec.listing.city == "Pasadena" and rec.listing.property_subtype == SFR
        assert 750_000 <= rec.listing.list_price <= 1_250_000
    # 1,000,000 / 2000 = $500 per sqft, the stub's median: "at" the median.
    assert result.subject_check.sentence == (
        "Listed at the median price per square foot of 7 comparable sales in "
        "ZIP 91101 over the last six months."
    )
    assert result.subject_check.range_sentence == (
        "The middle half of those sales ran from $450 to $560 per square foot."
    )
    assert envelope.message == format_recommendations(result, ASOF)
    assert envelope.message.startswith("Similar to *1 Invented Way*:")
    assert "Similar 1 of 5" in envelope.message and envelope.warnings == []
    assert envelope.provenance.tables == ["rets_property", "california_sold"]
    assert envelope.provenance.as_of.active == ASOF.active
    assert envelope.provenance.as_of.sold == ASOF.sold
    assert envelope.provenance.tool == "recommend"
    # One connection, closed. The subject is fetched with no filter; the candidates
    # with the four hard filters, in rank order, once.
    assert fake_db["connect"] == 1 and fake_db["conns"][0].closed is True
    (subject_call, candidate_call) = fake_db["fetch"]
    assert subject_call == (PropertySearchFilters(), [SUBJECT])
    assert candidate_call == (
        PropertySearchFilters(
            city="Pasadena",
            property_subtype=SFR,
            min_price=750_000,
            max_price=1_250_000,
        ),
        [k for k, _ in _expected()],
    )


def test_each_listing_carries_its_own_fixed_shape_check(fake_db):
    result = _recommend(listing_key=SUBJECT).data
    by_key = {r.listing.listing_key: r.comp_evidence for r in result.recommendations}
    # 1,200,000 / 2400 = 500: at the median. 950,000 / 1900 = 500 too.
    assert by_key[9870003].delta_pct == 0.0 and by_key[9870003].sufficient
    # 1,100,000 / 2200 = 500; 800,000 / 1600 = 500. 9870008 has no living area.
    assert by_key[9870008].sufficient is False and by_key[9870008].level is None
    assert by_key[9870008].sentence == (
        "The price cannot be checked: this listing is missing its size, bedroom "
        "count, or type."
    )
    # The uncheckable listing ran no statement: subject plus four others.
    assert len(fake_db["comps"]) == 5
    for evidence in [result.subject_check, *by_key.values()]:
        assert sentence_shape(evidence.sentence) is not None
        if evidence.sufficient:
            assert sentence_shape(str(evidence.range_sentence)) == "range"


def test_a_percentage_above_and_below_is_worded_by_sign(fake_db):
    def aggregate(subject):
        # $400 per sqft: the subject at $500 is 25% above; 9870004 is too.
        return CompsAggregate(
            "postal_code",
            f"ZIP {subject.postal_code}",
            5,
            (Decimal("400"),),
            None,
            (Decimal("380"), Decimal("420")),
        )

    fake_db["aggregate"] = aggregate
    result = _recommend(listing_key=SUBJECT, k=1).data
    assert result.subject_check.delta_pct == 25.0
    assert result.subject_check.sentence.startswith("Listed 25% above the median")


@pytest.mark.parametrize("k", [1, 3, 5])
def test_k_caps_the_recommendations(fake_db, k):
    result = _recommend(listing_key=SUBJECT, k=k).data
    assert result.k == k and len(result.recommendations) == k


def test_k_defaults_to_five(fake_db):
    assert _recommend(listing_key=SUBJECT).data.k == 5


def test_fewer_than_k_says_so_in_the_warnings_and_the_card(fake_db):
    fake_db["drop"] = {9870002, 9870003, 9870004}
    envelope = _recommend(listing_key=SUBJECT)
    assert len(envelope.data.recommendations) == 2
    line = "Only 2 of the 5 similar listings asked for came back."
    assert line in envelope.warnings and line in envelope.message
    assert any("3 ranked listings were left out" in w for w in envelope.warnings)


def test_the_city_level_is_named_with_its_zip(fake_db):
    # Six comps: the two middles 450 and 550 average to 500, the subject's own.
    fake_db["aggregate"] = lambda s: CompsAggregate(
        "city",
        s.city,
        6,
        (Decimal("450"), Decimal("550")),
        f"ZIP {s.postal_code}",
        (Decimal("440.5"), Decimal("1560.5")),
    )
    envelope = _recommend(listing_key=SUBJECT, k=0)
    check = envelope.data.subject_check
    assert check.level == "city" and check.widened_from == "ZIP 91101"
    # Ends 440.5 -> 440 and 1,560.5 -> 1,560, each half-even.
    assert envelope.message == (
        "Listed at the median price per square foot of 6 comparable sales in "
        "Pasadena over the last six months (widened from ZIP 91101, which had too "
        "few). The middle half of those sales ran from $440 to $1,560 per square "
        "foot."
    )


# --- k 0: the price check alone ---


def test_k_zero_is_the_subject_sentence_alone_and_touches_no_index(
    fake_db, monkeypatch, capsys
):
    _no_index(monkeypatch)
    envelope = _recommend(listing_key=SUBJECT, k=0)
    assert envelope.ok is True
    result = envelope.data
    assert result.recommendations == [] and result.index_as_of is None
    check = result.subject_check
    assert envelope.message == f"{check.sentence} {check.range_sentence}"
    assert "\n" not in envelope.message
    assert fake_db["fetch"] == [(PropertySearchFilters(), [SUBJECT])]
    assert envelope.provenance.tables == ["rets_property", "california_sold"]
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "no_similar" and line["k"] == 0
    assert line["recommendations"] == 0 and line["index_as_of"] is None


def test_k_zero_works_with_no_index_configured(fake_db, monkeypatch):
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", "")
    mcp.reset_semantic_for_tests()
    envelope = _recommend(listing_key=SUBJECT, k=0)
    assert envelope.ok is True and isinstance(envelope.data, RecommendationResult)


# --- no similar listing ---


def test_a_mask_that_leaves_nothing_is_no_similar_and_fetches_no_candidate(
    fake_db, capsys
):
    """The Monrovia listing has no other Monrovia single-family row in the index."""
    envelope = _recommend(listing_key=9870006)
    assert envelope.ok is True
    result = envelope.data
    assert result.recommendations == [] and result.index_as_of == INDEX_ASOF
    check = result.subject_check
    assert envelope.message == "\n\n".join(
        [f"{check.sentence} {check.range_sentence}", NO_SIMILAR_LINE]
    )
    assert fake_db["fetch"] == [(PropertySearchFilters(), [9870006])]
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "no_similar" and line["keys_fetched"] == 0


def test_sql_dropping_every_candidate_is_no_similar(fake_db):
    fake_db["drop"] = CANDIDATES
    envelope = _recommend(listing_key=SUBJECT)
    assert envelope.ok is True and envelope.data.recommendations == []
    assert any("5 ranked listings were left out" in w for w in envelope.warnings)


def test_a_subject_with_no_vector_is_no_similar_with_a_warning_and_no_embedding(
    fake_db, monkeypatch
):
    def boom(*args, **kwargs):
        raise AssertionError("no embedder may be built or called")

    monkeypatch.setattr(semantic_embedder, "make_embedder", boom)
    monkeypatch.setattr(semantic_embedder.HashingEmbedder, "embed", boom)
    monkeypatch.setattr(semantic_embedder.OpenAIEmbedder, "embed", boom)
    envelope = _recommend(listing_key=NOT_INDEXED)
    assert envelope.ok is True and envelope.data.recommendations == []
    assert envelope.warnings == [mcp.NO_VECTOR_WARNING]
    assert fake_db["fetch"] == [(PropertySearchFilters(), [NOT_INDEXED])]


def test_the_ranking_builds_no_embedder(fake_db, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no embedder may be built or called")

    monkeypatch.setattr(semantic_embedder, "make_embedder", boom)
    monkeypatch.setattr(semantic_embedder.HashingEmbedder, "embed", boom)
    monkeypatch.setattr(semantic_embedder.OpenAIEmbedder, "__init__", boom)
    assert len(_recommend(listing_key=SUBJECT).data.recommendations) == 5


# --- the stale index ---


def test_an_index_older_than_the_database_adds_the_stale_line(fake_db):
    fake_db["asof"] = AsOfDates(sold=date(2026, 9, 24), active=date(2026, 9, 25))
    envelope = _recommend(listing_key=SUBJECT, k=1)
    (warning,) = envelope.warnings
    assert "listings added since 2026-09-18 are not ranked" in warning
    assert warning in envelope.message
    assert "Closed sales to 2026-09-24; listings as of 2026-09-25." in envelope.message


# --- Clarification ---


@pytest.mark.parametrize(
    ("kwargs", "field", "reason"),
    [
        ({}, "listing_key", "missing_listing"),
        ({"k": 3}, "listing_key", "missing_listing"),
        ({"listing_key": SUBJECT, "k": 6}, "k", "above_maximum"),
        ({"listing_key": SUBJECT, "k": -1}, "k", "below_minimum"),
        ({"listing_key": 0}, "listing_key", "below_minimum"),
        ({"sender_id": "sender-a", "position": 0}, "position", "below_minimum"),
        ({"position": 2}, "position", "no_session"),
        ({"sender_id": "sender-a", "position": 2}, "position", "no_session"),
    ],
)
def test_a_bad_request_is_a_clarification_that_runs_no_query(
    fake_db, monkeypatch, capsys, kwargs, field, reason
):
    _no_index(monkeypatch)
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: "a1" * 32)
    mcp.reset_store_for_tests(InMemorySessionStore(timedelta(minutes=30), 10, _clock))
    try:
        envelope = _recommend(**kwargs)
    finally:
        mcp.reset_store_for_tests()
    assert envelope.ok is True and isinstance(envelope.data, Clarification)
    assert envelope.data.field == field and envelope.data.reason == reason
    assert envelope.message == envelope.data.question
    if reason in RECOMMEND_QUESTIONS:
        assert envelope.message == RECOMMEND_QUESTIONS[reason]
    assert fake_db["connect"] == 0 and fake_db["fetch"] == [] and not fake_db["comps"]
    assert envelope.provenance.as_of.active is None and envelope.provenance.tables == []
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "clarification" and line["field"] == field


def test_an_unknown_argument_is_unsupported(fake_db, monkeypatch):
    _no_index(monkeypatch)
    envelope = mcp.recommend_result({"listing_key": SUBJECT, "city": "Pasadena"})
    assert isinstance(envelope.data, Clarification)
    assert envelope.data.reason == "unsupported_filter"
    assert fake_db["connect"] == 0


# --- the session: read once for a position, never written ---


def _clock():
    return datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class WriteRaisingStore(InMemorySessionStore):
    """A store any write fails; reads are counted."""

    def __init__(self, sessions=()):
        super().__init__(timedelta(minutes=30), 10, _clock)
        for session in sessions:
            super().put(session)
        self.gets = 0

    def get(self, key):
        self.gets += 1
        return super().get(key)

    def put(self, session):
        raise AssertionError("recommend must never write the session store")

    def reset(self, key):
        raise AssertionError("recommend must never reset the session store")


@pytest.fixture
def remembered(monkeypatch):
    """A sender whose last result showed three listings; writes fail the test."""
    from idx_agent.domain.models import UserSession

    keys = {"sender-a": "a1" * 32, "sender-b": "b2" * 32}
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: keys.get(raw))
    session = UserSession(
        sender_id=keys["sender-a"],
        last_result_keys=[9870004, SUBJECT, 9870009],
        updated_at=_clock(),
    )
    store = mcp.reset_store_for_tests(WriteRaisingStore([session]))
    yield store
    mcp.reset_store_for_tests()


def test_a_position_resolves_from_the_last_result_read_only(
    fake_db, remembered, capsys
):
    envelope = _recommend(sender_id="sender-a", position=2, k=2)
    assert envelope.ok is True
    assert envelope.data.subject.listing_key == SUBJECT
    assert remembered.gets == 1
    ((line,), err) = _log_lines(capsys)
    assert line["resolved_by"] == "position" and line["outcome"] == "recommendations"
    assert "sender-a" not in err


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sender_id": "sender-a", "position": 4},  # past the end of three
        {"sender_id": "sender-b", "position": 1},  # no session for this sender
        {"sender_id": "unknown", "position": 1},  # the id does not hash
    ],
)
def test_no_usable_session_is_the_no_session_clarification(fake_db, remembered, kwargs):
    envelope = _recommend(**kwargs)
    assert isinstance(envelope.data, Clarification)
    assert envelope.data.reason == "no_session"
    assert (
        envelope.message == "I no longer have that result. Which listing do you mean?"
    )
    assert fake_db["connect"] == 0


def test_a_key_wins_over_a_position_with_a_warning_and_no_store_read(
    fake_db, remembered, capsys
):
    envelope = _recommend(listing_key=9870003, sender_id="sender-a", position=2, k=1)
    assert envelope.data.subject.listing_key == 9870003
    assert KEY_WINS_WARNING in envelope.warnings
    assert remembered.gets == 0
    ((line,), _) = _log_lines(capsys)
    assert line["resolved_by"] == "key"


def test_a_key_alone_never_touches_the_store(fake_db, monkeypatch):
    def boom():
        raise AssertionError("the store must not be touched without a position")

    monkeypatch.setattr(mcp, "_get_store", boom)
    assert _recommend(listing_key=SUBJECT, k=1).ok is True


def test_recommend_between_searches_leaves_more_paging(fake_db, monkeypatch):
    """Search, recommend by position, then "more": the stored search is unchanged,
    and "more" returns page 2 of the same search."""
    keys = {"sender-a": "a1" * 32}
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: keys.get(raw))
    store = mcp.reset_store_for_tests(
        InMemorySessionStore(timedelta(minutes=30), 10, _clock)
    )
    try:
        search = AgentResult[SearchResult | Clarification].model_validate(
            mcp.search_listings(city="Pasadena", sender_id="sender-a")
        )
        assert search.data.applied_filters.page == 1
        before = store.get(keys["sender-a"]).model_dump()
        assert before["last_result_keys"] == [SUBJECT]
        envelope = _recommend(sender_id="sender-a", position=1)
        assert envelope.ok and envelope.data.subject.listing_key == SUBJECT
        assert store.get(keys["sender-a"]).model_dump() == before
        more = AgentResult[SearchResult | Clarification].model_validate(
            mcp.search_listings(mode="more", sender_id="sender-a")
        )
        assert more.data.applied_filters.page == 2
        assert more.data.applied_filters.city == "Pasadena"
    finally:
        mcp.reset_store_for_tests()


# --- errors ---


def test_a_key_that_is_not_active_is_not_found(fake_db, capsys):
    payload = mcp.recommend(listing_key=9999999)
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "not_found"
    assert (
        envelope.error.message
        == "That listing is not among the current active listings."
    )
    assert "detail" not in _keys(payload) and not fake_db["comps"]
    assert fake_db["conns"][0].closed is True
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "error" and line["error"] == "not_found"


def test_no_index_with_k_above_zero_is_not_found_before_any_query(
    fake_db, monkeypatch, capsys
):
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", "")
    mcp.reset_semantic_for_tests()
    payload = mcp.recommend(listing_key=SUBJECT)
    envelope = Envelope.model_validate(payload)
    assert envelope.error.category == "not_found"
    assert (
        envelope.error.message
        == "Similar-listing search is not set up on this server yet."
    )
    assert fake_db["connect"] == 0
    ((line,), _) = _log_lines(capsys)
    assert line["error_type"] == "index_dir_unset"


def test_database_not_configured_is_a_db_error(served, monkeypatch):
    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: False)
    envelope = _recommend(listing_key=SUBJECT)
    assert envelope.ok is False and envelope.error.category == "db"


def test_a_database_failure_is_a_db_error_without_detail(fake_db, monkeypatch):
    def fail(subject, window, as_of, conn):
        raise pymysql.err.OperationalError(2013, "Lost connection secret-host")

    monkeypatch.setattr(db_comps, "fetch_comps", fail)
    payload = mcp.recommend(listing_key=SUBJECT)
    envelope = Envelope.model_validate(payload)
    assert envelope.error.category == "db"
    assert "secret-host" not in json.dumps(payload)
    assert fake_db["conns"][0].closed is True


def test_a_comps_statement_over_its_cap_is_an_internal_error(fake_db, monkeypatch):
    def over_cap(subject, window, as_of, conn):
        raise db_market.RowCapExceeded("comps_city returned 51 rows")

    monkeypatch.setattr(db_comps, "fetch_comps", over_cap)
    envelope = _recommend(listing_key=SUBJECT)
    assert envelope.ok is False and envelope.error.category == "internal"


def test_a_candidate_statement_over_its_cap_is_an_internal_error(fake_db, monkeypatch):
    real = db_listings.fetch_candidates

    def over_cap(filters, keys, conn):
        if filters != PropertySearchFilters():
            raise ValueError("candidate statement returned more than 50 rows")
        return real(filters, keys, conn)

    monkeypatch.setattr(db_listings, "fetch_candidates", over_cap)
    envelope = _recommend(listing_key=SUBJECT)
    assert envelope.ok is False and envelope.error.category == "internal"


def test_more_recommendations_than_k_is_an_internal_error(fake_db, monkeypatch):
    real = mcp._neighbors

    def too_many(subject, k, index, conn):
        return real(subject, k + 1, index, conn)

    monkeypatch.setattr(mcp, "_neighbors", too_many)
    envelope = _recommend(listing_key=SUBJECT, k=2)
    assert envelope.ok is False and envelope.error.category == "internal"


def test_at_most_twelve_comps_statements_even_when_every_check_widens(fake_db):
    fake_db["aggregate"] = lambda s: CompsAggregate(
        "city",
        s.city,
        3,
        (Decimal("500"),),
        f"ZIP {s.postal_code}",
        (Decimal("500"), Decimal("500")),
    )
    envelope = _recommend(listing_key=SUBJECT)
    assert envelope.ok is True
    # Subject plus four checkable listings, two statements each; the cap is 12.
    assert len(fake_db["comps"]) == 5 and mcp.MAX_COMPS_STATEMENTS == 12
    budget = mcp._CompsBudget()
    budget.used = 11
    with pytest.raises(RuntimeError):
        budget.check(_listing(SUBJECT), FakeConn(), ASOF)


# --- the log line, spans, and the payload ---


def test_one_log_line_with_counts_and_no_key_address_remark_or_sentence(
    fake_db, capsys
):
    payload = mcp.recommend(listing_key=SUBJECT, k=2)
    ((line,), err) = _log_lines(capsys)
    assert line["event"] == "tool_call" and line["tool"] == "recommend"
    assert line["trace_id"] == payload["provenance"]["trace_id"]
    assert line["outcome"] == "recommendations" and line["k"] == 2
    assert line["resolved_by"] == "key" and line["level"] == "postal_code"
    assert line["comps"] == 7 and line["recommendations"] == 2
    assert line["dropped"] == 0 and line["keys_fetched"] == len(CANDIDATES)
    assert line["index_as_of"] == "2026-09-18" and line["stale_index"] is False
    assert "ms" in line
    markers = (REMARK_MARKER, "Invented Way", "Listed ", "comparable", "middle half")
    for text in (*markers, "oak", "ZIP 91101"):
        assert text not in err
    for key in ALL_ROWS:
        assert str(key) not in err and str(key + 400000) not in err


def test_spans_carry_counts_only(fake_db):
    memory_exporter = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter"
    )
    from idx_agent.observability import tracing

    exporter = memory_exporter.InMemorySpanExporter()
    tracing.configure_for_tests(exporter)
    try:
        mcp.recommend(listing_key=SUBJECT, k=2)
        spans = exporter.get_finished_spans()
    finally:
        tracing.configure_for_tests(None)
    names = {s.name for s in spans}
    root = next(s for s in spans if s.name == "idx.tool_call")
    stages = {
        "idx.recommend.validate",
        "idx.recommend.subject",
        "idx.recommend.comps",
        "idx.recommend.rank",
        "idx.recommend.fetch",
        "idx.recommend.format",
    }
    assert stages <= names
    for s in spans:
        if s.name in stages:
            assert s.parent.span_id == root.context.span_id, s.name
    attrs = dict(root.attributes)
    assert (
        attrs["idx.tool"] == "recommend" and attrs["idx.outcome"] == "recommendations"
    )
    assert attrs["idx.k"] == 2 and attrs["idx.resolved_by"] == "key"
    assert attrs["idx.level"] == "postal_code" and attrs["idx.comps"] == 7
    assert attrs["idx.recommendations"] == 2 and attrs["idx.dropped"] == 0
    assert set(attrs) <= tracing.ALLOWED_ATTRIBUTES
    text = json.dumps([dict(s.attributes) for s in spans], default=str)
    for marker in (REMARK_MARKER, "Invented Way", "Listed ", "oak"):
        assert marker not in text
    for key in ALL_ROWS:
        assert str(key) not in text


def test_the_payload_holds_no_remark_and_no_agent_field(fake_db):
    payload = mcp.recommend(listing_key=SUBJECT)
    text = json.dumps(payload)
    assert REMARK_MARKER not in text and "oak floors" not in text
    assert not _keys(payload) & (AGENT_CONTACT | DENYLIST)
    assert not [name for name in AGENT_CONTACT | DENYLIST if f'"{name}"' in text]
    assert payload["data"]["subject"]["remarks"] is None
    assert all(
        r["listing"]["remarks"] is None for r in payload["data"]["recommendations"]
    )


def test_no_message_explanation_or_warning_holds_a_forbidden_word(fake_db):
    for kwargs in ({"listing_key": SUBJECT}, {"listing_key": SUBJECT, "k": 0}):
        envelope = _recommend(**kwargs)
        assert not contains_forbidden(envelope.message), envelope.message
        assert not any(contains_forbidden(w) for w in envelope.warnings)
        for rec in envelope.data.recommendations:
            assert not contains_forbidden(rec.explanation)
    assert not contains_forbidden(NO_SIMILAR_LINE)
    assert not contains_forbidden(mcp.NO_VECTOR_WARNING)
    assert not contains_forbidden(mcp.NOT_ACTIVE_MESSAGE)


# --- imports: no embedder object and no provider package ---

_SUBPROCESS = """
import sys
from datetime import date
from decimal import Decimal
from idx_agent.mcp_server import server as mcp
from idx_agent.db import listings as L
from idx_agent.db import comps as C
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.comps import CompsAggregate
from idx_agent.domain.models import Listing

class Conn:
    def close(self):
        pass

def fetch(filters, keys, conn):
    rows = [
        Listing(listing_key=k, listing_id=str(k), city="Pasadena", postal_code="91101",
                list_price=1000000, bedrooms=3, living_area=2000,
                property_subtype="SingleFamilyResidence")
        for k in keys
    ]
    return L.SearchOutcome(listings=rows)

mcp.db_pool.database_configured = lambda: True
mcp.db_pool.connect = lambda config=None: Conn()
mcp.db_asof.get_asof_dates = lambda conn: AsOfDates(
    sold=date(2026, 9, 17), active=date(2026, 9, 18))
L.fetch_candidates = fetch
C.fetch_comps = lambda s, w, a, c: CompsAggregate(
    "postal_code", "ZIP " + s.postal_code, 5, (Decimal(500),), None,
    (Decimal(450), Decimal(550)))
out = mcp.recommend(listing_key=__KEY__, k=__K__)
assert out["ok"], out
assert len(out["data"]["recommendations"]) == __EXPECT__, out["data"]
loaded = [m for m in __MODULES__ if m in sys.modules]
assert not loaded, loaded
"""


@pytest.mark.parametrize(
    ("k", "expect", "modules"),
    [
        # k 0 never loads the semantic package, NumPy, or openai.
        (0, 0, ("numpy", "openai", "idx_agent.semantic")),
        # k 5 loads the index (NumPy) but never openai or the query path's embedder.
        (5, 5, ("openai",)),
    ],
)
def test_a_fresh_interpreter_imports_no_provider(tmp_path, k, expect, modules):
    path = _write_index(tmp_path / "index")
    code = (
        _SUBPROCESS.replace("__KEY__", str(SUBJECT))
        .replace("__K__", str(k))
        .replace("__EXPECT__", str(expect))
        .replace("__MODULES__", repr(modules))
    )
    env = {**os.environ, **_settings(path), "MYSQL_HOST": ""}
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SRC,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_the_recommend_code_names_no_embedder():
    """No function on the recommend path refers to the embedder or the query embed."""
    banned = {"make_embedder", "_semantic", "_CheckedEmbedder", "find_similar", "embed"}
    for fn in (
        mcp.recommend,
        mcp.recommend_result,
        mcp._validate_recommend,
        mcp._resolve_subject,
        mcp._recommend_run,
        mcp._neighbors,
        mcp._CompsBudget.check,
        mcp._semantic_index,
    ):
        names, stack = set(), [fn.__code__]
        while stack:
            code = stack.pop()
            names |= set(code.co_names)
            stack += [c for c in code.co_consts if hasattr(c, "co_names")]
        assert not names & banned, fn.__name__
