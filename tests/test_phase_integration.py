"""Combined offline checks for the features on main (#142, #143, #149, #146).

Search, badges, explanations and analysis routing: default off equals main, each
switch alone, all on, a broken store, rollback residue, and env versus .env (a switch
conflict or an image conflict leaves the tool off and is reported).
"""

# Ported from tests/test_phase_integration.py on the scratch branch
# `chore-phase-integration` (d6f4759), keeping the checks for features on main. The
# saved-alert checks live in #150 (tests/test_phase_integration_saved_searches.py) and
# the chart-delivery checks in #148 (tests/test_phase_integration_charts.py). One
# synthetic world: a real effective store of invented statuses, the real listing SQL
# on an SQLite stand-in, the WO-011 recommend harness, and install.sh against a temp
# HOME. Switches live in a temp `.env` in a temp working directory, as in production.

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
from evals import run as runner
from mcp.types import ImageContent
from tests.synthetic_store import write_synthetic_store
from tests.test_analysis_executor import fake_docker  # noqa: F401 - fixture
from tests.test_analysis_integration import (  # noqa: F401 - fixtures
    CODE,
    MEAN,
    SCATTER,
    reader,
    session_call,
    switch_on,
    worker,
    worker_json,
)
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

from idx_agent.analysis import tool as analysis_tool
from idx_agent.db import comps as db_comps
from idx_agent.db import listings as db_listings
from idx_agent.db import pool as db_pool
from idx_agent.db.comps import CompsAggregate
from idx_agent.domain.fieldmap import listing_columns
from idx_agent.enrichment import access as fa
from idx_agent.enrichment import effective_store
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore

