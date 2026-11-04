"""Effective remark facets: original results plus the validated correction overlays.

Pure functions only. A facet with no label is unknown and is never stored; only a
"present" status may be shown or matched as a current feature (WO-021).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

# The 20 facets eligible for integration: held-out F1 of at least 80% with at least
# 10 gold examples (WO-018, 2026-10-28). Nothing else may be filtered or shown.
ELIGIBLE_FACETS: frozenset[str] = frozenset(
    {
        "adu",
        "bonus_room",
        "clubhouse",
        "community_pool",
        "condominium",
        "fitness_center",
        "garage",
        "gated_community",
        "hardwood",
        "mountain_view",
        "near_grocery_mentioned",
        "near_transit_mentioned",
        "open_plan",
        "patio",
        "pool",
        "single_level",
        "solar",
        "stainless_appliances",
        "walk_in_closet",
        "water_view",
    }
)

FacetStatus = Literal[
    "present", "stated_absent", "contradictory", "planned", "uncertain", "historical"
]
FACET_STATUSES: tuple[str, ...] = (
    "present",
    "stated_absent",
    "contradictory",
    "planned",
    "uncertain",
    "historical",
)
# The single status a feature filter matches.
MATCHING_STATUS = "present"
_NOW = ("current", "unspecified")


def apply_overlay(stored: Sequence[Mapping[str, Any]], disposition: Mapping[str, Any]):
    """Return labels after a resolved disposition; an unresolved one changes nothing.

    The stored list is never modified. Raises ValueError for a change that cannot apply.
    """
    result = [dict(label) for label in stored]
    if disposition.get("status") == "unresolved":
        return result
    for change in disposition.get("changes", ()):
        if change["operation"] == "remove":
            try:
                result.remove(dict(change["original"]))
            except ValueError:
                raise ValueError(
                    "overlay removes a label that is not present"
                ) from None
        elif change["operation"] == "add":
            result.append(dict(change["corrected_annotation"]))
        else:
            raise ValueError("unknown overlay operation")
    return result


def facet_status(labels: Iterable[Mapping[str, Any]]) -> FacetStatus | None:
    """Collapse one facet's labels to a status, or None (unknown) when there are none.

    Present needs an affirmed current or unspecified-time mention. Contradiction beats
    presence; presence beats planned, uncertain and historical mentions.
    """
    labels = list(labels)
    if not labels:
        return None
    present = any(
        x["polarity"] == "affirmed" and x["temporality"] in _NOW for x in labels
    )
    absent = any(
        x["polarity"] == "negated" and x["temporality"] in _NOW for x in labels
    )
    if present and absent:
        return "contradictory"
    if present:
        return "present"
    if absent:
        return "stated_absent"
    if any(x["temporality"] == "planned" for x in labels):
        return "planned"
    if any(x["polarity"] == "uncertain" for x in labels):
        return "uncertain"
    if any(x["temporality"] == "historical" for x in labels):
        return "historical"
    raise ValueError("label with an unknown polarity or temporality")


def facet_statuses(labels: Iterable[Mapping[str, Any]]) -> dict[str, FacetStatus]:
    """Map each eligible facet that has labels to its status; others stay unknown."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for label in labels:
        if label["value"] in ELIGIBLE_FACETS:
            grouped.setdefault(label["value"], []).append(label)
    statuses = {facet: facet_status(group) for facet, group in grouped.items()}
    return {facet: status for facet, status in statuses.items() if status is not None}


def effective_labels(results, diagnostic, dataset):
    """Yield (sequence, listing_key, labels) for every result after its overlay, if any.

    `results` yields (sequence, listing_key, facets); overlays map sequence to their
    disposition. A disposition whose key differs from the result's raises ValueError.
    """
    seen: set[int] = set()
    for sequence, key, facets in results:
        overlays = [o for o in (diagnostic.get(sequence), dataset.get(sequence)) if o]
        if len(overlays) > 1:
            raise ValueError("a result has both a diagnostic and a dataset overlay")
        labels = list(facets)
        if overlays:
            if str(overlays[0]["listing_key"]) != str(key):
                raise ValueError("overlay listing key differs from the result")
            labels = apply_overlay(labels, overlays[0])
        seen.add(sequence)
        yield sequence, str(key), labels
    if (set(diagnostic) | set(dataset)) - seen:
        raise ValueError("an overlay has no matching result")


def effective_rows(results, diagnostic, dataset):
    """Yield (listing_key, statuses) for every result, applying its overlay if any.

    `results` yields (sequence, listing_key, facets); overlays map sequence to their
    disposition. A disposition whose key differs from the result's raises ValueError.
    """
    for _, key, labels in effective_labels(results, diagnostic, dataset):
        yield key, facet_statuses(labels)
