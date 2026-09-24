"""Connection settings from the environment and a connection factory (WO-004).

`DbConfig.from_env()` reads MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER and
MYSQL_PASSWORD from the environment, with the gitignored `.env` filling any gaps.
`connect()` returns a pymysql connection with dict rows, reader user only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pymysql
import pymysql.cursors
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "READER_USER",
    "DbConfig",
    "ReaderOnlyError",
    "connect",
    "database_configured",
    "dotenv_values",
]

# The SELECT-only MySQL user created in WO-002; no other user may connect.
READER_USER = "idx_reader"
# Seconds to wait for a connection, then for a query's rows. Together they stay
# under the 30 s MCP request timeout, so a slow database is an error, not a hang.
CONNECT_TIMEOUT_S = 10
READ_TIMEOUT_S = 15
# The checkout root (src/idx_agent/db/pool.py -> three levels up); its .env is the
# fallback when the working directory has none.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def dotenv_values(path: Path | None = None) -> dict[str, str]:
    """Return the MYSQL_* settings in a .env file; {} when there is no readable file.

    Default file: `<cwd>/.env` if it exists, else `<repo root>/.env`. Lines are
    KEY=VALUE (an `export ` prefix is allowed); comments, blanks, and other keys are
    skipped; quotes around a value are stripped. Values are never logged or printed.
    """
    if path is None:
        local = Path.cwd() / ".env"
        path = local if local.is_file() else _REPO_ROOT / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    # Same rules as scripts/profile_data.py load_env; the first value for a key wins.
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if key.startswith("MYSQL_"):
            values.setdefault(key, value.strip().strip("\"'"))
    return values


def _mysql_settings(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """MYSQL_* from `environ` (default: os.environ), gaps filled from .env.

    A key present in the environment wins even when empty, so MYSQL_HOST=""
    switches the database off whatever .env says.
    """
    env = os.environ if environ is None else environ
    merged = dotenv_values()
    merged.update({k: v for k, v in env.items() if k.startswith("MYSQL_")})
    return merged


class ReaderOnlyError(RuntimeError):
    """Raised when the configured database user is not the SELECT-only reader."""


class DbConfig(BaseModel):
    """Connection settings: host, port, database, user, password (hidden from repr).

    Frozen; input values are kept out of validation errors so the password never
    appears in a traceback or a log line.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    host: str
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = "idx_exchange"
    user: str = READER_USER
    password: str = Field(default="", repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DbConfig:
        """Build settings from MYSQL_* in `environ` (default: os.environ), then .env.

        Defaults follow .env.example (localhost, 3306, idx_exchange, idx_reader);
        the password has no default and is empty when unset.
        """
        env = _mysql_settings(environ)
        return cls(
            host=env.get("MYSQL_HOST") or "localhost",
            port=int(env.get("MYSQL_PORT") or 3306),
            database=env.get("MYSQL_DATABASE") or "idx_exchange",
            user=env.get("MYSQL_USER") or READER_USER,
            password=env.get("MYSQL_PASSWORD") or "",
        )


def database_configured() -> bool:
    """True when MYSQL_HOST is non-empty in the environment or, if unset there, .env."""
    return bool(_mysql_settings().get("MYSQL_HOST"))


def connect(config: DbConfig | None = None) -> Any:
    """Open a pymysql connection (DictCursor, autocommit, read-only session).

    Uses `DbConfig.from_env()` when no config is given. Raises ReaderOnlyError,
    without opening a connection, when the user is not READER_USER.
    """
    config = config or DbConfig.from_env()
    if config.user != READER_USER:
        raise ReaderOnlyError(f"only the {READER_USER} user may connect")
    # The session is also marked read-only, a second guard beside the SELECT-only
    # grants: a write fails here even if the grants were ever widened.
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=CONNECT_TIMEOUT_S,
        read_timeout=READ_TIMEOUT_S,
        init_command="SET SESSION TRANSACTION READ ONLY",
    )
