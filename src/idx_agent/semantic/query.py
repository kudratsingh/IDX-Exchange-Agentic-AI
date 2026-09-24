"""Similar-listing query path (WO-010): prepare, embed, mask and rank, re-check in SQL.

`find_similar` prepares the request text as the build prepares remarks, embeds it (one
call), ranks the index rows that pass the hard filters, then fetches up to 200 ranked
keys in batches of 50 (`fetch_in_rank_order`, shared with WO-011) until k survive."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from idx_agent.db.listings import MAX_ROWS, SearchOutcome, fetch_candidates
from idx_agent.domain.models import (
    Listing,
    PropertySearchFilters,
    SimilarListingsRequest,
    SimilarMatch,
)
from idx_agent.observability.tracing import span
from idx_agent.semantic.embedder import prepare_text, redact_enabled
from idx_agent.semantic.index import rank, rows_after_mask

if TYPE_CHECKING:
    from idx_agent.semantic.embedder import Embedder
    from idx_agent.semantic.index import SemanticIndex

__all__ = [
    "FETCH_BATCH",
    "MAX_RANKED_KEYS",
    "MAX_STATEMENTS",
    "RankedFetch",
    "SimilarOutcome",
    "UnusableText",
    "fetch_in_rank_order",
    "find_similar",
]

# At most 200 ranked keys, fetched 50 per statement, so at most 4 statements.
MAX_RANKED_KEYS = 200
FETCH_BATCH = MAX_ROWS
MAX_STATEMENTS = MAX_RANKED_KEYS // FETCH_BATCH


class UnusableText(ValueError):
    """The description is too little to rank by: under 20 characters once prepared,
    or it embedded to a zero or non-unit vector. The tool asks for more words."""


@dataclass(frozen=True)
class SimilarOutcome:
    """A finished similar search: matches in rank order plus counts for the log.

    `rows_ranked`: index rows left after the mask; `keys_fetched`: ranked keys sent to
    SQL; `dropped`: those SQL did not return as a listing, of which `skipped_rows`
    came back but failed Listing validation; `index_as_of`: the index's date.
    """

    matches: list[SimilarMatch]
    rows_ranked: int
    keys_fetched: int
    dropped: int
    index_as_of: date
    skipped_rows: int = 0


def _query_vector(embedder: Embedder, text: str) -> Any:
    """Embed the text as exactly one vector (one call); raise ValueError otherwise.

    `rank` then refuses a vector of the wrong width or not unit length.
    """
    vectors = embedder.embed([text])
    if len(vectors) != 1:
        raise ValueError("the embedder returned the wrong number of vectors")
    return vectors[0]


def _batches(
    ranked: Sequence[tuple[int, float]],
) -> list[Sequence[tuple[int, float]]]:
    """Split the ranked keys into batches of at most 50, at most 4 of them."""
    batches = [
        ranked[start : start + FETCH_BATCH]
        for start in range(0, len(ranked), FETCH_BATCH)
    ]
    if len(batches) > MAX_STATEMENTS:
        raise ValueError(f"more than {MAX_STATEMENTS} candidate statements")
    return batches


@dataclass(frozen=True)
class RankedFetch:
    """Ranked keys fetched in rank order: what survived SQL, plus the log counts.

    `found`: (listing, score) pairs in rank order, at most k; `keys_fetched`: keys
    sent to SQL; `dropped`: keys of the fetched batches SQL did not return (counted
    for the whole batch, also past k); `skipped_rows`: rows that failed validation.
    """

    found: list[tuple[Listing, float]]
    keys_fetched: int
    dropped: int
    skipped_rows: int


def fetch_in_rank_order(
    ranked: Sequence[tuple[int, float]],
    filters: PropertySearchFilters,
    k: int,
    conn: Any,
    fetch: Callable[[PropertySearchFilters, Sequence[int], Any], SearchOutcome]
    | None = None,
) -> RankedFetch:
    """Fetch the ranked keys 50 per statement (at most 4) until k listings survive.

    Each statement re-checks `filters` in SQL, whose answer decides. `fetch` is the
    candidate statement, `fetch_candidates` by default; the recommend tool passes its
    own module's reference. Raises ValueError past the statement cap.
    """
    run = fetch or fetch_candidates
    found: list[tuple[Listing, float]] = []
    keys_fetched = dropped = skipped = 0
    for batch in _batches(ranked):
        if len(found) >= k:
            break
        keys = [key for key, _ in batch]
        fetched = run(filters, keys, conn)
        listings = {x.listing_key: x for x in fetched.listings}
        keys_fetched += len(keys)
        skipped += fetched.skipped_rows
        for key, score in batch:
            listing = listings.get(key)
            if listing is None:
                dropped += 1
            elif len(found) < k:
                found.append((listing, score))
    return RankedFetch(found, keys_fetched, dropped, skipped)


def find_similar(
    request: SimilarListingsRequest,
    index: SemanticIndex,
    embedder: Embedder,
    conn: Any,
) -> SimilarOutcome:
    """Return up to k active listings most similar to the request text.

    Hard filters mask the index before ranking and are applied again in SQL, whose
    answer decides. Raises UnusableText (before any embedding call) when the prepared
    text is under 20 characters, and ValueError for an unusable embedding or a broken
    cap (the SimilarResult built from the matches refuses more than k).
    """
    filters = request.hard_filters()
    # 1. The same text rule as the build: whitespace collapsed, links, emails, and
    #    phones masked (unless IDX_EMBED_REDACT is off), the 20-character floor.
    text = prepare_text(request.text, redact=redact_enabled())
    if text is None:
        raise UnusableText("the description is too short to rank by")
    # 2. One embedding call for the prepared text; nothing else is sent.
    vector = _query_vector(embedder, text)
    # 3. Mask by the index's snapshot of the filters, then rank (score, then key).
    with span("idx.similar.rank"):
        ranked = rank(index, vector, filters, MAX_RANKED_KEYS)
        rows_ranked = rows_after_mask(index, filters)
    # 4. Fetch in rank order until k listings are in hand; count what SQL dropped.
    with span("idx.similar.fetch"):
        fetched = fetch_in_rank_order(ranked, filters, request.k, conn)
    # SimilarMatch rounds the score to 4 decimals; remarks are dropped.
    matches = [
        SimilarMatch(rank=position, score=score, listing=listing)
        for position, (listing, score) in enumerate(fetched.found, start=1)
    ]
    return SimilarOutcome(
        matches=matches,
        rows_ranked=rows_ranked,
        keys_fetched=fetched.keys_fetched,
        dropped=fetched.dropped,
        index_as_of=index.meta.active_as_of,
        skipped_rows=fetched.skipped_rows,
    )
