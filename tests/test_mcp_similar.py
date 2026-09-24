"""The `find_similar_listings` tool (WO-010) over the MCP layer, with no database.

A tiny `test:hashing` index of invented remarks is served via IDX_SEMANTIC_INDEX_DIR;
the candidate fetch and as-of dates are faked. Covers the four outcomes, the log line,
the spans, and the untouched session store. No key, network, provider, or MySQL."""

import asyncio
import json
import pathlib
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

import pymysql
import pytest

from idx_agent.channels.format import format_similar_reply
from idx_agent.db import listings as db_listings
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import (
    Clarification,
    Listing,
    PropertySearchFilters,
    SearchResult,
    SimilarListingsRequest,
    SimilarResult,
)
from idx_agent.domain.results import AgentResult
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST
from idx_agent.semantic import embedder as semantic_embedder
from idx_agent.semantic import index as semantic_index
from idx_agent.semantic import query as semantic_query
from idx_agent.semantic.embedder import HashingEmbedder, OpenAIEmbedder
from idx_agent.semantic.index import IndexAttrs, rank, write_index

Envelope = AgentResult[SimilarResult | Clarification]
DIMS = 64
# The index is built at the fixture's active as-of date; the database agrees unless
# a test says otherwise (the stale-index case).
INDEX_ASOF = date(2026, 9, 18)
ASOF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
# Markers that must never reach a log line, a span, or the payload.
TEXT_MARKER = "zanzibarquokka"
REMARK_MARKER = "REMARK-MARKER-QX9"
TEXT = f"a quiet mid-century home with a big yard near good schools {TEXT_MARKER}"
SRC = str(pathlib.Path(mcp.__file__).resolve().parents[2])

# Invented listings: key -> (city, subtype, price, beds, remarks).
ROWS = {
    9870001: (
        "Pasadena",
        "SingleFamilyResidence",
        1_200_000,
        4,
        "quiet mid-century home with a big yard near good schools",
    ),
    9870002: (
        "Pasadena",
        "SingleFamilyResidence",
        950_000,
        3,
        "mid-century ranch on a quiet street with a big back yard",
    ),
    9870003: (
        "Pasadena",
        "Condominium",
        650_000,
        2,
        "bright modern condo with city views and a gym in the building",
    ),
    9870004: (
        "Monrovia",
        "SingleFamilyResidence",
        800_000,
        3,
        "cozy cottage close to shops and cafes with a quiet garden",
    ),
    9870005: (
        "Monrovia",
        "Condominium",
        500_000,
        1,
        "updated condo with canyon views and a new kitchen",
    ),
    9870006: (
        "Pasadena",
        "SingleFamilyResidence",
        1_500_000,
        5,
        "pool and spa, great for entertaining, big yard and schools nearby",
    ),
}


def _listing(key: int) -> Listing:
    """The invented listing for `key`, carrying a remark that must never leave."""
    city, subtype, price, beds, remarks = ROWS[key]
    return Listing(
        listing_key=key,
        listing_id=str(key),
        address=f"{key % 1000} Invented Way",
        city=city,
        postal_code="91100",
        list_price=price,
        bedrooms=beds,
        bathrooms=2.0,
        property_subtype=subtype,
        status="Active",
        days_on_market=9,
        photo_count=4,
        remarks=f"{remarks} {REMARK_MARKER}",
    )


def _write_index(path: pathlib.Path, as_of: date = INDEX_ASOF) -> pathlib.Path:
    """Embed the invented remarks with the hashing embedder and write the index."""
    keys = sorted(ROWS)
    remarks = [f"{ROWS[k][4]} {REMARK_MARKER}" for k in keys]
    write_index(
        path,
        vectors=HashingEmbedder(DIMS).embed(remarks),
        keys=keys,
        attrs=IndexAttrs.from_values(
            city=[ROWS[k][0] for k in keys],
            list_price=[ROWS[k][2] for k in keys],
            bedrooms=[ROWS[k][3] for k in keys],
            property_subtype=[ROWS[k][1] for k in keys],
        ),
        model="test:hashing",
        active_as_of=as_of,
    )
    return path


