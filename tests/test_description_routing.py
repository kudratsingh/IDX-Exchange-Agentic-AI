"""Description features versus structured pool (owner decision 2026-11-05, after P1-4).

Model-free: the skill and the tool schema say the same rule, and the real search body
replays P1-1..P1-3 then both P1-4 wordings over an invented store and a fake database.
Paid routing cases: evals/cases/description_routing.yaml and evals/cases/relay.yaml.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from evals import run as runner
from tests.synthetic_store import write_synthetic_store
from tests.test_mcp_search_features import ASOF, META, WATERMARK, FakeConn, _listing

from idx_agent.db import listings as db_listings
from idx_agent.domain.models import Clarification, SearchResult
from idx_agent.domain.results import AgentResult
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore

Envelope = AgentResult[SearchResult | Clarification]
NEW_P1_4 = (
    "Only homes whose listing descriptions say they have both a pool and solar panels."
)
OLD_P1_4 = "Any of those with a pool too?"
# Invented rows: 201 has both features in its description, 202 solar only, 203 pool
# only, 204 neither.
ROWS = [
    ("201", {"solar": "present", "pool": "present"}),
    ("202", {"solar": "present"}),
    ("203", {"pool": "present"}),
    ("204", {}),
]
SENDER = "invented-p1-4"


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _skill_body() -> str:
    _description, body = runner.skill_parts(
        "property-search", runner.DEFAULT_SKILLS_DIR
    )
    return _one_line(body)


def test_the_skill_keeps_structured_pool_for_an_ordinary_request():
    body = _skill_body()
    assert "For a pool or a view, use the `pool` or `view` filter above" in body
    assert '"with a pool" or "any of those with a pool too?" is `pool: true`' in body


def test_the_skill_sends_what_descriptions_say_to_features():
    body = _skill_body()
    assert "What listing descriptions say:" in body
    assert "put every feature they name from the list above in `features`" in body
    assert "a pool included, and leave `pool` and `view` out" in body
    assert f'"{NEW_P1_4}" is `features: ["pool", "solar"]`' in body
    assert 'after an earlier search it is `mode: "update"` with that list' in body


def test_the_description_line_is_unchanged():
    """The routing pin covers the description; the rule lives in the body only."""
    description, _body = runner.skill_parts(
        "property-search", runner.DEFAULT_SKILLS_DIR
    )
    assert description.startswith("Find active homes or listings for sale")
    assert "descriptions" not in description


def test_the_features_parameter_says_the_same():
    tool = next(
        t for t in asyncio.run(mcp.server.list_tools()) if t.name == "search_listings"
    )
    props = tool.input_schema["properties"]
    words = _one_line(props["features"]["description"])
    assert "Use the pool and view filters for a pool or a view, unless" in words
    assert "asks what listing descriptions say" in words
    assert "list each named feature here (pool included)" in words
    assert "pool" in props["features"]["description"].split("list: ")[1]
    assert "true when the user asks for a pool" in props["pool"]["description"]


@pytest.fixture
def world(monkeypatch, tmp_path):
    path = tmp_path / "effective.sqlite3"
    write_synthetic_store(path, ROWS, META)
    calls = {"search": []}

    def search(filters, conn, scope=None):
        calls["search"].append((filters, scope))
        keys = [int(k) for k in scope.keys] if scope else [201, 202, 203, 204]
        return db_listings.SearchOutcome(listings=[_listing(k) for k in keys])

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", lambda config=None: FakeConn())
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", lambda *a, **k: 0)
    monkeypatch.setattr(mcp.db_listings, "count_changed_since", lambda *a: 0)
    monkeypatch.setattr(
        mcp.db_listings, "fetch_freshness", lambda watermark, conn: (1000, 5)
    )
    monkeypatch.setattr(mcp.effective_store, "configured_store_path", lambda: path)
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


def _send(**arguments) -> Envelope:
    return Envelope.model_validate(mcp.search_listings(sender_id=SENDER, **arguments))


def _p1_1_to_p1_3() -> None:
    _send(city="Pasadena", features=["solar"])
    _send(mode="update", min_beds=3)
    _send(mode="more")


def test_the_reworded_p1_4_is_a_description_search_for_both_features(world):
    """features ["pool", "solar"] with the carried city and beds; no structured pool;
    the feature line names both and the limitation is whole."""
    _p1_1_to_p1_3()
    result = _send(mode="update", features=["solar", "pool"])
    applied = result.data.applied_filters
    assert (applied.city, applied.min_beds, applied.page) == ("Pasadena", 3, 1)
    assert applied.features == ("pool", "solar") and applied.pool is None
    feature = result.data.feature_filter
    assert feature.status == "applied" and feature.features == ["pool", "solar"]
    assert feature.snapshot_watermark == WATERMARK
    assert [x.listing_key for x in result.data.listings] == [201]
    filters, scope = world["search"][-1]
    assert scope.keys == ("201",) and filters.pool is None
    stamp = WATERMARK[:10]  # the snapshot date
    assert (
        f"Features matched from listing descriptions as of {stamp}: pool, solar."
    ) in result.message
    assert mcp.FEATURE_LIMITATION in result.message


def test_the_old_p1_4_keeps_the_structured_pool_filter(world):
    """The recorded failed turn's call: mode update, pool true, solar carried."""
    _p1_1_to_p1_3()
    result = _send(mode="update", pool=True)
    applied = result.data.applied_filters
    assert applied.pool is True and applied.features == ("solar",)
    assert result.data.feature_filter.features == ["solar"]
    filters, scope = world["search"][-1]
    assert filters.pool is True and set(scope.keys) == {"201", "202"}
