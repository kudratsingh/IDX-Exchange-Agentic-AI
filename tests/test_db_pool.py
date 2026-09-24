"""Unit tests for db/pool.py and db/asof.py; no database (a fake connection stands in).

Covers settings from the environment and .env, the reader-only refusal before
connecting, and the as-of reader's SQL, parsing, and cache. The real .env is never
read: each test runs in an empty temporary directory.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pymysql
import pytest

from idx_agent.db import asof, pool
from idx_agent.db.pool import READER_USER, DbConfig, ReaderOnlyError

# An invented, low-entropy value used only to check that it never shows in a repr.
FAKE_PASSWORD = "testonly" * 3


class FakeCursor:
    """Records each execute call and returns queued rows from fetchone/fetchall."""

    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.conn.calls.append((sql, tuple(params)))

    def fetchone(self) -> dict[str, Any] | None:
        return self.conn.rows.pop(0)


class FakeConnection:
    """Stands in for a pymysql connection: `rows` are returned in order."""

    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


@pytest.fixture(autouse=True)
def _fresh_asof_cache():
    """Each test starts and ends with an empty as-of cache."""
    asof.clear_asof_cache()
    yield
    asof.clear_asof_cache()


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch, tmp_path):
    """Run in an empty temp dir with the repo-root fallback pointed there too,
    and no MYSQL_* in the environment, so the checkout's .env is never read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pool, "_REPO_ROOT", tmp_path / "no-repo")
    for key in ("HOST", "PORT", "DATABASE", "USER", "PASSWORD"):
        monkeypatch.delenv(f"MYSQL_{key}", raising=False)


def _write_env(directory: Path, *lines: str) -> Path:
    """Write invented lines to `directory/.env` and return its path."""
    path = directory / ".env"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- pool.py: .env fallback ---


def test_dotenv_values_reads_only_mysql_keys_and_strips_quotes(tmp_path):
    path = _write_env(
        tmp_path,
        "# a comment",
        "",
        'MYSQL_HOST="db.dotenv.test"',
        "export MYSQL_PORT='3308'",
        "MYSQL_DATABASE = idx_test ",
        "OTHER_SETTING=ignored",
        "not a setting line",
    )
    assert pool.dotenv_values(path) == {
        "MYSQL_HOST": "db.dotenv.test",
        "MYSQL_PORT": "3308",
        "MYSQL_DATABASE": "idx_test",
    }


def test_dotenv_values_missing_file_is_empty(tmp_path):
    assert pool.dotenv_values(tmp_path / "absent.env") == {}
    assert pool.dotenv_values() == {}  # no .env in cwd or at the (fake) repo root


def test_dotenv_values_default_prefers_cwd_then_repo_root(tmp_path):
    root = tmp_path / "no-repo"
    root.mkdir()
    _write_env(root, "MYSQL_HOST=root.test")
    assert pool.dotenv_values() == {"MYSQL_HOST": "root.test"}
    _write_env(tmp_path, "MYSQL_HOST=cwd.test")
    assert pool.dotenv_values() == {"MYSQL_HOST": "cwd.test"}


def test_environment_wins_and_dotenv_fills_the_gaps(tmp_path, monkeypatch):
    _write_env(
        tmp_path,
        "MYSQL_HOST=file-host.test",
        "MYSQL_DATABASE=idx_from_file",
        f"MYSQL_PASSWORD={FAKE_PASSWORD}",
    )
    monkeypatch.setenv("MYSQL_HOST", "env-host.test")
    config = DbConfig.from_env()
    assert config.host == "env-host.test"
    assert config.database == "idx_from_file"
    assert config.password == FAKE_PASSWORD
    # A given mapping is treated like the environment.
    assert DbConfig.from_env({"MYSQL_DATABASE": "idx_given"}).database == "idx_given"


def test_database_configured_uses_dotenv_when_the_environment_is_silent(
    tmp_path, monkeypatch
):
    assert pool.database_configured() is False
    _write_env(tmp_path, "MYSQL_HOST=localhost")
    assert pool.database_configured() is True
    # Set in the environment, even empty, it wins over the file.
    monkeypatch.setenv("MYSQL_HOST", "")
    assert pool.database_configured() is False


def test_reading_settings_prints_nothing(tmp_path, capsys):
    _write_env(tmp_path, "MYSQL_HOST=quiet.test", f"MYSQL_PASSWORD={FAKE_PASSWORD}")
    pool.dotenv_values()
    DbConfig.from_env()
    pool.database_configured()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


# --- pool.py ---


def test_from_env_defaults_follow_env_example():
    config = DbConfig.from_env({})
    assert config.host == "localhost"
    assert config.port == 3306
    assert config.database == "idx_exchange"
    assert config.user == READER_USER
    assert config.password == ""


