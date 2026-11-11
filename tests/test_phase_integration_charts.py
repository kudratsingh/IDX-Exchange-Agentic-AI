"""Combined offline checks: WO-030 chart delivery with the features already on main.

Badges, explanations (#142, WO-024) and bounded analysis (#146) with chart delivery:
default off equals main, each switch moves only its surface, routing, expiry, rollback,
and install.sh and the server agreeing on IDX_CHART_DELIVERY and IDX_CHART_DIR.
"""

# Ported from tests/test_phase_integration.py on the scratch branch
# `chore-phase-integration`, keeping the checks that concern chart delivery. Its three
# strict xfails are obsolete (#148 made install.sh and the server agree): they are real
# assertions here, against `server.configure_chart_delivery()` and
# `server.chart_delivery_problem()`. Saved feature searches (WO-025) stay with #147.
# One synthetic world: a real effective store of invented statuses, the real listing
# SQL on an SQLite stand-in, the WO-011 recommend harness, and install.sh against a temp
# HOME. Switches live in a temp `.env` in a temp working directory, as in production.

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
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
from tests.test_analysis_service import PNG
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

from idx_agent.analysis import delivery
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
    "charts": delivery.SWITCH,
}
TRACE = "0" * 32
IMAGE_ENV = analysis_tool.IMAGE_ENV
BEFORE = "2026-09-01 10:00:00"
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
# Digest note, 2026-11-05 (owner-accepted 2026-11-05; P1-4 follow-up, PR #169):
# idx_tools 7e1e85cc -> 8185de44. Only the search_listings `features` parameter
# description changed, to match the property-search skill: a request about what
# listing descriptions say goes to `features`, a pool included. The skill and the
# schema had disagreed (P1-4, trace 8e84ac5c94834523), and this digest hashes every
# parameter description, so the pin moved with that one sentence. The tool list, the
# instructions digest and the routing pins (tests/test_routing_contract.py) did not.
# Digest note, 2026-11-10 (WO-042): instructions 46dfa9cc -> 594b8468. The "can't help"
# sentence leaves out a transactional request, which gets the response policy's
# referral line; the same move as the routing pin. The tool list did not change.
MAIN_DIGESTS = {
    "idx_tools": "8185de445e856ab49935d94a17c6710bd027f92ea5f3a844a863f82c7924469c",
    "instructions": "594b8468e33742b9396dff02bda83b81606b08a0a7b7ed3fbbeeb246db34e4d3",
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
    monkeypatch.delenv(delivery.DIR_SETTING, raising=False)
    monkeypatch.delenv(IMAGE_ENV, raising=False)


@pytest.fixture
def world(tmp_path, monkeypatch, served):  # noqa: F811
    engine = _engine()
    workspace = tmp_path / "workspace-idx"
    workspace.mkdir()
    state = {
        "engine": engine,
        "store_path": _write_store(tmp_path / "effective.sqlite3"),
        "configured": None,  # no store configured until a test says so
        "chart_dir": workspace / delivery.DIR_NAME,
        "cwd": tmp_path / "repo",
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

    _clear_switch_env(monkeypatch)
    monkeypatch.setattr(db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(db_pool, "connect", lambda config=None: Conn(engine))
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(db_listings, "fetch_candidates", fetch)
    monkeypatch.setattr(db_comps, "fetch_comps", comps)
    monkeypatch.setattr(
        effective_store, "configured_store_path", lambda: state["configured"]
    )
    monkeypatch.setattr(mcp, "new_trace_id", lambda: TRACE)
    monkeypatch.setattr(mcp, "memory_key", lambda raw, secret=None: raw and "c1" * 32)
    _fresh_sessions()
    fa.reset_for_tests()
    delivery.reset_store_for_tests()
    yield state
    fa.reset_for_tests()
    mcp.reset_store_for_tests()
    mcp.reset_analysis_tool_for_tests()
    delivery.reset_store_for_tests()


def _fresh_sessions() -> None:
    mcp.reset_store_for_tests(
        InMemorySessionStore(
            timedelta(minutes=30), 10, lambda: datetime(2026, 9, 18, tzinfo=UTC)
        )
    )


def restart(world, **on: str) -> None:
    """Write the cwd `.env` (the switches' one home) and restart the tool server as
    `main()` does: analysis switch, chart delivery, start sweep."""
    lines = [f"{SWITCHES[name]}={value}" for name, value in on.items()]
    lines += [f"{IMAGE_ENV}={IMAGE}", f"{delivery.DIR_SETTING}={world['chart_dir']}"]
    (Path.cwd() / ".env").write_text("\n".join(lines) + "\n")
    mcp.reset_analysis_tool_for_tests()
    delivery.reset_store_for_tests()
    mcp.register_analysis_tool()
    mcp.configure_chart_delivery()
    assert mcp._prune_charts_at_start() is True
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
        "search_plain": _dump(mcp.search_listings(city="Pasadena")),
        "search_features": _dump(
            mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
        ),
        "recommend": _dump(mcp.recommend(listing_key=SUBJECT)),
        "charts": str(mcp._chart_state is not None and mcp._chart_state.on),
    }


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _changed(base: dict[str, str], other: dict[str, str]) -> set[str]:
    return {k for k in base if base[k] != other[k]}


# --- (a) default off: no switch => main's surfaces, nothing armed ---


def test_default_off_surfaces_match_main(world):
    restart(world)
    got = surfaces()
    assert mcp.tool_names() == MAIN_IDX_TOOLS
    for name, digest in MAIN_DIGESTS.items():
        assert _digest(got[name]) == digest, name
    assert got["charts"] == "False" and mcp.chart_delivery_problem() is None
    assert mcp._arm_chart_expiry() is False
    assert not world["chart_dir"].exists()


_OFF_PROBE = """
import json, signal, sys, threading
import idx_agent.mcp_server.server as s
s.register_analysis_tool()
s.configure_chart_delivery()
s._prune_charts_at_start()
armed = s._arm_chart_expiry()
print(json.dumps({"armed": armed, "threads": threading.active_count(),
                  "sigterm": signal.getsignal(signal.SIGTERM) is signal.SIG_DFL,
                  "tools": s.tool_names()}))
"""


def test_default_off_start_arms_no_handler_and_no_thread(tmp_path):
    """A fresh process through main()'s start steps with an empty `.env`: no
    SIGTERM handler, no expiry thread, main's tool list."""
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / ".env").write_text("")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("IDX_", "MYSQL_"))}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["HOME"] = str(tmp_path / "home")
    done = subprocess.run(
        [sys.executable, "-c", _OFF_PROBE],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out == {
        "armed": False,
        "threads": 1,
        "sigterm": True,
        "tools": MAIN_IDX_TOOLS,
    }


# --- (b) charts with the other switches: only their own surfaces move ---


def test_charts_alone_are_inert(world):
    """Without the analysis switch chart delivery changes nothing at all."""
    world["configured"] = world["store_path"]
    restart(world)
    base = surfaces()
    restart(world, charts="1")
    assert _changed(base, surfaces()) == set()
    assert mcp.chart_delivery_problem() is None


def test_charts_with_analysis_change_only_the_delivery_state(world):
    """Same tools, schemas, descriptions and instructions as analysis alone: routing
    (#146's server instructions and tool description) does not move with charts."""
    world["configured"] = world["store_path"]
    restart(world, analysis="1")
    analysis_only = surfaces()
    restart(world, analysis="1", charts="1")
    both = surfaces()
    assert _changed(analysis_only, both) == {"charts"}
    assert analysis_tool.TOOL_NAME in mcp.tool_names()
    assert mcp.server.instructions == mcp.ANALYSIS_INSTRUCTIONS


def test_all_on_badges_explanations_analysis_and_charts_agree(world):
    world["configured"] = world["store_path"]
    restart(world, **dict.fromkeys(SWITCHES, "1"))
    found = mcp.search_listings(city="Pasadena", features=SOLAR_POOL)
    assert found["data"]["feature_filter"]["status"] == "applied"
    keys = [x["listing_key"] for x in found["data"]["listings"]]
    assert sorted(keys) == [SUBJECT, 9870002]
    card = found["data"]["card_badges"]
    badges = {int(k): v for k, v in card["badges"].items()}
    for key in keys:
        assert badges[key][:2] == SOLAR_POOL
    rec = mcp.recommend(listing_key=SUBJECT)
    shared = {int(k): v for k, v in rec["data"]["shared_features"]["features"].items()}
    assert shared == {9870002: SOLAR_POOL, 9870004: ["hardwood"]}
    assert mcp.tool_names() == sorted([*MAIN_IDX_TOOLS, analysis_tool.TOOL_NAME])
    assert surfaces()["charts"] == "True"
    assert mcp.chart_delivery_problem() is None


# --- (c) analyst routing to a delivered chart, with expiry and rollback ---


@pytest.fixture
def charted(monkeypatch, tmp_path, request):
    """WO-027's worker fixtures plus chart delivery decided as at start."""
    request.getfixturevalue("reader")
    fake = request.getfixturevalue("worker")
    workspace = tmp_path / "workspace-idx"
    workspace.mkdir()
    directory = workspace / delivery.DIR_NAME
    real = db_pool.dotenv_values
    charts = {delivery.SWITCH: "1", delivery.DIR_SETTING: str(directory)}
    for key in charts:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        db_pool, "dotenv_values", lambda path=None: {**real(path), **charts}
    )
    monkeypatch.setenv(mcp.BADGES_SETTING, "1")
    monkeypatch.setenv(mcp.EXPLANATIONS_SETTING, "1")
    delivery.reset_store_for_tests()
    assert mcp.configure_chart_delivery() is True
    yield {"dir": directory, "worker": fake, "settings": charts}
    delivery.reset_store_for_tests()


