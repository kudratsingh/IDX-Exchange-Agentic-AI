"""The owner-only card store and the listing-handle map (WO-036 prototype, ADR-0015).

The server writes each issued card here; only the gateway's WhatsApp release hook
reads it back (extensions/idx-card-delivery/store.mjs). It lives in OpenClaw's state
directory, outside every agent workspace, so the model's `read` tool cannot open it.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from idx_agent.channels.card_delivery import CardRecord, file_name, parse_record

DIR_SETTING = "IDX_CARD_DIR"
# The directory's own name is fixed, so a setting can never point the writer (or the
# pruner) at a directory that holds anything else.
DIR_NAME = "idx-cards"
# OpenClaw's state directory (scripts/install.sh: STATE_DIR, default ~/.openclaw). The
# store sits beside, never inside, the idx agent workspace (config/openclaw.idx.json5);
# that workspace is the only tree the agent's `read` tool may open.
STATE_DIR = "~/.openclaw"
WORKSPACE = STATE_DIR + "/workspace-idx"
DEFAULT_DIR = STATE_DIR + "/" + DIR_NAME
TTL_SECONDS = 300
MAX_FILES = 64
MAX_RECORD_BYTES = 64 * 1024
STALE_TEMP_SECONDS = 60
_FILE = re.compile(r"card-[0-9a-f]{64}\.json")
_TEMP = re.compile(r"\.card-[0-9a-f]{64}\.[0-9a-f]{16}\.tmp")
_UNSAFE_PATH = re.compile(r"[\s\"'`]")

Setting = Callable[[str], str | None]


class CardStoreError(Exception):
    """A store problem, as a fixed code (never a path or a value)."""


def card_dir(setting: Setting) -> Path | None:
    """IDX_CARD_DIR, else DEFAULT_DIR, as an absolute `.../idx-cards` path; None when
    unusable, including any path inside the agent workspace (symlinks resolved)."""
    raw = setting(DIR_SETTING) or DEFAULT_DIR
    if _UNSAFE_PATH.search(raw):
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute() or path.name != DIR_NAME or ".." in path.parts:
        return None
    if _inside(path, Path(WORKSPACE).expanduser()):
        return None
    return path


def _inside(path: Path, root: Path) -> bool:
    real, top = os.path.realpath(path), os.path.realpath(root)
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


class CardStore:
    """Writes card records into one directory (mode 700, files 600) and prunes only
    its own expired files; a full store refuses the write instead of evicting."""

    def __init__(
        self,
        directory: Path,
        *,
        max_files: int = MAX_FILES,
        max_bytes: int = MAX_RECORD_BYTES,
        ttl: float = TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if directory.name != DIR_NAME or not directory.is_absolute():
            raise ValueError("card directory must be an absolute .../idx-cards path")
        self.directory = directory
        self.max_files = max(1, max_files)
        self.max_bytes = min(max_bytes, MAX_RECORD_BYTES)
        self.ttl = ttl
        self._clock = clock

    def _ready(self) -> None:
        """Create the directory (mode 700) in an existing parent; insist it is a real
        directory of this user's, never a symlink; repair a looser mode."""
        if not self.directory.parent.is_dir():
            raise CardStoreError("parent_missing")
        try:
            os.mkdir(self.directory, 0o700)
        except FileExistsError:
            pass
        except OSError:
            raise CardStoreError("dir_unavailable") from None
        try:
            info = os.lstat(self.directory)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise CardStoreError("dir_unsafe")
            if stat.S_IMODE(info.st_mode) != 0o700:
                os.chmod(self.directory, 0o700)
        except OSError:
            raise CardStoreError("dir_unavailable") from None

    def write(self, record: CardRecord) -> Path:
        """Write `record` durably (temp file, fsync, rename, directory fsync) and
        return its path; CardStoreError (too_large, full, ...) when it cannot."""
        data = json.dumps(record.model_dump(), ensure_ascii=False).encode("utf-8")
        if len(data) > self.max_bytes:
            raise CardStoreError("too_large")
        self._ready()
        self.prune()
        if self.live_count() >= self.max_files:
            raise CardStoreError("full")
        final = self.directory / file_name(record.ref)
        temp = self.directory / f".{final.stem}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            if os.path.lexists(final):
                raise CardStoreError("exists")
            fd = os.open(temp, flags, 0o600)
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view) :]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(temp, final)
            _fsync_dir(self.directory)
        except OSError:
            _unlink(temp)
            raise CardStoreError("write_failed") from None
        return final

    def read(self, ref: str) -> CardRecord | None:
        """The record for `ref`, or None when it is missing or anything about the
        directory or file is unsafe (symlink, owner, mode, size, shape)."""
        try:
            info = os.lstat(self.directory)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                return None
            path = self.directory / file_name(ref)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                st = os.fstat(fd)
                if (
                    not stat.S_ISREG(st.st_mode)
                    or st.st_uid != os.getuid()
                    or st.st_mode & 0o077
                    or st.st_size > self.max_bytes
                ):
                    return None
                data = os.read(fd, self.max_bytes + 1)
            finally:
                os.close(fd)
            record = parse_record(json.loads(data))
        except (OSError, ValueError):
            return None
        return record if record is not None and record.ref == ref else None

    def _own_files(self) -> list[tuple[os.DirEntry[str], bool]]:
        try:
            entries = list(os.scandir(self.directory))
        except OSError:
            return []
        out = []
        for entry in entries:
            temp = _TEMP.fullmatch(entry.name) is not None
            if temp or _FILE.fullmatch(entry.name):
                out.append((entry, temp))
        return out

    def prune(self) -> int:
        """Remove this store's expired records and stale temp files; nothing else."""
        now, removed = self._clock(), 0
        for entry, temp in self._own_files():
            try:
                age = now - entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            if age > (STALE_TEMP_SECONDS if temp else self.ttl):
                removed += _unlink(Path(entry.path))
        return removed

    def live_count(self) -> int:
        """Records not yet expired (by file time)."""
        now = self._clock()
        count = 0
        for entry, temp in self._own_files():
            if temp:
                continue
            try:
                if now - entry.stat(follow_symlinks=False).st_mtime <= self.ttl:
                    count += 1
            except OSError:
                continue
        return count


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink(path: Path) -> int:
    try:
        os.unlink(path)
    except OSError:
        return 0
    return 1


