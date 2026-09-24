"""Shared pytest configuration.

Unit tests need no database; tests marked `@pytest.mark.db` are integration tests
and are skipped unless MYSQL_HOST is set in the environment. Every other test runs
with the `.env` fallback isolated (see `_isolate_env_file`).
"""

import os

import pytest

from idx_agent.db import pool as db_pool


def pytest_configure(config):
    """Register the `real_env` marker (`db` is registered in pyproject.toml)."""
    config.addinivalue_line(
        "markers",
        "real_env: keep the real .env fallback (repo root and working directory)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `db` when no database host is configured.

    pytest hook run after collection: if MYSQL_HOST is unset, every collected
    item carrying the `db` marker gets a skip marker with the reason.
    """
    if os.environ.get("MYSQL_HOST"):
        return
    skip_db = pytest.mark.skip(reason="MYSQL_HOST is unset; no database available")
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip_db)


@pytest.fixture(autouse=True)
def _isolate_env_file(request, monkeypatch, tmp_path_factory):
    """Hide the developer's `.env` from every test, so no local value leaks in.

    Points `db.pool._REPO_ROOT` and the working directory at two empty temp dirs.
    Not applied to tests marked `db` (they need the real .env) or `real_env` (an
    opt-out). A test may still chdir or write its own .env; monkeypatch undoes it.
    """
    node = request.node
    if node.get_closest_marker("db") or node.get_closest_marker("real_env"):
        return
    monkeypatch.setattr(db_pool, "_REPO_ROOT", tmp_path_factory.mktemp("no_env_root"))
    monkeypatch.chdir(tmp_path_factory.mktemp("no_env_cwd"))
