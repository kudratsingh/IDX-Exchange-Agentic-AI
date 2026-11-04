"""WO-030: deliver a bounded-analysis chart to the chat that asked for it.

Off unless `chart_state` (.env decides; IDX_CHART_DELIVERY and IDX_ANALYSIS_TOOL "1")
says on; off, the tool returns WO-027's result byte for byte. On, the PNG is written
once into a dedicated directory and the message ends with a `MEDIA:` line.
"""

from __future__ import annotations

import argparse
import atexit
import errno
import fcntl
import json
import os
import re
import secrets
import signal
import stat
import threading
import time
import weakref
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.types import TextContent

from idx_agent.analysis import tool as analysis_tool
from idx_agent.analysis.png import png_size
from idx_agent.channels.format import format_chart_line
from idx_agent.domain.analysis_worker import RENDER_STDOUT_CAP

# How it works. The checked PNG never goes to the model. It is written once, under a
# fresh 128-bit random name, into one directory inside the `idx` agent's OpenClaw
# workspace, and the result's message ends with one standalone `MEDIA:` line naming it
# (workspace-relative in the default directory, else absolute; `media_reference`).
# OpenClaw 2026.9.5 parses that line in the agent's final reply, copies the file
# into its own outbound media store under the agent's existing `read` policy, and
# attaches it to the reply to the chat the turn came from. No OpenClaw tool or policy
# changes: no `message` tool, no public URL, no other directory. The text never depends
# on the image; any failure here replaces the caption with a line saying the chart
# could not be prepared. Retention touches our own file names only (regular files,
# never symlinks): after TTL_SECONDS; beyond MAX_FILES, but never a chart younger than
# SUPERSEDE_GRACE_SECONDS (a full directory refuses the new chart instead); temp files
# only once STALE_TEMP_SECONDS old; and a session's own earlier charts
# SUPERSEDE_GRACE_SECONDS after issue once that session writes a newer one. So one
# session's chart never removes another session's chart while its reply may be pending.
# The MAX_FILES cap holds across those processes: admission (sweep, count, write,
# rename) runs under an exclusive advisory lock (`flock`) on LOCK_NAME inside the
# directory, a regular file of ours, mode 600, opened with O_NOFOLLOW, never written to
# and never removed by retention. A writer waits at most LOCK_WAIT_SECONDS for it, then
# refuses its chart (`dir_busy`; the figures still return). The kernel drops the lock
# when its holder exits, however it exits, so a killed writer never blocks the others.
# Those processes sweep concurrently: a file another one removed first is skipped, and
# any other file-system error becomes a DeliveryError (never a failed tool call).
# Expiry while the server lives is not left to those sweeps: the server's store
# (`store_for`) runs one daemon thread that removes each chart this process wrote at
# its deadline, TTL_SECONDS after writing, with no further request needed; a clean exit
# (stdin closed, SIGTERM, SIGINT) removes this process's charts at once
# (`arm_exit_cleanup`). A SIGKILLed process leaves its charts to the next sweep by any
# server (start, write or deadline) or the operator's prune; docs/CHART_DELIVERY.md
# section 5 states that residual window and the not-installed launchd proposal.

__all__ = [
    "CHART_NOT_DELIVERED_LINE",
    "DELIVERY_ENV_ONLY",
    "DELIVERY_FILE_ONLY",
    "DIR_DIFFERS",
    "DEFAULT_DIR",
    "DIR_NAME",
    "DIR_SETTING",
    "EXPIRY_CHECK_SECONDS",
    "LOCK_NAME",
    "LOCK_WAIT_SECONDS",
    "MAX_BYTES",
    "MAX_FILES",
    "MEDIA_PREFIX",
    "STALE_TEMP_SECONDS",
    "SUPERSEDE_GRACE_SECONDS",
    "SWITCH",
    "TTL_SECONDS",
    "WORKSPACE",
    "ChartFile",
    "ChartState",
    "ChartStore",
    "DeliveryError",
    "arm_exit_cleanup",
    "chart_dir",
    "chart_state",
    "configured_dir",
    "content_blocks",
    "deliver",
    "enabled",
    "media_reference",
    "owner_for",
    "reset_store_for_tests",
    "store_for",
]