def _expected_keys(text: str, filters: PropertySearchFilters, k: int) -> list[int]:
    """The ranking the tool must return, recomputed with the core's own rank()."""
    index = semantic_index.load_index(INDEX_DIR[0], "test:hashing", DIMS)
    vector = HashingEmbedder(DIMS).embed([" ".join(text.split())])[0]
    return [key for key, _ in rank(index, vector, filters, k)]


# The index directory of the running test (set by the `served` fixture).
INDEX_DIR: list[pathlib.Path] = []


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Serve a fresh hashing index through the settings; forget it afterwards."""
    path = _write_index(tmp_path / "index")
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", str(path))
    monkeypatch.setenv("IDX_EMBED_MODEL", "test:hashing")
    monkeypatch.setenv("IDX_EMBED_DIMS", str(DIMS))
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


@pytest.fixture
def fake_db(monkeypatch, served):
    """Patch pool, as-of, and the candidate fetch (and search, for the memory test).

    The fetch returns every asked key that passes the filters, in the asked order,
    minus the keys in calls["drop"] (as SQL drops a changed listing).
    """
    calls = {"connect": 0, "fetch": [], "drop": set(), "asof": ASOF, "conns": []}

    def connect(config=None):
        calls["connect"] += 1
        conn = FakeConn()
        calls["conns"].append(conn)
        return conn

    def passes(key, f):
        city, subtype, price, beds, _ = ROWS[key]
        return (
            (f.city is None or f.city == city)
            and (f.property_subtype is None or f.property_subtype == subtype)
            and (f.max_price is None or price <= f.max_price)
            and (f.min_beds is None or beds >= f.min_beds)
        )

    def fetch(filters, keys, conn):
        calls["fetch"].append((filters, list(keys)))
        found = [
            _listing(k) for k in keys if k not in calls["drop"] and passes(k, filters)
        ]
        return db_listings.SearchOutcome(listings=found)

    def search(filters, conn):
        return db_listings.SearchOutcome(listings=[_listing(9870001)])

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", connect)
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: calls["asof"])
    monkeypatch.setattr(semantic_query, "fetch_candidates", fetch)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)
    return calls


def _similar(**kwargs):
    """Call the MCP entry point and parse the envelope."""
    return Envelope.model_validate(mcp.find_similar_listings(**kwargs))


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


# --- registration ---


def test_the_tool_is_registered_with_six_flat_arguments_and_no_sender():
    """Listed with the others; exactly the request fields, and no sender id."""
    assert "find_similar_listings" in mcp.tool_names()
    tool = next(
        t
        for t in asyncio.run(mcp.server.list_tools())
        if t.name == "find_similar_listings"
    )
    props = set(tool.input_schema["properties"])
    assert props == set(SimilarListingsRequest.model_fields)
    assert props == {"text", "k", "city", "max_price", "min_beds", "property_subtype"}
    assert "find_similar_listings" in mcp.server.instructions


# --- matches ---


def test_matches_come_back_in_rank_order_with_the_card_and_provenance(fake_db):
    envelope = _similar(text=TEXT, k=3)
    assert envelope.ok is True and envelope.error is None
    result = envelope.data
    assert isinstance(result, SimilarResult)
    expected = _expected_keys(TEXT, PropertySearchFilters(), 3)
    assert [m.listing.listing_key for m in result.matches] == expected
    assert [m.rank for m in result.matches] == [1, 2, 3]
    assert result.k == 3 and result.rows_ranked == len(ROWS)
    assert result.model == "test:hashing@64" and result.index_as_of == INDEX_ASOF
    assert result.applied_filters == PropertySearchFilters()
    assert all(m.listing.remarks is None for m in result.matches)
    scores = [m.score for m in result.matches]
    assert scores == sorted(scores, reverse=True)
    assert envelope.message == format_similar_reply(result, ASOF.active)
    assert "Match 1 of 3" in envelope.message and envelope.warnings == []
    assert envelope.provenance.tables == ["rets_property"]
    assert envelope.provenance.as_of.active == ASOF.active
    assert envelope.provenance.as_of.sold == ASOF.sold
    assert envelope.provenance.tool == "find_similar_listings"
    # One connection, closed; the first batch of ranked keys was fetched once.
    assert fake_db["connect"] == 1 and fake_db["conns"][0].closed is True
    ((filters, keys),) = fake_db["fetch"]
    assert keys[:3] == expected and filters == PropertySearchFilters()


def test_k_defaults_to_five(fake_db):
    result = _similar(text=TEXT).data
    assert result.k == 5 and len(result.matches) == 5


def test_each_hard_filter_is_masked_before_ranking_and_sent_to_sql(fake_db):
    """City and subtype: only matching rows are ranked; SQL gets the same filters."""
    envelope = _similar(text=TEXT, city="monrovia", property_subtype="Condominium")
    result = envelope.data
    assert result.rows_ranked == 1
    assert [m.listing.listing_key for m in result.matches] == [9870005]
    assert result.applied_filters == PropertySearchFilters(
        city="Monrovia", property_subtype="Condominium"
    )
    ((filters, keys),) = fake_db["fetch"]
    assert filters.city == "Monrovia" and keys == [9870005]


def test_fewer_than_k_says_so_and_names_a_filter_to_drop(fake_db):
    envelope = _similar(text=TEXT, min_beds=5)
    assert [m.listing.listing_key for m in envelope.data.matches] == [9870006]
    assert envelope.warnings == [
        "Only 1 of the 5 matches asked for came back. Dropping the bedroom minimum "
        "may find more."
    ]
    assert envelope.warnings[0] in envelope.message


def test_dropped_candidates_are_counted_and_the_next_one_moves_up(fake_db, capsys):
    top = _expected_keys(TEXT, PropertySearchFilters(), 1)[0]
    fake_db["drop"] = {top}
    envelope = _similar(text=TEXT, k=2)
    keys = [m.listing.listing_key for m in envelope.data.matches]
    assert top not in keys
    assert keys == _expected_keys(TEXT, PropertySearchFilters(), 3)[1:]
    assert [m.rank for m in envelope.data.matches] == [1, 2]
    assert any("1 ranked listing was left out" in w for w in envelope.warnings)
    ((line,), _) = _log_lines(capsys)
    assert line["dropped"] == 1 and line["outcome"] == "matches"


# --- no match ---


def test_filters_that_leave_nothing_are_no_match_and_run_no_fetch(fake_db, capsys):
    envelope = _similar(text=TEXT, city="Monrovia", max_price=100_000)
    assert envelope.ok is True
    result = envelope.data
    assert isinstance(result, SimilarResult) and result.matches == []
    assert result.rows_ranked == 0 and fake_db["fetch"] == []
    assert envelope.message.startswith("*No close matches to your description*")
    assert "Dropping the price limit may find some." in envelope.message
    assert envelope.provenance.tables == ["rets_property"]
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "no_match" and line["matches"] == 0


def test_sql_dropping_every_candidate_is_no_match(fake_db):
    fake_db["drop"] = set(ROWS)
    envelope = _similar(text=TEXT, city="Pasadena")
    assert envelope.ok is True and envelope.data.matches == []
    assert any("ranked listings were left out" in w for w in envelope.warnings)


# --- the stale index ---


def test_an_index_older_than_the_database_adds_the_stale_warning_and_line(fake_db):
    fake_db["asof"] = AsOfDates(sold=date(2026, 9, 24), active=date(2026, 9, 25))
    envelope = _similar(text=TEXT, k=1)
    assert len(envelope.data.matches) == 1
    (warning,) = envelope.warnings
    assert "listings added since 2026-09-18 are not ranked" in warning
    assert warning in envelope.message
    assert envelope.data.index_as_of == INDEX_ASOF
    assert envelope.provenance.as_of.active == date(2026, 9, 25)


# --- Clarification ---


@pytest.mark.parametrize(
    ("kwargs", "field", "reason"),
    [
        ({"text": "cozy"}, "text", "below_minimum"),
        ({}, "text", "below_minimum"),
        ({"text": "x " * 300}, "text", "above_maximum"),
        ({"text": TEXT, "k": 11}, "k", "above_maximum"),
        ({"text": TEXT, "k": 0}, "k", "below_minimum"),
        ({"text": TEXT, "city": "Atlantis Springs"}, "city", "unknown_city"),
        ({"text": TEXT, "property_subtype": "Castle"}, "property_subtype", None),
    ],
)
def test_a_bad_request_is_a_clarification_that_embeds_and_queries_nothing(
    fake_db, monkeypatch, capsys, kwargs, field, reason
):
    def boom(*args, **kwargs):
        raise AssertionError("a Clarification must not load, embed, or query")

    monkeypatch.setattr(mcp, "_semantic", boom)
    envelope = _similar(**kwargs)
    assert envelope.ok is True and isinstance(envelope.data, Clarification)
    assert envelope.data.field == field
    if reason:
        assert envelope.data.reason == reason
    assert envelope.message == envelope.data.question
    assert fake_db["connect"] == 0 and fake_db["fetch"] == []
    assert envelope.provenance.as_of.active is None and envelope.provenance.tables == []
    assert TEXT_MARKER not in json.dumps(envelope.model_dump(mode="json"))
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "clarification" and line["field"] == field


class ZeroEmbedder:
    """A stub embedder whose every row is zero, as the hashing embedder gives for
    text under 20 characters or with no a-z/0-9 word."""

    name, dims = "test:hashing", DIMS

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        import numpy as np

        self.calls += 1
        return np.zeros((len(texts), DIMS), dtype=np.float32)


def test_a_description_that_embeds_to_zeros_is_a_clarification(
    fake_db, monkeypatch, capsys
):
    """Not an internal error: the question asks for more words; nothing is fetched."""
    stub = ZeroEmbedder()
    monkeypatch.setattr(semantic_embedder, "make_embedder", lambda m, d, **kw: stub)
    # Over 20 characters, so it reaches the embedder, which returns zeros.
    envelope = _similar(text="ÉÉÉÉÉÉ ÉÉÉÉÉÉ ÉÉÉÉÉÉÉÉ")
    assert envelope.ok is True and isinstance(envelope.data, Clarification)
    assert envelope.data.field == "text" and envelope.data.reason == "below_minimum"
    assert envelope.message == "Please describe the home in a few more words."
    assert stub.calls == 1 and fake_db["fetch"] == []
    assert fake_db["conns"][0].closed is True
    assert envelope.provenance.as_of.active is None
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "clarification" and line["field"] == "text"


def test_short_text_is_the_same_clarification_without_an_embedding_call(
    fake_db, monkeypatch
):
    """Eight letters in two words pass validation but are under 20 characters once
    prepared: the same question, and the embedder is never called."""
    stub = ZeroEmbedder()
    monkeypatch.setattr(semantic_embedder, "make_embedder", lambda m, d, **kw: stub)
    envelope = _similar(text="cozy yards")
    assert isinstance(envelope.data, Clarification)
    assert envelope.message == "Please describe the home in a few more words."
    assert stub.calls == 0 and fake_db["fetch"] == []


# --- errors: not_found ---


def test_no_index_setting_is_not_found_and_other_tools_still_work(monkeypatch, capsys):
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", "")
    mcp.reset_semantic_for_tests()
    payload = mcp.find_similar_listings(text=TEXT)
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "not_found"
    assert (
        envelope.error.message
        == "Similar-listing search is not set up on this server yet."
    )
    assert "detail" not in _keys(payload)
    ((line,), _) = _log_lines(capsys)
    assert line["error_type"] == "index_dir_unset" and line["outcome"] == "error"
    assert mcp.health()["ok"] is True


def test_a_directory_without_an_index_is_not_found(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", str(tmp_path / "nothing-here"))
    monkeypatch.setenv("IDX_EMBED_MODEL", "test:hashing")
    mcp.reset_semantic_for_tests()
    envelope = _similar(text=TEXT)
    assert envelope.error.category == "not_found"
    ((line,), _) = _log_lines(capsys)
    assert line["error_type"] == "index_missing"


def test_a_real_model_index_outside_data_is_not_found(served, monkeypatch, capsys):
    """The default OpenAI model may only be served from data/; a temp dir is refused."""
    monkeypatch.setenv("IDX_EMBED_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("IDX_EMBED_DIMS", "1536")
    mcp.reset_semantic_for_tests()
    envelope = _similar(text=TEXT)
    assert envelope.error.category == "not_found"
    ((line,), _) = _log_lines(capsys)
    assert line["error_type"] == "index_outside_data"


def test_without_the_semantic_extra_the_tool_is_not_found(served, monkeypatch):
    """A missing NumPy or openai shows as an ImportError on the lazy import."""
    monkeypatch.setitem(sys.modules, "idx_agent.semantic.index", None)
    envelope = _similar(text=TEXT)
    assert envelope.error.category == "not_found"


def test_the_index_loads_once_per_process(fake_db, monkeypatch):
    real = semantic_index.load_index
    loads = []

    def counting(*args, **kwargs):
        loads.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(semantic_index, "load_index", counting)
    _similar(text=TEXT)
    _similar(text=TEXT, city="Pasadena")
    assert len(loads) == 1


# --- errors: provider ---


class StubClient:
    """An OpenAI-shaped client that records calls and fails like the provider can."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.embeddings = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error or RuntimeError("stub provider failure")


