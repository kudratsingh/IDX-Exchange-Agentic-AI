"""WO-030: chart delivery to the chat, offline.

Writer, PNG checks, size cap, retention (our files only), one file and line per request,
isolation, failure text, default off, rollback, and install.sh's report (temp HOME).
The sink is a temp directory; live WhatsApp delivery is not and cannot be tested here.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import stat
import threading
from pathlib import Path

import pytest
from mcp import Client
from mcp.types import ImageContent, TextContent
from tests.test_analysis_executor import fake_docker  # noqa: F401 - fixture
from tests.test_analysis_integration import (  # noqa: F401 - fixtures
    BOUNDED,
    CODE,
    MEAN,
    SCATTER,
    mount_source,
    reader,
    session_call,
    switch_on,
    worker,
    worker_json,
)
from tests.test_analysis_service import PNG, _png
from tests.test_openclaw_merge_config import IMAGE, OWNER, SKILLS, _install, load

from idx_agent.analysis import delivery, executor
from idx_agent.analysis import tool as analysis_tool
from idx_agent.channels.format import CHART_IMAGE_FALLBACK, format_chart_line
from idx_agent.db import pool as db_pool
from idx_agent.mcp_server import server

MEDIA = re.compile(r"^MEDIA:(/\S+/idx-charts/chart-[0-9a-f]{32}\.png)$")


def settings(**values: str):
    return lambda name: values.get(name)


@pytest.fixture
def chart_dir(tmp_path) -> Path:
    """A stand-in agent workspace (exists) and its idx-charts path (not yet)."""
    workspace = tmp_path / "workspace-idx"
    workspace.mkdir()
    return workspace / delivery.DIR_NAME


@pytest.fixture
def worker_on(request):
    """WO-027's fixtures by name: the switch, the sample reader and the fake docker
    worker (looked up here so this module never shadows the imported names)."""
    request.getfixturevalue("reader")
    return request.getfixturevalue("worker")


def charts_in_dotenv(monkeypatch, **values: str) -> bool:
    """Exactly these chart settings in `.env` (both removed from the process
    environment, where they never belong), then decide as the server does at start
    (a restart). True if chart delivery is on."""
    chart_keys = (delivery.SWITCH, delivery.DIR_SETTING)
    for key in chart_keys:
        monkeypatch.delenv(key, raising=False)
    before = db_pool.dotenv_values

    def dotenv(path=None):
        kept = {k: v for k, v in before(path).items() if k not in chart_keys}
        return {**kept, **values}

    monkeypatch.setattr(db_pool, "dotenv_values", dotenv)
    delivery.reset_store_for_tests()
    return server.configure_chart_delivery()


@pytest.fixture
def delivery_on(monkeypatch, chart_dir, request):
    request.getfixturevalue("switch_on")
    assert charts_in_dotenv(
        monkeypatch, IDX_CHART_DELIVERY="1", IDX_CHART_DIR=str(chart_dir)
    )
    yield chart_dir
    delivery.reset_store_for_tests()


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _ours(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.startswith("chart-"))


def _age(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime), follow_symlinks=False)


# --- the switch and the directory setting ---


@pytest.mark.parametrize("value", [None, "", "0", "true", " 1", "1 ", "yes"])
def test_delivery_is_off_unless_exactly_1(value):
    on = {analysis_tool.TOOL_SETTING: "1"}
    if value is not None:
        on[delivery.SWITCH] = value
    assert delivery.enabled(settings(**on)) is False


def test_delivery_needs_the_analysis_switch_too():
    assert delivery.enabled(settings(IDX_CHART_DELIVERY="1")) is False
    both = settings(IDX_CHART_DELIVERY="1", IDX_ANALYSIS_TOOL="1")
    assert delivery.enabled(both) is True


def test_both_settings_are_on_the_pool_allowlist():
    assert db_pool.allowed_setting(delivery.SWITCH)
    assert db_pool.allowed_setting(delivery.DIR_SETTING)
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    assert "\nIDX_CHART_DELIVERY=\n" in env_example
    assert "\nIDX_CHART_DIR=\n" in env_example


def test_the_default_directory_is_inside_the_idx_workspace():
    path = delivery.chart_dir(settings())
    assert path == Path.home() / ".openclaw" / "workspace-idx" / "idx-charts"


@pytest.mark.parametrize(
    "raw",
    [
        "relative/idx-charts",
        "/tmp/charts",
        "/tmp/idx-charts/sub",
        "/tmp/../etc/idx-charts",
        "/tmp/my dir/idx-charts",
        '/tmp/"x"/idx-charts',
        "/tmp/a\nb/idx-charts",
    ],
)
def test_an_unusable_directory_setting_gives_no_directory(raw):
    assert delivery.chart_dir(settings(IDX_CHART_DIR=raw)) is None


# --- the writer: dedicated directory, validation, size cap ---


def test_a_checked_png_is_written_once_under_a_random_name(chart_dir):
    store = delivery.ChartStore(chart_dir)
    written = store.write(PNG)
    assert written.path.parent == chart_dir
    assert re.fullmatch(r"chart-[0-9a-f]{32}\.png", written.path.name)
    assert written.path.read_bytes() == PNG
    assert stat.S_IMODE(written.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(chart_dir.stat().st_mode) == 0o700
    assert MEDIA.match(written.media_line)
    assert written.media_line == "MEDIA:" + str(written.path)
    # No temp file is left behind.
    assert [p.name for p in chart_dir.iterdir()] == [written.path.name]


def test_every_write_gets_a_new_token(chart_dir):
    store = delivery.ChartStore(chart_dir)
    first, second = store.write(PNG), store.write(PNG)
    assert first.token != second.token and first.path != second.path


def test_a_token_is_never_reused(chart_dir):
    store = delivery.ChartStore(chart_dir, token=lambda: "a" * 32)
    store.write(PNG)
    with pytest.raises(delivery.DeliveryError) as err:
        store.write(PNG)
    assert err.value.reason == "name_taken"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (None, "no_image"),
        (b"", "no_image"),
        ("not bytes", "no_image"),
        (b"GIF89a" + PNG[6:], "invalid_png"),  # wrong magic bytes
        (PNG[:-20], "invalid_png"),  # truncated, header still says PNG
        (_png(2100, 600), "invalid_png"),  # wider than the cap
        (_png(960, 1600), "invalid_png"),  # taller than the cap
        (_png(100, 600), "invalid_png"),  # narrower than the floor
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * (delivery.MAX_BYTES + 1), "too_large"),
    ],
)
def test_anything_but_a_checked_png_within_the_cap_is_refused(chart_dir, data, reason):
    store = delivery.ChartStore(chart_dir)
    with pytest.raises(delivery.DeliveryError) as err:
        store.write(data)
    assert err.value.reason == reason
    assert not chart_dir.exists()  # refused before the directory is touched


def test_a_lower_size_cap_is_honoured_and_a_higher_one_is_not(chart_dir):
    small = delivery.ChartStore(chart_dir, max_bytes=len(PNG) - 1)
    with pytest.raises(delivery.DeliveryError) as err:
        small.write(PNG)
    assert err.value.reason == "too_large"
    big = delivery.ChartStore(chart_dir, max_bytes=delivery.MAX_BYTES * 10)
    assert big.max_bytes == delivery.MAX_BYTES


def test_a_missing_workspace_is_never_created(tmp_path):
    directory = tmp_path / "no-workspace" / delivery.DIR_NAME
    with pytest.raises(delivery.DeliveryError) as err:
        delivery.ChartStore(directory).write(PNG)
    assert err.value.reason == "workspace_missing"
    assert not directory.parent.exists()


def test_a_symlinked_chart_directory_is_refused(tmp_path, chart_dir):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    chart_dir.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(delivery.DeliveryError) as err:
        delivery.ChartStore(chart_dir).write(PNG)
    assert err.value.reason == "dir_unsafe"
    assert list(elsewhere.iterdir()) == []


def test_a_loose_directory_mode_is_tightened(chart_dir):
    chart_dir.mkdir(mode=0o755)
    os.chmod(chart_dir, 0o755)
    delivery.ChartStore(chart_dir).write(PNG)
    assert stat.S_IMODE(chart_dir.stat().st_mode) == 0o700


def test_the_store_only_accepts_a_dedicated_directory(tmp_path):
    with pytest.raises(ValueError):
        delivery.ChartStore(tmp_path / "charts")
    with pytest.raises(ValueError):
        delivery.ChartStore(Path("idx-charts"))


# --- retention: our own files only ---


def test_pruning_removes_only_our_expired_files(tmp_path, chart_dir):
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    old, fresh = store.write(PNG), store.write(PNG)
    _age(old.path, clock.now - delivery.TTL_SECONDS - 1)
    # Things that are not ours, or not plain files, are never touched.
    (chart_dir / "notes.txt").write_text("keep")
    (chart_dir / "chart-NOTHEX.png").write_bytes(PNG)
    target = tmp_path / "target.png"
    target.write_bytes(PNG)
    link = chart_dir / ("chart-" + "c" * 32 + ".png")
    link.symlink_to(target)
    _age(link, clock.now - 10 * delivery.TTL_SECONDS)
    sub = chart_dir / ("chart-" + "d" * 32 + ".png")
    sub.mkdir()
    removed = store.prune()
    assert removed == 1
    assert not old.path.exists() and fresh.path.exists()
    assert (chart_dir / "notes.txt").exists() and (
        chart_dir / "chart-NOTHEX.png"
    ).exists()
    assert link.is_symlink() and target.read_bytes() == PNG and sub.is_dir()


def test_pruning_keeps_at_most_max_files_oldest_out_once_past_the_grace(chart_dir):
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock, max_files=3, grace=10)
    files = []
    for n in range(5):
        clock.now += 10
        written = store.write(PNG, owner=f"session-{n}")
        _age(written.path, clock.now)
        files.append(written)
    assert len(_ours(chart_dir)) == 3
    assert [f.path.exists() for f in files] == [False, False, True, True, True]


def test_a_full_directory_of_young_charts_refuses_the_new_one_and_removes_nothing(
    chart_dir,
):
    """Every server process (one per chat session) shares the directory. Making room
    never removes a chart younger than the grace period, whose reply may still be
    pending in another session: the new chart fails visibly instead."""
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock, max_files=3)
    others = [store.write(PNG, owner=f"session-{n}") for n in range(3)]
    for written in others:
        _age(written.path, clock.now)
    clock.now += delivery.SUPERSEDE_GRACE_SECONDS - 1
    with pytest.raises(delivery.DeliveryError) as err:
        store.write(PNG, owner="late")
    assert err.value.reason == "dir_full"
    assert all(written.path.exists() for written in others)
    clock.now += 1  # the oldest is past the grace period now
    store.write(PNG, owner="late")
    assert len(_ours(chart_dir)) == 3


def test_a_leftover_temp_file_is_pruned_once_stale(chart_dir):
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    store.write(PNG)
    temp = chart_dir / (".chart-" + "e" * 32 + ".tmp")
    temp.write_bytes(b"partial")
    _age(temp, clock.now - delivery.STALE_TEMP_SECONDS - 1)
    store.prune()
    assert not temp.exists()


def test_another_processes_write_in_progress_is_never_pruned(chart_dir):
    """Two server processes (two chat sessions) on one directory: B's write, and a
    third process's start-up prune, leave A's temp file (a write in progress) and A's
    fresh chart alone, so A's rename cannot fail because of them."""
    clock = Clock()
    a = delivery.ChartStore(chart_dir, clock=clock)
    b = delivery.ChartStore(chart_dir, clock=clock)
    mine = a.write(PNG, owner="a")
    _age(mine.path, clock.now)
    clock.now += delivery.SUPERSEDE_GRACE_SECONDS + 1
    temp = chart_dir / (".chart-" + "f" * 32 + ".tmp")
    temp.write_bytes(b"in progress")
    _age(temp, clock.now - 1)
    b.write(PNG, owner="b")
    delivery.ChartStore(chart_dir, clock=clock).prune()
    assert temp.exists() and mine.path.exists()