Setting = Callable[[str], str | None]

SWITCH = "IDX_CHART_DELIVERY"
DIR_SETTING = "IDX_CHART_DIR"
# The directory's own name is fixed, so a setting can never point the writer (or the
# pruner) at a directory that holds anything else.
DIR_NAME = "idx-charts"
# The idx agent workspace that config/openclaw.idx.json5 sets; OpenClaw's outbound
# media roots include it (docs/CHART_DELIVERY.md, evidence E5). The default directory
# sits directly inside it.
WORKSPACE = "~/.openclaw/workspace-idx"
DEFAULT_DIR = WORKSPACE + "/" + DIR_NAME
TTL_SECONDS = 300
SUPERSEDE_GRACE_SECONDS = 120
# A temp file lives for the milliseconds of one write; older, its writer is gone.
STALE_TEMP_SECONDS = 60
MAX_FILES = 20
# Admission across server processes (one per chat session). The name matches neither
# retention pattern, so no sweep, expiry or `prune --all` removes it. Holders keep it
# for one write (milliseconds: at most MAX_BYTES and an fsync); the wait is bounded so
# a stuck holder costs a chart, never the tool call.
LOCK_NAME = ".idx-charts.lock"
LOCK_WAIT_SECONDS = 2.0
_LOCK_POLL_SECONDS = 0.01
# The expiry thread's longest wait. Its waits run on the monotonic clock, which does not
# advance while the Mac sleeps; deadlines are wall-clock times, so after a wake (or a
# clock change) a due chart is removed within this many seconds of the process running.
EXPIRY_CHECK_SECONDS = 15
# The renderer's own cap; png_size never accepts more. Far below WhatsApp's 50 MB.
MAX_BYTES = RENDER_STDOUT_CAP
MEDIA_PREFIX = "MEDIA:"

CHART_NOT_DELIVERED_LINE = (
    "Chart: could not be prepared for this chat this time; the figures above are the "
    "whole result."
)
# WO-027's caption says the image came back with the tool result; delivered, it
# follows in the chat instead. Built from format_chart_line so the two stay in step.
_RETURNED = ", returned as an image with this result."
_FOLLOWS = ", follows as an image in this chat."

# Used with fullmatch: `$` alone would also accept a name ending in a newline.
_FILE = re.compile(r"chart-[0-9a-f]{32}\.png")
_TEMP = re.compile(r"\.chart-[0-9a-f]{32}\.tmp")
# A MEDIA reference with whitespace or quotes is not one token to OpenClaw's parser.
_UNSAFE_PATH = re.compile(r"[\s\"'`\\]")