@pytest.mark.parametrize(
    ("consent", "environ", "error", "reason"),
    [
        (False, {"OPENAI_API_KEY": "test-key-not-real"}, None, "no_consent"),
        (True, {}, None, "missing_key"),
        (True, {"OPENAI_API_KEY": "test-key-not-real"}, TimeoutError(), "timeout"),
        (True, {"OPENAI_API_KEY": "test-key-not-real"}, None, "failed"),
    ],
)
def test_a_refused_or_failed_embedding_is_a_provider_error(
    fake_db, monkeypatch, capsys, consent, environ, error, reason
):
    """The real OpenAIEmbedder with a stub client: a refused call makes no request;
    a failed one is a provider error; nothing is fetched and the connection closes."""
    client = StubClient(error)
    embedder = OpenAIEmbedder(
        client=client, environ=environ, consent_check=lambda: consent
    )
    monkeypatch.setattr(
        semantic_embedder, "make_embedder", lambda model, dims, **kw: embedder
    )
    payload = mcp.find_similar_listings(text=TEXT)
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "provider"
    assert envelope.error.message == mcp.PROVIDER_MESSAGE
    assert "detail" not in _keys(payload)
    assert fake_db["fetch"] == [] and fake_db["conns"][0].closed is True
    if reason in {"no_consent", "missing_key"}:
        assert client.calls == []
    else:
        assert len(client.calls) == 1 and client.calls[0]["input"] == [
            " ".join(TEXT.split())
        ]
    ((line,), err) = _log_lines(capsys)
    assert line["error_type"] == "ProviderError" and line["error"] == "provider"
    assert "test-key-not-real" not in err and TEXT_MARKER not in err