def test_prune_everything_removes_all_of_ours_and_nothing_else(chart_dir):
    store = delivery.ChartStore(chart_dir)
    store.write(PNG)
    store.write(PNG)
    (chart_dir / "notes.txt").write_text("keep")
    assert store.prune(everything=True) == 2
    assert [p.name for p in chart_dir.iterdir()] == ["notes.txt"]


def test_pruning_a_missing_directory_is_a_no_op(chart_dir):
    assert delivery.ChartStore(chart_dir).prune(everything=True) == 0
    assert not chart_dir.exists()


# --- concurrent sweeps: every server process prunes the same directory ---


class RacingScandir:
    """`os.scandir` as another server process wins the race: each entry is removed
    after the listing names it and before this process stats it. Deterministic, no
    second process or timing involved."""

    def __init__(self, real):
        self._real = real

    def __call__(self, path):
        self._it = self._real(path)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._it.close()

    def __iter__(self):
        for entry in self._it:
            Path(entry.path).unlink(missing_ok=True)
            yield entry


def _expired_chart(directory: Path, now: float) -> Path:
    directory.mkdir(mode=0o700, exist_ok=True)
    old = directory / ("chart-" + "a" * 32 + ".png")
    old.write_bytes(PNG)
    _age(old, now - delivery.TTL_SECONDS - 1)
    return old


