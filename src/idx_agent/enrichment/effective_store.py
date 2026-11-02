"""The private effective-facet store: written offline, opened read-only at search time.

A store that is missing, malformed, from another schema or incomplete is unavailable;
callers then fail closed instead of guessing (WO-021). No listing text is stored.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from idx_agent.db.pool import env_setting
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
    "built_from",
)
_WATERMARK_FORMAT = "%Y-%m-%d %H:%M:%S"


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
        """Listing keys whose every requested facet is present, in key order."""
        wanted = sorted(set(features))
        if not wanted or any(f not in ELIGIBLE_FACETS for f in wanted):
            raise ValueError("features must be a non-empty set of eligible facets")
        marks = ", ".join("?" * len(wanted))
        rows = self._db.execute(
            "SELECT listing_key FROM facets WHERE status = ? AND facet IN "
            f"({marks}) GROUP BY listing_key HAVING COUNT(*) = ? ORDER BY listing_key",
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


def open_store(path: Path | None) -> FacetStore | StoreUnavailable:
    """Open and validate a store read-only, or say why it cannot be used."""
    if path is None:
        return StoreUnavailable("not_configured")
    if not path.is_file():
        return StoreUnavailable("missing")
    try:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return StoreUnavailable("unreadable")
    try:
        meta = dict(db.execute("SELECT name, value FROM meta"))
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise LookupError("schema")
        if any(name not in meta for name in _REQUIRED_META):
            raise LookupError("incomplete")
        datetime.strptime(meta["source_watermark"], _WATERMARK_FORMAT)
        json.loads(meta["built_from"])
        count = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        # The builder records how many results it validated; a store covering fewer
        # listings than that was not built from the certified source.
        if count == 0 or not count == int(meta["listing_count"]) == int(
            meta["source_rows"]
        ):
            raise LookupError("incomplete")
        marks = ", ".join("?" * len(FACET_STATUSES))
        bad = db.execute(
            f"SELECT COUNT(*) FROM facets WHERE status NOT IN ({marks})", FACET_STATUSES
        ).fetchone()[0]
        if bad:
            raise LookupError("malformed")
    except LookupError as exc:
        db.close()
        return StoreUnavailable("schema_mismatch" if str(exc) == "schema" else str(exc))
    except (sqlite3.Error, ValueError, KeyError):
        db.close()
        return StoreUnavailable("malformed")
    info = StoreInfo(
        source_watermark=meta["source_watermark"],
        policy_version=meta["policy_version"],
        rules_version=meta["rules_version"],
        listing_count=count,
    )
    return FacetStore(db, info)
