"""WO-007 file fallback: with IDX_LOG_FILE set, every log line is also appended to a
local file that rotates by size and never loses or removes a line.

Runs in temp directories only (conftest hides the real .env). No database.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from idx_agent.mcp_server import server as mcp
from idx_agent.observability import logging as obs

SRC = str(pathlib.Path(obs.__file__).resolve().parents[2])
REPO = pathlib.Path(SRC).parent


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    """No log file or size from the outer environment; the cached settings and the
    once-flag start unset. Settings are read once, so a test sets them first."""
    for name in ("IDX_LOG_FILE", "IDX_LOG_FILE_MAX_BYTES", "IDX_OTLP_ENDPOINT"):
        monkeypatch.setenv(name, "")
    obs.reset_log_file_settings_for_tests()
    yield
    obs.reset_log_file_settings_for_tests()


def _lines(directory):
    """Every line of every file under `directory`, parsed, archives included."""
    out = []
    for path in sorted(directory.iterdir()):
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n"), path.name  # no partial last line
        out.extend(json.loads(x) for x in text.splitlines())
    return out


def test_unset_writes_no_file(tmp_path, capsys):
    obs.log_event("t", "id1", n=1)
    assert list(tmp_path.iterdir()) == []
    assert json.loads(capsys.readouterr().err)["n"] == 1


def test_each_line_is_appended_whole_and_stderr_is_unchanged(
    tmp_path, monkeypatch, capsys
):
    target = tmp_path / "logs" / "idx-agent.log"  # the directory is created
    monkeypatch.setenv("IDX_LOG_FILE", str(target))
    for n in range(3):
        obs.log_event("t", "id1", n=n)
    err = capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == err
    assert [x["n"] for x in _lines(target.parent)] == [0, 1, 2]


def test_a_relative_path_resolves_against_the_working_directory(monkeypatch):
    monkeypatch.setenv("IDX_LOG_FILE", "logs/idx-agent.log")
    obs.log_event("t", "id1")
    assert (pathlib.Path.cwd() / "logs" / "idx-agent.log").is_file()


def test_the_tool_call_line_lands_in_the_file_redacted(tmp_path, monkeypatch, capsys):
    target = tmp_path / "idx-agent.log"
    monkeypatch.setenv("IDX_LOG_FILE", str(target))
    payload = mcp.health()
    # Built at runtime so this file never holds a literal address.
    obs.log_event("t", "id2", note="mail " + "agent" + "@" + "brokerage.com")
    (call, note) = _lines(tmp_path)
    assert call["event"] == "tool_call" and call["tool"] == "health"
    assert call["trace_id"] == payload["provenance"]["trace_id"]
    assert note["note"] == "mail [email]"
    assert target.read_text(encoding="utf-8") == capsys.readouterr().err


def test_rotation_keeps_every_archive_and_every_line(tmp_path, monkeypatch):
    target = tmp_path / "idx-agent.log"
    monkeypatch.setenv("IDX_LOG_FILE", str(target))
    monkeypatch.setenv("IDX_LOG_FILE_MAX_BYTES", "400")
    seen_archives: set[str] = set()
    for n in range(40):
        obs.log_event("t", "id1", n=n)
        archives = {p.name for p in tmp_path.glob("idx-agent.*.log")}
        assert seen_archives <= archives  # no archive ever disappears
        seen_archives = archives
    assert len(seen_archives) >= 3 and target.is_file()
    assert sorted(x["n"] for x in _lines(tmp_path)) == list(range(40))
    # Each archive stopped at the first write that reached the limit.
    for name in seen_archives:
        size = (tmp_path / name).stat().st_size
        assert 400 <= size < 400 + 200


def test_an_archive_name_is_never_reused(tmp_path):
    """Timestamp plus pid (two processes never collide), then a counter."""
    live = tmp_path / "idx-agent.log"
    now = datetime(2026, 7, 2, 12, 0, 0, 123456, tzinfo=UTC)
    base = f"idx-agent.20260702T120000123456Z-{os.getpid()}"
    first = obs.archive_path(live, now)
    assert first.name == f"{base}.log"
    first.write_text("kept\n", encoding="utf-8")
    second = obs.archive_path(live, now)
    assert second.name == f"{base}-2.log"
    assert first.read_text(encoding="utf-8") == "kept\n"


def test_the_settings_are_read_once_per_process(tmp_path, monkeypatch):
    """Not on every line: a later change needs a restart (or the reset helper)."""
    reads = []

    def counting(name, environ=None):
        reads.append(name)
        return os.environ.get(name)

    first, second = tmp_path / "first.log", tmp_path / "second.log"
    monkeypatch.setattr(obs, "env_setting", counting)
    monkeypatch.setenv("IDX_LOG_FILE", str(first))
    for n in range(3):
        obs.log_event("t", "id1", n=n)
    monkeypatch.setenv("IDX_LOG_FILE", str(second))
    obs.log_event("t", "id1", n=3)
    assert sorted(reads) == ["IDX_LOG_FILE", "IDX_LOG_FILE_MAX_BYTES"]
    assert [x["n"] for x in _lines(tmp_path)] == [0, 1, 2, 3]
    obs.reset_log_file_settings_for_tests()
    obs.log_event("t", "id1", n=4)
    assert json.loads(second.read_text(encoding="utf-8"))["n"] == 4


@pytest.mark.parametrize("raw", ["", "lots", "0", "-5"])
def test_a_bad_size_falls_back_to_ten_megabytes(monkeypatch, raw):
    monkeypatch.setenv("IDX_LOG_FILE_MAX_BYTES", raw)
    assert obs._max_bytes() == obs.DEFAULT_LOG_FILE_MAX_BYTES == 10 * 1024 * 1024


def test_a_write_failure_is_reported_once_and_logging_goes_on(
    tmp_path, monkeypatch, capsys
):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv("IDX_LOG_FILE", str(blocker / "idx-agent.log"))
    obs.log_event("t", "id1", n=1)
    obs.log_event("t", "id1", n=2)
    lines = [json.loads(x) for x in capsys.readouterr().err.strip().splitlines()]
    assert [x["event"] for x in lines] == ["t", "log_file_error", "t"]
    assert lines[1]["error"] in {"NotADirectoryError", "FileExistsError"}


# One writer process: `count` lines tagged with its name, as fast as it can.
_WRITER = """
import sys
from idx_agent.observability.logging import log_event
name, count = sys.argv[1], int(sys.argv[2])
for n in range(count):
    log_event("t", "id1", writer=name, n=n, pad="x" * 200)