def _unlistable(path):
    raise PermissionError(13, "Permission denied", str(path))


def test_a_file_another_process_removed_mid_sweep_is_skipped(chart_dir, monkeypatch):
    """Review finding (WO-030): the stat after the listing raised FileNotFoundError
    when another process unlinked the entry first. Now it is skipped: prune and
    write both carry on, and the new chart is written."""
    clock = Clock()
    _expired_chart(chart_dir, clock.now)
    store = delivery.ChartStore(chart_dir, clock=clock)
    monkeypatch.setattr(delivery.os, "scandir", RacingScandir(os.scandir))
    assert store.prune() == 0  # the other process removed it, not this one
    _expired_chart(chart_dir, clock.now)
    written = store.write(PNG, owner="a")
    assert written.path.read_bytes() == PNG


def test_an_unlistable_directory_fails_the_write_not_the_caller(chart_dir, monkeypatch):
    store = delivery.ChartStore(chart_dir)
    monkeypatch.setattr(delivery.os, "scandir", _unlistable)
    with pytest.raises(delivery.DeliveryError) as err:
        store.write(PNG)
    assert err.value.reason == "dir_unavailable"
    monkeypatch.undo()  # `delivery.os` is the os module; list with the real scandir
    assert _ours(chart_dir) == []


def test_a_chart_removed_right_after_its_rename_fails_visibly(chart_dir, monkeypatch):
    """The operator's `prune --all` (or any other process) removes the new file
    between the rename and the size check: a DeliveryError, never an OSError."""
    real = os.rename

    def rename_then_lose(src, dst):
        real(src, dst)
        os.unlink(dst)

    monkeypatch.setattr(delivery.os, "rename", rename_then_lose)
    with pytest.raises(delivery.DeliveryError) as err:
        delivery.ChartStore(chart_dir).write(PNG)
    assert err.value.reason == "write_failed"
    assert list(chart_dir.iterdir()) == []


def test_a_directory_that_vanishes_after_mkdir_fails_visibly(chart_dir, monkeypatch):
    real = os.lstat

    def lstat(path, *args, **kwargs):
        if Path(path) == chart_dir:
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(delivery.os, "lstat", lstat)
    with pytest.raises(delivery.DeliveryError) as err:
        delivery.ChartStore(chart_dir).write(PNG)
    assert err.value.reason == "dir_unavailable"


def test_a_name_that_only_looks_like_ours_is_never_pruned(chart_dir):
    """`$` also matches before a trailing newline; the names are matched whole."""
    chart_dir.mkdir(mode=0o700)
    foreign = [
        chart_dir / ("chart-" + "b" * 32 + ".png\n"),
        chart_dir / (".chart-" + "c" * 32 + ".tmp\n"),
    ]
    for path in foreign:
        path.write_bytes(b"not ours")
        _age(path, 0)
    assert delivery.ChartStore(chart_dir).prune(everything=True) == 0
    assert all(path.exists() for path in foreign)


