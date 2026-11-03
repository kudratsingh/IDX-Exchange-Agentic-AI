"""Saved feature searches (WO-025): the off switch, the snapshot horizon and the one
feature decision shared by `save_search` and the alert job."""

# Features are bound only through `enrichment.access.FeatureAccess.bind` (WO-023); this
# module never reads the store itself. Any refusal or failure is `unavailable`: the
# caller refuses the save, or leaves that saved search unchecked and unchanged.

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from idx_agent.db import pool
from idx_agent.db.listings import FeatureScope
from idx_agent.enrichment.access import Binding

# Off unless exactly "1". Feature search itself needs only IDX_ENRICHMENT_STORE; this
# switch lets saved feature searches be activated and rolled back on their own.
SETTING = "IDX_FEATURE_SAVED_SEARCHES"


def enabled() -> bool:
    """True only when IDX_FEATURE_SAVED_SEARCHES is exactly "1"."""
    return pool.env_setting(SETTING) == "1"


def snapshot_date(watermark: str) -> date:
    """The calendar day of a store's source watermark ("YYYY-MM-DD HH:MM:SS")."""
    if not isinstance(watermark, str) or len(watermark) < 10:
        raise ValueError("unusable snapshot watermark")
    return date.fromisoformat(watermark[:10])


@dataclass(frozen=True)
class FeatureCheck:
    """One saved search's features, bound for a save or one alert run."""

    # `applied` with a scope: query with it. `applied` without one: no listing has every
    # feature present (match nothing, no query). `unavailable`: never check the search,
    # never claim no matches, change nothing. `horizon` is the last listing date the
    # snapshot can speak for: min(active as-of date, snapshot date). `watermark` is the
    # snapshot's exact source watermark, for the job's unchecked-listing test.

    status: Literal["applied", "unavailable"]
    reason: str | None = None
    scope: FeatureScope | None = None
    horizon: date | None = None
    snapshot: date | None = None
    watermark: str | None = None

    @property
    def matches_nothing(self) -> bool:
        return self.status == "applied" and self.scope is None


def unavailable(reason: str) -> FeatureCheck:
    return FeatureCheck("unavailable", reason=reason)


def check(
    features: Sequence[str],
    bind: Callable[[Sequence[str]], Binding] | None,
    active_as_of: date,
) -> FeatureCheck:
    """Bind `features` (switch first, then `bind`) and fix the snapshot horizon.

    Never raises for an enrichment problem: every refusal or exception is unavailable
    with a fixed reason code (never an exception text, key or path).
    """
    if not features:
        raise ValueError("a feature check needs at least one feature")
    if not enabled():
        return unavailable("not_enabled")
    if bind is None:
        return unavailable("not_configured")
    try:
        binding = bind(list(features))
        if binding.refused:
            return unavailable(binding.reason or binding.status)
        if binding.info is None:
            return unavailable("no_provenance")
        snapshot = snapshot_date(binding.info.source_watermark)
    except Exception:  # noqa: BLE001 - any enrichment failure fails closed
        return unavailable("failed")
    return FeatureCheck(
        "applied",
        scope=binding.scope,
        horizon=min(active_as_of, snapshot),
        snapshot=snapshot,
        watermark=binding.info.source_watermark,
    )
