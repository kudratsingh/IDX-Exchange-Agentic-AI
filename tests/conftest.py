"""Shared pytest configuration; unit tests need no database.

Tests marked `@pytest.mark.db` are integration tests, skipped unless MYSQL_HOST is set.
Every other test runs with the `.env` fallback isolated (`_isolate_env_file`); every
test runs with span export and the log file off (`_no_tracing_or_log_file`).
"""

import os

import pytest

from idx_agent.db import pool as db_pool
from idx_agent.email import settings as email_settings
from idx_agent.enrichment import source_check
from idx_agent.observability import logging as obs_logging
from idx_agent.observability import tracing
from idx_agent.safety import consent


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


@pytest.fixture(autouse=True, scope="session")
def _no_rag_settings_from_dotenv():
    """No served document index, no floor override and no analysis switch reach any
    test from the developer's .env or shell, module-scoped fixtures included (they
    are built before the per-test patches run). Set empty for the whole session: the
    environment beats .env, and an empty value means unset."""
    with pytest.MonkeyPatch.context() as patch:
        for name in ("IDX_RAG_INDEX_DIR", "IDX_RAG_FLOOR_BM25", "IDX_RAG_FLOOR_COSINE"):
            patch.setenv(name, "")
        # The bounded-analysis switch (WO-027) is off unless a test turns it on, so
        # the default tool list, skill list and instructions are what every test sees.
        patch.setenv("IDX_ANALYSIS_TOOL", "")
        yield


@pytest.fixture
def analysis_switch_in_dotenv(monkeypatch):
    """IDX_ANALYSIS_TOOL=1 in `.env` and absent from the process environment: the one
    place install.sh and the tool server both read it (WO-027). An IDX_ANALYSIS_IMAGE
    the environment holds when `.env` is read (CI exports one) is in `.env` too, as
    install.sh requires; other `.env` values are kept as the test would see them."""
    real = db_pool.dotenv_values
    monkeypatch.delenv("IDX_ANALYSIS_TOOL", raising=False)

    def with_switch(path=None):
        image = os.environ.get("IDX_ANALYSIS_IMAGE")
        extra = {} if image is None else {"IDX_ANALYSIS_IMAGE": image}
        return {**real(path), "IDX_ANALYSIS_TOOL": "1", **extra}

    monkeypatch.setattr(db_pool, "dotenv_values", with_switch)


@pytest.fixture(autouse=True)
def _no_tracing_or_log_file(monkeypatch):
    """Every test (db ones too) starts with no span export and no log file.

    Both variables are set empty (the environment beats .env) and the cached
    settings are cleared; a tracing or log-file test sets its own values.
    """
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", "")
    monkeypatch.setenv("IDX_LOG_FILE", "")
    tracing.configure_for_tests(None)
    obs_logging.reset_log_file_settings_for_tests()
    yield
    tracing.configure_for_tests(None)
    obs_logging.reset_log_file_settings_for_tests()


@pytest.fixture(autouse=True)
def paid_consent_dir(monkeypatch, tmp_path_factory):
    """Every test's paid gate reads a fresh temp consent dir, never the real one,
    and starts with no paid run and no lazy server mode. The reader's
    `process_argv` is registered too, so `run_as` changes are undone."""
    directory = tmp_path_factory.mktemp("consent")
    module = consent.reader()
    monkeypatch.setattr(module, "consent_dir", lambda ignore_env=False: directory)
    monkeypatch.setattr(module, "process_argv", module.process_argv)
    consent.reset_for_tests()
    yield directory
    consent.reset_for_tests()


@pytest.fixture(autouse=True)
def _isolate_env_file(request, monkeypatch, tmp_path_factory):
    """Hide the developer's `.env` from every test, so no local value leaks in.

    Points `db.pool._REPO_ROOT` and the working directory at two empty temp dirs.
    Not applied to tests marked `db` (they need the real .env) or `real_env` (an
    opt-out). A test may still chdir or write its own .env; monkeypatch undoes it."""
    node = request.node
    if node.get_closest_marker("db") or node.get_closest_marker("real_env"):
        return
    monkeypatch.setattr(db_pool, "_REPO_ROOT", tmp_path_factory.mktemp("no_env_root"))
    monkeypatch.setattr(email_settings, "ROOT", db_pool._REPO_ROOT)
    monkeypatch.chdir(tmp_path_factory.mktemp("no_env_cwd"))


@pytest.fixture(autouse=True)
def _trusted_sources_per_test(monkeypatch):
    """Every test starts with production's trusted (digest, count) pairs only, in a
    copy that `tests/synthetic_store.py` may add synthetic pairs to (WO-035). The
    production mapping itself stays read-only and is restored after the test."""
    monkeypatch.setattr(
        source_check, "TRUSTED_SOURCES", dict(source_check.TRUSTED_SOURCES)
    )