# --- errors: db and internal ---


def test_database_not_configured_is_a_db_error(served, monkeypatch):
    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: False)
    envelope = _similar(text=TEXT)
    assert envelope.ok is False and envelope.error.category == "db"


def test_a_database_failure_is_a_db_error_without_detail(fake_db, monkeypatch):
    def fail(filters, keys, conn):
        raise pymysql.err.OperationalError(2013, "Lost connection secret-host")

    monkeypatch.setattr(semantic_query, "fetch_candidates", fail)
    payload = mcp.find_similar_listings(text=TEXT)
    envelope = Envelope.model_validate(payload)
    assert envelope.error.category == "db"
    assert "secret-host" not in json.dumps(payload)
    assert fake_db["conns"][0].closed is True


def test_a_cap_breach_is_an_internal_error(fake_db, monkeypatch):
    """SQL returning more than 50 rows raises in the db layer: internal, not db."""

    def over_cap(filters, keys, conn):
        raise ValueError("candidate statement returned more than 50 rows")

    monkeypatch.setattr(semantic_query, "fetch_candidates", over_cap)
    envelope = _similar(text=TEXT)
    assert envelope.ok is False and envelope.error.category == "internal"


def test_more_matches_than_k_is_an_internal_error(fake_db, monkeypatch):
    real = semantic_query.find_similar

    def too_many(request, index, embedder, conn):
        outcome = real(request.model_copy(update={"k": 3}), index, embedder, conn)
        return outcome

    monkeypatch.setattr(semantic_query, "find_similar", too_many)
    envelope = _similar(text=TEXT, k=2)
    assert envelope.ok is False and envelope.error.category == "internal"


