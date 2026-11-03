"""Combined Phase 1/2 checks across #142, WO-024, WO-025, #146 and WO-030 (offline).

One synthetic world: a real effective store of invented statuses, the real listing SQL
on an SQLite stand-in, the WO-011 recommend harness, a synthetic alert store, and
install.sh against a temp HOME. Switches live in a temp `.env`, as in production.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
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
from tests.test_openclaw_merge_config import IMAGE, OWNER, SKILLS, _install, load
from tests.test_recommend_explanations import META, STATUSES

from idx_agent.alerts import features as saved_features
from idx_agent.alerts import server as alerts
from idx_agent.alerts.query import fetch_new, fetch_new_features
from idx_agent.alerts.run import run_job
from idx_agent.alerts.store import AlertStore
from idx_agent.analysis import delivery
from idx_agent.analysis import tool as analysis_tool
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

POSIX = pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
SWITCHES = {
    "badges": mcp.BADGES_SETTING,
    "explanations": mcp.EXPLANATIONS_SETTING,
    "saved": saved_features.SETTING,
    "analysis": analysis_tool.TOOL_SETTING,
    "charts": delivery.SWITCH,
}
TRACE = "0" * 32
IMAGE_ENV = "IDX_ANALYSIS_IMAGE"
SENDER = "ab" * 32
BEFORE, AFTER = "2026-09-01 10:00:00", "2026-10-01 10:00:00"
LISTED, CHECKED = "2026-09-12", date(2026, 9, 10)
FILLER = [9_000_000 + i for i in range(40)]  # unchanged, keeps the store fresh
SOLAR_POOL = ["pool", "solar"]
# Pinned from main 5432dc2 (cross-tree probe): default-off surfaces must not move.
MAIN_IDX_TOOLS = [
    "draft_email",
    "find_similar_listings",
    "get_market_stats",
    "health",
    "rag_answer",
    "recommend",
    "search_listings",
]
MAIN_ALERT_TOOLS = [
    "save_search",
    "list_saved_searches",
    "delete_saved_search",
    "forget_me",
]
MAIN_DIGESTS = {
    "idx_tools": "7e1e85cce10c29047d215d6656d93d03eee72c89f147309a49f2fdc8d352e0c7",
    "instructions": "46dfa9cc268710ced8776ecac5524fcb361953c6efd5b490bbedb09da1e61b06",
    "alerts_tools": "3d9f918f166a2a8a55be0145d192d9377fd66e66787fe94bec6313321f70e62d",
}


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


def _write_store(path: Path) -> Path:
    statuses = {**STATUSES, **{k: {"garage": "present"} for k in FILLER}}
    rows = [(str(k), v) for k, v in sorted(statuses.items())]
    effective_store.write_store(path, rows, dict(META, source_rows=len(rows)))
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
    monkeypatch.delenv(delivery.DIR_SETTING, raising=False)
    monkeypatch.delenv(IMAGE_ENV, raising=False)  # CI exports its worker image
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
    monkeypatch.setattr(mcp, "memory_key", lambda raw, secret=None: raw and "c1" * 32)
    mcp.reset_store_for_tests(
        InMemorySessionStore(
            timedelta(minutes=30), 10, lambda: datetime(2026, 9, 18, tzinfo=UTC)
        )
    )
    fa.reset_for_tests()
    yield state
    fa.reset_for_tests()
    mcp.reset_store_for_tests()
    mcp.reset_analysis_tool_for_tests()


def _fresh_sessions() -> None:
    mcp.reset_store_for_tests(
        InMemorySessionStore(
            timedelta(minutes=30), 10, lambda: datetime(2026, 9, 18, tzinfo=UTC)
        )
    )


def dotenv(**on: str) -> None:
    """Write the cwd `.env` (the switches' one home) and restart the tool server."""
    lines = [f"{SWITCHES[name]}={value}" for name, value in on.items()]
    (Path.cwd() / ".env").write_text("\n".join(lines) + "\n")
    mcp.reset_analysis_tool_for_tests()
    mcp.register_analysis_tool()
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
        "instructions": mcp.server.instructions or "",
        "alerts_tools": _dump(asyncio.run(_list(alerts.server))),
        "search_plain": _dump(mcp.search_listings(city="Pasadena")),
        "search_features": _dump(
            mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
        ),
        "recommend": _dump(mcp.recommend(listing_key=SUBJECT)),
        "save_plain": _dump(alerts.save_search(city="Monrovia")),
        "save_features": _dump(alerts.save_search(city="Pasadena", features=["solar"])),
        "list": _dump(alerts.list_saved_searches()),
        "charts": str(delivery.enabled(db_pool.env_setting)),
    }
    _forget_saved(world)
    return out


