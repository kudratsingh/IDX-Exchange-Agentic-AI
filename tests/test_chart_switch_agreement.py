"""WO-030 review: install.sh and the tool server decide chart delivery the same way.

IDX_CHART_DELIVERY and IDX_CHART_DIR live in `.env` (WO-027's rule, `chart_state`): a
contradicting environment makes install.sh refuse and the server keep delivery off and
report it. install.sh runs as a copy in a temp HOME and state dir; ~/.openclaw is safe.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.test_openclaw_merge_config import IMAGE, OWNER, _install

from idx_agent.analysis import delivery
from idx_agent.analysis import tool as analysis_tool
from idx_agent.db import pool as db_pool
from idx_agent.mcp_server import server

SWITCH = delivery.SWITCH
DIR = delivery.DIR_SETTING
TOOL = analysis_tool.TOOL_SETTING
IMAGE_ENV = "IDX_ANALYSIS_IMAGE"
D = "/srv/x/idx-charts"
E = "/srv/y/idx-charts"
POSIX = pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
VALUES = [None, "1", "0", "", "true"]

# (switch in the environment, switch in .env, expected), with the analysis tool on in
# .env only and no IDX_CHART_DIR anywhere. None: the key is absent. "on" and "off"
# agree; "conflict": install refuses and the server keeps delivery off and reports it.
# Every pair of VALUES is listed once; the expectation is written out, not derived.
SWITCH_COMBINATIONS = [
    (None, None, "off"),
    (None, "1", "on"),
    (None, "0", "off"),
    (None, "", "off"),
    (None, "true", "off"),
    ("1", None, "conflict"),
    ("1", "1", "on"),
    ("1", "0", "conflict"),
    ("1", "", "conflict"),
    ("1", "true", "conflict"),
    ("0", None, "off"),
    ("0", "1", "conflict"),
    ("0", "0", "off"),
    ("0", "", "off"),
    ("0", "true", "off"),
    ("", None, "off"),
    ("", "1", "conflict"),
    ("", "0", "off"),
    ("", "", "off"),
    ("", "true", "off"),
    ("true", None, "off"),
    ("true", "1", "conflict"),
    ("true", "0", "off"),
    ("true", "", "off"),
    ("true", "true", "off"),
    (" 1", "1", "conflict"),
    ("1 ", None, "off"),
]
# (switch env, switch .env, dir env, dir .env, analysis on in .env, expected).
# "dir": the switch agrees and is on, but the environment's IDX_CHART_DIR differs from
# .env (install refuses, the server keeps delivery off and reports it). "inert": on in
# .env but the analysis tool is off, so nothing happens. "bad-dir": on with an
# unusable directory (every chart fails visibly; install says so).
DIR_COMBINATIONS = [
    (None, "1", None, None, True, "on"),
    (None, "1", None, D, True, "on"),
    (None, "1", D, D, True, "on"),
    ("1", "1", D, D, True, "on"),
    (None, "1", f" {D} ", D, True, "on"),
    (None, "1", "", None, True, "on"),
    (None, "1", E, D, True, "dir"),
    ("1", "1", E, D, True, "dir"),
    (None, "1", E, None, True, "dir"),
    (None, "1", D, None, True, "dir"),
    (None, "1", "", D, True, "dir"),
    (None, "1", None, "relative/idx-charts", True, "bad-dir"),
    (None, None, E, D, True, "off"),
    (None, "0", E, D, True, "off"),
    (None, "1", None, None, False, "inert"),
    (None, "1", E, D, False, "inert"),
    ("1", None, None, None, False, "conflict"),
    ("1", "1", None, None, False, "inert"),
]
COMBINATIONS = [
    (env, dotenv, None, None, True, want) for env, dotenv, want in SWITCH_COMBINATIONS
] + DIR_COMBINATIONS


def _ids(combo) -> str:
    env, dotenv, dir_env, dir_dotenv, analysis, _ = combo
    return (
        f"env={env!r}-dotenv={dotenv!r}-dir_env={dir_env!r}-dir_dotenv={dir_dotenv!r}"
        f"-analysis={'on' if analysis else 'off'}"
    )


def _keys(switch: str | None, directory: str | None) -> dict[str, str]:
    pairs = ((SWITCH, switch), (DIR, directory))
    return {key: value for key, value in pairs if value is not None}


def _dotenv(combo) -> dict[str, str]:
    _, dotenv, _, dir_dotenv, analysis, _ = combo
    analysis_keys = {TOOL: "1", IMAGE_ENV: IMAGE} if analysis else {}
    return {**analysis_keys, **_keys(dotenv, dir_dotenv)}


@pytest.fixture(autouse=True)
def _reset_after():
    delivery.reset_store_for_tests()
    yield
    server.reset_analysis_tool_for_tests()
    delivery.reset_store_for_tests()


def _runtime(monkeypatch, environ: dict[str, str], dotenv: dict[str, str]) -> bool:
    """Start as main() does, with exactly this environment for the four settings
    (the analysis switch and image included, so a value exported by the shell running
    pytest never leaks in) and this .env content. True if chart delivery is on."""
    for key in (TOOL, IMAGE_ENV, SWITCH, DIR):
        if key in environ:
            monkeypatch.setenv(key, environ[key])
        else:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(dotenv))
    server.register_analysis_tool()
    return server.configure_chart_delivery()


# --- the rule itself ---


@pytest.mark.parametrize("combo", COMBINATIONS, ids=_ids)
def test_chart_state_over_every_combination(combo, monkeypatch, tmp_path):
    env, _, dir_env, _, _, expected = combo
    monkeypatch.setenv("HOME", str(tmp_path))
    state = delivery.chart_state(_keys(env, dir_env), _dotenv(combo))
    assert state.on is (expected in ("on", "bad-dir"))
    problems = {
        "conflict": {delivery.DELIVERY_FILE_ONLY, delivery.DELIVERY_ENV_ONLY},
        "dir": {delivery.DIR_DIFFERS},
    }
    assert state.problem in problems.get(expected, {None})
    if state.problem:
        assert ".env" in state.problem and "\n" not in state.problem
        assert (SWITCH if expected == "conflict" else DIR) in state.problem
        assert state.directory is None
    if expected == "bad-dir":
        assert state.directory is None


def test_the_two_conflict_directions_name_what_is_out_of_step():
    analysis = {TOOL: "1"}
    file_only = delivery.chart_state({SWITCH: "0"}, {**analysis, SWITCH: "1"})
    env_only = delivery.chart_state({SWITCH: "1"}, analysis)
    assert file_only.problem == delivery.DELIVERY_FILE_ONLY
    assert env_only.problem == delivery.DELIVERY_ENV_ONLY
    assert "1 in .env but not in the process environment" in file_only.problem
    assert "1 in the process environment but not in .env" in env_only.problem


def test_the_rule_reuses_the_analysis_switch_helpers():
    """One test for every switch: WO-027's switch_state and this rule share it."""
    assert analysis_tool.switch_contradicted(SWITCH, {SWITCH: "1"}, {}) is True
    assert analysis_tool.switch_contradicted(SWITCH, {SWITCH: "0"}, {}) is False
    assert analysis_tool.value_differs(DIR, {DIR: f" {D}"}, {DIR: D}) is False
    assert analysis_tool.value_differs(DIR, {DIR: E}, {DIR: D}) is True
    assert analysis_tool.value_differs(DIR, {}, {DIR: D}) is False