# --- the log line, spans, and the payload ---


def test_one_log_line_with_counts_and_no_text_vector_remark_or_key(fake_db, capsys):
    payload = mcp.find_similar_listings(text=TEXT, city="Pasadena", k=2)
    ((line,), err) = _log_lines(capsys)
    assert line["event"] == "tool_call" and line["tool"] == "find_similar_listings"
    assert line["trace_id"] == payload["provenance"]["trace_id"]
    assert line["outcome"] == "matches" and line["k"] == 2
    assert line["filters"] == {"city": "Pasadena"}
    assert line["text_words"] == len(TEXT.split())
    assert line["text_chars"] == len(" ".join(TEXT.split()))
    assert line["rows_ranked"] == 4 and line["keys_fetched"] == 4
    assert line["dropped"] == 0 and line["matches"] == 2
    assert line["index_as_of"] == "2026-09-18" and line["stale_index"] is False
    assert line["model"] == "test:hashing" and line["dims"] == DIMS and "ms" in line
    for text in (TEXT_MARKER, REMARK_MARKER, "Invented Way", "mid-century", "[0."):
        assert text not in err
    for key in ROWS:
        assert str(key) not in err


def test_spans_carry_counts_only(fake_db):
    memory_exporter = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter"
    )
    from idx_agent.observability import tracing

    exporter = memory_exporter.InMemorySpanExporter()
    tracing.configure_for_tests(exporter)
    try:
        mcp.find_similar_listings(text=TEXT, city="Pasadena", k=2)
        spans = {s.name: s for s in exporter.get_finished_spans()}
    finally:
        tracing.configure_for_tests(None)
    root = spans["idx.tool_call"]
    stages = (
        "idx.similar.validate",
        "idx.similar.embed",
        "idx.similar.rank",
        "idx.similar.fetch",
        "idx.similar.format",
    )
    for stage in stages:
        assert spans[stage].parent.span_id == root.context.span_id, stage
    attrs = dict(root.attributes)
    assert attrs["idx.tool"] == "find_similar_listings"
    assert attrs["idx.outcome"] == "matches" and attrs["idx.k"] == 2
    assert attrs["idx.rows_ranked"] == 4 and attrs["idx.matches"] == 2
    assert attrs["idx.model"] == "test:hashing" and attrs["idx.dims"] == DIMS
    assert attrs["idx.filters.city"] == "Pasadena"
    assert set(attrs) <= tracing.ALLOWED_ATTRIBUTES
    text = json.dumps([dict(s.attributes) for s in spans.values()], default=str)
    for marker in (TEXT_MARKER, REMARK_MARKER, "Invented Way", "[0."):
        assert marker not in text
    for key in ROWS:
        assert str(key) not in text


