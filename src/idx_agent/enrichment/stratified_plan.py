"""Pure, seeded allocation of already supplied listing groups by subtype."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateGroup:
    """One deduplicated listing group and its single property subtype."""

    group: str
    subtype: str


def _allocate(population: dict[str, int], total: int) -> dict[str, int]:
    """Largest-remainder proportional allocation, with deterministic ties."""
    size = sum(population.values())
    if total < 0 or total > size or not size:
        raise ValueError("insufficient candidate groups")
    allocated = {key: total * count // size for key, count in population.items()}
    remaining = total - sum(allocated.values())
    order = sorted(population, key=lambda key: (-(total * population[key] % size), key))
    for key in order[:remaining]:
        allocated[key] += 1
    return allocated


def stratified_plan(
    groups: list[CandidateGroup], seed: str, *, dev: int = 100, test: int = 150
) -> dict[str, str]:
    """Assign a deterministic sample to splits without data access or I/O."""
    if (
        not isinstance(seed, str)
        or not seed
        or type(dev) is not int
        or type(test) is not int
        or dev < 1
        or test < 1
    ):
        raise ValueError("invalid sampling configuration")
    by_group: dict[str, str] = {}
    for item in groups:
        if (
            not isinstance(item, CandidateGroup)
            or not isinstance(item.group, str)
            or not item.group
            or not isinstance(item.subtype, str)
            or not item.subtype
        ):
            raise ValueError("invalid candidate group")
        old = by_group.setdefault(item.group, item.subtype)
        if old != item.subtype:
            raise ValueError("conflicting group subtype")
    by_type: dict[str, list[str]] = defaultdict(list)
    for group, subtype in by_group.items():
        by_type[subtype].append(group)
    allocation = _allocate(dict(Counter(by_group.values())), dev + test)
    dev_allocation = _allocate(allocation, dev)

    def priority(group: str) -> bytes:
        h = hashlib.sha256()
        for value in (seed, group):
            encoded = value.encode("utf-8")
            h.update(len(encoded).to_bytes(8, "big"))
            h.update(encoded)
        return h.digest()

    result = {}
    for subtype in sorted(by_type):
        selected = sorted(by_type[subtype], key=lambda group: (priority(group), group))[
            : allocation[subtype]
        ]
        for index, group in enumerate(selected):
            result[group] = "dev" if index < dev_allocation[subtype] else "test"
    return result