def _forget_saved(world) -> None:
    with world["alerts"].transaction(write=True) as conn:
        conn.execute("DELETE FROM searches")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _changed(base: dict[str, str], other: dict[str, str]) -> set[str]:
    return {k for k in base if base[k] != other[k]}


def _keys(envelope: dict) -> list[int]:
    return [x["listing_key"] for x in envelope["data"]["listings"]]


def _job(world, conn=None):
    """The alert job exactly as `alerts.run.main` wires it."""
    conn = conn or Conn(world["engine"])
    with fa.FeatureAccess.configured() as access:
        return run_job(
            world["alerts"],
            world["gate"],
            reader=lambda s, d: fetch_new(s, d, conn),
            dates=ASOF,
            recipient="owner" + "@" + "example.test",
            bind_features=lambda f: access.bind(f, conn),
            feature_reader=lambda s, h, sc: fetch_new_features(s, h, sc, conn),
        )


def _drafts(world) -> list:
    gate = world["gate"]
    return gate.list_pending() if gate.path.exists() else []


def _make_stale(world) -> None:
    """More than STALE_SHARE of active listings changed after the snapshot."""
    world["engine"].execute(
        "UPDATE rets_property SET ModificationTimestamp = ? WHERE L_ListingID IN "
        f"({', '.join('?' * 10)})",
        [AFTER, *(str(k) for k in FILLER[:10])],
    )
    fa.reset_for_tests()


# --- (a) default off: no switch, no store => main's behaviour ---


def test_default_off_surfaces_match_main(world):
    dotenv()
    got = surfaces(world)
    assert mcp.tool_names() == MAIN_IDX_TOOLS
    assert [t["name"] for t in json.loads(got["alerts_tools"])] == MAIN_ALERT_TOOLS
    for name, digest in MAIN_DIGESTS.items():
        assert _digest(got[name]) == digest, name
    assert world["opened"] == 0  # nothing opened the store: none is configured
    assert got["charts"] == "False"


def test_a_configured_store_with_every_switch_off_changes_nothing_but_features(world):
    """Feature search itself needs only the store (WO-021, Phase 1 step 1)."""
    dotenv()
    unset = surfaces(world)
    world["configured"] = world["store_path"]
    dotenv(**dict.fromkeys(SWITCHES, "0"))
    configured = surfaces(world)
    assert _changed(unset, configured) == {"search_features"}
    assert world["opened"] >= 1


# --- (b) each switch alone changes only its own surface ---

ALONE = {
    "badges": {"search_plain", "search_features"},
    "explanations": {"recommend"},
    "saved": {"save_features", "list"},
    "analysis": {"idx_tools", "instructions"},
    "charts": set(),  # inert without the analysis switch
}


@pytest.mark.parametrize("name", list(ALONE))
def test_each_switch_alone_changes_only_its_own_surface(world, name):
    world["configured"] = world["store_path"]
    dotenv()
    base = surfaces(world)
    dotenv(**{name: "1"})
    assert _changed(base, surfaces(world)) == ALONE[name]


def test_charts_with_analysis_change_only_the_delivery_switch(world):
    """Same tools, schemas and instructions as analysis alone (WO-030 claim)."""
    world["configured"] = world["store_path"]
    dotenv(analysis="1")
    analysis_only = surfaces(world)
    dotenv(analysis="1", charts="1")
    both = surfaces(world)
    assert _changed(analysis_only, both) == {"charts"}
    assert analysis_tool.TOOL_NAME in mcp.tool_names()


# --- (c) all on together: one store, one set of facts ---