def test_the_payload_holds_no_remark_and_no_agent_field(fake_db):
    payload = mcp.find_similar_listings(text=TEXT, k=5)
    text = json.dumps(payload)
    assert REMARK_MARKER not in text and TEXT_MARKER not in text
    assert not _keys(payload) & (AGENT_CONTACT | DENYLIST)
    assert not [name for name in AGENT_CONTACT | DENYLIST if f'"{name}"' in text]
    assert all(m["listing"]["remarks"] is None for m in payload["data"]["matches"])


# --- stateless (requirement 14) ---

_STATE_NAMES = {
    name
    for name, value in vars(mcp).items()
    if getattr(value, "__module__", "").startswith("idx_agent.memory")
} | {"_get_store", "_store", "_sender_lock", "_remember", "reset_store_for_tests"}


def _names_used(fn):
    """Global names a function's code (and its nested code) refers to."""
    names, stack = set(), [fn.__code__]
    while stack:
        code = stack.pop()
        names |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return names


def test_the_similar_code_names_nothing_from_the_session_store():
    assert {"sender_key", "_get_store", "merge_filters"} <= _STATE_NAMES
    for fn in (
        mcp.find_similar_listings,
        mcp.similar_result,
        mcp._semantic,
        mcp._similar_error,
        mcp._text_counts,
        mcp._similar_filter_fields,
        mcp._dropped_warning,
    ):
        assert not _names_used(fn) & _STATE_NAMES, fn.__name__


