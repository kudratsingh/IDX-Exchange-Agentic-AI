"""The private effective-facet store: written offline, opened read-only at search time.

A store that is missing, malformed, from another schema or source, or incomplete is
unavailable; callers then fail closed instead of guessing (WO-021). No listing text is
stored.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from idx_agent.db.pool import env_setting
from idx_agent.enrichment import source_check, store_v5
from idx_agent.enrichment.effective import (
    ELIGIBLE_FACETS,
    FACET_STATUSES,
    MATCHING_STATUS,
)

SCHEMA_VERSION = "1"
STORE_SETTING = "IDX_ENRICHMENT_STORE"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REQUIRED_META = (
    "schema_version",
    "source_watermark",
    "policy_version",
    "rules_version",
    "listing_count",
    "source_rows",
    "results_digest",
    "built_from",
)
_WATERMARK_FORMAT = "%Y-%m-%d %H:%M:%S"
# The last store that passed validation, by file identity, so an unchanged file is not
# re-scanned on every search. A replaced or edited file has another identity. A file
# modified this recently is not cached: coarse file clocks could hide a second edit.
_RECENT_NS = 2_000_000_000
_validated: dict[tuple, StoreInfo] = {}
_validated_guard = threading.Lock()


@dataclass(frozen=True)
class StoreInfo:
    """What a store was built from: provenance shown with every applied filter."""

    source_watermark: str
    policy_version: str
    rules_version: str
    listing_count: int


@dataclass(frozen=True)
class StoreUnavailable:
    """Why no store can be used; `reason` is a fixed code, never file contents."""

    reason: str


def configured_store_path(environ: Mapping[str, str] | None = None) -> Path | None:
    """IDX_ENRICHMENT_STORE as a path; a relative one resolves from the repo root."""
    value = (env_setting(STORE_SETTING, environ) or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else _REPO_ROOT / path


def write_store(
    path: Path, rows: Iterable[tuple[str, Mapping[str, str]]], meta: Mapping
):
    """Write a store atomically with owner-only permissions; return listings written.

    Rows are (listing_key, {facet: status}); every key is recorded as covered.
    """
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    count = 0
    db = sqlite3.connect(tmp)
    try:
        db.executescript(
            """
            CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE listings (listing_key TEXT PRIMARY KEY);
            CREATE TABLE facets (
                listing_key TEXT NOT NULL REFERENCES listings(listing_key),
                facet TEXT NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY (listing_key, facet)
            );
            CREATE INDEX facets_by_status ON facets (facet, status, listing_key);
            """
        )
        for key, statuses in rows:
            db.execute("INSERT INTO listings VALUES (?)", (key,))
            for facet, status in sorted(statuses.items()):
                if facet not in ELIGIBLE_FACETS or status not in FACET_STATUSES:
                    raise ValueError("ineligible facet or unknown status")
                db.execute("INSERT INTO facets VALUES (?,?,?)", (key, facet, status))
            count += 1
        values = dict(meta, schema_version=SCHEMA_VERSION, listing_count=str(count))
        for name, value in values.items():
            db.execute("INSERT INTO meta VALUES (?,?)", (name, str(value)))
        db.commit()
    finally:
        db.close()
    os.replace(tmp, path)
    return count


class FacetStore:
    """A validated, read-only store. Open it with `open_store`, never directly."""

    def __init__(self, db: sqlite3.Connection, info: StoreInfo):
        self._db = db
        self.info = info

    def keys_with_all(self, features: Sequence[str]) -> list[str]:
        """Listing keys whose every requested facet is present, in key order.

        Distinct facets are counted, so a repeated row never stands in for another
        facet (validation also refuses a store with repeated rows).
        """
        wanted = sorted(set(features))
        if not wanted or any(f not in ELIGIBLE_FACETS for f in wanted):
            raise ValueError("features must be a non-empty set of eligible facets")
        marks = ", ".join("?" * len(wanted))
        rows = self._db.execute(
            "SELECT listing_key FROM facets WHERE status = ? AND facet IN "
            f"({marks}) GROUP BY listing_key HAVING COUNT(DISTINCT facet) = ? "
            "ORDER BY listing_key",
            (MATCHING_STATUS, *wanted, len(wanted)),
        )
        return [key for (key,) in rows]

    def statuses(self, key: str) -> dict[str, str]:
        """Every known facet status for one listing; an uncovered key gives {}."""
        rows = self._db.execute(
            "SELECT facet, status FROM facets WHERE listing_key = ?", (str(key),)
        )
        return dict(rows)

    def covered_keys(self) -> list[str]:
        """Every listing key the store covers, in key order (refresh preflight)."""
        rows = self._db.execute("SELECT listing_key FROM listings ORDER BY listing_key")
        return [key for (key,) in rows]

    def close(self) -> None:
        self._db.close()


def _identity(path: Path) -> tuple:
    """Path, inode, size, change times and SQLite's change counter (header bytes
    24-27, bumped by every committed write in the store's rollback-journal mode)."""
    st = path.stat()
    with path.open("rb") as fh:
        counter = fh.read(28)[24:28]
    return (
        str(path.resolve()),
        st.st_ino,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
        counter,
    )


