"""WO-030: deliver a bounded-analysis chart to the chat that asked for it.

Off unless IDX_CHART_DELIVERY and IDX_ANALYSIS_TOOL are both exactly "1"; off, the tool
returns WO-027's result byte for byte. On, the PNG is written once into a dedicated
directory and the message ends with a `MEDIA:` line (docs/CHART_DELIVERY.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import threading
import time
import weakref
from collections.abc import Callable, Mapping
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
# workspace, and the result's message ends with one standalone `MEDIA:<absolute path>`
# line. OpenClaw 2026.9.5 parses that line in the agent's final reply, copies the file
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

__all__ = [
    "CHART_NOT_DELIVERED_LINE",
    "DEFAULT_DIR",
    "DIR_NAME",
    "DIR_SETTING",
    "MAX_BYTES",
    "MAX_FILES",
    "MEDIA_PREFIX",
    "STALE_TEMP_SECONDS",
    "SUPERSEDE_GRACE_SECONDS",
    "SWITCH",
    "TTL_SECONDS",
    "ChartFile",
    "ChartStore",
    "DeliveryError",
    "chart_dir",
    "content_blocks",
    "deliver",
    "enabled",
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
# Inside the idx agent workspace that config/openclaw.idx.json5 sets; OpenClaw's
# outbound media roots include that workspace (docs/CHART_DELIVERY.md, evidence E5).
DEFAULT_DIR = "~/.openclaw/workspace-idx/" + DIR_NAME
TTL_SECONDS = 300
SUPERSEDE_GRACE_SECONDS = 120
# A temp file lives for the milliseconds of one write; older, its writer is gone.
STALE_TEMP_SECONDS = 60
MAX_FILES = 20
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

_FILE = re.compile(r"^chart-[0-9a-f]{32}\.png$")
_TEMP = re.compile(r"^\.chart-[0-9a-f]{32}\.tmp$")
# A MEDIA reference with whitespace or quotes is not one token to OpenClaw's parser.
_UNSAFE_PATH = re.compile(r"[\s\"'`\\]")


class DeliveryError(Exception):
    """A chart that could not be prepared; `reason` is a fixed code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ChartFile:
    """One written chart: its random token and absolute path."""

    token: str
    path: Path

    @property
    def media_line(self) -> str:
        return MEDIA_PREFIX + str(self.path)


def enabled(setting: Setting) -> bool:
    """True only when IDX_CHART_DELIVERY and IDX_ANALYSIS_TOOL are both exactly "1"."""
    return analysis_tool.enabled(setting) and setting(SWITCH) == "1"


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
        # token -> (owner, issued at): an owner is one MCP session (`owner_for`).
        self._issued: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

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
        info = os.lstat(self.directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise DeliveryError("dir_unsafe")
        if stat.S_IMODE(info.st_mode) != 0o700:
            os.chmod(self.directory, 0o700)

    # --- writing ---

    def write(self, png: object, owner: str = "") -> ChartFile:
        """Validate, then write one new file for `owner` (one session); raises
        DeliveryError with a fixed code. Only `owner`'s own earlier charts are
        superseded; a directory full of young charts refuses this one (`dir_full`)."""
        if not isinstance(png, bytes) or not png:
            raise DeliveryError("no_image")
        if len(png) > self.max_bytes:
            raise DeliveryError("too_large")
        if png_size(png, self.max_bytes) is None:
            raise DeliveryError("invalid_png")
        with self._lock:
            self._ready()
            now = self._clock()
            self._supersede(now, owner)
            _, remaining = self._sweep(now, everything=False, room=1)
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
            except OSError:
                _unlink(temp)
                raise DeliveryError("write_failed") from None
            if os.path.getsize(final) != len(png):
                _unlink(final)
                raise DeliveryError("write_failed")
            self._issued[token] = (owner, now)
            return ChartFile(token=token, path=final)

    def _supersede(self, now: float, owner: str) -> None:
        """Remove `owner`'s earlier charts once the grace period has passed: by then
        the reply that named each one has been sent and OpenClaw holds a copy. Another
        session's charts are never touched here."""
        for token, (whose, issued) in list(self._issued.items()):
            if whose == owner and now - issued >= self.grace:
                _unlink(self.directory / f"chart-{token}.png")
                del self._issued[token]

    # --- retention ---

    def prune(
        self, now: float | None = None, *, everything: bool = False, room: int = 0
    ) -> int:
        """Delete our expired charts and stale temp files (all of ours with
        `everything`), then the oldest charts past the grace period until at most
        `max_files - room` remain. Only names matching our pattern, only regular
        files, never a symlink, never a subdirectory. Returns the count removed."""
        now = self._clock() if now is None else now
        return self._sweep(now, everything=everything, room=room)[0]

    def _sweep(self, now: float, *, everything: bool, room: int) -> tuple[int, int]:
        """`prune`'s work: (files removed, our charts left). Every server process (one
        per chat session) sweeps the same directory, so nothing that may still be in
        use by another session is removed: no temp file younger than
        STALE_TEMP_SECONDS (a write in progress) and, to make room, no chart younger
        than the grace period (its reply may be pending)."""
        if not self.directory.is_dir() or self.directory.is_symlink():
            return 0, 0
        kept: list[tuple[float, str]] = []
        removed = 0
        with os.scandir(self.directory) as entries:
            for entry in entries:
                temp = bool(_TEMP.match(entry.name))
                if not (temp or _FILE.match(entry.name)):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                age = now - entry.stat(follow_symlinks=False).st_mtime
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


def store_for(setting: Setting) -> ChartStore | None:
    """This process's store for the configured directory (None: unusable setting).
    One store per process keeps the issued-token ledger (by owner) across calls."""
    global _store
    directory = chart_dir(setting)
    if directory is None:
        return None
    with _store_guard:
        if _store is None or _store.directory != directory:
            _store = ChartStore(directory)
        return _store


def reset_store_for_tests() -> None:
    global _store
    with _store_guard:
        _store = None


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
    (or all of ours) in the configured directory; prints only the count."""
    from idx_agent.db.pool import env_setting

    parser = argparse.ArgumentParser(prog="python -m idx_agent.analysis.delivery")
    parser.add_argument("command", choices=["prune"])
    parser.add_argument("--all", action="store_true", help="every chart file of ours")
    args = parser.parse_args(argv)
    directory = chart_dir(env_setting)
    if directory is None:
        print("IDX_CHART_DIR is not a usable .../idx-charts path; nothing pruned")
        return 1
    removed = ChartStore(directory).prune(everything=args.all)
    print(f"removed {removed} chart file(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main() in tests
    raise SystemExit(main())
