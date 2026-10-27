"""Plan a small invented group split without reading a feed or exporting records."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

_MAX_ROWS = 50
_MAX_GROUPS = 30
_GROUP = re.compile(r"synthetic-(?:0|[1-9][0-9]{0,5})\Z")
_SEED = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


@dataclass(frozen=True)
class SyntheticSplitPlan:
    """Only caller-supplied invented group labels; no remarks or MLS identifiers."""

    development: tuple[str, ...]
    test: tuple[str, ...]
    input_rows: int


def plan_synthetic_split(rows: Sequence[str], *, seed: str) -> SyntheticSplitPlan:
    """Group and reproducibly split invented labels; do not access any data source.

    The 50-row input cap includes duplicates. The synthetic prefix is an input
    contract, not proof of real-world provenance. No label or input is logged.
    """
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, str | bytes)
        or len(rows) > _MAX_ROWS
    ):
        raise ValueError("invalid synthetic input size")
    if not isinstance(seed, str) or not _SEED.fullmatch(seed):
        raise ValueError("invalid synthetic seed")
    if any(not isinstance(row, str) or not _GROUP.fullmatch(row) for row in rows):
        raise ValueError("invalid synthetic group label")
    groups = set(rows)
    if len(groups) < 3:
        raise ValueError("at least three synthetic groups are required")
    order = sorted(
        groups,
        key=lambda group: (
            hashlib.sha256((seed + "\0" + group).encode()).digest(),
            group,
        ),
    )[:_MAX_GROUPS]
    development = len(order) * 2 // 3
    return SyntheticSplitPlan(
        tuple(order[:development]), tuple(order[development:]), len(rows)
    )
