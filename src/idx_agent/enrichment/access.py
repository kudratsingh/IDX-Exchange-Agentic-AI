"""Shared access to the effective-facet store for every feature consumer (WO-023).

Search, badges, recommendation explanations and saved-search alerts read remark
features only through `FeatureAccess`, so they agree on one rule set (below).
"""

# The rules:
# - Only an eligible facet whose effective status is `present` qualifies.
# - A missing label is unknown, never false; a never-extracted listing has no features.
# - Uncertain, planned, historical, stated-absent and contradictory never qualify.
# - A listing with any row changed after the snapshot, or with no recorded change time,
#   has no usable features (its description may have changed).
# - More than `STALE_SHARE` of active listings changed since the snapshot: stale.
# - An unconfigured, missing, unreadable, malformed, incomplete or other-source store
#   is unavailable. Stale and unavailable fail closed: callers refuse or show nothing,
#   and never widen a request by dropping its features. Nothing here reads listing text.

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from idx_agent.db import listings as db_listings
from idx_agent.enrichment import effective_store
from idx_agent.enrichment.effective import ELIGIBLE_FACETS, MATCHING_STATUS

__all__ = [
    "AREA_FACETS",
    "FRESHNESS_TTL_SECONDS",
    "LIMITATION",
    "STALE_SHARE",
    "Binding",
    "FeatureAccess",
    "FeatureLookup",
    "Readiness",
    "ordered",
    "present_in",
    "reset_for_tests",
    "snapshot_freshness",
]

LIMITATION = (
    "Features come from listing descriptions, checked against a review policy. A small "
    "share are estimated to be wrong, and a home not matched may still have the "
    "feature: a missing feature is unknown, not absent."
)
# More than this share of active listings changed since the snapshot: stale.
STALE_SHARE = 0.10
# The snapshot freshness counts (a full table scan) are reused for this long; the
# per-listing change test still runs for every key a consumer uses.
FRESHNESS_TTL_SECONDS = 60.0
# Facets that describe the surroundings rather than the home itself.
AREA_FACETS = frozenset({"near_grocery_mentioned", "near_transit_mentioned"})

_freshness: dict[str, tuple[float, tuple[int, int]]] = {}
_freshness_guard = threading.Lock()

Status = Literal["usable", "unavailable", "stale"]
Outcome = Literal["applied", "unavailable", "stale"]


def reset_for_tests() -> None:
    """Forget cached freshness counts (tests and the eval runner only)."""
    with _freshness_guard:
        _freshness.clear()


def snapshot_freshness(watermark: str, conn: Any) -> tuple[int, int]:
    """(active listings, changed since the snapshot), reused for a short window."""
    now = time.monotonic()
    with _freshness_guard:
        hit = _freshness.get(watermark)
    if hit is not None and now - hit[0] < FRESHNESS_TTL_SECONDS:
        return hit[1]
    counts = db_listings.fetch_freshness(watermark, conn)
    with _freshness_guard:
        _freshness.clear()
        _freshness[watermark] = (now, counts)
    return counts


def present_in(
    statuses: dict[str, str], facets: Collection[str] = ELIGIBLE_FACETS
) -> frozenset[str]:
    """Eligible facets among `facets` whose effective status is present."""
    return frozenset(
        f
        for f, s in statuses.items()
        if s == MATCHING_STATUS and f in ELIGIBLE_FACETS and f in facets
    )


@dataclass(frozen=True)
class Readiness:
    """Whether the store can be used now, with its provenance when it opened."""

    status: Status
    reason: str | None = None
    info: effective_store.StoreInfo | None = None
    active: int | None = None
    changed: int | None = None

    @property
    def usable(self) -> bool:
        return self.status == "usable"


@dataclass(frozen=True)
class Binding:
    """A feature request bound for SQL, or why it was refused; never widened."""

    # Check `refused` first. `applied` with a scope: listings with every feature
    # present, as a `db_listings.FeatureScope` whose SQL also leaves out listings
    # changed since the snapshot. `applied` without a scope: no listing has every
    # feature present, so match nothing. `unavailable` (an unusable store, `closed`,
    # or `too_broad` when too many keys match to bind) and `stale`: refuse, and never
    # run the request without its features.

    status: Outcome
    readiness: Readiness
    scope: db_listings.FeatureScope | None = None
    reason: str | None = None
    # Store keys with every feature present, before the too-broad check (for logs).
    matched: int = 0

    @property
    def refused(self) -> bool:
        return self.status != "applied"

    @property
    def matches_nothing(self) -> bool:
        return self.status == "applied" and self.scope is None

    @property
    def info(self) -> effective_store.StoreInfo | None:
        return self.readiness.info


@dataclass(frozen=True)
class FeatureLookup:
    """Per-key present features, and which of the asked keys changed since the
    snapshot (any row, or no change time); changed keys have no features."""

    present: dict[str, frozenset[str]]
    changed: frozenset[str]