class DeliveryError(Exception):
    """A chart that could not be prepared; `reason` is a fixed code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def media_reference(path: Path) -> str:
    """How the MEDIA line names a chart: `idx-charts/<name>` (workspace-relative) when
    the file is in the default directory, so the user name in an absolute path never
    shows if the line is not turned into media; else the absolute path. OpenClaw
    resolves both against the agent workspace under the same read policy (E15)."""
    if path.parent == Path(DEFAULT_DIR).expanduser():
        return f"{DIR_NAME}/{path.name}"
    return str(path)


@dataclass(frozen=True)
class ChartFile:
    """One written chart: its random token and absolute path."""

    token: str
    path: Path

    @property
    def media_line(self) -> str:
        return MEDIA_PREFIX + media_reference(self.path)


def enabled(setting: Setting) -> bool:
    """True only when IDX_CHART_DELIVERY and IDX_ANALYSIS_TOOL are both exactly "1"."""
    return analysis_tool.enabled(setting) and setting(SWITCH) == "1"


# --- one rule for install.sh and the server (WO-027's switch_state, extended) ---

DELIVERY_FILE_ONLY = (
    f"Chart delivery is misconfigured: {SWITCH} is 1 in .env but not in the process "
    f"environment, so chart delivery is off. {analysis_tool.KEEP_IN_DOTENV}"
)
DELIVERY_ENV_ONLY = (
    f"Chart delivery is misconfigured: {SWITCH} is 1 in the process environment but "
    f"not in .env, so chart delivery is off. {analysis_tool.KEEP_IN_DOTENV}"
)
DIR_DIFFERS = (
    f"Chart delivery is misconfigured: {DIR_SETTING} in the process environment "
    "differs from .env, so install.sh reported one chart directory and the server "
    f"would write to the other; chart delivery is off. {analysis_tool.KEEP_IN_DOTENV}"
)


@dataclass(frozen=True)
class ChartState:
    """Chart delivery as install.sh and the tool server both decide it (WO-030).

    `on` means charts are delivered (into `directory`, None when IDX_CHART_DIR is
    unusable, so every chart fails visibly); `problem` is one line for the operator
    when the process environment contradicts `.env`, else None."""

    on: bool
    directory: Path | None = None
    problem: str | None = None


def configured_dir(
    environ: Mapping[str, str], dotenv: Mapping[str, str]
) -> tuple[Path | None, str | None]:
    """The chart directory from `.env` (None: unusable), or the problem line when the
    process environment sets IDX_CHART_DIR to something else."""
    if analysis_tool.value_differs(DIR_SETTING, environ, dotenv):
        return None, DIR_DIFFERS
    return chart_dir(dotenv.get), None


def chart_state(environ: Mapping[str, str], dotenv: Mapping[str, str]) -> ChartState:
    """`.env` decides, as for IDX_ANALYSIS_TOOL: an `environ` that contradicts it on
    IDX_CHART_DELIVERY gives off plus a problem line; with delivery on in `.env` and
    the analysis tool on, an IDX_CHART_DIR in `environ` that differs from `.env` does
    too. Delivery also needs `analysis_tool.switch_state` on (else it is inert)."""
    file_on = dotenv.get(SWITCH) == "1"
    if analysis_tool.switch_contradicted(SWITCH, environ, dotenv):
        return ChartState(
            False, problem=DELIVERY_FILE_ONLY if file_on else DELIVERY_ENV_ONLY
        )
    if not file_on or not analysis_tool.switch_state(environ, dotenv).on:
        return ChartState(False)
    directory, problem = configured_dir(environ, dotenv)
    if problem:
        return ChartState(False, problem=problem)
    return ChartState(True, directory)


def chart_dir(setting: Setting) -> Path | None:
    """The dedicated chart directory, or None when the setting is unusable.

    IDX_CHART_DIR, else DEFAULT_DIR; `~` expands; the result must be absolute, end in
    DIR_NAME, contain no `..`, and have no whitespace or quote characters."""
    raw = setting(DIR_SETTING) or DEFAULT_DIR
    if _UNSAFE_PATH.search(raw):
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute() or path.name != DIR_NAME or ".." in path.parts:
        return None
    return path


class ChartStore:
    """Writes checked PNGs into one directory and prunes only its own files."""

    def __init__(
        self,
        directory: Path,
        *,
        ttl: float = TTL_SECONDS,
        grace: float = SUPERSEDE_GRACE_SECONDS,
        max_files: int = MAX_FILES,
        max_bytes: int = MAX_BYTES,
        clock: Callable[[], float] = time.time,
        token: Callable[[], str] = lambda: secrets.token_hex(16),
        expire_in_background: bool = False,
        lock_wait: float = LOCK_WAIT_SECONDS,
    ) -> None:
        if directory.name != DIR_NAME or not directory.is_absolute():
            raise ValueError("chart directory must be an absolute .../idx-charts path")
        self.directory = directory
        self.ttl = ttl
        self.grace = grace
        self.max_files = max(1, max_files)
        self.max_bytes = min(max_bytes, MAX_BYTES)  # a caller may lower the cap only
        self._clock = clock
        self._token = token
        self.lock_wait = max(0.0, lock_wait)
        # token -> (owner, issued at): an owner is one MCP session (`owner_for`).
        self._issued: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        # The expiry thread (`expire_in_background`; the server's store): started by
        # the first write, woken by every write, stopped by `stop` or `close`.
        self._background = expire_in_background
        self._expirer: threading.Thread | None = None
        self._wake = threading.Event()
        self._stopped = False

    # --- the directory ---

    def _ready(self) -> None:
        """Create the directory (mode 700) inside an existing parent, then insist it
        is a real directory owned by this user; never follow a symlink."""
        parent = self.directory.parent
        if not parent.is_dir():
            raise DeliveryError("workspace_missing")
        try:
            os.mkdir(self.directory, 0o700)
        except FileExistsError:
            pass
        except OSError:
            raise DeliveryError("dir_unavailable") from None
        try:
            info = os.lstat(self.directory)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise DeliveryError("dir_unsafe")
            if stat.S_IMODE(info.st_mode) != 0o700:
                os.chmod(self.directory, 0o700)
        except OSError:
            raise DeliveryError("dir_unavailable") from None

    @contextmanager
    def _admission(self) -> Iterator[None]:
        """Hold the exclusive `flock` on LOCK_NAME that every server process shares,
        so a count and its write are one step across processes. Never via a symlink;
        only a regular file of this user's, mode 600. DeliveryError: `lock_unsafe`,
        `lock_unavailable`, or `dir_busy` after `lock_wait` seconds."""
        # O_NONBLOCK: a FIFO planted under the name cannot stall the open (then
        # refused by the regular-file check). Closing the descriptor drops the lock.
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_NONBLOCK
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            fd = os.open(self.directory / LOCK_NAME, flags, 0o600)
        except OSError as exc:
            unsafe = exc.errno in (errno.ELOOP, errno.EISDIR, errno.ENXIO)
            raise DeliveryError(
                "lock_unsafe" if unsafe else "lock_unavailable"
            ) from None
        try:
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise DeliveryError("lock_unsafe")
                if stat.S_IMODE(info.st_mode) != 0o600:
                    os.fchmod(fd, 0o600)
            except OSError:
                raise DeliveryError("lock_unavailable") from None
            deadline = time.monotonic() + self.lock_wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DeliveryError("dir_busy") from None
                    time.sleep(_LOCK_POLL_SECONDS)
                except OSError:
                    raise DeliveryError("lock_unavailable") from None
            yield
        finally:
            os.close(fd)  # releases the lock

    # --- writing ---

    def write(self, png: object, owner: str = "") -> ChartFile:
        """Validate, then write one new file for `owner` (one session); raises
        DeliveryError with a fixed code. Only `owner`'s own earlier charts are
        superseded; a full directory of young charts refuses this one (`dir_full`).
        Count and write hold the cross-process lock (`_admission`), so all processes
        together keep `max_files`. Any file-system error is a DeliveryError too."""
        if not isinstance(png, bytes) or not png:
            raise DeliveryError("no_image")
        if len(png) > self.max_bytes:
            raise DeliveryError("too_large")
        if png_size(png, self.max_bytes) is None:
            raise DeliveryError("invalid_png")
        with self._lock:
            self._ready()
            with self._admission():
                now = self._clock()
                self._supersede(now, owner)
                try:
                    _, remaining = self._sweep(now, everything=False, room=1)
                except OSError:
                    raise DeliveryError("dir_unavailable") from None
                if remaining >= self.max_files:
                    raise DeliveryError("dir_full")
                token = self._token()
                if not re.fullmatch(r"[0-9a-f]{32}", token):
                    raise DeliveryError("bad_token")
                final = self.directory / f"chart-{token}.png"
                temp = self.directory / f".chart-{token}.tmp"
                if os.path.lexists(final):
                    raise DeliveryError("name_taken")  # never reuse a token
                try:
                    _write_new(temp, png)
                    os.rename(temp, final)
                    size = os.path.getsize(final)  # gone if `prune --all` ran meanwhile
                except OSError:
                    _unlink(temp)
                    _unlink(final)
                    raise DeliveryError("write_failed") from None
                if size != len(png):
                    _unlink(final)
                    raise DeliveryError("write_failed")
                self._issued[token] = (owner, now)
                if self._background:
                    self._start_expirer()
                    self._wake.set()
                return ChartFile(token=token, path=final)

    def _supersede(self, now: float, owner: str) -> None:
        """Remove `owner`'s earlier charts once the grace period has passed: by then
        the reply that named each one has been sent and OpenClaw holds a copy. Another
        session's charts are never touched here."""
        for token, (whose, issued) in list(self._issued.items()):
            if whose == owner and now - issued >= self.grace:
                _unlink(self.directory / f"chart-{token}.png")
                self._issued.pop(token, None)

    # --- expiry of this process's own charts ---

    def expire_due(self, now: float | None = None) -> int:
        """Remove every chart this store wrote whose deadline (written + ttl) has
        come, whatever else happens; then, if any was due, sweep other expired files of
        ours (a crashed process's). Returns the count of this store's charts removed."""
        now = self._clock() if now is None else now
        removed = 0
        with self._lock:
            for token, (_, issued) in list(self._issued.items()):
                if now >= issued + self.ttl:
                    removed += _unlink(self.directory / f"chart-{token}.png")
                    self._issued.pop(token, None)
            if removed:
                try:
                    self._sweep(now, everything=False, room=0)
                except OSError:  # unlistable: the next sweep or prune retries
                    pass
        return removed

    def next_check(self, now: float | None = None) -> float | None:
        """Seconds until the earliest pending deadline, at most EXPIRY_CHECK_SECONDS;
        None when this store has no chart pending."""
        now = self._clock() if now is None else now
        deadlines = [issued + self.ttl for _, issued in list(self._issued.values())]
        if not deadlines:
            return None
        return max(0.0, min(min(deadlines) - now, EXPIRY_CHECK_SECONDS))

    def pending(self) -> list[str]:
        """Tokens of this store's charts not yet removed (for tests and the docs)."""
        return sorted(self._issued)

    def _start_expirer(self) -> None:
        if self._expirer is None and not self._stopped:
            self._expirer = threading.Thread(
                target=self._expire_loop, name="idx-chart-expiry", daemon=True
            )
            self._expirer.start()

    def _expire_loop(self) -> None:
        while True:
            self._wake.clear()  # before the checks: a write or stop after it wakes us
            if self._stopped:
                return
            self.expire_due()
            self._wake.wait(self.next_check())

    def stop(self) -> None:
        """Stop the expiry thread; files stay (`close` removes them)."""
        self._stopped = True
        self._wake.set()
        thread = self._expirer
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=EXPIRY_CHECK_SECONDS)

    def close(self) -> int:
        """At exit: remove every chart this store wrote, now. Never takes the lock
        (a signal handler may run while this thread holds it). Returns the count."""
        self._stopped = True
        self._wake.set()
        removed = 0
        for token in list(self._issued):
            removed += _unlink(self.directory / f"chart-{token}.png")
            self._issued.pop(token, None)
        return removed

    # --- retention ---

    def prune(
        self, now: float | None = None, *, everything: bool = False, room: int = 0
    ) -> int:
        """Delete our expired charts and stale temp files (all of ours with
        `everything`), then the oldest charts past the grace period until at most
        `max_files - room` remain. Only names matching our pattern, only regular
        files, never a symlink, never a subdirectory. Returns the count removed.
        Raises OSError only when the directory cannot be listed."""
        now = self._clock() if now is None else now
        return self._sweep(now, everything=everything, room=room)[0]

    def _sweep(self, now: float, *, everything: bool, room: int) -> tuple[int, int]:
        """`prune`'s work: (files removed, our charts left). Every server process (one
        per chat session) sweeps this directory, at any moment, so no file another
        session may still use is removed: no temp file younger than STALE_TEMP_SECONDS
        and, to make room, no chart younger than the grace period. Raises OSError only
        when the directory itself cannot be listed."""
        # An entry another process removed after this listing named it is skipped (it
        # is gone), as is one this process cannot stat (never removed unseen).
        if not self.directory.is_dir() or self.directory.is_symlink():
            return 0, 0
        kept: list[tuple[float, str]] = []
        removed = 0
        with os.scandir(self.directory) as entries:
            for entry in entries:
                temp = bool(_TEMP.fullmatch(entry.name))
                if not (temp or _FILE.fullmatch(entry.name)):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:  # FileNotFoundError: another process removed it
                    continue
                age = now - mtime
                limit = STALE_TEMP_SECONDS if temp else self.ttl
                if everything or age > limit:
                    removed += _unlink(Path(entry.path))
                elif not temp:
                    kept.append((now - age, entry.path))
        kept.sort()
        while len(kept) > self.max_files - room and now - kept[0][0] >= self.grace:
            _, path = kept.pop(0)
            removed += _unlink(Path(path))
        return removed, len(kept)


