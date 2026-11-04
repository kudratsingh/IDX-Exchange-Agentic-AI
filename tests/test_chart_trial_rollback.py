"""WO-030, D5 trial: the rollback runs at once and proves analysis and charts off.

The script runs as a copy in a throwaway repo (temp HOME and state dir, stub openclaw,
node and launchctl first on PATH); nothing real is restarted, booted out or loaded.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from tests.test_openclaw_merge_config import IMAGE, OWNER, ROOT, _fake_repo

pytestmark = pytest.mark.skipif(os.name != "posix", reason="bash scripts")

LABEL = "local.idx-exchange.chart-prune"
CHART = "chart-" + "1" * 32 + ".png"
TEMP = ".chart-" + "2" * 32 + ".tmp"
ON = [
    f"IDX_OWNER_E164={OWNER}",
    "IDX_ANALYSIS_TOOL=1",
    f"IDX_ANALYSIS_IMAGE={IMAGE}",
    "IDX_CHART_DELIVERY=1",
]

# The stubs answer from the files the steps change, so the verification sees the
# effect of the rollback, not a canned answer: OpenClaw lists bounded_analysis while
# install.sh's analysis fragment exists, and launchd knows the job while it is loaded.
OPENCLAW = """#!/bin/sh
echo "openclaw $*" >> "$HOME/calls"
case "$1 $2" in
  "gateway restart") [ -e "$HOME/restart-fails" ] && exit 1; echo restarted ;;
  "mcp doctor")
    echo "idx: 7 tools"
    [ -e "$OPENCLAW_STATE_DIR/openclaw.analysis.json5" ] && echo idx__bounded_analysis
    ;;
  "skills list")
    echo email
    [ -e "$OPENCLAW_STATE_DIR/openclaw.analysis.json5" ] && echo bounded-analysis
    ;;
  --version*) echo "openclaw 0.0.0-test" ;;
esac
exit 0
"""
LAUNCHCTL = """#!/bin/sh
echo "launchctl $*" >> "$HOME/calls"
case "$1" in
  print)
    [ -e "$HOME/loaded" ] && { echo "path = $HOME/Library/LaunchAgents/x"; exit 0; }
    echo "Could not find service \\"local.idx-exchange.chart-prune\\" in domain" >&2
    exit 113
    ;;
  bootout) [ -e "$HOME/loaded" ] || exit 3; rm "$HOME/loaded"; exit 0 ;;