def test_analysis_routes_to_a_delivered_chart_that_expires_while_idle(
    charted, monkeypatch
):
    """The bounded_analysis call (as routed by #146) delivers the chart through the
    MEDIA line with badges and explanations also on; with no further request the
    file is gone at its deadline (ttl shortened to 0.3 s)."""
    removed = threading.Event()
    real = delivery._unlink

    def unlink(path):
        done = real(path)
        if done and path.name.startswith("chart-"):
            removed.set()
        return done

    monkeypatch.setattr(delivery, "_unlink", unlink)
    delivery.store_for(charted["dir"]).ttl = 0.3
    charted["worker"]["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    assert f"${MEAN:,.2f}, verified (n=50)" in payload["message"]
    line = payload["message"].split("\n")[-1]
    assert line == payload["data"]["chart"]["delivery"]["media_line"]
    path = Path(line.removeprefix(delivery.MEDIA_PREFIX))
    assert path.read_bytes() == PNG
    assert removed.wait(timeout=5), "the chart outlived its deadline"
    assert not path.exists()


def test_rolling_back_charts_restores_wo027_and_disarms_expiry(
    charted, monkeypatch, capsys
):
    charted["worker"]["set"](worker_json(chart=SCATTER))
    session_call(city="Pasadena", code=CODE)
    assert len(list(charted["dir"].glob("chart-*.png"))) == 1
    before = signal.getsignal(signal.SIGTERM)
    hooks: list = []
    monkeypatch.setattr(delivery.atexit, "register", hooks.append)
    try:
        assert mcp._arm_chart_expiry() is True
    finally:
        signal.signal(signal.SIGTERM, before)
    # Rollback: IDX_CHART_DELIVERY leaves .env, the server restarts, prune --all.
    del charted["settings"][delivery.SWITCH]
    delivery.reset_store_for_tests()
    assert mcp.configure_chart_delivery() is False
    hooks.clear()
    assert mcp._arm_chart_expiry() is False and hooks == []
    payload, images = session_call(city="Pasadena", code=CODE)
    assert [type(b) for b in images] == [ImageContent]
    assert "MEDIA:" not in payload["message"]
    assert "delivery" not in payload["data"]["chart"]
    assert delivery.main(["prune", "--all"]) == 0
    assert "removed 1 chart file(s)" in capsys.readouterr().out
    assert list(charted["dir"].glob("chart-*.png")) == []


def test_rollback_of_every_switch_returns_to_the_default(world):
    world["configured"] = world["store_path"]
    restart(world, **dict.fromkeys(SWITCHES, "0"))
    base = surfaces()
    restart(world, **dict.fromkeys(SWITCHES, "1"))
    on = surfaces()
    assert _changed(base, on) == {
        "idx_tools",
        "instructions",
        "search_plain",
        "search_features",
        "recommend",
        "charts",
    }
    remaining = dict.fromkeys(SWITCHES, "1")
    for name in ["charts", "analysis", "explanations", "badges"]:
        remaining[name] = "0"
        restart(world, **remaining)
    assert surfaces() == base
    assert mcp._arm_chart_expiry() is False


# --- (d) install.sh and the server agree on IDX_CHART_DELIVERY and IDX_CHART_DIR ---


@POSIX
def test_install_rollback_restores_the_default_config_with_charts(tmp_path):
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


# The three cases the scratch branch marked as strict xfails, now required to hold:
# each side either agrees with `.env` or reports the contradiction (install refuses,
# the server keeps delivery off and names the problem).
CASES = [
    # (environment value, .env value, expected problem)
    ("", "1", delivery.DELIVERY_FILE_ONLY),
    ("0", "1", delivery.DELIVERY_FILE_ONLY),
    ("1", None, delivery.DELIVERY_ENV_ONLY),
]
CASE_IDS = ["env-empty-dotenv-1", "env-0-dotenv-1", "env-1-dotenv-absent"]


@pytest.mark.parametrize(("env", "dotenv_value", "problem"), CASES, ids=CASE_IDS)
def test_the_server_reports_a_contradicting_chart_switch(
    monkeypatch, env, dotenv_value, problem
):
    values = {analysis_tool.TOOL_SETTING: "1", IMAGE_ENV: IMAGE}
    if dotenv_value is not None:
        values[delivery.SWITCH] = dotenv_value
    _clear_switch_env(monkeypatch)
    monkeypatch.setenv(delivery.SWITCH, env)
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(values))
    try:
        assert mcp.register_analysis_tool() is True
        assert mcp.configure_chart_delivery() is False
        assert mcp.chart_delivery_problem() == problem
        health = mcp.health()
        assert problem in health["message"] and problem in health["warnings"]
        assert mcp._arm_chart_expiry() is False
    finally:
        mcp.reset_analysis_tool_for_tests()