def _write_new(path: Path, data: bytes) -> None:
    """Create `path` (never an existing file, never through a symlink), mode 600."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink(path: Path) -> int:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return 0
    except OSError:
        return 0
    return 1


# --- the per-process store ---

_store: ChartStore | None = None
_store_guard = threading.Lock()


def store_for(directory: Path | None) -> ChartStore | None:
    """This process's store for `directory` (None: unusable setting). One store per
    process keeps the issued-token ledger (by owner) across calls."""
    global _store
    if directory is None:
        return None
    with _store_guard:
        if _store is None or _store.directory != directory:
            if _store is not None:
                _store.stop()
            _store = ChartStore(directory, expire_in_background=True)
        return _store


def reset_store_for_tests() -> None:
    global _store
    with _store_guard:
        if _store is not None:
            _store.stop()
        _store = None


def arm_exit_cleanup(store: ChartStore) -> bool:
    """Remove `store`'s charts when this process ends cleanly: at interpreter exit
    (stdin closed, so `server.run` returned; SIGINT) and on SIGTERM, which then ends the
    process as SIGTERM would have. Only from the main thread with SIGTERM at its
    default; otherwise the exit hook alone. True when the SIGTERM handler was set.
    SIGKILL cannot be handled: those charts wait for the next sweep."""
    atexit.register(store.close)
    if threading.current_thread() is not threading.main_thread():
        return False
    if signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL:
        return False

    def on_sigterm(signum: int, frame: object) -> None:
        store.close()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, on_sigterm)
    return True


# One random owner key per live MCP session object; it goes when the session does.
_owners: weakref.WeakKeyDictionary[object, str] = weakref.WeakKeyDictionary()


def owner_for(session: object | None) -> str:
    """The ledger key for one MCP session ("" without one). OpenClaw starts one server
    process per chat session (E13), so in production this is the process; it keeps
    sessions apart even when one process serves several (as in tests)."""
    if session is None:
        return ""
    with _store_guard:
        key = _owners.get(session)
        if key is None:
            key = _owners[session] = secrets.token_hex(8)
        return key


# --- the result ---


def deliver(
    payload: Mapping[str, Any],
    png: bytes | None,
    store: ChartStore | None,
    owner: str = "",
) -> tuple[dict[str, Any], str | None]:
    """The payload to return when delivery is on, and the failure reason (or None).

    Only an ok result with a drawn chart changes: on success the caption says the
    chart follows and the message ends with the MEDIA line; on failure the caption
    becomes CHART_NOT_DELIVERED_LINE. `data.chart.delivery` says which; no image."""
    out = dict(payload)
    data = out.get("data")
    chart = data.get("chart") if isinstance(data, Mapping) else None
    if not out.get("ok") or not isinstance(chart, Mapping):
        return out, None
    if chart.get("status") != "rendered":
        return out, None
    assert isinstance(data, Mapping)
    caption = _caption(data, chart)
    message = str(out.get("message") or "")
    try:
        if store is None:
            raise DeliveryError("dir_invalid")
        written = store.write(png, owner)
    except DeliveryError as exc:
        if caption:
            message = message.replace(caption, CHART_NOT_DELIVERED_LINE)
        out["message"] = message
        delivery = {"status": "failed", "reason": exc.reason}
        out["data"] = {
            **data,
            "chart": {**chart, "image_attached": False, "delivery": delivery},
        }
        return out, exc.reason
    if caption:
        message = message.replace(caption, caption.replace(_RETURNED, _FOLLOWS))
    out["message"] = message.rstrip("\n") + "\n" + written.media_line
    delivery = {
        "status": "ready",
        "media_line": written.media_line,
        "expires_in_s": int(store.ttl) if store is not None else TTL_SECONDS,
    }
    out["data"] = {
        **data,
        "chart": {**chart, "image_attached": False, "delivery": delivery},
    }
    return out, None


def _caption(data: Mapping[str, Any], chart: Mapping[str, Any]) -> str | None:
    title, used = chart.get("title"), chart.get("n_used")
    if not isinstance(title, str) or not isinstance(used, int):
        return None
    rows = chart.get("n_rows") or data.get("n") or 0
    return format_chart_line(title, used, int(rows))


def content_blocks(
    payload: Mapping[str, Any],
    png: bytes | None,
    store: ChartStore | None,
    log: Callable[..., Any] | None = None,
    owner: str = "",
) -> list[Any]:
    """The tool's content when delivery is on: the envelope JSON as text only. A
    failure is logged (fixed reason code, no path) and stated in the message."""
    out, reason = deliver(payload, png, store, owner)
    if log is not None and out.get("ok"):
        chart = (out.get("data") or {}).get("chart") or {}
        status = (chart.get("delivery") or {}).get("status")
        if status is not None:
            trace = (out.get("provenance") or {}).get("trace_id") or ""
            log("chart_delivery", trace, status=status, reason=reason)
    return [TextContent(type="text", text=json.dumps(out, sort_keys=True))]


# --- operator command: prune (also the rollback step) ---


def main(argv: list[str] | None = None) -> int:
    """`python -m idx_agent.analysis.delivery prune [--all]`: delete expired charts
    (or all of ours) in the directory `.env` names; prints only the count. Refuses,
    like install.sh, when the process environment names another directory."""
    from idx_agent.db.pool import dotenv_values

    parser = argparse.ArgumentParser(prog="python -m idx_agent.analysis.delivery")
    parser.add_argument("command", choices=["prune"])
    parser.add_argument("--all", action="store_true", help="every chart file of ours")
    args = parser.parse_args(argv)
    directory, problem = configured_dir(os.environ, dotenv_values())
    if problem:
        print(f"{problem} Nothing pruned.")
        return 1
    if directory is None:
        print("IDX_CHART_DIR is not a usable .../idx-charts path; nothing pruned")
        return 1
    try:
        removed = ChartStore(directory).prune(everything=args.all)
    except OSError:
        print("the chart directory could not be listed; nothing pruned")
        return 1
    print(f"removed {removed} chart file(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main() in tests
    raise SystemExit(main())