"""


def test_two_writer_processes_on_one_path_lose_and_split_nothing(tmp_path):
    """Two processes append and rotate the same file at once: every line is
    whole, and each writer's lines are all there, across the live file and archives."""
    logs = tmp_path / "logs"
    env = {
        **os.environ,
        "PYTHONPATH": SRC,
        "IDX_LOG_FILE": str(logs / "idx-agent.log"),
        "IDX_LOG_FILE_MAX_BYTES": "20000",
        "IDX_OTLP_ENDPOINT": "",
    }
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _WRITER, name, "400"],
            env=env,
            cwd=tmp_path,
            stderr=subprocess.DEVNULL,
        )
        for name in ("a", "b")
    ]
    assert [p.wait(60) for p in procs] == [0, 0]
    lines = _lines(logs)
    assert len(list(logs.iterdir())) > 2  # rotation happened
    for name in ("a", "b"):
        assert sorted(x["n"] for x in lines if x["writer"] == name) == list(range(400))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_default_file_and_its_archives_are_gitignored():
    names = ["logs/idx-agent.log", "logs/idx-agent.20260702T120000123456Z-4242.log"]
    done = subprocess.run(
        ["git", "check-ignore", "--no-index", *names],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if done.returncode == 128:
        pytest.skip("not a git checkout")
    assert done.stdout.split() == names