def open_store(path: Path | None) -> FacetStore | StoreUnavailable:
    """Open and validate a store read-only, or say why it cannot be used.

    A file identical to the last one that validated is opened without re-scanning.
    """
    if path is None:
        return StoreUnavailable("not_configured")
    if not path.is_file():
        return StoreUnavailable("missing")
    try:
        before = _identity(path)
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (OSError, sqlite3.Error):
        return StoreUnavailable("unreadable")
    with _validated_guard:
        known = _validated.get(before)
    if known is not None and _same_file(path, before):
        return FacetStore(db, known)
    checked = _validate(db)
    settled = time.time_ns() - max(before[3], before[4]) > _RECENT_NS
    if isinstance(checked, StoreInfo) and settled and _same_file(path, before):
        with _validated_guard:
            _validated.clear()
            _validated[before] = checked
    return checked if isinstance(checked, StoreUnavailable) else FacetStore(db, checked)


def _same_file(path: Path, before: tuple) -> bool:
    """True when the file still has the identity it had before it was opened."""
    try:
        return _identity(path) == before
    except OSError:
        return False


def _validate(db: sqlite3.Connection) -> StoreInfo | StoreUnavailable:
    """Check an opened store; close it and say why when it cannot be used."""
    try:
        meta = dict(db.execute("SELECT name, value FROM meta"))
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise LookupError("schema")
        if any(name not in meta for name in _REQUIRED_META):
            raise LookupError("incomplete")
        # Built from the approved original results, never another source (WO-021),
        # and covering exactly the count trusted for them (WO-035).
        trusted = source_check.trusted_source_rows(meta["results_digest"])
        if trusted is None:
            raise LookupError("source_mismatch")
        datetime.strptime(meta["source_watermark"], _WATERMARK_FORMAT)
        json.loads(meta["built_from"])
        try:
            # A v5 store must carry consistent v5 provenance; a v4 one passes as before.
            store_v5.check_store_provenance(meta)
        except ValueError:
            raise LookupError("provenance_mismatch") from None
        count = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        # The builder records how many results it validated; a store covering fewer
        # listings than that was not built from the certified source.
        if count == 0 or not count == int(meta["listing_count"]) == int(
            meta["source_rows"]
        ):
            raise LookupError("incomplete")
        # A store carrying the approved digest with any other count was not built from
        # the approved source, however consistent its own counts are (WO-035).
        if count != trusted:
            raise LookupError("source_count_mismatch")
        marks = ", ".join("?" * len(FACET_STATUSES))
        bad = db.execute(
            f"SELECT COUNT(*) FROM facets WHERE status NOT IN ({marks})", FACET_STATUSES
        ).fetchone()[0]
        if bad:
            raise LookupError("malformed")
        # One status per (listing, facet): the builder's primary key guarantees it, but
        # a store built without it could widen a request or pick a status arbitrarily.
        repeated = db.execute(
            "SELECT 1 FROM facets GROUP BY listing_key, facet HAVING COUNT(*) > 1 "
            "LIMIT 1"
        ).fetchone()
        if repeated:
            raise LookupError("malformed")
    except LookupError as exc:
        db.close()
        return StoreUnavailable("schema_mismatch" if str(exc) == "schema" else str(exc))
    except (sqlite3.Error, ValueError, KeyError):
        db.close()
        return StoreUnavailable("malformed")
    return StoreInfo(
        source_watermark=meta["source_watermark"],
        policy_version=meta["policy_version"],
        rules_version=meta["rules_version"],
        listing_count=count,
    )