def test_all_on_search_badges_explanations_and_alerts_agree(world):
    world["configured"] = world["store_path"]
    dotenv(**dict.fromkeys(SWITCHES, "1"))
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
    rec = mcp.recommend(listing_key=keys[0] if keys[0] == SUBJECT else keys[1])
    shared = {int(k): v for k, v in rec["data"]["shared_features"]["features"].items()}
    assert shared == {9870002: SOLAR_POOL, 9870004: ["hardwood"]}
    for key, features in shared.items():
        assert set(features) <= set(_present(world, key))
    assert set(shared[9870002]) <= set(badges[9870002])
    # A saved feature search alerts on exactly what a live search finds.
    saved = alerts.save_search(city="Pasadena", features=["solar"])
    assert saved["ok"] and saved["data"]["filters"]["features"] == ["solar"]
    _forget_saved(world)
    world["alerts"].add_feature_search(
        "c1" * 32, PropertySearchFilters(city="Pasadena", features=["solar"]), CHECKED
    )
    summary = _job(world)
    assert summary["drafts"] == 1 and summary["unavailable"] == 0
    [draft] = _drafts(world)
    live = mcp.search_listings(city="Pasadena", features=["solar"], limit=10)
    for key in _keys(live):
        assert f"*{key % 1000} Invented Way*" in draft.body
    assert draft.body.count(" Invented Way*") == len(_keys(live))
    assert "solar" in draft.body
    # Analysis and charts are registered beside them; the base tools are unchanged.
    assert mcp.tool_names() == sorted([*MAIN_IDX_TOOLS, analysis_tool.TOOL_NAME])
    assert delivery.enabled(db_pool.env_setting)


def _present(world, key: int) -> frozenset[str]:
    conn = Conn(world["engine"])
    with fa.FeatureAccess.configured() as access:
        assert access.readiness(conn).usable
        return access.present_features([key], conn).get(str(key), frozenset())


@pytest.mark.parametrize("breakage", ["stale", "missing"])
def test_all_on_with_a_broken_store_is_unavailable_everywhere(world, breakage):
    world["configured"] = world["store_path"]
    dotenv(**dict.fromkeys(SWITCHES, "1"))
    world["alerts"].add_feature_search(
        "c1" * 32, PropertySearchFilters(city="Pasadena", features=["solar"]), CHECKED
    )
    plain = world["alerts"].add(
        "c1" * 32, PropertySearchFilters(city="Monrovia"), CHECKED
    )
    before = {
        s.id: (s.checked_as_of, s.alerted_keys) for s in world["alerts"].all_searches()
    }
    if breakage == "stale":
        _make_stale(world)
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


# --- (d) rollback: each switch back off => (a), with no residue ---


def test_rollback_of_every_switch_returns_to_the_default(world):
    world["configured"] = world["store_path"]
    dotenv(**dict.fromkeys(SWITCHES, "0"))
    base = surfaces(world)
    dotenv(**dict.fromkeys(SWITCHES, "1"))
    on = surfaces(world)
    assert _changed(base, on) == {
        "idx_tools",
        "instructions",
        "search_plain",
        "search_features",
        "recommend",
        "save_features",
        "list",
        "charts",
    }
    remaining = dict.fromkeys(SWITCHES, "1")
    for name in ["charts", "analysis", "saved", "explanations", "badges"]:
        remaining[name] = "0"
        dotenv(**remaining)
    assert surfaces(world) == base


def test_a_feature_search_saved_while_on_stays_inert_after_rollback(world):
    world["configured"] = world["store_path"]
    dotenv(saved="1")
    earlier = ASOF.model_copy(update={"active": CHECKED})
    real = alerts.asof.get_asof_dates
    alerts.asof.get_asof_dates = lambda conn: earlier
    try:
        saved = alerts.save_search(city="Pasadena", features=["solar"])
    finally:
        alerts.asof.get_asof_dates = real
    assert saved["ok"] and saved["data"]["checked_as_of"] == str(CHECKED)
    [stored] = world["alerts"].all_searches()
    dotenv(saved="0")
    listed = alerts.list_saved_searches()
    assert alerts.SAVED_FEATURES_PAUSED.strip("; ") in listed["message"]
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


