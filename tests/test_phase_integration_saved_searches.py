"""Cross-feature acceptance for WO-025 saved feature searches with what is on main.

Saved alerts with search, badges and explanations on one synthetic store; a stale or
missing store; rollback with IDX_FEATURE_SAVED_SEARCHES off. Offline and invented.
"""

# Ported from the scratch branch chore-phase-integration and adapted to current APIs.
# Checks for the analysis tool or chart delivery stay with #147. The world: a real
# effective store of invented statuses, the real listing SQL on an SQLite stand-in,
# the WO-011 recommend harness, synthetic alert and approval files; switches live in a
# temp `.env`, as in production.

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tests.test_mcp_recommend import (  # noqa: F401 - `served` is a fixture
    ALL_ROWS,
    ASOF,
    SUBJECT,
    _listing,
    _passes,
    served,
)
from tests.test_recommend_explanations import META, STATUSES

from idx_agent.alerts import features as saved_features
from idx_agent.alerts import server as alerts
from idx_agent.alerts.query import fetch_new, fetch_new_features, fetch_unchecked_from
from idx_agent.alerts.run import run_job
from idx_agent.alerts.store import AlertStore
from idx_agent.db import comps as db_comps
from idx_agent.db import listings as db_listings
from idx_agent.db import pool as db_pool
from idx_agent.db.comps import CompsAggregate
from idx_agent.domain.fieldmap import listing_columns
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.enrichment import access as fa
from idx_agent.enrichment import effective_store
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore
from idx_agent.safety.approval import ApprovalStore

SWITCHES = {
    "badges": mcp.BADGES_SETTING,
    "explanations": mcp.EXPLANATIONS_SETTING,
    "saved": saved_features.SETTING,
}
TRACE = "0" * 32
SENDER = "ab" * 32
OWNER_KEY = "c1" * 32
BEFORE, AFTER = "2026-09-01 10:00:00", "2026-10-01 10:00:00"
LISTED, CHECKED = "2026-09-12", date(2026, 9, 10)
FILLER = [9_000_000 + i for i in range(40)]  # unchanged, keeps the store fresh
SOLAR_POOL = ["pool", "solar"]
SOLAR = PropertySearchFilters(city="Pasadena", features=["solar"])
# A rebuilt snapshot after AFTER, and active data that has caught up with it.
REBUILT = "2026-10-02 07:00:00"
LATER = ASOF.model_copy(update={"active": date(2026, 10, 2)})


# --- the synthetic world ---


class Cursor:
    def __init__(self, engine):
        self.engine, self.rows = engine, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        bound = [str(p) if isinstance(p, date) else p for p in params]
        self.rows = [
            dict(r) for r in self.engine.execute(sql.replace("%s", "?"), bound)
        ]

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, engine):
        self.engine = engine

    def cursor(self):
        return Cursor(self.engine)

    def close(self):
        pass


def _engine():
    engine = sqlite3.connect(":memory:", check_same_thread=False)
    engine.row_factory = sqlite3.Row
    columns = list(
        dict.fromkeys(
            [*listing_columns(), "ModificationTimestamp", "ListingContractDate"]
        )
    )
    engine.execute(f"CREATE TABLE rets_property ({', '.join(columns)})")
    rows = [(k, v[0], v[2]) for k, v in sorted(ALL_ROWS.items())]
    rows += [(k, "Arcadia", 600_000) for k in FILLER]
    for n, (key, city, price) in enumerate(rows):
        values = dict.fromkeys(columns)
        values.update(
            L_ListingID=str(key),
            L_DisplayId=f"D{key}-{n}",
            L_Address=f"{key % 1000} Invented Way",
            L_City=city,
            L_Zip="91101",
            L_SystemPrice=price,
            L_Keyword2=3,
            StandardStatus="Active",
            ModificationTimestamp=BEFORE,
            ListingContractDate=LISTED if key in ALL_ROWS else "2026-08-01",
        )
        marks = ", ".join("?" * len(columns))
        engine.execute(
            f"INSERT INTO rets_property VALUES ({marks})", [values[c] for c in columns]
        )
    return engine


def _write_store(path: Path, watermark: str = META["source_watermark"]) -> Path:
    statuses = {**STATUSES, **{k: {"garage": "present"} for k in FILLER}}
    rows = [(str(k), v) for k, v in sorted(statuses.items())]
    meta = dict(META, source_rows=len(rows), source_watermark=watermark)
    effective_store.write_store(path, rows, meta)
    return path