def test_the_semantic_package_does_not_import_memory():
    """A fresh interpreter importing the semantic package loads no idx_agent.memory."""
    code = (
        "import sys\n"
        "import idx_agent.semantic.embedder, idx_agent.semantic.index\n"
        "import idx_agent.semantic.query, idx_agent.channels.format\n"
        "assert 'idx_agent.memory' not in sys.modules, 'memory imported'\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SRC,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_the_server_imports_no_semantic_module_until_the_first_call():
    """Requirement 10: NumPy, openai, and the semantic package load lazily."""
    code = (
        "import sys\n"
        "import idx_agent.mcp_server.server\n"
        "loaded = [m for m in ('numpy', 'openai', 'idx_agent.semantic') if m in "
        "sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SRC,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_a_similar_search_between_searches_leaves_more_paging(fake_db, monkeypatch):
    """Search, then a similar search, then "more": the stored search is unchanged by
    the similar call, and "more" returns page 2 of the same search."""
    keys = {"sender-a": "a1" * 32}
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: keys.get(raw))
    clock = lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC)  # noqa: E731
    store = mcp.reset_store_for_tests(
        InMemorySessionStore(timedelta(minutes=30), 10, clock)
    )
    try:
        search = AgentResult[SearchResult | Clarification].model_validate(
            mcp.search_listings(city="Pasadena", sender_id="sender-a")
        )
        assert search.data.applied_filters.page == 1
        before = store.get(keys["sender-a"]).model_dump()
        similar = _similar(text=TEXT)
        assert similar.ok and isinstance(similar.data, SimilarResult)
        assert store.get(keys["sender-a"]).model_dump() == before
        more = AgentResult[SearchResult | Clarification].model_validate(
            mcp.search_listings(mode="more", sender_id="sender-a")
        )
        assert more.data.applied_filters.page == 2
        assert more.data.applied_filters.city == "Pasadena"
    finally:
        mcp.reset_store_for_tests()
