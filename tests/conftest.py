"""Shared pytest configuration.

Unit tests need no database; tests marked `@pytest.mark.db` are integration tests
and are skipped unless MYSQL_HOST is set in the environment.
"""

import os

import pytest


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