def test_a_concurrent_sweep_never_costs_the_figures(
    worker_on, delivery_on, monkeypatch
):
    """Over MCP, as the review reproduced it: before the fix the result was
    `Error executing tool bounded_analysis`. Now the chart is delivered and the
    figures and caveats are whole."""
    _expired_chart(delivery_on, Clock().now - 10_000)
    monkeypatch.setattr(delivery.os, "scandir", RacingScandir(os.scandir))
    worker_on["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    assert f"${MEAN:,.2f}, verified (n=50)" in payload["message"]
    assert "Caveats: " + BOUNDED in payload["message"]
    assert payload["data"]["chart"]["delivery"]["status"] == "ready"
    match = MEDIA.match(payload["message"].split("\n")[-1])
    assert match and Path(match.group(1)).read_bytes() == PNG


def test_an_unlistable_directory_costs_the_chart_not_the_figures(
    worker_on, delivery_on, monkeypatch
):
    monkeypatch.setattr(delivery.os, "scandir", _unlistable)
    worker_on["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    assert delivery.CHART_NOT_DELIVERED_LINE in payload["message"]
    assert f"${MEAN:,.2f}, verified (n=50)" in payload["message"]
    assert "MEDIA:" not in payload["message"]
    assert payload["data"]["chart"]["delivery"] == {
        "status": "failed",
        "reason": "dir_unavailable",
    }


@pytest.mark.parametrize("scandir", ["racing", "unlistable"])
def test_the_start_up_prune_never_stops_the_server(
    delivery_on, monkeypatch, capsys, scandir
):
    """`main()` prunes before `server.run`; neither race nor an unlistable
    directory may end the process (the session would have no idx tools)."""
    _expired_chart(delivery_on, Clock().now - 10_000)
    racing = RacingScandir(os.scandir)
    monkeypatch.setattr(
        delivery.os, "scandir", racing if scandir == "racing" else _unlistable
    )
    capsys.readouterr()
    ok = server._prune_charts_at_start()
    err = capsys.readouterr().err
    if scandir == "racing":
        assert ok is True and "chart_prune" not in err
    else:
        assert ok is False
        line = json.loads(err.strip().splitlines()[-1])
        assert line["event"] == "chart_prune"
        assert (line["status"], line["reason"]) == ("failed", "dir_unavailable")
        assert str(delivery_on) not in err


def test_the_prune_command_reports_an_unlistable_directory(
    monkeypatch, capsys, chart_dir
):
    charts_in_dotenv(monkeypatch, IDX_CHART_DIR=str(chart_dir))
    chart_dir.mkdir(mode=0o700)
    monkeypatch.setattr(delivery.os, "scandir", _unlistable)
    assert delivery.main(["prune", "--all"]) == 1
    assert "could not be listed; nothing pruned" in capsys.readouterr().out


# --- expiry: at the deadline while the server lives, at a clean exit, after a kill ---
# Review finding (WO-030 round 3): cleanup ran only at start, before another write or
# through prune, so during inactivity a chart stayed readable past its 300 s.


def test_a_chart_is_removed_at_its_deadline_with_no_further_request(chart_dir):
    """The deadline check alone removes it: no write, no prune, no start."""
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    written = store.write(PNG, owner="a")
    clock.now += delivery.TTL_SECONDS - 1
    assert store.expire_due() == 0 and written.path.exists()
    clock.now += 1  # exactly the deadline
    assert store.expire_due() == 1
    assert not written.path.exists() and store.pending() == []


def test_the_deadline_check_waits_at_most_the_check_interval(chart_dir):
    """Waits run on the monotonic clock (stopped while the Mac sleeps); deadlines are
    wall-clock, so the thread looks again at least every EXPIRY_CHECK_SECONDS."""
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    assert store.next_check() is None  # nothing pending: sleep until a write
    store.write(PNG)
    assert store.next_check() == delivery.EXPIRY_CHECK_SECONDS
    clock.now += delivery.TTL_SECONDS - 0.5
    assert store.next_check() == 0.5
    clock.now += 3_600  # the wall clock moved on (a wake from sleep)
    assert store.next_check() == 0
    assert store.expire_due() == 1 and store.next_check() is None


def test_the_deadline_also_sweeps_a_crashed_processes_expired_charts(chart_dir):
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    store.write(PNG)
    orphan = _expired_chart(chart_dir, clock.now)  # another, killed process's chart
    clock.now += delivery.TTL_SECONDS
    assert store.expire_due() == 1
    assert _ours(chart_dir) == [] and not orphan.exists()


def test_the_expiry_thread_removes_a_chart_at_its_deadline(chart_dir, monkeypatch):
    """A real background thread, a short ttl and no further call: the file goes."""
    removed = threading.Event()
    real = delivery._unlink

    def unlink(path):
        done = real(path)
        if done and path.name.startswith("chart-"):
            removed.set()
        return done

    monkeypatch.setattr(delivery, "_unlink", unlink)
    store = delivery.ChartStore(chart_dir, ttl=0.2, expire_in_background=True)
    try:
        written = store.write(PNG)
        assert written.path.exists()
        assert removed.wait(timeout=10), "the expiry thread never removed the chart"
        assert not written.path.exists() and store.pending() == []
    finally:
        store.stop()


def test_over_mcp_an_idle_chart_is_gone_at_its_deadline(
    worker_on, delivery_on, monkeypatch
):
    """The review's reproduction: one request, then nothing (no request, no restart,
    no prune). Before the fix the file stayed readable past its deadline, so a later
    reply repeating the MEDIA line would resend it. The ttl is shortened to 0.3 s."""
    removed = threading.Event()
    real = delivery._unlink

    def unlink(path):
        done = real(path)
        if done and path.name.startswith("chart-"):
            removed.set()
        return done

    monkeypatch.setattr(delivery, "_unlink", unlink)
    delivery.store_for(delivery_on).ttl = 0.3
    worker_on["set"](worker_json(chart=SCATTER))
    payload, _ = session_call(city="Pasadena", code=CODE)
    path = Path(MEDIA.match(payload["message"].split("\n")[-1]).group(1))
    assert path.read_bytes() == PNG
    assert removed.wait(timeout=5), "the chart is still readable after its deadline"
    assert not path.exists()


def test_the_server_store_expires_in_background_and_stops_cleanly(chart_dir):
    store = delivery.store_for(chart_dir)
    try:
        store.write(PNG)
        thread = store._expirer
        assert thread is not None and thread.daemon and thread.is_alive()
    finally:
        delivery.reset_store_for_tests()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(_ours(chart_dir)) == 1  # stopping is not removing; close removes


def test_close_removes_only_this_stores_charts(chart_dir):
    clock = Clock()
    mine = delivery.ChartStore(chart_dir, clock=clock)
    other = delivery.ChartStore(chart_dir, clock=clock)
    kept = other.write(PNG)
    mine.write(PNG)
    mine.write(PNG)
    assert mine.close() == 2
    assert _ours(chart_dir) == [kept.path.name]


_EXIT_PROBE = """
import sys
from pathlib import Path
from idx_agent.analysis import delivery
store = delivery.store_for(Path(sys.argv[1]))
delivery.arm_exit_cleanup(store)
print(store.write(Path(sys.argv[2]).read_bytes(), owner="s").path, flush=True)
sys.stdin.read()  # serve until the transport closes, as server.run does
"""


def _probe_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("IDX_", "MYSQL_"))}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["HOME"] = str(tmp_path / "home")
    return env