esac
echo "unexpected launchctl call" >&2
exit 99
"""

DONE_RECORD = [
    "chart trial rollback record (WO-030, D5)",
    "  trial result: {result}",
    "  rollback started: <T>  finished: <T>",
    "  step .env: IDX_ANALYSIS_TOOL 1 line(s) set to 0,"
    " IDX_CHART_DELIVERY {chart_lines} line(s) set to 0",
    "  step install.sh: ok",
    "  step gateway restart: ok",
    "  step prune --all: removed {removed} chart file(s)",
    "  step launchd prune job: {job}",
    "  verify .env: IDX_ANALYSIS_TOOL off, IDX_CHART_DELIVERY off",
    "  verify server: bounded_analysis absent (not listed), chart_state off,"
    " problems None / None",
    "  verify health: 0 warning(s), no analysis/chart line",
    "  verify chart files: 0",
    "  verify mcp doctor: bounded_analysis listed 0 time(s)",
    "  verify skills: bounded-analysis listed 0 time(s)",
    "  verify analysis fragment: absent",
    "  verify launchctl: Could not find service",
    "ROLLBACK DONE: analysis off, chart delivery off",
]


def _trial_state(tmp_path: Path, env_lines: list[str], job: bool) -> Path:
    """The Mac as the trial leaves it: switches on in `.env`, the analysis fragment
    rendered, one chart and one temp file in the default directory (with the lock
    file), and the launchd job loaded with its plist, or never installed."""
    repo = _fake_repo(tmp_path, env_lines)
    shutil.copy2(
        ROOT / "scripts" / "chart_trial_rollback.sh",
        repo / "scripts" / "chart_trial_rollback.sh",
    )
    (repo / ".env").chmod(0o600)
    for name, text in (("openclaw", OPENCLAW), ("launchctl", LAUNCHCTL)):
        stub = tmp_path / "bin" / name
        stub.write_text(text)
        stub.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    (state / "openclaw.analysis.json5").write_text("{}\n")
    charts = tmp_path / ".openclaw" / "workspace-idx" / "idx-charts"
    charts.mkdir(parents=True)
    for name in (CHART, TEMP, ".idx-charts.lock"):
        (charts / name).write_bytes(b"")
    if job:
        agents = tmp_path / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / f"{LABEL}.plist").write_text("<plist/>\n")
        (tmp_path / "loaded").write_text("")
    return repo


def _rollback(
    tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "IDX_PYTHON": sys.executable,
        "OPENCLAW_STATE_DIR": str(tmp_path / "state"),
        "PYTHONPATH": str(ROOT / "src"),
        "MYSQL_HOST": "",
        **(extra_env or {}),
    }
    return subprocess.run(
        ["bash", str(tmp_path / "repo" / "scripts" / "chart_trial_rollback.sh"), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _record(stdout: str) -> list[str]:
    """The record block, with its two times replaced by <T> (checked for shape)."""
    block = stdout[stdout.index("chart trial rollback record") :].splitlines()
    stamp = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
    assert re.fullmatch(rf"  rollback started: {stamp}  finished: {stamp}", block[2])
    block[2] = "  rollback started: <T>  finished: <T>"
    return block


def _calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls").read_text().splitlines()


def test_rollback_after_the_trial_turns_everything_off_and_says_so(tmp_path):
    """Job installed: every step runs, the job is booted out and its plist removed,
    and every verification line reads off. Exit 0, the pinned record."""
    repo = _trial_state(tmp_path, ON, job=True)
    done = _rollback(tmp_path, "pass")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _record(done.stdout) == [
        line.format(
            result="pass", chart_lines=1, removed=2, job="booted out, plist removed"
        )
        for line in DONE_RECORD
    ]
    assert (repo / ".env").read_text().splitlines() == [
        f"IDX_OWNER_E164={OWNER}",
        "IDX_ANALYSIS_TOOL=0",
        f"IDX_ANALYSIS_IMAGE={IMAGE}",
        "IDX_CHART_DELIVERY=0",
    ]
    assert stat.S_IMODE((repo / ".env").stat().st_mode) == 0o600
    assert not (tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()
    charts = tmp_path / ".openclaw" / "workspace-idx" / "idx-charts"
    assert sorted(p.name for p in charts.iterdir()) == [".idx-charts.lock"]
    launchd = [c for c in _calls(tmp_path) if c.startswith("launchctl")]
    service = f"gui/{os.getuid()}/{LABEL}"
    assert launchd == [
        f"launchctl print {service}",
        f"launchctl bootout {service}",
        f"launchctl print {service}",
    ]
    openclaw = [c for c in _calls(tmp_path) if c.startswith("openclaw")]
    assert openclaw.index("openclaw gateway restart") < openclaw.index(
        "openclaw mcp doctor idx --probe"
    )


def test_a_never_installed_job_is_reported_not_installed_and_is_no_error(tmp_path):
    """No plist and not loaded: no bootout, no rm, "not installed", still exit 0."""
    _trial_state(tmp_path, ON, job=False)
    done = _rollback(tmp_path, "fail")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _record(done.stdout) == [
        line.format(result="fail", chart_lines=1, removed=2, job="not installed")
        for line in DONE_RECORD
    ]
    assert "launchctl bootout" not in "\n".join(_calls(tmp_path))


def test_every_switch_line_is_edited_in_place_not_appended(tmp_path):
    """The first line for a key wins (`dotenv_values`), so each one is set to 0 where
    it stands, an `export` line included; no line is added and the rest are kept."""
    lines = [
        "# comment kept",
        f"IDX_OWNER_E164={OWNER}",
        "export IDX_CHART_DELIVERY=1",
        "IDX_ANALYSIS_TOOL = 1",
        f"IDX_ANALYSIS_IMAGE={IMAGE}",
        'IDX_CHART_DELIVERY="1"',
    ]
    repo = _trial_state(tmp_path, lines, job=True)
    done = _rollback(tmp_path, "aborted")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (repo / ".env").read_text().splitlines() == [
        "# comment kept",
        f"IDX_OWNER_E164={OWNER}",
        "IDX_CHART_DELIVERY=0",
        "IDX_ANALYSIS_TOOL=0",
        f"IDX_ANALYSIS_IMAGE={IMAGE}",
        "IDX_CHART_DELIVERY=0",
    ]
    assert _record(done.stdout)[1:4] == [
        "  trial result: aborted",
        "  rollback started: <T>  finished: <T>",
        "  step .env: IDX_ANALYSIS_TOOL 1 line(s) set to 0,"
        " IDX_CHART_DELIVERY 2 line(s) set to 0",
    ]


def test_a_failed_step_does_not_stop_the_rest_and_the_record_says_incomplete(tmp_path):
    """The gateway restart fails: every later step still runs (the job is removed,
    the charts pruned), the record names the failure, and the exit status is 1."""
    _trial_state(tmp_path, ON, job=True)
    (tmp_path / "restart-fails").write_text("")
    done = _rollback(tmp_path, "fail")
    assert done.returncode == 1
    record = _record(done.stdout)
    assert "  step gateway restart: FAILED" in record
    assert "  step launchd prune job: booted out, plist removed" in record
    assert "  verify launchctl: Could not find service" in record
    assert record[-1] == "ROLLBACK INCOMPLETE: gateway restart"


def test_a_switch_still_exported_in_the_shell_is_not_reported_as_off(tmp_path):
    """IDX_ANALYSIS_TOOL=1 exported: install.sh refuses and the server rule reports
    the contradiction, so the rollback cannot claim analysis is off."""
    _trial_state(tmp_path, ON, job=False)
    done = _rollback(tmp_path, "pass", extra_env={"IDX_ANALYSIS_TOOL": "1"})
    assert done.returncode == 1
    record = _record(done.stdout)
    assert record[4].startswith("  step install.sh: FAILED (install.sh: ")
    assert any(
        line.startswith("  verify server: bounded_analysis absent")
        and "problems None / None" not in line
        for line in record
    )
    # install.sh wrote nothing, so the analysis fragment and OpenClaw's lists stay.
    assert record[-1] == (
        "ROLLBACK INCOMPLETE: install.sh, server probe, mcp doctor, skills,"
        " analysis fragment"
    )


@pytest.mark.parametrize("args", [(), ("maybe",), ("pass", "extra")])
def test_a_bad_argument_changes_nothing(tmp_path, args):
    """The result word is required; without it nothing is edited, run or called."""
    repo = _trial_state(tmp_path, ON, job=True)
    before = (repo / ".env").read_text()
    done = _rollback(tmp_path, *args)
    if args == ("pass", "extra"):
        # Extra words are ignored: the first one is the result.
        assert done.returncode == 0, done.stdout + done.stderr
        return
    assert done.returncode == 2
    assert "usage: scripts/chart_trial_rollback.sh pass|fail|aborted" in done.stderr
    assert (repo / ".env").read_text() == before
    assert not (tmp_path / "calls").exists()


def test_the_rollback_never_loads_or_installs_anything():
    """It only removes: no bootstrap, load, copy of the template or plist render."""
    text = (ROOT / "scripts" / "chart_trial_rollback.sh").read_text()
    commands = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    for word in ("bootstrap", "launchctl load", "enable", "plist.proposal", "plutil"):
        assert all(word not in line for line in commands), word