def test_from_env_reads_every_variable():
    env = {
        "MYSQL_HOST": "db.internal.test",
        "MYSQL_PORT": "3307",
        "MYSQL_DATABASE": "idx_test",
        "MYSQL_USER": READER_USER,
        "MYSQL_PASSWORD": FAKE_PASSWORD,
    }
    config = DbConfig.from_env(env)
    assert (config.host, config.port, config.database) == (
        "db.internal.test",
        3307,
        "idx_test",
    )
    assert config.password == FAKE_PASSWORD


def test_from_env_uses_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "env-host.test")
    monkeypatch.setenv("MYSQL_PASSWORD", FAKE_PASSWORD)
    assert DbConfig.from_env().host == "env-host.test"


def test_password_is_not_in_repr_or_str():
    config = DbConfig(host="localhost", password=FAKE_PASSWORD)
    assert FAKE_PASSWORD not in repr(config)
    assert FAKE_PASSWORD not in str(config)


def test_config_is_frozen():
    config = DbConfig(host="localhost")
    with pytest.raises(ValueError):
        config.user = "root"


def test_database_configured_follows_mysql_host(monkeypatch):
    monkeypatch.delenv("MYSQL_HOST", raising=False)
    assert pool.database_configured() is False
    monkeypatch.setenv("MYSQL_HOST", "")
    assert pool.database_configured() is False
    monkeypatch.setenv("MYSQL_HOST", "localhost")
    assert pool.database_configured() is True


@pytest.mark.parametrize("user", ["root", "idx_admin", "IDX_READER", ""])
def test_non_reader_user_is_refused_before_connecting(monkeypatch, user):
    def must_not_connect(**kwargs: Any) -> None:
        raise AssertionError("pymysql.connect was called for a non-reader user")

    monkeypatch.setattr(pymysql, "connect", must_not_connect)
    config = DbConfig(host="localhost", user=user, password=FAKE_PASSWORD)
    with pytest.raises(ReaderOnlyError) as info:
        pool.connect(config)
    assert FAKE_PASSWORD not in str(info.value)


def test_non_reader_user_from_env_is_refused(monkeypatch):
    monkeypatch.setattr(pymysql, "connect", lambda **kw: pytest.fail("connected"))
    monkeypatch.setenv("MYSQL_HOST", "localhost")
    monkeypatch.setenv("MYSQL_USER", "root")
    with pytest.raises(ReaderOnlyError):
        pool.connect()


def test_reader_connect_passes_dict_cursor_and_timeouts(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> str:
        seen.update(kwargs)
        return "connection"

    monkeypatch.setattr(pymysql, "connect", fake_connect)
    config = DbConfig(host="localhost", password=FAKE_PASSWORD)
    assert pool.connect(config) == "connection"
    assert seen["user"] == READER_USER
    assert seen["cursorclass"] is pymysql.cursors.DictCursor
    assert seen["autocommit"] is True
    assert seen["read_timeout"] == pool.READ_TIMEOUT_S == 15
    # Connect plus read stays under the 30 s MCP request timeout.
    assert seen["connect_timeout"] + seen["read_timeout"] < 30
    assert "READ ONLY" in seen["init_command"]


# --- asof.py ---


def test_read_asof_dates_parses_text_and_bounds_sold_by_active():
    conn = FakeConnection(
        [{"active_max": "2026-09-18 21:04:11"}, {"sold_max": "2026-09-17"}]
    )
    dates = asof.read_asof_dates(conn)
    assert dates.active == date(2026, 9, 18)
    assert dates.sold == date(2026, 9, 17)
    (active_sql, active_params), (sold_sql, sold_params) = conn.calls
    assert "ModificationTimestamp" in active_sql and active_params == ()
    assert "close_date_d <= %s" in sold_sql
    assert sold_params == (date(2026, 9, 18),)
    assert "*" not in active_sql + sold_sql


def test_read_asof_dates_accepts_driver_date_objects():
    conn = FakeConnection(
        [{"active_max": datetime(2026, 9, 18, 8, 0)}, {"sold_max": date(2026, 9, 17)}]
    )
    assert asof.read_asof_dates(conn).sold == date(2026, 9, 17)


@pytest.mark.parametrize("bad", [None, "0000-00-00 00:00:00", "not a date"])
def test_read_asof_dates_refuses_an_unusable_date(bad):
    conn = FakeConnection([{"active_max": bad}, {"sold_max": "2026-09-17"}])
    with pytest.raises(RuntimeError, match="active"):
        asof.read_asof_dates(conn)


def test_get_asof_dates_caches_until_cleared():
    rows = [{"active_max": "2026-09-18"}, {"sold_max": "2026-09-17"}]
    conn = FakeConnection(rows * 2)
    first = asof.get_asof_dates(conn)
    assert asof.get_asof_dates(conn) is first
    assert len(conn.calls) == 2
    asof.clear_asof_cache()
    asof.get_asof_dates(conn)
    assert len(conn.calls) == 4
