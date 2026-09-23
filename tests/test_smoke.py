"""The package imports and reports the version pyproject.toml declares."""

import os
import tomllib
from pathlib import Path

import pytest

import idx_agent

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_is_a_non_empty_string():
    assert isinstance(idx_agent.__version__, str)
    assert idx_agent.__version__.strip()


def test_pyproject_reads_version_from_the_package():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "version" in project["project"]["dynamic"]
    attr = project["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "idx_agent.__version__"


# Placeholder: delete when the first real db-marked test lands (WO-004).
@pytest.mark.db
def test_database_host_is_configured():
    assert os.environ.get("MYSQL_HOST")