@POSIX
@pytest.mark.parametrize(("env", "dotenv_value", "problem"), CASES, ids=CASE_IDS)
def test_install_refuses_the_same_contradiction(tmp_path, env, dotenv_value, problem):
    lines = [
        f"IDX_OWNER_E164={OWNER}",
        f"IDX_ANALYSIS_IMAGE={IMAGE}",
        f"{analysis_tool.TOOL_SETTING}=1",
    ]
    if dotenv_value is not None:
        lines.append(f"{delivery.SWITCH}={dotenv_value}")
    done = _install(tmp_path, lines, extra_env={delivery.SWITCH: env})
    assert done.returncode == 1
    assert problem in done.stdout + done.stderr
    assert not (tmp_path / "state" / "openclaw.json").exists()


def test_a_differing_chart_dir_is_reported_by_both(tmp_path, monkeypatch):
    chart = tmp_path / "workspace-idx" / delivery.DIR_NAME
    values = {
        analysis_tool.TOOL_SETTING: "1",
        IMAGE_ENV: IMAGE,
        delivery.SWITCH: "1",
        delivery.DIR_SETTING: str(chart),
    }
    _clear_switch_env(monkeypatch)
    monkeypatch.setenv(delivery.DIR_SETTING, "/srv/elsewhere/idx-charts")
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(values))
    try:
        mcp.register_analysis_tool()
        assert mcp.configure_chart_delivery() is False
        assert mcp.chart_delivery_problem() == delivery.DIR_DIFFERS
    finally:
        mcp.reset_analysis_tool_for_tests()
    if os.name == "posix":
        lines = [f"IDX_OWNER_E164={OWNER}", *(f"{k}={v}" for k, v in values.items())]
        done = _install(
            tmp_path / "inst",
            lines,
            extra_env={delivery.DIR_SETTING: "/srv/elsewhere/idx-charts"},
        )
        assert done.returncode == 1
        assert delivery.DIR_DIFFERS in done.stdout + done.stderr
