"""Shared pytest configuration."""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `db` when no database host is configured."""
    if os.environ.get("MYSQL_HOST"):
        return
    skip_db = pytest.mark.skip(reason="MYSQL_HOST is unset; no database available")
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip_db)
