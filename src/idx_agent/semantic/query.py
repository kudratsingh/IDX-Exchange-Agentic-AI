"""Similar-listing query path (WO-010): prepare, embed, mask and rank, re-check in SQL.

`find_similar` prepares the request text as the build prepares remarks, embeds it (one
call), ranks the index rows that pass the hard filters, then fetches up to 200 ranked
keys in batches of 50 through `fetch_candidates` until k survive. SQL decides."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from idx_agent.db.listings import MAX_ROWS, fetch_candidates
from idx_agent.domain.models import SimilarListingsRequest, SimilarMatch
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
    "SimilarOutcome",
    "UnusableText",
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
    matches: list[SimilarMatch] = []
    keys_fetched = dropped = skipped = 0
    with span("idx.similar.fetch"):
        for batch in _batches(ranked):
            if len(matches) >= request.k:
                break
            keys = [key for key, _ in batch]
            fetched = fetch_candidates(filters, keys, conn)
            found = {x.listing_key: x for x in fetched.listings}
            keys_fetched += len(keys)
            skipped += fetched.skipped_rows
            for key, score in batch:
                listing = found.get(key)
                if listing is None:
                    dropped += 1
                elif len(matches) < request.k:
                    # SimilarMatch rounds the score to 4 decimals; remarks are dropped.
                    matches.append(
                        SimilarMatch(
                            rank=len(matches) + 1, score=score, listing=listing
                        )
                    )
    return SimilarOutcome(
        matches=matches,
        rows_ranked=rows_ranked,
        keys_fetched=keys_fetched,
        dropped=dropped,
        index_as_of=index.meta.active_as_of,
        skipped_rows=skipped,
    )
