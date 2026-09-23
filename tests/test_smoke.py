"""The package imports and reports the version pyproject.toml declares.

pyproject.toml reads the version dynamically from `idx_agent.__version__`, so the
package attribute is the single source.
"""

import os
import tomllib
from pathlib import Path

import pytest

import idx_agent

# Repo-root pyproject.toml, located relative to this test file.
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_is_a_non_empty_string():
    """`idx_agent.__version__` is a string with visible content."""
    assert isinstance(idx_agent.__version__, str)
    assert idx_agent.__version__.strip()


def test_pyproject_reads_version_from_the_package():
    """pyproject.toml marks version dynamic and points it at the package attr."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "version" in project["project"]["dynamic"]
    attr = project["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "idx_agent.__version__"


# Placeholder: delete when the first real db-marked test lands (WO-004).
@pytest.mark.db
def test_database_host_is_configured():
    """Runs only when MYSQL_HOST is set (see conftest); proves the db marker works."""
    assert os.environ.get("MYSQL_HOST")
