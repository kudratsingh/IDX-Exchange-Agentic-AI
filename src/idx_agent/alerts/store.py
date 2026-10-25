"""Private SQLite writer with isolated buckets, caps and transactional confirmation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from idx_agent.domain.alerts import SavedSearch
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.safety.approval import ROOT, ApprovalRefused, ignored

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, bucket TEXT NOT NULL, "
    "filters TEXT NOT NULL, created TEXT NOT NULL, checked TEXT NOT NULL, "
    "last_alert TEXT, keys TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS confirmations (bucket TEXT NOT NULL, "
    "action TEXT NOT NULL, "
    "target TEXT NOT NULL, digest TEXT NOT NULL, expires TEXT NOT NULL, "
    "PRIMARY KEY (bucket, action, target))",
    "CREATE TABLE IF NOT EXISTS alerts (search_id TEXT NOT NULL, as_of TEXT NOT NULL, "
    "draft_id TEXT NOT NULL, PRIMARY KEY (search_id, as_of))",
)


class AlertStore:
    def __init__(
        self,
        path: Path,
        *,
        data_root: Path = ROOT / "data",
        is_ignored: Callable[[Path], bool] = ignored,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.path = Path(path).absolute()
        self.data_root = Path(data_root).resolve()
        self.clock = clock
        if (
            self.path.is_symlink()
            or not self.path.resolve().is_relative_to(self.data_root)
            or not is_ignored(self.path)
        ):
            raise ApprovalRefused("unsafe_store")
        self.path = self.path.resolve()

    @contextmanager
    def transaction(self, *, write=False) -> Iterator[sqlite3.Connection | None]:
        path = self.path
        if path.is_symlink() or path.resolve() != path:
            raise ApprovalRefused("unsafe_store")
        if not write and not path.exists():
            yield None
            return
        if write:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.parent.resolve() != path.parent:
                raise ApprovalRefused("unsafe_store")
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
        conn = sqlite3.connect(
            path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            if write:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("BEGIN IMMEDIATE")
                for statement in SCHEMA:
                    conn.execute(statement)
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _model(row) -> SavedSearch:
        return SavedSearch(
            id=row["id"],
            sender_key=row["bucket"],
            filters=PropertySearchFilters.model_validate_json(row["filters"]),
            created_at=datetime.fromisoformat(row["created"]),
            checked_as_of=date.fromisoformat(row["checked"]),
            last_alert_as_of=date.fromisoformat(row["last_alert"])
            if row["last_alert"]
            else None,
            alerted_keys=json.loads(row["keys"]),
        )

    def rows(self, conn, key=None) -> list[SavedSearch]:
        if conn is None:
            return []
        sql = (
            "SELECT id, bucket, filters, created, checked, last_alert, keys "
            "FROM searches"
        )
        params = ()
        if key is not None:
            sql += " WHERE bucket = ?"
            params = (key,)
        sql += " ORDER BY rowid LIMIT 201"
        return [self._model(row) for row in conn.execute(sql, params)]

    def list_searches(self, key: str) -> list[SavedSearch]:
        with self.transaction() as conn:
            return self.rows(conn, key)

    def all_searches(self) -> list[SavedSearch]:
        with self.transaction() as conn:
            return self.rows(conn)

    def add(self, key: str, filters: PropertySearchFilters, as_of: date) -> SavedSearch:
        filters = filters.model_copy(
            update={"page": 1, "limit": min(filters.limit, 10)}
        )
        with self.transaction(write=True) as conn:
            own = self.rows(conn, key)
            if len(own) >= 5 or len(self.rows(conn)) >= 200:
                raise ApprovalRefused("too_many_saved")
            search = SavedSearch(
                id=secrets.token_hex(16),
                sender_key=key,
                filters=filters,
                created_at=self.clock(),
                checked_as_of=as_of,
            )
            conn.execute(
                "INSERT INTO searches (id, bucket, filters, created, checked, keys) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    search.id,
                    key,
                    filters.model_dump_json(),
                    search.created_at.isoformat(),
                    as_of.isoformat(),
                    "[]",
                ),
            )
            return search

    def issue_code(self, key: str, action: str, target: str) -> str:
        code = secrets.token_hex(4)
        with self.transaction(write=True) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO confirmations "
                "(bucket, action, target, digest, expires) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    key,
                    action,
                    target,
                    hashlib.sha256(code.encode()).hexdigest(),
                    (self.clock() + timedelta(minutes=10)).isoformat(),
                ),
            )
        return code

    def remove(self, key: str, action: str, target: str, code: str, gate) -> int:
        """Confirm and expire drafts before deleting; gate failure rolls SQLite back."""
        with self.transaction(write=True) as conn:
            row = conn.execute(
                "SELECT digest, expires FROM confirmations "
                "WHERE bucket = ? AND action = ? AND target = ?",
                (key, action, target),
            ).fetchone()
            if (
                not row
                or self.clock() >= datetime.fromisoformat(row["expires"])
                or not hmac.compare_digest(
                    row["digest"], hashlib.sha256(code.encode()).hexdigest()
                )
            ):
                raise ApprovalRefused("invalid_confirmation")
            wanted = [
                s for s in self.rows(conn, key) if action == "forget" or s.id == target
            ]
            gate.expire_idempotency_prefixes([f"alert:{s.id}:" for s in wanted])
            for search in wanted:
                conn.execute("DELETE FROM alerts WHERE search_id = ?", (search.id,))
                conn.execute(
                    "DELETE FROM searches WHERE id = ? AND bucket = ?", (search.id, key)
                )
            if action == "forget":
                conn.execute("DELETE FROM confirmations WHERE bucket = ?", (key,))
            else:
                conn.execute(
                    "DELETE FROM confirmations WHERE bucket = ? "
                    "AND action = ? AND target = ?",
                    (key, action, target),
                )
            return len(wanted)


def configured_store() -> AlertStore:
    # Writer-only setting. Never add this name to db.pool's fallback allowlist.
    from idx_agent.email.settings import ROOT as settings_root

    value = os.environ.get("IDX_ALERTS_DB_PATH")
    if value is None:
        try:
            for line in (settings_root / ".env").read_text().splitlines():
                name, sep, candidate = (
                    line.strip().removeprefix("export ").partition("=")
                )
                if sep and name.strip() == "IDX_ALERTS_DB_PATH":
                    value = candidate.strip().strip("\"'")
                    break
        except OSError:
            pass
    path = Path(value or ROOT / "data/state/alerts.sqlite")
    return AlertStore(path if path.is_absolute() else ROOT / path)
