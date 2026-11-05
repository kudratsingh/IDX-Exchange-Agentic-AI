"""Sentinels for the WO-034 owner acceptance checks (2026-11-04, checks 3 and 4).

`guarded()` records and refuses key reads, provider clients, sockets and opens of
listed paths; `snapshot` captures a directory byte for byte. Values are invented."""

# While `guarded()` is active, each of these is recorded and raises `Touched`:
# - a read of a provider key: an environment variable whose name contains `API_KEY`
#   (an invented value is set first, so iterating the environment reads it too), a
#   `.env` file, the repo's key loader (`evals.run._local_setting`) or the drivers'
#   `read_key`;
# - a provider client: any attribute of the provider SDK module (a sentinel module
#   stands in for it), and the `httpx` client classes;
# - the network: `urllib.request.urlopen`, `OpenerDirector.open`,
#   `http.client.HTTPConnection.connect`, `socket.socket`, `socket.create_connection`
#   and `socket.getaddrinfo`;
# - an open of a listed path (`forbidden`), which is also made unreadable (mode 000)
#   for the duration.
# `Touched` is a BaseException, so a driver's `except Exception` cannot swallow it.

from __future__ import annotations

import builtins
import contextlib
import http.client
import importlib
import io as stdio
import os
import socket
import sys
import types
import urllib.request
from collections.abc import Iterator, MutableMapping
from pathlib import Path

import pytest

SDK = "anthropic"
INVENTED_KEY_VALUE = "invented-sentinel-not-a-key"


class Touched(BaseException):
    """A guarded resource was used."""


def _is_key_name(name: object) -> bool:
    return isinstance(name, str) and "API_KEY" in name.upper()


class _Environ(MutableMapping):
    """`os.environ` with every key-variable read recorded."""

    def __init__(self, real, guard: Guard) -> None:
        self._real, self._guard = real, guard

    def _check(self, name) -> None:
        if _is_key_name(name):
            self._guard.hit(f"environ:{name}")

    def __getitem__(self, name):
        self._check(name)
        return self._real[name]

    def __setitem__(self, name, value) -> None:
        self._real[name] = value

    def __delitem__(self, name) -> None:
        del self._real[name]

    def __contains__(self, name) -> bool:
        self._check(name)
        return name in self._real

    def __iter__(self) -> Iterator[str]:
        return iter(self._real)

    def __len__(self) -> int:
        return len(self._real)

    def copy(self) -> dict:
        return dict(self.items())


class Guard:
    """The record of guarded uses; `hit` records one and raises `Touched`."""

    def __init__(self, forbidden: tuple[Path, ...]) -> None:
        self.events: list[str] = []
        self.forbidden = {os.path.realpath(p) for p in forbidden}

    def hit(self, what: str):
        self.events.append(what)
        raise Touched(what)

    def check_path(self, file) -> None:
        if isinstance(file, int):
            return
        try:
            path = os.fsdecode(os.fspath(file))
        except TypeError:
            return
        if os.path.basename(path) == ".env":
            self.hit(f"open:{path}")
        if os.path.realpath(path) in self.forbidden:
            self.hit(f"open:{path}")


@contextlib.contextmanager
def guarded(*forbidden: Path) -> Iterator[Guard]:
    """Install every sentinel for the `with` body; undo them all afterwards."""
    guard = Guard(tuple(forbidden))
    modes = {p: p.stat().st_mode for p in forbidden if p.exists()}
    real_open, real_os_open = builtins.open, os.open

    def open_(file, *args, **kwargs):
        guard.check_path(file)
        return real_open(file, *args, **kwargs)

    def os_open(path, *args, **kwargs):
        guard.check_path(path)
        return real_os_open(path, *args, **kwargs)

    def refuse(what):
        def call(*_args, **_kwargs):
            guard.hit(what)

        return call

    class NoSocket(socket.socket):
        def __init__(self, *_args, **_kwargs) -> None:
            guard.hit("socket.socket")

    def sdk_attribute(name: str):
        if name.startswith("__"):  # module introspection (inspect.getmodule) is fine
            raise AttributeError(name)
        guard.hit(f"provider client: {SDK}.{name}")

    sdk = types.ModuleType(SDK)
    sdk.__getattr__ = sdk_attribute

    from evals import run as evals_run
    from scripts import enrichment_v3_io

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ANTHROPIC_API_KEY", INVENTED_KEY_VALUE)
        patch.setattr(os, "environ", _Environ(os.environ, guard))
        patch.setattr(evals_run, "_local_setting", refuse("key loader"))
        patch.setattr(enrichment_v3_io, "read_key", refuse("read_key"))
        patch.setitem(sys.modules, SDK, sdk)
        try:
            httpx = importlib.import_module("httpx")
        except ImportError:
            httpx = None
        if httpx is not None:
            for name in ("Client", "AsyncClient"):
                patch.setattr(httpx, name, refuse(f"provider client: httpx.{name}"))
        patch.setattr(urllib.request, "urlopen", refuse("urlopen"))
        patch.setattr(urllib.request.OpenerDirector, "open", refuse("opener"))
        patch.setattr(http.client.HTTPConnection, "connect", refuse("http connect"))
        patch.setattr(socket, "socket", NoSocket)
        patch.setattr(socket, "create_connection", refuse("create_connection"))
        patch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
        patch.setattr(builtins, "open", open_)
        patch.setattr(stdio, "open", open_)
        patch.setattr(os, "open", os_open)
        for path in modes:
            path.chmod(0)
        try:
            yield guard
        finally:
            for path, mode in modes.items():
                path.chmod(mode)


def snapshot(directory: Path) -> dict[str, bytes]:
    """Every file under `directory` (relative path to bytes); {} when absent."""
    if not directory.exists():
        return {}
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