POSIX = pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
SWITCHES = {
    "badges": mcp.BADGES_SETTING,
    "explanations": mcp.EXPLANATIONS_SETTING,
    "analysis": analysis_tool.TOOL_SETTING,
}
TRACE = "0" * 32
IMAGE_ENV = analysis_tool.IMAGE_ENV
BEFORE, AFTER = "2026-09-01 10:00:00", "2026-10-01 10:00:00"
LISTED = "2026-09-12"
FILLER = [9_000_000 + i for i in range(40)]  # unchanged, keeps the store fresh
SOLAR_POOL = ["pool", "solar"]
# Pinned from main cbad756 (computed there with this module's `surfaces` dump): the
# default-off tool list and instructions must not move.
MAIN_IDX_TOOLS = [
    "draft_email",
    "find_similar_listings",
    "get_market_stats",
    "health",
    "rag_answer",
    "recommend",
    "search_listings",
]
MAIN_DIGESTS = {
    "idx_tools": "7e1e85cce10c29047d215d6656d93d03eee72c89f147309a49f2fdc8d352e0c7",
    "instructions": "46dfa9cc268710ced8776ecac5524fcb361953c6efd5b490bbedb09da1e61b06",
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
    write_synthetic_store(path, rows, dict(META, source_rows=len(rows)))
    return path


def _clear_switch_env(monkeypatch) -> None:
    """The switches belong in `.env` only; CI exports its worker image."""
    for name in SWITCHES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(IMAGE_ENV, raising=False)


@pytest.fixture
def world(tmp_path, monkeypatch, served):  # noqa: F811
    engine = _engine()
    state = {
        "engine": engine,
        "store_path": _write_store(tmp_path / "effective.sqlite3"),
        "configured": None,  # no store configured until a test says so
        "cwd": tmp_path / "repo",
        "opened": 0,
    }
    state["cwd"].mkdir()
    monkeypatch.chdir(state["cwd"])  # the `.env` written below is this one

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

    _clear_switch_env(monkeypatch)
    monkeypatch.setattr(db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(db_pool, "connect", lambda config=None: Conn(engine))
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(db_listings, "fetch_candidates", fetch)
    monkeypatch.setattr(db_comps, "fetch_comps", comps)
    monkeypatch.setattr(effective_store, "open_store", counting_open)
    monkeypatch.setattr(
        effective_store, "configured_store_path", lambda: state["configured"]
    )
    monkeypatch.setattr(mcp, "new_trace_id", lambda: TRACE)
    monkeypatch.setattr(mcp, "memory_key", lambda raw, secret=None: raw and "c1" * 32)
    _fresh_sessions()
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


def restart(**on: str) -> None:
    """Write the cwd `.env` (the switches' one home) and restart the tool server as
    `main()` does: the analysis switch is read once, at start."""
    lines = [f"{SWITCHES[name]}={value}" for name, value in on.items()]
    lines.append(f"{IMAGE_ENV}={IMAGE}")
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


def surfaces() -> dict[str, str]:
    """Everything a user or the model sees, with one fresh session per read."""
    _fresh_sessions()
    return {
        "idx_tools": _dump(asyncio.run(_list(mcp.server))),
        "instructions": mcp.server.instructions or "",
        "routing": runner.routing_prompt(runner.configured_skills()),
        "search_plain": _dump(mcp.search_listings(city="Pasadena")),
        "search_features": _dump(
            mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
        ),
        "recommend": _dump(mcp.recommend(listing_key=SUBJECT)),
    }


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _changed(base: dict[str, str], other: dict[str, str]) -> set[str]:
    return {k for k in base if base[k] != other[k]}


def _keys(envelope: dict) -> list[int]:
    return [x["listing_key"] for x in envelope["data"]["listings"]]


def _present(world, key: int) -> frozenset[str]:
    conn = Conn(world["engine"])
    with fa.FeatureAccess.configured() as access:
        assert access.readiness(conn).usable
        return access.present_features([key], conn).get(str(key), frozenset())


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
    restart()
    got = surfaces()
    assert mcp.tool_names() == MAIN_IDX_TOOLS
    for name, digest in MAIN_DIGESTS.items():
        assert _digest(got[name]) == digest, name
    assert runner.configured_skills() == SKILLS
    assert "bounded" not in got["routing"]
    assert world["opened"] == 0  # nothing opened the store: none is configured
    assert mcp.analysis_switch_problem() is None


def test_a_configured_store_with_every_switch_off_changes_nothing_but_features(world):
    """Feature search itself needs only the store (WO-021, Phase 1 step 1)."""
    restart()
    unset = surfaces()
    world["configured"] = world["store_path"]
    restart(**dict.fromkeys(SWITCHES, "0"))
    configured = surfaces()
    assert _changed(unset, configured) == {"search_features"}
    assert world["opened"] >= 1


# --- (b) each switch alone changes only its own surface ---

ALONE = {
    "badges": {"search_plain", "search_features"},
    "explanations": {"recommend"},
    "analysis": {"idx_tools", "instructions", "routing"},
}


@pytest.mark.parametrize("name", list(ALONE))
def test_each_switch_alone_changes_only_its_own_surface(world, name):
    world["configured"] = world["store_path"]
    restart()
    base = surfaces()
    restart(**{name: "1"})
    assert _changed(base, surfaces()) == ALONE[name]


# --- (c) all on together: one store, one set of facts ---


def test_all_on_search_badges_explanations_and_routing_agree(world):
    world["configured"] = world["store_path"]
    restart(**dict.fromkeys(SWITCHES, "1"))
    found = mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
    assert found["data"]["feature_filter"]["status"] == "applied"
    keys = _keys(found)
    assert sorted(keys) == [SUBJECT, 9870002]
    card = found["data"]["card_badges"]
    assert card["snapshot_watermark"] == META["source_watermark"]
    badges = {int(k): v for k, v in card["badges"].items()}
    for key in keys:
        assert badges[key][:2] == SOLAR_POOL  # requested first
        assert set(badges[key]) <= set(_present(world, key))
    # Recommend's explanations come from the same store as the search's badges.
    rec = mcp.recommend(listing_key=SUBJECT)
    shared = {int(k): v for k, v in rec["data"]["shared_features"]["features"].items()}
    assert shared == {9870002: SOLAR_POOL, 9870004: ["hardwood"]}
    for key, features in shared.items():
        assert set(features) <= set(_present(world, key))
    assert set(shared[9870002]) <= set(badges[9870002])
    # Analysis is registered beside them; the base tools are unchanged.
    assert mcp.tool_names() == sorted([*MAIN_IDX_TOOLS, analysis_tool.TOOL_NAME])
    assert mcp.server.instructions == mcp.ANALYSIS_INSTRUCTIONS
    assert runner.configured_skills() == [*SKILLS, "bounded-analysis"]
    assert "## Skill: bounded-analysis" in runner.routing_prompt(
        runner.configured_skills()
    )


@pytest.mark.parametrize("breakage", ["stale", "missing"])
def test_all_on_with_a_broken_store_is_unavailable_everywhere(world, breakage):
    world["configured"] = world["store_path"]
    restart(**dict.fromkeys(SWITCHES, "1"))
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
    plain = mcp.search_listings(city="Pasadena")
    assert plain["data"]["listings"]
    assert "card_badges" not in plain["data"]
    rec = mcp.recommend(listing_key=SUBJECT)
    assert rec["ok"] and "shared_features" not in rec["data"]
    # The analysis tool does not depend on the feature store.
    assert analysis_tool.TOOL_NAME in mcp.tool_names()


# --- (d) analyst routing: the routed call runs with the store features also on ---


def test_analysis_routes_to_a_checked_answer_with_badges_and_explanations_on(
    reader,  # noqa: F811 - the imported fixture
    worker,  # noqa: F811 - the imported fixture
    monkeypatch,
):
    """The bounded_analysis call #146 routes to returns verified figures and the
    checked PNG inline (no chart delivery on main), with the other switches on."""
    monkeypatch.setenv(mcp.BADGES_SETTING, "1")
    monkeypatch.setenv(mcp.EXPLANATIONS_SETTING, "1")
    assert mcp.server.instructions == mcp.ANALYSIS_INSTRUCTIONS
    assert "bounded_analysis (a one-off analysis" in mcp.server.instructions
    worker["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True
    assert f"${MEAN:,.2f}, verified (n=50)" in payload["message"]
    assert [type(b) for b in images] == [ImageContent]
    assert "MEDIA:" not in payload["message"]
    assert reader["fetch"] == 1


# --- (e) rollback: each switch back off => (a), with no residue ---


def test_rollback_of_every_switch_returns_to_the_default(world):
    world["configured"] = world["store_path"]
    restart(**dict.fromkeys(SWITCHES, "0"))
    base = surfaces()
    restart(**dict.fromkeys(SWITCHES, "1"))
    assert _changed(base, surfaces()) == {
        "idx_tools",
        "instructions",
        "routing",
        "search_plain",
        "search_features",
        "recommend",
    }
    remaining = dict.fromkeys(SWITCHES, "1")
    for name in ["analysis", "explanations", "badges"]:
        remaining[name] = "0"
        restart(**remaining)
    assert surfaces() == base
    # Phase 1 rollback: the store setting goes too, and main's surfaces come back.
    world["configured"] = None
    restart()
    got = surfaces()
    for name, digest in MAIN_DIGESTS.items():
        assert _digest(got[name]) == digest, name


@POSIX
def test_install_rollback_leaves_no_residue_in_a_temp_home(tmp_path):
    base = [f"IDX_OWNER_E164={OWNER}", f"IDX_ANALYSIS_IMAGE={IMAGE}"]
    default = _install(tmp_path / "a", base)
    assert default.returncode == 0, default.stderr
    every = [*base, *(f"{s}=1" for s in SWITCHES.values())]
    on = _install(tmp_path / "b", every)
    assert on.returncode == 0, on.stderr
    state = tmp_path / "b" / "state"
    assert (state / "openclaw.analysis.json5").exists()
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
    # Residue: the same files as a default install, plus install.sh's own backup.
    assert sorted(p.name for p in state.iterdir()) == sorted(
        [p.name for p in (tmp_path / "a" / "state").iterdir()]
        + ["openclaw.json.pre-idx.bak"]
    )


# --- (f) env versus .env ---


@POSIX
@pytest.mark.parametrize("name", ["badges", "explanations"])
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


OTHER_IMAGE = "sha256:" + "b" * 64
TOOL = analysis_tool.TOOL_SETTING
# (kind, the switch line in .env or None, the process environment). The switch kind
# contradicts .env on IDX_ANALYSIS_TOOL; the image kind has the switch on in .env (and
# in the environment too, for the second) and exports a different worker digest.
CONFLICTS = {
    "switch-env-0": ("switch", "1", {TOOL: "0"}),
    "switch-env-only": ("switch", None, {TOOL: "1"}),
    "image": ("image", "1", {IMAGE_ENV: OTHER_IMAGE}),
    "image-switch-in-both": ("image", "1", {TOOL: "1", IMAGE_ENV: OTHER_IMAGE}),
}


@POSIX
@pytest.mark.parametrize("case", list(CONFLICTS))
def test_a_switch_or_image_conflict_unregisters_and_reports(
    tmp_path, monkeypatch, capsys, case
):
    """install.sh refuses both kinds before writing. The server registers nothing for
    either (7 tools, base instructions; an image conflict fails closed, owner decision
    2026-11-03) and reports the problem in health and in the start log."""
    kind, dotenv_value, env = CONFLICTS[case]
    lines = [f"IDX_OWNER_E164={OWNER}", f"{IMAGE_ENV}={IMAGE}"]
    lines += [f"{TOOL}={dotenv_value}"] if dotenv_value is not None else []
    done = _install(tmp_path, lines, extra_env=env)
    named = TOOL if kind == "switch" else IMAGE_ENV
    assert done.returncode == 1 and done.stderr.startswith("install.sh: Bounded")
    assert named in done.stderr
    assert not (tmp_path / "state").exists()  # refused before anything was written
    _clear_switch_env(monkeypatch)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    values = db_pool.dotenv_values(tmp_path / "repo" / ".env")
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(values))
    monkeypatch.setattr(db_pool, "database_configured", lambda: False)
    try:
        registered = mcp.register_analysis_tool()
        mcp.log_start()
        problem = mcp.analysis_switch_problem()
        assert problem and named in problem and problem in done.stderr
        assert (problem == analysis_tool.IMAGE_DIFFERS) is (kind == "image")
        assert "the tool is not registered." in problem
        assert registered is False
        assert analysis_tool.TOOL_NAME not in mcp.tool_names()
        assert mcp.server.instructions == mcp.BASE_INSTRUCTIONS
        health = mcp.health_result(trace_id=TRACE)
        assert health.ok and health.warnings == [problem]
        assert health.message.endswith(problem)
        start = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
        assert start["event"] == "server_start"
        assert start["analysis_switch_problem"] == problem
        assert analysis_tool.TOOL_NAME not in start["tools"]
        assert len(start["tools"]) == len(MAIN_IDX_TOOLS)
    finally:
        mcp.reset_analysis_tool_for_tests()