@pytest.fixture
def world(tmp_path, monkeypatch, served):  # noqa: F811
    engine = _engine()
    data = tmp_path / "data"
    now = datetime(2026, 10, 24, tzinfo=UTC)
    state = {
        "engine": engine,
        "store_path": _write_store(tmp_path / "effective.sqlite3"),
        "configured": None,  # no store configured until a test says so
        "alerts": AlertStore(
            data / "state" / "alerts.sqlite",
            data_root=data,
            is_ignored=lambda _: True,
            clock=lambda: now,
        ),
        "gate": ApprovalStore(
            data / "email", data_root=data, is_ignored=lambda _: True, clock=lambda: now
        ),
        "opened": 0,
    }

    def fetch(filters, keys, conn):
        found = [_listing(k) for k in keys if k in ALL_ROWS and _passes(k, filters)]
        return db_listings.SearchOutcome(listings=found)

    def comps(subject, window, as_of, conn):
        return CompsAggregate(
            "postal_code",
            f"ZIP {subject.postal_code}",
            7,
            (Decimal("500"),),
            None,
            (Decimal("450"), Decimal("560")),
        )

    real_open = effective_store.open_store

    def counting_open(path):
        state["opened"] += path is not None
        return real_open(path)

    for name in SWITCHES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IDX_SENDER_KEY", SENDER)
    monkeypatch.setattr(db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(db_pool, "connect", lambda config=None: Conn(engine))
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(alerts.asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(db_listings, "fetch_candidates", fetch)
    monkeypatch.setattr(db_comps, "fetch_comps", comps)
    monkeypatch.setattr(effective_store, "open_store", counting_open)
    monkeypatch.setattr(
        effective_store, "configured_store_path", lambda: state["configured"]
    )
    monkeypatch.setattr(alerts, "configured_store", lambda: state["alerts"])
    monkeypatch.setattr(alerts, "configured_gate", lambda: state["gate"])
    monkeypatch.setattr(mcp, "new_trace_id", lambda: TRACE)
    monkeypatch.setattr(alerts, "new_trace_id", lambda: TRACE)
    monkeypatch.setattr(mcp, "memory_key", lambda raw, secret=None: raw and OWNER_KEY)
    _fresh_sessions()
    fa.reset_for_tests()
    yield state
    fa.reset_for_tests()
    mcp.reset_store_for_tests()


def _fresh_sessions() -> None:
    mcp.reset_store_for_tests(
        InMemorySessionStore(
            timedelta(minutes=30), 10, lambda: datetime(2026, 9, 18, tzinfo=UTC)
        )
    )


def dotenv(**on: str) -> None:
    """Write the cwd `.env` (the switches' one home) and start fresh sessions."""
    lines = [f"{SWITCHES[name]}={value}" for name, value in on.items()]
    (Path.cwd() / ".env").write_text("\n".join(lines) + "\n")
    _fresh_sessions()
    fa.reset_for_tests()


def _dump(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


async def _list(server):
    return [
        t.model_dump(mode="json", exclude_none=True) for t in await server.list_tools()
    ]


def surfaces(world) -> dict[str, str]:
    """Everything a user or the model sees, with one fresh session per read."""
    _fresh_sessions()
    out = {
        "idx_tools": _dump(asyncio.run(_list(mcp.server))),
        "alerts_tools": _dump(asyncio.run(_list(alerts.server))),
        "search_plain": _dump(mcp.search_listings(city="Pasadena")),
        "search_features": _dump(
            mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
        ),
        "recommend": _dump(mcp.recommend(listing_key=SUBJECT)),
        "save_plain": _dump(alerts.save_search(city="Monrovia")),
        "save_features": _dump(alerts.save_search(city="Pasadena", features=["solar"])),
        "list": _dump(alerts.list_saved_searches()),
    }
    _forget_saved(world)
    return out


def _forget_saved(world) -> None:
    with world["alerts"].transaction(write=True) as conn:
        conn.execute("DELETE FROM searches")


def _changed(base: dict[str, str], other: dict[str, str]) -> set[str]:
    return {k for k in base if base[k] != other[k]}


def _keys(envelope: dict) -> list[int]:
    return [x["listing_key"] for x in envelope["data"]["listings"]]


def _job(world, dates=ASOF):
    """The alert job exactly as `alerts.run.main` wires it."""
    conn = Conn(world["engine"])
    with fa.FeatureAccess.configured() as access:
        return run_job(
            world["alerts"],
            world["gate"],
            reader=lambda s, d: fetch_new(s, d, conn),
            dates=dates,
            recipient="owner" + "@" + "example.test",
            bind_features=lambda f: access.bind(f, conn),
            feature_reader=lambda s, h, sc: fetch_new_features(s, h, sc, conn),
            unchecked_reader=lambda s, h, w: fetch_unchecked_from(s, h, w, conn),
        )


def _drafts(world) -> list:
    gate = world["gate"]
    return gate.list_pending() if gate.path.exists() else []


def _touch(world, keys, stamp=AFTER) -> None:
    """Record a change after the snapshot for `keys` (their features become unknown)."""
    world["engine"].execute(
        "UPDATE rets_property SET ModificationTimestamp = ? WHERE L_ListingID IN "
        f"({', '.join('?' * len(keys))})",
        [stamp, *(str(k) for k in keys)],
    )
    fa.reset_for_tests()


def _present(world, key: int) -> frozenset[str]:
    conn = Conn(world["engine"])
    with fa.FeatureAccess.configured() as access:
        assert access.readiness(conn).usable
        return access.present_features([key], conn).get(str(key), frozenset())


# --- the saved switch alone, and back off ---


def test_the_saved_switch_alone_changes_only_saving_and_listing(world):
    world["configured"] = world["store_path"]
    dotenv()
    base = surfaces(world)
    dotenv(saved="1")
    assert _changed(base, surfaces(world)) == {"save_features", "list"}
    dotenv(saved="0")
    assert surfaces(world) == base


# --- all on together: one store, one set of facts ---


def test_all_on_search_badges_explanations_and_alerts_agree(world):
    world["configured"] = world["store_path"]
    dotenv(badges="1", explanations="1", saved="1")
    found = mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
    assert found["data"]["feature_filter"]["status"] == "applied"
    keys = _keys(found)
    assert sorted(keys) == [SUBJECT, 9870002]
    card = found["data"]["card_badges"]
    assert card["snapshot_watermark"] == META["source_watermark"]
    badges = {int(k): v for k, v in card["badges"].items()}
    for key in keys:
        assert badges[key][:2] == SOLAR_POOL  # requested first
    # The search's result feeds recommend; its explanations use the same facts.
    rec = mcp.recommend(listing_key=SUBJECT)
    shared = {int(k): v for k, v in rec["data"]["shared_features"]["features"].items()}
    assert shared == {9870002: SOLAR_POOL, 9870004: ["hardwood"]}
    for key, features in shared.items():
        assert set(features) <= set(_present(world, key))
    assert set(shared[9870002]) <= set(badges[9870002])
    # A saved feature search alerts on exactly what a live search finds.
    saved = alerts.save_search(city="Pasadena", features=["solar"])
    assert saved["ok"] and saved["data"]["filters"]["features"] == ["solar"]
    _forget_saved(world)
    world["alerts"].add_feature_search(OWNER_KEY, SOLAR, CHECKED)
    summary = _job(world)
    assert summary["drafts"] == 1 and summary["unavailable"] == 0
    assert summary["deferred"] == 0
    [draft] = _drafts(world)
    live = mcp.search_listings(city="Pasadena", features=["solar"], limit=10)
    for key in _keys(live):
        assert f"*{key % 1000} Invented Way*" in draft.body
    assert draft.body.count(" Invented Way*") == len(_keys(live))
    assert "solar" in draft.body


def test_a_changed_listing_is_left_out_everywhere_then_alerted_once_after_rebuild(
    world,
):
    """9870002 changes after the snapshot: search, badges and explanations leave it
    out, the alert defers it; a rebuilt store brings it back everywhere, once."""
    world["configured"] = world["store_path"]
    dotenv(badges="1", explanations="1", saved="1")
    world["alerts"].add_feature_search(OWNER_KEY, SOLAR, CHECKED)
    _touch(world, [9870002])
    found = mcp.search_listings(city="Pasadena", features=["solar"])
    assert _keys(found) == [SUBJECT]
    assert "9870002" not in found["data"]["card_badges"]["badges"]
    rec = mcp.recommend(listing_key=SUBJECT)
    assert 9870002 not in {int(k) for k in rec["data"]["shared_features"]["features"]}
    summary = _job(world)
    assert summary["drafts"] == 1 and summary["deferred"] == 1
    [first] = _drafts(world)
    assert "1 other new listing(s) changed after the snapshot" in first.body
    [held] = world["alerts"].all_searches()
    assert held.alerted_keys == [SUBJECT]
    assert held.checked_as_of == date(2026, 9, 11)  # the day before 9870002's date
    # Rebuilt after the change, with active data caught up: one more draft, for it.
    _write_store(world["store_path"], REBUILT)
    fa.reset_for_tests()
    live = mcp.search_listings(city="Pasadena", features=["solar"])
    assert sorted(_keys(live)) == [SUBJECT, 9870002]
    after = _job(world, dates=LATER)
    assert after["drafts"] == 1 and after["deferred"] == 0
    [current] = world["alerts"].all_searches()
    assert current.alerted_keys == [SUBJECT, 9870002]
    assert current.checked_as_of == LATER.active
    second = next(d for d in _drafts(world) if d.id != first.id)
    assert "*2 Invented Way*" in second.body and "*1 Invented Way*" not in second.body
    assert _job(world, dates=LATER)["drafts"] == 0 and len(_drafts(world)) == 2
    assert world["alerts"].all_searches() == [current]


@pytest.mark.parametrize("breakage", ["stale", "missing"])
def test_all_on_with_a_broken_store_is_unavailable_everywhere(world, breakage):
    world["configured"] = world["store_path"]
    dotenv(badges="1", explanations="1", saved="1")
    world["alerts"].add_feature_search(OWNER_KEY, SOLAR, CHECKED)
    plain = world["alerts"].add(
        OWNER_KEY, PropertySearchFilters(city="Monrovia"), CHECKED
    )
    before = {
        s.id: (s.checked_as_of, s.alerted_keys) for s in world["alerts"].all_searches()
    }
    if breakage == "stale":
        _touch(world, FILLER[:10])  # more than STALE_SHARE changed after the snapshot
    else:
        world["configured"] = world["store_path"].with_name("absent.sqlite3")
    found = mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
    expected = "stale" if breakage == "stale" else "unavailable"
    assert found["data"]["feature_filter"]["status"] == expected
    assert found["data"]["listings"] == [] and found["data"]["total_matches"] is None
    assert found["message"] == (
        mcp.FEATURE_STALE_MESSAGE
        if breakage == "stale"
        else mcp.FEATURE_UNAVAILABLE_MESSAGE
    )
    # Plain search still works and carries no badges; recommend has no explanations.
    plain_search = mcp.search_listings(city="Pasadena")
    assert plain_search["data"]["listings"]
    assert "card_badges" not in plain_search["data"]
    assert "shared_features" not in mcp.recommend(listing_key=SUBJECT)["data"]
    refused = alerts.save_search(city="Pasadena", features=["pool"])
    assert refused["data"]["reason"] == "features_unavailable"
    # The alert job: the feature search is unavailable and untouched, never broadened.
    summary = _job(world)
    assert summary["unavailable"] == 1 and summary["failed"] == 0
    assert summary["unavailable_reasons"] == [breakage]
    after = {
        s.id: (s.checked_as_of, s.alerted_keys) for s in world["alerts"].all_searches()
    }
    feature_ids = [s.id for s in world["alerts"].all_searches() if s.filters.features]
    for sid in feature_ids:
        assert after[sid] == before[sid]
    bodies = [d.body for d in _drafts(world)]
    assert len(bodies) == 1 and "Monrovia" in bodies[0]
    assert all("solar" not in b for b in bodies)
    assert all("no new" not in b.lower() for b in bodies)
    assert after[plain.id][0] == ASOF.active  # the plain search still ran


# --- rollback: IDX_FEATURE_SAVED_SEARCHES off ---


def test_a_feature_search_saved_while_on_stays_inert_after_rollback(world, monkeypatch):
    world["configured"] = world["store_path"]
    dotenv(saved="1")
    earlier = ASOF.model_copy(update={"active": CHECKED})
    with monkeypatch.context() as m:
        m.setattr(alerts.asof, "get_asof_dates", lambda conn: earlier)
        saved = alerts.save_search(city="Pasadena", features=["solar"])
    assert saved["ok"] and saved["data"]["checked_as_of"] == str(CHECKED)
    [stored] = world["alerts"].all_searches()
    dotenv(saved="0")
    listed = alerts.list_saved_searches()
    assert alerts.SAVED_FEATURES_PAUSED.strip("; ") in listed["message"]
    # A new feature save is refused with the WO-021 question, never saved broader.
    refused = alerts.save_search(city="Pasadena", features=["pool"])
    assert refused["message"] == alerts.SAVED_FEATURES_QUESTION
    assert len(world["alerts"].all_searches()) == 1
    summary = _job(world)
    assert summary["unavailable_reasons"] == ["not_enabled"] and summary["drafts"] == 0
    [after] = world["alerts"].all_searches()
    assert after.filters.features == ("solar",)  # kept, never stripped or broadened
    assert (after.checked_as_of, after.alerted_keys) == (
        stored.checked_as_of,
        stored.alerted_keys,
    )
    assert _drafts(world) == []
    # Removing the store setting too (full Phase 1 rollback) is still fail-closed.
    world["configured"] = None
    assert _job(world)["unavailable"] == 1 and _drafts(world) == []
    # Switching back on resumes from the kept window: nothing was lost meanwhile.
    world["configured"] = world["store_path"]
    dotenv(saved="1")
    resumed = _job(world)
    assert resumed["drafts"] == 1 and resumed["unavailable"] == 0
