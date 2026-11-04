"""WO-027 review: install.sh and the tool server read IDX_ANALYSIS_TOOL the same way.

The switch lives in `.env`; an environment that contradicts it, or (switch on) holds an
IDX_ANALYSIS_IMAGE that differs from `.env`, makes install.sh refuse and the server stay
off and report it (owner decision 2026-11-03: an image conflict fails closed). Installs
run a copy of install.sh against a temp HOME and state dir with stub commands; the real
~/.openclaw is never touched.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest
from tests.test_openclaw_merge_config import IMAGE, OWNER, SKILLS, _install, load

from idx_agent.analysis import tool as analysis_tool
from idx_agent.db import pool as db_pool
from idx_agent.mcp_server import server

SWITCH = analysis_tool.TOOL_SETTING
IMAGE_ENV = "IDX_ANALYSIS_IMAGE"
OTHER_IMAGE = "sha256:" + "c" * 64
POSIX = pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")

# One case: (switch in the process environment, switch in .env, image in the process
# environment, image in .env, expected). None means the key is absent; both the switch
# and IDX_ANALYSIS_IMAGE are set or removed explicitly on both sides for every case, so
# an image exported by the shell running pytest (CI does) never leaks into a case.
# "on"/"off" agree; "conflict": the switch is contradicted, install refuses and the
# server stays off and reports it; "image": the switch is on but the environment's image
# differs from .env, install refuses and the server stays off and reports it, exactly as
# for "conflict" but with IMAGE_DIFFERS (owner decision 2026-11-03: fail closed).
SWITCH_COMBINATIONS = [
    (None, None, "off"),
    ("1", None, "conflict"),
    (None, "1", "on"),
    ("0", "1", "conflict"),
    ("1", "0", "conflict"),
    ("1", "1", "on"),
    ("", "1", "conflict"),
    ("", None, "off"),
    ("0", None, "off"),
    ("true", None, "off"),
    (None, "true", "off"),
    (" 1", "1", "conflict"),
    ("yes", "0", "off"),
]
IMAGE_COMBINATIONS = [
    (None, "1", None, None, "on"),
    (None, "1", None, IMAGE, "on"),
    (None, "1", IMAGE, None, "image"),
    ("1", "1", IMAGE, None, "image"),
    (None, "1", IMAGE, IMAGE, "on"),
    (None, "1", f" {IMAGE} ", IMAGE, "on"),
    (None, "1", OTHER_IMAGE, IMAGE, "image"),
    ("1", "1", OTHER_IMAGE, IMAGE, "image"),
    (None, "1", "", IMAGE, "image"),
    (None, None, IMAGE, None, "off"),
    (None, None, OTHER_IMAGE, IMAGE, "off"),
    ("1", None, OTHER_IMAGE, IMAGE, "conflict"),
    ("0", "1", OTHER_IMAGE, IMAGE, "conflict"),
]
COMBINATIONS = [
    (env, dotenv, None, IMAGE, want) for env, dotenv, want in SWITCH_COMBINATIONS
] + IMAGE_COMBINATIONS


def _ids(combo) -> str:
    env, dotenv, image_env, image_dotenv, _ = combo
    names = {None: None, IMAGE: "A", OTHER_IMAGE: "C", f" {IMAGE} ": " A ", "": ""}
    return (
        f"env={env!r}-dotenv={dotenv!r}"
        f"-image_env={names[image_env]!r}-image_dotenv={names[image_dotenv]!r}"
    )


def _keys(switch: str | None, image: str | None) -> dict[str, str]:
    """The switch and the image as one side holds them; None leaves a key out."""
    pairs = ((SWITCH, switch), (IMAGE_ENV, image))
    return {key: value for key, value in pairs if value is not None}


@pytest.fixture(autouse=True)
def _reset_after():
    yield
    server.reset_analysis_tool_for_tests()


def _runtime(
    monkeypatch, env: str | None, dotenv: dict[str, str], image_env: str | None = None
) -> bool:
    """Start-time registration with this environment and this .env content. Both the
    switch and IDX_ANALYSIS_IMAGE are set or removed in the process environment."""
    for key, value in ((SWITCH, env), (IMAGE_ENV, image_env)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(db_pool, "dotenv_values", lambda path=None: dict(dotenv))
    return server.register_analysis_tool()


# --- the rule itself ---


@pytest.mark.parametrize("combo", COMBINATIONS, ids=_ids)
def test_switch_state_over_every_combination(combo):
    env, dotenv, image_env, image_dotenv, expected = combo
    state = analysis_tool.switch_state(
        _keys(env, image_env), _keys(dotenv, image_dotenv)
    )
    assert state.on is (expected == "on")
    problems = {
        "conflict": {
            analysis_tool.SKILL_WITHOUT_TOOL,
            analysis_tool.TOOL_WITHOUT_SKILL,
        },
        "image": {analysis_tool.IMAGE_DIFFERS},
    }
    assert state.problem in problems.get(expected, {None})
    if state.problem:
        assert ".env" in state.problem and "\n" not in state.problem
        assert (SWITCH if expected == "conflict" else IMAGE_ENV) in state.problem


def test_the_two_conflict_directions_name_what_is_out_of_step():
    skill_only = analysis_tool.switch_state({SWITCH: "0"}, {SWITCH: "1"}).problem
    tool_only = analysis_tool.switch_state({SWITCH: "1"}, {}).problem
    assert skill_only and "skill is installed" in skill_only
    assert tool_only and "added no bounded-analysis skill" in tool_only
    assert skill_only != tool_only


# Every form of an image conflict with the switch on: (image in the process environment,
# image in .env). None means the key is absent.
IMAGE_CONFLICTS = [
    pytest.param(IMAGE, None, id="env_set-dotenv_unset"),
    pytest.param("", IMAGE, id="env_empty-dotenv_set"),
    pytest.param(OTHER_IMAGE, IMAGE, id="two_digests"),
]


@pytest.mark.parametrize(("image_env", "image_dotenv"), IMAGE_CONFLICTS)
def test_an_image_that_differs_from_dotenv_turns_the_switch_off(
    image_env, image_dotenv
):
    """Owner decision 2026-11-03: fail closed, the same as a switch conflict."""
    for env in (None, "1"):
        state = analysis_tool.switch_state(
            _keys(env, image_env), _keys("1", image_dotenv)
        )
        assert state == analysis_tool.SwitchState(False, analysis_tool.IMAGE_DIFFERS)
        assert IMAGE_ENV in state.problem and SWITCH not in state.problem
        assert "not registered" in state.problem
        assert state.problem not in (
            analysis_tool.SKILL_WITHOUT_TOOL,
            analysis_tool.TOOL_WITHOUT_SKILL,
        )


def test_an_agreeing_image_or_a_switch_off_is_no_image_conflict():
    same = analysis_tool.switch_state(
        {SWITCH: "1", IMAGE_ENV: f" {IMAGE}"}, {SWITCH: "1", IMAGE_ENV: IMAGE}
    )
    assert same == analysis_tool.SwitchState(on=True, problem=None)
    off = analysis_tool.switch_state({IMAGE_ENV: OTHER_IMAGE}, {IMAGE_ENV: IMAGE})
    assert off == analysis_tool.SwitchState(on=False, problem=None)


# --- install and runtime together, from the same .env and the same environment ---


@POSIX
@pytest.mark.parametrize("combo", COMBINATIONS, ids=_ids)
def test_install_and_runtime_agree_or_both_report(tmp_path, monkeypatch, combo):
    env, dotenv, image_env, image_dotenv, expected = combo
    lines = [f"IDX_OWNER_E164={OWNER}"]
    lines += [f"{key}={value}" for key, value in _keys(dotenv, image_dotenv).items()]
    done = _install(tmp_path, lines, extra_env=_keys(env, image_env))
    state = tmp_path / "state"
    repo_env = db_pool.dotenv_values(tmp_path / "repo" / ".env")
    held = {key: repo_env[key] for key in (SWITCH, IMAGE_ENV) if key in repo_env}
    assert held == _keys(dotenv, image_dotenv)
    registered = _runtime(monkeypatch, env, repo_env, image_env)

    if expected in ("conflict", "image"):
        assert done.returncode == 1
        assert done.stderr.startswith("install.sh: ")
        assert (SWITCH if expected == "conflict" else IMAGE_ENV) in done.stderr
        problem = server.analysis_switch_problem()
        assert problem is not None and problem in done.stderr
        assert not (state / "openclaw.json").exists()
        assert not (state / "openclaw.analysis.json5").exists()
        assert registered is False
        assert analysis_tool.TOOL_NAME not in server.tool_names()
        assert server.server.instructions == server.BASE_INSTRUCTIONS
        return
    assert done.returncode == 0, done.stderr
    skills = load().load_json5(state / "openclaw.json")["agents"]["entries"]["idx"]
    skill_on = "bounded-analysis" in skills["skills"]
    assert skill_on is registered is (expected == "on")
    assert server.analysis_switch_problem() is None
    tools_on = analysis_tool.TOOL_NAME in server.tool_names()
    assert tools_on is skill_on
    expect = server.ANALYSIS_INSTRUCTIONS if skill_on else server.BASE_INSTRUCTIONS
    assert server.server.instructions == expect
    unpinned = "IDX_ANALYSIS_IMAGE in .env is unset or not pinned" in done.stdout
    assert unpinned is (skill_on and image_dotenv is None)


@POSIX
def test_install_refuses_an_image_that_differs_from_dotenv(tmp_path):
    lines = [f"IDX_OWNER_E164={OWNER}", f"{SWITCH}=1", f"IDX_ANALYSIS_IMAGE={IMAGE}"]
    done = _install(tmp_path, lines, extra_env={IMAGE_ENV: OTHER_IMAGE})
    assert done.returncode == 1 and IMAGE_ENV in done.stderr
    assert not (tmp_path / "state" / "openclaw.json").exists()


# --- the gateway's environment differs from the shell install.sh ran in ---


@pytest.mark.parametrize(
    ("env", "dotenv", "phrase"),
    [
        ("0", {SWITCH: "1"}, "skill is installed and the tool is not registered"),
        ("", {SWITCH: "1"}, "skill is installed and the tool is not registered"),
        ("1", {}, "added no bounded-analysis skill"),
    ],
)
def test_health_reports_a_mismatch_found_at_start(monkeypatch, env, dotenv, phrase):
    """install.sh saw only .env; the server's own environment disagrees. The server
    stays off and `health` carries the problem in its message and warnings."""
    assert _runtime(monkeypatch, env, dotenv) is False
    assert analysis_tool.TOOL_NAME not in server.tool_names()
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.health_result(trace_id="a" * 32)
    assert len(result.warnings) == 1 and phrase in result.warnings[0]
    assert result.message.endswith(result.warnings[0])


@pytest.mark.parametrize(("image_env", "image_dotenv"), IMAGE_CONFLICTS)
def test_an_image_conflict_found_at_start_unregisters_and_is_reported(
    monkeypatch, capsys, image_env, image_dotenv
):
    """The gateway's IDX_ANALYSIS_IMAGE differs from .env with the switch on: the
    server registers nothing (7 tools), keeps the base instructions, and reports the
    problem in health and the start log, the same channel as a switch conflict."""
    dotenv = _keys("1", image_dotenv)
    assert _runtime(monkeypatch, None, dotenv, image_env) is False
    names = server.tool_names()
    assert analysis_tool.TOOL_NAME not in names and len(names) == 7
    assert server.server.instructions == server.BASE_INSTRUCTIONS
    assert server.analysis_switch_problem() == analysis_tool.IMAGE_DIFFERS
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.health_result(trace_id="c" * 32)
    assert result.warnings == [analysis_tool.IMAGE_DIFFERS]
    assert result.message == (
        f"{server.health_line(result.data, 'c' * 32)} {analysis_tool.IMAGE_DIFFERS}"
    )
    server.log_start()
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert record["event"] == "server_start"
    assert record["analysis_switch_problem"] == analysis_tool.IMAGE_DIFFERS
    assert analysis_tool.TOOL_NAME not in record["tools"]


def test_the_start_log_names_the_problem(monkeypatch, capsys):
    _runtime(monkeypatch, "1", {})
    server.log_start()
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert record["event"] == "server_start"
    assert "added no bounded-analysis skill" in record["analysis_switch_problem"]
    assert "bounded_analysis" not in record["tools"]


def test_default_off_health_and_start_log_are_unchanged(monkeypatch, capsys):
    """No switch anywhere: no warning, no extra log field, the default tool list."""
    assert _runtime(monkeypatch, None, {}) is False
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.health_result(trace_id="b" * 32)
    assert result.warnings == []
    assert result.message == server.health_line(result.data, "b" * 32)
    server.log_start()
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert set(record) == {"ts", "event", "trace_id", "server", "tools"}


def test_reset_clears_a_recorded_problem(monkeypatch):
    _runtime(monkeypatch, "1", {})
    assert server.analysis_switch_problem() is not None
    server.reset_analysis_tool_for_tests()
    assert server.analysis_switch_problem() is None


# --- activation and rollback leave nothing behind ---


@POSIX
def test_on_then_off_restores_the_default_install_and_removes_the_render(
    tmp_path, monkeypatch
):
    base = [f"IDX_OWNER_E164={OWNER}", f"IDX_ANALYSIS_IMAGE={IMAGE}"]
    off_first = _install(tmp_path / "a", base)
    assert off_first.returncode == 0, off_first.stderr
    default = (tmp_path / "a" / "state" / "openclaw.json").read_text()

    on = _install(tmp_path / "b", [*base, f"{SWITCH}=1"])
    assert on.returncode == 0, on.stderr
    state = tmp_path / "b" / "state"
    assert (state / "openclaw.analysis.json5").exists()
    assert _runtime(monkeypatch, None, {SWITCH: "1"}) is True

    off = _install(tmp_path / "b", base, name="repo")
    assert off.returncode == 0, off.stderr
    assert not (state / "openclaw.analysis.json5").exists()
    assert "removed" in off.stdout and "openclaw.analysis.json5" in off.stdout
    merged = json.loads((state / "openclaw.json").read_text())
    assert merged["agents"]["entries"]["idx"]["skills"] == SKILLS
    relocated = tmp_path / "default.json5"
    relocated.write_text(_relocated(default, tmp_path / "a", tmp_path / "b"))
    assert merged == load().load_json5(relocated)
    assert sorted(p.name for p in state.iterdir()) == sorted(
        p.name for p in (tmp_path / "a" / "state").iterdir()
    ) + ["openclaw.json.pre-idx.bak"]

    server.reset_analysis_tool_for_tests()
    assert _runtime(monkeypatch, None, {}) is False
    assert analysis_tool.TOOL_NAME not in server.tool_names()
    assert server.server.instructions == server.BASE_INSTRUCTIONS
    assert server.analysis_switch_problem() is None


def _relocated(text: str, old: pathlib.Path, new: pathlib.Path) -> str:
    """The default install's config text with its temp root swapped for another's."""
    return text.replace(str(old), str(new))