@pytest.mark.parametrize("ending", ["stdin_closed", "sigterm", "sigint", "sigkill"])
def test_how_the_process_ends_decides_what_happens_to_its_charts(
    tmp_path, chart_dir, ending
):
    """A real child process with the server's store and exit hooks. OpenClaw closes
    stdin, then SIGTERM after 2 s, then SIGKILL after 2 s more (owned-stdio). A
    clean end removes the chart at once; SIGKILL cannot be handled and leaves it."""
    import signal
    import subprocess
    import sys

    png = tmp_path / "chart.png"
    png.write_bytes(PNG)
    child = subprocess.Popen(
        [sys.executable, "-c", _EXIT_PROBE, str(chart_dir), str(png)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_probe_env(tmp_path),
        text=True,
    )
    path = Path(child.stdout.readline().strip())
    assert path.parent == chart_dir and path.read_bytes() == PNG
    if ending == "stdin_closed":
        child.stdin.close()
    else:
        sig = {"sigterm": signal.SIGTERM, "sigint": signal.SIGINT}
        child.send_signal(sig.get(ending, signal.SIGKILL))
    code = child.wait(timeout=30)
    err = child.stderr.read()
    for stream in (child.stdin, child.stdout, child.stderr):
        stream.close()
    expected = {
        "stdin_closed": 0,
        "sigterm": -signal.SIGTERM,  # still ends as SIGTERM would
        "sigint": -signal.SIGINT,  # an uncaught KeyboardInterrupt, after atexit
        "sigkill": -signal.SIGKILL,
    }[ending]
    assert code == expected, err
    if ending == "sigkill":
        assert path.exists()  # the residual: until the next sweep
    else:
        assert not path.exists()


def test_after_a_kill_the_next_start_sweep_removes_the_expired_chart(
    delivery_on, tmp_path
):
    """The killed process's chart, once past its ttl, is gone after the next server
    start (any session's); a younger one is kept for its own pending reply."""
    import subprocess
    import sys

    png = tmp_path / "chart.png"
    png.write_bytes(PNG)
    child = subprocess.Popen(
        [sys.executable, "-c", _EXIT_PROBE, str(delivery_on), str(png)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=_probe_env(tmp_path),
        text=True,
    )
    path = Path(child.stdout.readline().strip())
    child.kill()
    child.wait(timeout=30)
    child.stdin.close()
    child.stdout.close()
    young = delivery.ChartStore(delivery_on).write(PNG)
    assert server._prune_charts_at_start() is True
    assert path.exists() and young.path.exists()  # neither has expired yet
    _age(path, Clock().now - delivery.TTL_SECONDS - 1)
    delivery.reset_store_for_tests()
    assert server._prune_charts_at_start() is True
    assert not path.exists() and young.path.exists()


def test_the_server_arms_expiry_only_when_delivery_is_on(delivery_on, monkeypatch):
    import signal

    hooks: list = []
    monkeypatch.setattr(delivery.atexit, "register", hooks.append)
    before = signal.getsignal(signal.SIGTERM)
    try:
        assert server._arm_chart_expiry() is True
        assert hooks and hooks[0].__self__ is delivery.store_for(delivery_on)
        assert signal.getsignal(signal.SIGTERM) is not before
    finally:
        signal.signal(signal.SIGTERM, before)
    hooks.clear()
    assert not charts_in_dotenv(monkeypatch, IDX_CHART_DIR=str(delivery_on))
    assert server._arm_chart_expiry() is False
    assert hooks == [] and signal.getsignal(signal.SIGTERM) is before


@pytest.mark.parametrize("ending", ["stdin_closed", "sigterm"])
def test_the_real_server_with_delivery_on_ends_cleanly(tmp_path, chart_dir, ending):
    """`python -m idx_agent.mcp_server.server` with delivery on in its `.env`: closing
    stdin (OpenClaw's first step) ends it with status 0, so the exit hook runs; SIGTERM
    (the second step, 2 s later) runs the handler and still ends it as SIGTERM."""
    import signal
    import subprocess
    import sys
    import time

    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / ".env").write_text(
        f"IDX_ANALYSIS_TOOL=1\nIDX_ANALYSIS_IMAGE={IMAGE}\n"
        f"IDX_CHART_DELIVERY=1\nIDX_CHART_DIR={chart_dir}\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-m", "idx_agent.mcp_server.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=_probe_env(tmp_path),
        text=True,
    )
    started = json.loads(child.stderr.readline())
    assert started["event"] == "server_start"
    assert "chart_delivery_problem" not in started
    assert "bounded_analysis" in started["tools"]
    began = time.monotonic()
    if ending == "stdin_closed":
        child.stdin.close()
    else:
        child.send_signal(signal.SIGTERM)
    code = child.wait(timeout=30)
    took = time.monotonic() - began
    for stream in (child.stdin, child.stdout, child.stderr):
        stream.close()
    assert code == (0 if ending == "stdin_closed" else -signal.SIGTERM)
    assert took < 10, took  # on the Mac well under OpenClaw's 2 s grace


def test_the_launchd_prune_proposal_runs_only_the_expired_prune_and_is_not_installed():
    """The strict-expiry proposal (owner decision): once a minute, `prune` without
    `--all`, from the repo (so `.env` names the directory), with no environment of
    its own (so it cannot contradict `.env`). Nothing installs or names it."""
    import plistlib

    repo = Path(__file__).resolve().parents[1]
    text = (repo / "config" / "chart-prune.launchd.plist.proposal").read_text()
    job = plistlib.loads(text.replace("__REPO__", "/r").encode())
    assert job["ProgramArguments"] == [
        "/r/.venv/bin/python",
        "-m",
        "idx_agent.analysis.delivery",
        "prune",
    ]
    assert job["WorkingDirectory"] == "/r" and job["StartInterval"] == 60
    assert "EnvironmentVariables" not in job and "KeepAlive" not in job
    assert job["Label"] == "local.idx-exchange.chart-prune"
    for path in [repo / "scripts" / "install.sh", *(repo / "src").rglob("*.py")]:
        assert "chart-prune" not in path.read_text(), path


def test_main_arms_expiry_after_the_start_sweep(monkeypatch):
    calls: list[str] = []
    for name in (
        "register_analysis_tool",
        "configure_chart_delivery",
        "_prune_charts_at_start",
        "_arm_chart_expiry",
        "log_start",
    ):
        monkeypatch.setattr(server, name, lambda n=name: calls.append(n))
    monkeypatch.setattr(server.consent, "allow_lazy_server_run", lambda: False)
    monkeypatch.setattr(server.server, "run", lambda transport: calls.append("run"))
    server.main()
    assert calls == [
        "register_analysis_tool",
        "configure_chart_delivery",
        "_prune_charts_at_start",
        "_arm_chart_expiry",
        "log_start",
        "run",
    ]


# --- at most once: a newer chart retires this process's older ones ---


def test_a_newer_chart_retires_older_ones_after_the_grace_period(chart_dir):
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    first = store.write(PNG)
    clock.now += delivery.SUPERSEDE_GRACE_SECONDS - 1
    second = store.write(PNG)
    # Still inside the grace period: its reply may be pending.
    assert first.path.exists()
    clock.now += 2
    third = store.write(PNG)
    assert not first.path.exists() and second.path.exists() and third.path.exists()
    clock.now += delivery.SUPERSEDE_GRACE_SECONDS
    store.write(PNG)
    assert not second.path.exists() and not third.path.exists()


def test_a_newer_chart_never_retires_another_sessions_chart(chart_dir):
    """Supersede is per session: B's newer chart leaves A's alone, however old;
    only A's own next chart retires it."""
    clock = Clock()
    store = delivery.ChartStore(chart_dir, clock=clock)
    first_a = store.write(PNG, owner="a")
    clock.now += delivery.SUPERSEDE_GRACE_SECONDS + 1
    b = store.write(PNG, owner="b")
    assert first_a.path.exists()
    second_a = store.write(PNG, owner="a")
    assert not first_a.path.exists()
    assert b.path.exists() and second_a.path.exists()


def test_each_mcp_session_gets_its_own_owner_key():
    class Session:
        pass

    one, two = Session(), Session()
    assert delivery.owner_for(one) == delivery.owner_for(one)
    assert delivery.owner_for(one) != delivery.owner_for(two)
    assert re.fullmatch(r"[0-9a-f]{16}", delivery.owner_for(one))
    assert delivery.owner_for(None) == ""


# --- the MEDIA reference: workspace-relative in the default directory ---


def test_the_default_directory_gives_a_workspace_relative_media_line(
    tmp_path, monkeypatch
):
    """OpenClaw resolves a relative MEDIA path against the agent workspace, through
    the same read check as an absolute one (docs/CHART_DELIVERY.md E15), and the
    relative form never shows the user name if the line stays text."""
    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = Path(delivery.WORKSPACE).expanduser()
    workspace.mkdir(parents=True)
    store = delivery.ChartStore(Path(delivery.DEFAULT_DIR).expanduser())
    written = store.write(PNG)
    assert written.path.parent == workspace / delivery.DIR_NAME
    line = written.media_line
    assert re.fullmatch(r"MEDIA:idx-charts/chart-[0-9a-f]{32}\.png", line)
    assert str(tmp_path) not in line
    assert (workspace / line.removeprefix("MEDIA:")).read_bytes() == PNG


def test_any_other_directory_keeps_the_absolute_media_line(chart_dir):
    written = delivery.ChartStore(chart_dir).write(PNG)
    assert written.media_line == "MEDIA:" + str(written.path)


def test_the_workspace_matches_the_idx_agent_config():
    """The relative form is right only while the idx agent's workspace is WORKSPACE."""
    config = (
        Path(__file__).resolve().parents[1] / "config/openclaw.idx.json5"
    ).read_text()
    workspaces = set(re.findall(r'workspace: "([^"]+)"', config))
    assert workspaces == {delivery.WORKSPACE}


# --- the result: caption, MEDIA line, failure text ---


def _payload(status: str = "rendered", ok: bool = True) -> dict:
    caption = format_chart_line("Sale price by living area", 48, 50)
    chart = {
        "status": status,
        "image_attached": True,
        "title": "Sale price by living area",
        "n_used": 48,
        "n_rows": 50,
    }
    message = "\n".join(
        ["Pasadena: 50 sales.", "mean_price: $1, verified (n=50)", caption]
        + ["Caveats: " + BOUNDED]
    )
    return {
        "ok": ok,
        "message": message,
        "data": {"n": 50, "chart": chart},
        "provenance": {"trace_id": "t-1"},
    }


def test_the_wo027_caption_still_has_the_phrase_delivery_rewrites():
    assert delivery._RETURNED in format_chart_line("T", 1, 2)


def test_a_delivered_chart_ends_the_message_with_one_media_line(chart_dir):
    store = delivery.ChartStore(chart_dir)
    out, reason = delivery.deliver(_payload(), PNG, store)
    assert reason is None
    lines = out["message"].split("\n")
    assert MEDIA.match(lines[-1])
    assert sum(line.startswith("MEDIA:") for line in lines) == 1
    assert "follows as an image in this chat." in out["message"]
    assert CHART_IMAGE_FALLBACK in out["message"]
    assert "returned as an image" not in out["message"]
    assert "Caveats: " + BOUNDED in out["message"]
    chart = out["data"]["chart"]
    assert chart["image_attached"] is False
    assert chart["delivery"] == {
        "status": "ready",
        "media_line": lines[-1],
        "expires_in_s": delivery.TTL_SECONDS,
    }
    assert Path(lines[-1].removeprefix("MEDIA:")).read_bytes() == PNG


def test_the_message_without_the_media_line_is_the_whole_answer(chart_dir):
    """If the model drops the line, or the chat shows no image, nothing is missing."""
    out, _ = delivery.deliver(_payload(), PNG, delivery.ChartStore(chart_dir))
    text = "\n".join(out["message"].split("\n")[:-1])
    assert "verified (n=50)" in text and "Caveats: " + BOUNDED in text
    assert CHART_IMAGE_FALLBACK in text


@pytest.mark.parametrize(
    ("store", "png", "reason"),
    [
        (None, PNG, "dir_invalid"),
        ("store", b"junk", "invalid_png"),
        ("store", None, "no_image"),
    ],
)
def test_a_failed_chart_says_so_and_the_text_stays_whole(chart_dir, store, png, reason):
    real = delivery.ChartStore(chart_dir) if store == "store" else None
    out, why = delivery.deliver(_payload(), png, real)
    assert why == reason
    assert delivery.CHART_NOT_DELIVERED_LINE in out["message"]
    assert (
        "MEDIA:" not in out["message"] and "returned as an image" not in out["message"]
    )
    assert "verified (n=50)" in out["message"] and BOUNDED in out["message"]
    assert out["data"]["chart"]["delivery"] == {"status": "failed", "reason": reason}
    assert out["data"]["chart"]["image_attached"] is False
    assert not chart_dir.exists() or _ours(chart_dir) == []


@pytest.mark.parametrize(
    "payload",
    [_payload(ok=False), _payload(status="refused"), _payload(status="not_requested")],
)
def test_results_without_a_drawn_chart_are_untouched(chart_dir, payload):
    out, reason = delivery.deliver(payload, PNG, delivery.ChartStore(chart_dir))
    assert out == payload and reason is None
    assert not chart_dir.exists()


def test_content_is_text_only_and_a_failure_is_logged_without_a_path(chart_dir):
    events = []

    def log(event, trace, **fields):
        events.append((event, trace, fields))

    blocks = delivery.content_blocks(
        _payload(), PNG, delivery.ChartStore(chart_dir), log
    )
    assert [type(b) for b in blocks] == [TextContent]
    assert events == [("chart_delivery", "t-1", {"status": "ready", "reason": None})]
    events.clear()
    delivery.content_blocks(_payload(), b"junk", delivery.ChartStore(chart_dir), log)
    assert events == [
        ("chart_delivery", "t-1", {"status": "failed", "reason": "invalid_png"})
    ]
    assert str(chart_dir) not in json.dumps(events)


# --- over a real MCP session ---


def test_with_delivery_unset_the_tool_returns_what_wo027_returns(
    worker_on, chart_dir, monkeypatch
):
    """Default off: the image block goes to the model, the caption is WO-027's, and
    nothing is written even with a chart directory configured."""
    monkeypatch.setenv(delivery.DIR_SETTING, str(chart_dir))
    worker_on["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert [type(b) for b in images] == [ImageContent]
    assert "returned as an image with this result" in payload["message"]
    assert "MEDIA:" not in payload["message"]
    assert "delivery" not in payload["data"]["chart"]
    assert not chart_dir.exists()


def test_with_delivery_on_the_chart_is_a_file_and_the_model_gets_no_image(
    worker_on, delivery_on
):
    worker_on["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    message = payload["message"]
    assert f"${MEAN:,.2f}, verified (n=50)" in message
    assert "Caveats: " + BOUNDED in message
    line = message.split("\n")[-1]
    match = MEDIA.match(line)
    assert match and Path(match.group(1)).parent == delivery_on
    assert Path(match.group(1)).read_bytes() == PNG
    # The 50-row boundary and caveats are as before.
    assert payload["data"]["n"] == 50 and BOUNDED in payload["warnings"]
    assert len(worker_on["seen"]["sample"]) == 50


def test_each_request_gets_its_own_file_and_line(worker_on, delivery_on):
    """One file and one MEDIA line per request; a second request never repeats the
    first one's line, and neither result names the other's token."""
    worker_on["set"](worker_json(chart=SCATTER))
    first, _ = session_call(city="Pasadena", code=CODE)
    second, _ = session_call(city="Pasadena", code=CODE)
    a = first["data"]["chart"]["delivery"]["media_line"]
    b = second["data"]["chart"]["delivery"]["media_line"]
    assert a != b
    token_a = re.search(r"chart-([0-9a-f]{32})", a).group(1)
    token_b = re.search(r"chart-([0-9a-f]{32})", b).group(1)
    assert token_a not in json.dumps(second) and token_b not in json.dumps(first)
    assert len(_ours(delivery_on)) == 2


def test_two_sessions_never_see_each_others_chart(worker_on, delivery_on):
    """Two client sessions, as two chats would have: each result names only the file
    written for it; the directory is private to this user."""
    worker_on["set"](worker_json(chart=SCATTER))

    async def one():
        async with Client(server.server) as client:
            result = await client.call_tool(
                "bounded_analysis", {"city": "Pasadena", "code": CODE}
            )
            return json.loads(result.content[0].text)

    async def both():
        return await asyncio.gather(one(), one())

    left, right = asyncio.run(both())
    lines = {r["data"]["chart"]["delivery"]["media_line"] for r in (left, right)}
    assert len(lines) == 2
    for mine, other in ((left, right), (right, left)):
        theirs = other["data"]["chart"]["delivery"]["media_line"]
        assert theirs not in json.dumps(mine)
    assert stat.S_IMODE(delivery_on.stat().st_mode) == 0o700


def test_a_render_started_after_another_sessions_input_still_gets_its_own_chart(
    worker_on, delivery_on, monkeypatch
):
    """The interleaving behind the old flake, forced: session A's render input
    directory is made, then session B's analysis input directory, then A's render
    starts while B's directory is the newest one. Each run reads only its own inputs
    (the fake docker takes them from the run's own mount, as docker does), so both
    sessions get a delivered chart and neither names the other's file."""
    worker_on["set"](worker_json(chart=SCATTER))
    calls = worker_on["calls"]
    make_dir, launch = executor.tempfile.mkdtemp, executor.subprocess.Popen
    order = itertools.count(1)
    b_dir_made, a_render_started = threading.Event(), threading.Event()
    seen: dict = {}

    def session_b():
        seen["b"] = session_call(city="Pasadena", code=CODE)[0]

    b = threading.Thread(target=session_b)

    def mkdtemp(**kwargs):
        step, path = next(order), make_dir(**kwargs)
        if step == 2:  # A's render input: start B, wait for B's analysis input
            b.start()
            assert b_dir_made.wait(10)
        elif step == 3:  # B's analysis input: hold B until A's render has started
            b_dir_made.set()
            assert a_render_started.wait(10)
        return path

    def popen(argv, **kwargs):
        first_render = "/opt/worker/render.py" in argv and "newest" not in seen
        if first_render:
            seen["newest"], seen["own"] = calls.dirs[-1], mount_source(argv)
        try:
            return launch(argv, **kwargs)
        finally:
            if first_render:
                a_render_started.set()

    monkeypatch.setattr(executor.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(executor.subprocess, "Popen", popen)
    a = session_call(city="Pasadena", code=CODE)[0]
    b.join(10)
    assert not b.is_alive()
    # The interleaving really happened: A's render was not the newest input.
    assert seen["newest"] != seen["own"]
    lines = []
    for mine, other in ((a, seen["b"]), (seen["b"], a)):
        assert mine["data"]["chart"]["status"] == "rendered"
        delivered = mine["data"]["chart"]["delivery"]
        assert delivered["status"] == "ready"
        assert Path(delivered["media_line"].removeprefix("MEDIA:")).read_bytes() == PNG
        assert other["data"]["chart"]["delivery"]["media_line"] not in json.dumps(mine)
        lines.append(delivered["media_line"])
    assert len(set(lines)) == 2
    # Two MCP sessions, two owners in the supersede ledger.
    issued = delivery.store_for(delivery_on)._issued
    assert len({owner for owner, _ in issued.values()}) == 2


def test_a_render_that_is_not_a_png_writes_nothing(worker_on, delivery_on):
    worker_on["set"](worker_json(chart=SCATTER), render=b"\x89PNG not really")
    payload, images = session_call(city="Pasadena", code=CODE)
    assert images == [] and "MEDIA:" not in payload["message"]
    assert payload["data"]["chart"]["status"] == "invalid_png"
    assert not delivery_on.exists() or _ours(delivery_on) == []


def test_an_unusable_directory_setting_fails_visibly(
    worker_on, delivery_on, monkeypatch
):
    assert charts_in_dotenv(
        monkeypatch, IDX_CHART_DELIVERY="1", IDX_CHART_DIR="relative/idx-charts"
    )
    worker_on["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert images == []
    assert delivery.CHART_NOT_DELIVERED_LINE in payload["message"]
    assert payload["data"]["chart"]["delivery"]["reason"] == "dir_invalid"


def test_delivery_without_the_analysis_switch_registers_nothing(monkeypatch):
    monkeypatch.setenv(delivery.SWITCH, "1")
    monkeypatch.delenv(analysis_tool.TOOL_SETTING, raising=False)
    assert server.register_analysis_tool() is False
    assert "bounded_analysis" not in server.tool_names()


def test_the_instructions_and_tool_list_do_not_change_with_delivery(delivery_on):
    async def go():
        async with Client(server.server) as client:
            tools = (await client.list_tools()).tools
            return client.instructions, {t.name: t.description for t in tools}

    instructions, tools = asyncio.run(go())
    assert instructions == server.ANALYSIS_INSTRUCTIONS
    assert tools["bounded_analysis"] == server.ANALYSIS_DESCRIPTION


def test_rollback_switch_off_restores_wo027_and_prune_removes_the_files(
    worker_on, delivery_on, monkeypatch, capsys
):
    worker_on["set"](worker_json(chart=SCATTER))
    session_call(city="Pasadena", code=CODE)
    assert len(_ours(delivery_on)) == 1
    # Rollback: the switch leaves .env (IDX_CHART_DIR may stay) and the server restarts.
    assert not charts_in_dotenv(monkeypatch, IDX_CHART_DIR=str(delivery_on))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert [type(b) for b in images] == [ImageContent]
    assert "MEDIA:" not in payload["message"]
    assert len(_ours(delivery_on)) == 1  # off writes nothing new
    assert delivery.main(["prune", "--all"]) == 0
    assert "removed 1 chart file(s)" in capsys.readouterr().out
    assert _ours(delivery_on) == []


def test_the_prune_command_refuses_an_unusable_directory(monkeypatch, capsys):
    charts_in_dotenv(monkeypatch, IDX_CHART_DIR="/tmp/not-ours")
    assert delivery.main(["prune"]) == 1
    assert "nothing pruned" in capsys.readouterr().out


def test_the_prune_command_refuses_an_environment_that_names_another_directory(
    monkeypatch, capsys, chart_dir
):
    """Like install.sh: the directory is the one .env names, never the shell's."""
    charts_in_dotenv(monkeypatch, IDX_CHART_DIR=str(chart_dir))
    delivery.ChartStore(chart_dir).write(PNG)
    monkeypatch.setenv(delivery.DIR_SETTING, "/srv/elsewhere/idx-charts")
    assert delivery.main(["prune", "--all"]) == 1
    out = capsys.readouterr().out
    assert delivery.DIR_DIFFERS in out and "Nothing pruned." in out
    assert len(_ours(chart_dir)) == 1


def test_a_contradicting_environment_keeps_delivery_off_over_mcp(
    worker_on, delivery_on, monkeypatch
):
    """The gateway's environment says IDX_CHART_DELIVERY=0 while .env says 1: the
    server keeps delivery off (WO-027's result, image to the model, nothing
    written) and reports the problem, instead of silently following either side."""
    monkeypatch.setenv(delivery.SWITCH, "0")
    assert server.configure_chart_delivery() is False
    assert server.chart_delivery_problem() == delivery.DELIVERY_FILE_ONLY
    worker_on["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert [type(b) for b in images] == [ImageContent]
    assert "MEDIA:" not in payload["message"]
    assert not delivery_on.exists() or _ours(delivery_on) == []


def test_the_skill_tells_the_model_to_keep_the_line_once_and_unformatted():
    text = (
        Path(__file__).resolve().parents[1] / "skills/bounded-analysis/SKILL.md"
    ).read_text()
    assert "`data.chart.delivery.status` is `ready`" in text
    assert "Never repeat it in a later reply" in text
    assert "never write any other `MEDIA:` line" in text


# --- install.sh: reports only, never renders or merges anything for charts ---


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_with_delivery_on_changes_no_openclaw_config(tmp_path):
    analysis = [
        f"IDX_OWNER_E164={OWNER}",
        "IDX_ANALYSIS_TOOL=1",
        f"IDX_ANALYSIS_IMAGE={IMAGE}",
    ]
    base = _install(tmp_path / "a", analysis)
    assert base.returncode == 0, base.stderr
    done = _install(
        tmp_path / "b",
        [*analysis, "IDX_CHART_DELIVERY=1", "IDX_CHART_DIR=/srv/x/idx-charts"],
    )
    assert done.returncode == 0, done.stderr
    without = json.loads((tmp_path / "a" / "state" / "openclaw.json").read_text())
    merged = json.loads((tmp_path / "b" / "state" / "openclaw.json").read_text())
    assert merged["agents"]["entries"]["idx"]["skills"] == [*SKILLS, "bounded-analysis"]
    # The two installs differ only in paths that name their own temp dirs.
    a, b = json.dumps(without), json.dumps(merged)
    assert a.replace(str(tmp_path / "a"), "") == b.replace(str(tmp_path / "b"), "")
    state = sorted(p.name for p in (tmp_path / "b" / "state").iterdir())
    assert not [n for n in state if "chart" in n]
    assert "Chart delivery is on" in done.stdout
    assert "/srv/x/idx-charts" in done.stdout
    assert "unverified until the acceptance check" in done.stdout
    assert "prune --all" in done.stdout


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_with_delivery_but_no_analysis_says_it_is_inert(tmp_path):
    done = _install(tmp_path, [f"IDX_OWNER_E164={OWNER}", "IDX_CHART_DELIVERY=1"])
    assert done.returncode == 0, done.stderr
    installed = load().load_json5(tmp_path / "state" / "openclaw.json")
    assert installed["agents"]["entries"]["idx"]["skills"] == SKILLS
    assert "has no effect while IDX_ANALYSIS_TOOL is not 1" in done.stdout
    assert "Chart delivery is on" not in done.stdout


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_reports_an_unusable_chart_directory(tmp_path):
    done = _install(
        tmp_path,
        [
            f"IDX_OWNER_E164={OWNER}",
            "IDX_ANALYSIS_TOOL=1",
            "IDX_CHART_DELIVERY=1",
            "IDX_CHART_DIR=charts",
        ],
    )
    assert done.returncode == 0, done.stderr
    assert "must be an absolute path ending in /idx-charts" in done.stdout


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
@pytest.mark.parametrize("value", ["", "0", "true"])
def test_install_with_delivery_off_prints_nothing_about_charts(tmp_path, value):
    done = _install(
        tmp_path,
        [
            f"IDX_OWNER_E164={OWNER}",
            "IDX_ANALYSIS_TOOL=1",
            f"IDX_CHART_DELIVERY={value}",
        ],
    )
    assert done.returncode == 0, done.stderr
    assert "hart" not in done.stdout
