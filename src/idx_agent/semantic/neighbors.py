"""Listings like an indexed listing (WO-011), ranked by its own stored vector.

The subject's vector is read from the index by key (binary search over the ascending
keys); nothing is embedded and no provider is called. Masking, scoring, and the
tiebreak are WO-010's `rank`, unchanged; only the subject's own row is removed here.
"""

from __future__ import annotations

import numpy as np

from idx_agent.domain.models import PropertySearchFilters
from idx_agent.semantic.index import SemanticIndex, rank

__all__ = [
    "SubjectNotIndexed",
    "neighbor_filters",
    "rank_neighbors",
    "subject_row",
    "subject_vector",
]


class SubjectNotIndexed(LookupError):
    """The subject listing has no vector in the index. The tool answers with no
    similar listing and a warning; it never embeds the listing instead."""


def subject_row(index: SemanticIndex, key: int) -> int:
    """The row of `key` in the index, by binary search; SubjectNotIndexed if absent."""
    row = int(np.searchsorted(index.keys, key))
    if row >= index.rows or int(index.keys[row]) != key:
        raise SubjectNotIndexed("the listing has no vector in the index")
    return row


def subject_vector(index: SemanticIndex, key: int) -> np.ndarray:
    """The stored unit vector of `key` (a view into the index, never re-embedded)."""
    return index.vectors[subject_row(index, key)]


def neighbor_filters(
    city: str, subtype: str, min_price: int, max_price: int
) -> PropertySearchFilters:
    """The hard filters for candidates: same city and subtype, inside the price band.

    The same object masks the index and is sent to `fetch_candidates`, so SQL
    re-checks exactly what the mask applied."""
    return PropertySearchFilters(
        city=city, property_subtype=subtype, min_price=min_price, max_price=max_price
    )


def rank_neighbors(
    index: SemanticIndex,
    subject_key: int,
    city: str,
    subtype: str,
    min_price: int,
    max_price: int,
    top: int,
) -> list[tuple[int, float]]:
    """Up to `top` (listing_key, score) pairs most like the subject, subject excluded.

    Scores are WO-010's: float32 dot products rounded to 6 decimals, score desc then
    key asc. Raises SubjectNotIndexed when the subject has no vector.
    """
    vector = subject_vector(index, subject_key)
    if top <= 0:
        return []
    filters = neighbor_filters(city, subtype, min_price, max_price)
    # One extra place, because the subject passes its own mask and is then removed.
    ranked = rank(index, vector, filters, top + 1)
    return [(key, score) for key, score in ranked if key != subject_key][:top]