class FeatureAccess:
    """One consumer's use of the store: open lazily, check once, always close.

    Use as a context manager, one per call or batch run. `readiness(conn)` opens the
    store and checks freshness (`bind` does so itself); other reads raise without it.
    """

    # After `close()` an access cannot be reused: `open()` and `readiness()` report
    # unavailable ("closed", keeping the provenance) and every read raises.

    def __init__(
        self,
        path: Path | None = None,
        *,
        opener: Callable[
            [Path | None], effective_store.FacetStore | effective_store.StoreUnavailable
        ]
        | None = None,
    ) -> None:
        self._path = path
        self._opener = opener
        self._store: effective_store.FacetStore | None = None
        self._readiness: Readiness | None = None
        self._closed = False

    @classmethod
    def configured(cls) -> FeatureAccess:
        """Access to the store named by IDX_ENRICHMENT_STORE (or none)."""
        return cls(effective_store.configured_store_path())

    def __enter__(self) -> FeatureAccess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
        info = self._readiness.info if self._readiness is not None else None
        self._readiness = Readiness("unavailable", reason="closed", info=info)
        self._closed = True

    def open(self) -> Readiness:
        """Open and validate the store without any database read."""
        if self._readiness is not None:
            return self._readiness
        # Looked up at call time, so a replaced opener (tests) is honoured.
        opener = self._opener or effective_store.open_store
        opened = opener(self._path)
        if isinstance(opened, effective_store.StoreUnavailable):
            self._readiness = Readiness("unavailable", reason=opened.reason)
        else:
            self._store = opened
            self._readiness = Readiness("usable", info=opened.info)
        return self._readiness

    def readiness(self, conn: Any) -> Readiness:
        """Open the store, then check the snapshot against the active listings."""
        first = self.open()
        if first.status != "usable" or first.active is not None:
            return first
        assert first.info is not None
        total, changed = snapshot_freshness(first.info.source_watermark, conn)
        stale = total == 0 or changed / total > STALE_SHARE
        self._readiness = Readiness(
            "stale" if stale else "usable",
            reason="stale" if stale else None,
            info=first.info,
            active=total,
            changed=changed,
        )
        return self._readiness

    def _usable(self) -> effective_store.FacetStore:
        if self._closed:
            raise RuntimeError("feature access is closed; use a new FeatureAccess")
        if (
            self._store is None
            or self._readiness is None
            or self._readiness.status != "usable"
            or self._readiness.active is None
        ):
            raise RuntimeError("check readiness(conn) before reading features")
        return self._store

    def bind(self, features: Sequence[str], conn: Any) -> Binding:
        """Check readiness, then bind the features as a scope for listing SQL.

        The one decision for every consumer that filters listings by features
        (search, saved-search alerts); see `Binding`. Bad features: ValueError.
        """
        ready = self.readiness(conn)
        if not ready.usable:
            return Binding(ready.status, ready, reason=ready.reason)
        assert ready.info is not None
        keys = self._usable().keys_with_all(features)
        if len(keys) > db_listings.MAX_FEATURE_KEYS:
            return Binding("unavailable", ready, reason="too_broad", matched=len(keys))
        if not keys:
            return Binding("applied", ready)
        scope = db_listings.FeatureScope(
            keys=tuple(keys), watermark=ready.info.source_watermark
        )
        return Binding("applied", ready, scope=scope, matched=len(keys))

    def lookup(
        self,
        keys: Iterable[int | str],
        conn: Any,
        facets: Collection[str] = ELIGIBLE_FACETS,
    ) -> FeatureLookup:
        """Present features for up to 50 keys still as at the snapshot, plus which
        of them changed since (left out). A key never extracted, or with no
        qualifying feature, is left out too. Keys come back as strings.
        """
        store = self._usable()
        wanted = sorted({str(k) for k in keys})
        if not wanted:
            return FeatureLookup({}, frozenset())
        assert self._readiness is not None and self._readiness.info is not None
        moved = db_listings.fetch_changed_keys(
            wanted, self._readiness.info.source_watermark, conn
        )
        out: dict[str, frozenset[str]] = {}
        for key in wanted:
            if key in moved:
                continue
            found = present_in(store.statuses(key), facets)
            if found:
                out[key] = found
        return FeatureLookup(out, frozenset(moved))

    def present_features(
        self,
        keys: Iterable[int | str],
        conn: Any,
        facets: Collection[str] = ELIGIBLE_FACETS,
    ) -> dict[str, frozenset[str]]:
        """{key: present features} for up to 50 keys (`lookup(...).present`)."""
        return self.lookup(keys, conn, facets).present

    def changed_keys(self, keys: Sequence[int | str], conn: Any) -> set[str]:
        """Which of up to 50 keys changed since the snapshot (or have no time)."""
        self._usable()
        assert self._readiness is not None and self._readiness.info is not None
        wanted = sorted({str(k) for k in keys})
        if not wanted:
            return set()
        return db_listings.fetch_changed_keys(
            wanted, self._readiness.info.source_watermark, conn
        )


def ordered(features: Collection[str], requested: Sequence[str] = ()) -> list[str]:
    """Requested features first (in request order), then the rest A-Z."""
    first = [f for f in dict.fromkeys(requested) if f in features]
    return first + sorted(set(features) - set(first))