_store: CardStore | None = None
_store_guard = threading.Lock()


def store_for(directory: Path | None) -> CardStore | None:
    """This process's store for `directory` (None: the setting is unusable)."""
    global _store
    if directory is None:
        return None
    with _store_guard:
        if _store is None or _store.directory != directory:
            _store = CardStore(directory)
        return _store


def reset_store_for_tests() -> None:
    global _store
    with _store_guard:
        _store = None


# --- opaque listing handles: what the model passes back in place of a listing key ---

HANDLE_TTL_SECONDS = 30 * 60
MAX_HANDLES = 1000
_HANDLE_LOW, _HANDLE_SPAN = 10**8, 9 * 10**8


class HandleMap:
    """Per-process map from random integer handles to listing keys (30 minutes, at
    most 1000, oldest dropped). An integer, so the tools' schemas stay unchanged."""

    def __init__(
        self,
        ttl: float = HANDLE_TTL_SECONDS,
        max_entries: int = MAX_HANDLES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl, self.max_entries, self._clock = ttl, max(1, max_entries), clock
        self._by_handle: OrderedDict[int, tuple[int, float]] = OrderedDict()
        self._by_key: dict[int, int] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._by_handle:
            handle, (key, at) = next(iter(self._by_handle.items()))
            if now - at <= self.ttl and len(self._by_handle) <= self.max_entries:
                break
            del self._by_handle[handle]
            self._by_key.pop(key, None)

    def issue(self, key: int) -> int:
        """The handle for listing `key` (the same one while it lives)."""
        with self._lock:
            now = self._clock()
            self._expire(now)
            handle = self._by_key.get(key)
            if handle is None:
                handle = _HANDLE_LOW + secrets.randbelow(_HANDLE_SPAN)
                while handle in self._by_handle:
                    handle = _HANDLE_LOW + secrets.randbelow(_HANDLE_SPAN)
                self._by_key[key] = handle
            self._by_handle[handle] = (key, now)
            self._by_handle.move_to_end(handle)
            self._expire(now)
            return handle

    def resolve(self, handle: object) -> int | None:
        """The listing key behind `handle`, or None (unknown, expired or not an int)."""
        if not isinstance(handle, int) or isinstance(handle, bool):
            return None
        with self._lock:
            self._expire(self._clock())
            found = self._by_handle.get(handle)
            return found[0] if found else None