def test_the_analysis_switch_problem_also_keeps_charts_off():
    """The environment contradicts the analysis switch: the tool is off, so are
    charts; the analysis problem is reported by WO-027's own path."""
    state = delivery.chart_state({TOOL: "0"}, {TOOL: "1", SWITCH: "1"})
    assert state == delivery.ChartState(False)


# --- install and runtime together, from the same .env and the same environment ---


@POSIX
@pytest.mark.parametrize("combo", COMBINATIONS, ids=_ids)
def test_install_and_runtime_agree_or_both_report(tmp_path, monkeypatch, combo):
    env, dotenv, dir_env, dir_dotenv, analysis, expected = combo
    environ = _keys(env, dir_env)
    lines = [f"IDX_OWNER_E164={OWNER}"]
    lines += [f"{key}={value}" for key, value in _dotenv(combo).items()]
    done = _install(tmp_path, lines, extra_env=environ)
    repo_env = db_pool.dotenv_values(tmp_path / "repo" / ".env")
    assert repo_env == _dotenv(combo)
    # The runtime expands `~` against the same HOME the install ran with.
    monkeypatch.setenv("HOME", str(tmp_path))
    on = _runtime(monkeypatch, environ, repo_env)
    state = tmp_path / "state"
    problem = server.chart_delivery_problem()

    if expected in ("conflict", "dir"):
        assert done.returncode == 1
        assert done.stderr.startswith("install.sh: ")
        assert problem is not None and problem in done.stderr
        assert (SWITCH if expected == "conflict" else DIR) in problem
        # Refused before anything was written.
        assert not state.exists() or list(state.iterdir()) == []
        assert on is False
        return
    assert done.returncode == 0, done.stderr
    assert problem is None
    assert on is (expected in ("on", "bad-dir"))
    if expected == "on":
        directory = server._chart_state.directory
        assert directory is not None
        assert f"charts are written to {directory}\n" in done.stdout
        want = Path(dir_dotenv or delivery.DEFAULT_DIR.replace("~", str(tmp_path)))
        assert directory == want
    elif expected == "bad-dir":
        assert "must be an absolute path ending in /idx-charts" in done.stdout
    elif expected == "inert":
        assert "has no effect while IDX_ANALYSIS_TOOL is not 1" in done.stdout
    else:
        assert "hart" not in done.stdout