@POSIX
def test_install_rollback_restores_the_default_config_with_every_switch(tmp_path):
    base = [f"IDX_OWNER_E164={OWNER}", f"IDX_ANALYSIS_IMAGE={IMAGE}"]
    default = _install(tmp_path / "a", base)
    assert default.returncode == 0, default.stderr
    every = [*base, *(f"{s}=1" for s in SWITCHES.values())]
    on = _install(tmp_path / "b", every)
    assert on.returncode == 0, on.stderr
    state = tmp_path / "b" / "state"
    assert (state / "openclaw.analysis.json5").exists()
    assert "Chart delivery is on" in on.stdout
    skills = load().load_json5(state / "openclaw.json")["agents"]["entries"]["idx"]
    assert skills["skills"] == [*SKILLS, "bounded-analysis"]
    off = _install(tmp_path / "b", base)
    assert off.returncode == 0, off.stderr
    assert not (state / "openclaw.analysis.json5").exists()
    merged = json.loads((state / "openclaw.json").read_text())
    expected = (tmp_path / "a" / "state" / "openclaw.json").read_text()
    relocated = tmp_path / "default.json5"
    relocated.write_text(expected.replace(str(tmp_path / "a"), str(tmp_path / "b")))
    assert merged == load().load_json5(relocated)
    assert "Chart delivery" not in off.stdout


# --- (e) env versus .env, for every switch install.sh and the server both read ---


@POSIX
@pytest.mark.parametrize("name", ["badges", "explanations", "saved"])
def test_runtime_only_switches_never_change_the_install(tmp_path, name):
    """install.sh never reads them, so env and .env cannot make it disagree."""
    base = [f"IDX_OWNER_E164={OWNER}"]
    plain = _install(tmp_path / "a", base)
    flipped = _install(
        tmp_path / "b", [*base, f"{SWITCHES[name]}=1"], extra_env={SWITCHES[name]: "0"}
    )
    assert plain.returncode == flipped.returncode == 0
    a = (tmp_path / "a" / "state" / "openclaw.json").read_text()
    b = (tmp_path / "b" / "state" / "openclaw.json").read_text()
    assert a.replace(str(tmp_path / "a"), "X") == b.replace(str(tmp_path / "b"), "X")
    assert plain.stdout.replace(str(tmp_path / "a"), "X") == flipped.stdout.replace(
        str(tmp_path / "b"), "X"
    )


@POSIX
@pytest.mark.parametrize(("env", "dotenv_value"), [("0", "1"), ("1", None)])
def test_analysis_conflict_stops_install_and_keeps_charts_off(
    tmp_path, monkeypatch, env, dotenv_value
):
    lines = [
        f"IDX_OWNER_E164={OWNER}",
        f"IDX_ANALYSIS_IMAGE={IMAGE}",
        f"{delivery.SWITCH}=1",
    ]
    if dotenv_value is not None:
        lines.append(f"{analysis_tool.TOOL_SETTING}={dotenv_value}")
    done = _install(tmp_path, lines, extra_env={analysis_tool.TOOL_SETTING: env})
    assert done.returncode == 1 and analysis_tool.TOOL_SETTING in done.stderr
    assert not (tmp_path / "state" / "openclaw.json").exists()
    monkeypatch.setenv(analysis_tool.TOOL_SETTING, env)
    monkeypatch.delenv(IMAGE_ENV, raising=False)  # CI exports its worker image
    values = db_pool.dotenv_values(tmp_path / "repo" / ".env")
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(values))
    try:
        assert mcp.register_analysis_tool() is False
        assert analysis_tool.TOOL_NAME not in mcp.tool_names()
    finally:
        mcp.reset_analysis_tool_for_tests()


@pytest.mark.xfail(
    strict=True,
    reason="#148: IDX_CHART_DELIVERY/IDX_CHART_DIR are env-wins at runtime but "
    "install.sh reports .env only; a contradicting environment goes unreported",
)
@pytest.mark.parametrize(("env", "dotenv_value"), [("", "1"), ("0", "1"), ("1", None)])
def test_chart_switch_env_and_dotenv_agree_or_are_reported(
    monkeypatch, env, dotenv_value
):
    values = {analysis_tool.TOOL_SETTING: "1"}
    if dotenv_value is not None:
        values[delivery.SWITCH] = dotenv_value
    install_says_on = delivery.enabled(values.get)  # what install.sh reports
    monkeypatch.delenv(IMAGE_ENV, raising=False)  # CI exports its worker image
    monkeypatch.setenv(delivery.SWITCH, env)
    monkeypatch.delenv(analysis_tool.TOOL_SETTING, raising=False)
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(values))
    try:
        mcp.register_analysis_tool()
        runtime_on = delivery.enabled(db_pool.env_setting)
        assert runtime_on == install_says_on or mcp.analysis_switch_problem()
    finally:
        mcp.reset_analysis_tool_for_tests()