# --- the gateway's environment differs from the shell install.sh ran in ---


@pytest.mark.parametrize(
    ("environ", "dotenv", "phrase"),
    [
        ({SWITCH: "0"}, {SWITCH: "1"}, "1 in .env but not in the process environment"),
        ({SWITCH: ""}, {SWITCH: "1"}, "1 in .env but not in the process environment"),
        ({SWITCH: "1"}, {}, "1 in the process environment but not in .env"),
        ({DIR: E}, {SWITCH: "1", DIR: D}, f"{DIR} in the process environment differs"),
    ],
)
def test_health_reports_a_chart_mismatch_found_at_start(
    monkeypatch, environ, dotenv, phrase
):
    """install.sh saw only .env; the server's own environment disagrees. Delivery
    stays off and `health` carries the problem in its message and warnings; the
    analysis tool itself is unaffected."""
    full = {TOOL: "1", IMAGE_ENV: IMAGE, **dotenv}
    assert _runtime(monkeypatch, environ, full) is False
    assert analysis_tool.TOOL_NAME in server.tool_names()
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.health_result(trace_id="a" * 32)
    assert len(result.warnings) == 1 and phrase in result.warnings[0]
    assert result.message.endswith(result.warnings[0])


def test_health_lists_both_problems_when_both_switches_disagree(monkeypatch):
    environ = {TOOL: "1", SWITCH: "1"}
    assert _runtime(monkeypatch, environ, {}) is False
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.health_result(trace_id="c" * 32)
    assert result.warnings == [
        analysis_tool.TOOL_WITHOUT_SKILL,
        delivery.DELIVERY_ENV_ONLY,
    ]
    assert result.message.endswith(" ".join(result.warnings))


def test_the_start_log_names_the_chart_problem(monkeypatch, capsys):
    _runtime(monkeypatch, {DIR: E}, {TOOL: "1", IMAGE_ENV: IMAGE, SWITCH: "1", DIR: D})
    server.log_start()
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert record["event"] == "server_start"
    assert record["chart_delivery_problem"] == delivery.DIR_DIFFERS
    assert "analysis_switch_problem" not in record
    assert "bounded_analysis" in record["tools"]


def test_charts_on_and_agreeing_add_nothing_to_health_or_the_start_log(
    monkeypatch, capsys
):
    full = {TOOL: "1", IMAGE_ENV: IMAGE, SWITCH: "1", DIR: D}
    assert _runtime(monkeypatch, {}, full) is True
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.health_result(trace_id="b" * 32)
    assert result.warnings == []
    assert result.message == server.health_line(result.data, "b" * 32)
    server.log_start()
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert set(record) == {"ts", "event", "trace_id", "server", "tools"}


def test_reset_clears_the_chart_state(monkeypatch):
    _runtime(monkeypatch, {SWITCH: "1"}, {TOOL: "1"})
    assert server.chart_delivery_problem() is not None
    server.reset_analysis_tool_for_tests()
    assert server.chart_delivery_problem() is None
    assert server._chart_state is None


def test_main_decides_charts_after_the_tool_and_before_pruning_and_the_log(
    monkeypatch,
):
    order = []
    monkeypatch.setattr(server, "register_analysis_tool", lambda: order.append("tool"))
    monkeypatch.setattr(
        server, "configure_chart_delivery", lambda: order.append("charts")
    )
    monkeypatch.setattr(server, "_prune_charts_at_start", lambda: order.append("prune"))
    monkeypatch.setattr(server, "log_start", lambda: order.append("log"))
    monkeypatch.setattr(server.consent, "allow_lazy_server_run", lambda: None)
    monkeypatch.setattr(server.server, "run", lambda transport: order.append("run"))
    server.main()
    assert order == ["tool", "charts", "prune", "log", "run"]
