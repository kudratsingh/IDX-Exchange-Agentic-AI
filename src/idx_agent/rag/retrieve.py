"""Retrieval over a loaded document index (WO-012): exact names, then ranked chunks.

Exact-name hits (an alias or field name) come first at 1.0; BM25 and, on a hybrid
index with an embedder, cosine ranks fill the rest by reciprocal rank fusion. The
floors decide "found". A ProviderError propagates unless the caller asks to degrade.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeVar

import numpy as np

from idx_agent.domain.models import (
    RAG_CONFIDENTIAL_MAX_WORDS,
    RAG_TOP_K,
    RagAnswer,
    RetrievedChunk,
)
from idx_agent.rag.aliases import alias_hits
from idx_agent.rag.chunk import IDENT, Chunk
from idx_agent.rag.lexical import bm25_scores, camel_parts, tokenize
from idx_agent.rag.sources import SOURCES
from idx_agent.semantic.embedder import (
    UNIT_TOLERANCE,
    ProviderError,
    prepare,
    redact_enabled,
)

if TYPE_CHECKING:
    from idx_agent.rag.store import DocIndex
    from idx_agent.semantic.embedder import Embedder

__all__ = [
    "RANK_DEPTH",
    "RRF_K",
    "TOP_K",
    "VECTOR_SKIPPED_WARNING",
    "Retrieval",
    "cap_chunk",
    "cap_text",
    "fuse",
    "lookup_exact",
    "rank_lexical",
    "rank_vector",
    "retrieve",
    "retrieve_detail",
]

TOP_K = RAG_TOP_K
RRF_K = 60
# How many ranked chunks each route hands to the fusion.
RANK_DEPTH = 50
ELLIPSIS = "…"
VECTOR_SKIPPED_WARNING = (
    "The question was too short to match by meaning, so its passages were matched "
    "on their words alone."
)
_QUESTION_WORD = re.compile(r"[A-Za-z0-9_]+")
# A chunk of either shape: the index's Chunk or the answer's RetrievedChunk.
_C = TypeVar("_C", Chunk, RetrievedChunk)


@dataclass(frozen=True)
class Retrieval:
    """An answer plus what the tool logs: exact hits, the top scores, whether the
    vector leg was skipped (a question under prepare's 20 characters), and the
    provider's reason code when it refused and the caller asked to degrade."""

    answer: RagAnswer
    exact_hits: int
    vector_skipped: bool
    lexical_top: float
    vector_top: float | None
    provider_reason: str | None = None


def _multi_part(name: str) -> bool:
    """A camel-case name of two or more parts (DaysOnMarket; not City or View)."""
    return len(camel_parts(name)) > 1


def lookup_exact(question: str, chunks: Sequence[Chunk]) -> list[Chunk]:
    """Chunks the question names: aliases in table order, then field names in
    question order. A multi-part name matches in any case, a one-word name (City,
    View) only as written. A missing target is skipped; a split section is found
    by its first part."""
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    hits: list[Chunk] = []
    for cid in alias_hits(question):
        chunk = by_id.get(cid) or by_id.get(f"{cid}.1")
        if chunk is not None and chunk not in hits:
            hits.append(chunk)
    exact: dict[str, Chunk] = {}
    folded: dict[str, Chunk] = {}
    for chunk in chunks:
        if SOURCES[chunk.doc].kind == "fields" and IDENT.match(chunk.key):
            exact.setdefault(chunk.key, chunk)
            if _multi_part(chunk.key):
                folded.setdefault(chunk.key.lower(), chunk)
    for word in _QUESTION_WORD.findall(question):
        chunk = exact.get(word) or folded.get(word.lower())
        if chunk is not None and chunk not in hits:
            hits.append(chunk)
    return hits


def _ordered(scores: np.ndarray, top: int) -> list[tuple[int, float]]:
    """(chunk index, score) by score high first, ties by chunk index."""
    order = np.lexsort((np.arange(len(scores)), -scores))[:top]
    return [(int(i), float(scores[i])) for i in order]


def rank_lexical(index: DocIndex, question: str, top: int) -> list[tuple[int, float]]:
    """BM25 ranks (scores rounded to 6 decimals); chunks scoring 0 are left out."""
    if top <= 0:
        return []
    scores = np.round(
        np.asarray(bm25_scores(index.lexical, tokenize(question)), np.float64), 6
    )
    return [(i, s) for i, s in _ordered(scores, top) if s > 0]


def rank_vector(
    index: DocIndex, query_vector: np.ndarray, top: int
) -> list[tuple[int, float]]:
    """Cosine ranks: float32 products rounded to 6 decimals in float64, as WO-010.

    Raises ValueError for a query of the wrong width or not unit length.
    """
    if index.vectors is None or top <= 0:
        return []
    query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    if query.shape[0] != index.vectors.shape[1]:
        raise ValueError("query vector width does not match the index")
    if abs(float(np.linalg.norm(query)) - 1.0) > UNIT_TOLERANCE:
        raise ValueError("query vector is not unit length")
    scores = np.round((index.vectors @ query).astype(np.float64), 6)
    return _ordered(scores, top)


def fuse(
    lexical: Sequence[tuple[int, float]], vector: Sequence[tuple[int, float]]
) -> list[tuple[int, float]]:
    """Reciprocal rank fusion, k = 60: each list adds 1 / (60 + rank) per chunk.

    Scores rounded to 6 decimals; ties by chunk index.
    """
    total: dict[int, float] = defaultdict(float)
    for ranked in (lexical, vector):
        for rank, (i, _) in enumerate(ranked, 1):
            total[i] += 1.0 / (RRF_K + rank)
    fused = [(i, round(score, 6)) for i, score in total.items()]
    return sorted(fused, key=lambda pair: (-pair[1], pair[0]))


def _query_vector(
    index: DocIndex, question: str, embedder: Embedder, redact: bool
) -> np.ndarray | None:
    """The question's unit vector, or None when prepare() finds it too short or the
    embedder gives no usable row. Raises ProviderError (no consent, key, or call)."""
    if (embedder.name, embedder.dims) != (index.meta.model, index.meta.dims):
        raise ValueError("the embedder does not match the index's model")
    prepared = prepare(question, redact=redact)
    if prepared.text is None:
        return None
    rows = np.asarray(embedder.embed([prepared.text]), dtype=np.float32)
    if rows.shape != (1, index.meta.dims):
        raise ValueError("the embedder returned the wrong number of vectors")
    if abs(float(np.linalg.norm(rows[0])) - 1.0) > UNIT_TOLERANCE:
        return None
    return rows[0]


def _retrieved(chunk: Chunk, score: float, exact: bool) -> RetrievedChunk:
    return RetrievedChunk(
        text=chunk.text,
        source_doc=chunk.doc,
        section_or_field=chunk.key,
        page=chunk.page,
        score=score,
        match="exact_name" if exact else "ranked",
        confidential=chunk.confidential,
    )


def retrieve_detail(
    index: DocIndex,
    question: str,
    embedder: Embedder | None = None,
    *,
    redact: bool | None = None,
    exact: Sequence[Chunk] | None = None,
    degrade: bool = False,
) -> Retrieval:
    """Exact hits (`exact` when the caller already looked them up), then fused ranks,
    up to TOP_K distinct chunks. Found: an exact hit, or a BM25 or cosine top at its
    floor. Route "hybrid" only when the vector leg ran; `degrade` turns a
    ProviderError into BM25 alone with its reason code."""
    chunks = index.chunks
    exact = list(lookup_exact(question, chunks) if exact is None else exact)
    lexical = rank_lexical(index, question, RANK_DEPTH)
    lexical_top = lexical[0][1] if lexical else 0.0
    vector: list[tuple[int, float]] = []
    skipped = False
    reason = None
    if index.vectors is not None and embedder is not None:
        use_redact = redact_enabled() if redact is None else redact
        try:
            query = _query_vector(index, question, embedder, use_redact)
        except ProviderError as exc:
            if not degrade:
                raise
            query, reason = None, exc.reason
        if query is None:
            skipped = reason is None
        else:
            vector = rank_vector(index, query, RANK_DEPTH)
    vector_top = vector[0][1] if vector else None
    hybrid = bool(vector)
    meta = index.meta
    found = (
        bool(exact)
        or lexical_top >= meta.floor_bm25
        or (vector_top is not None and vector_top >= meta.floor_cosine)
    )
    route = "hybrid" if hybrid else "bm25"
    if not found:
        answer = RagAnswer(found=False, route=route, index_built_at=meta.built_at)
        return Retrieval(answer, 0, skipped, lexical_top, vector_top, reason)
    picked: list[RetrievedChunk] = [_retrieved(c, 1.0, True) for c in exact[:TOP_K]]
    labels = [c.label for c in exact[:TOP_K]]
    seen = {c.chunk_id for c in exact}
    for i, score in fuse(lexical, vector) if hybrid else lexical:
        if len(picked) >= TOP_K:
            break
        chunk = chunks[i]
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        picked.append(_retrieved(chunk, score, False))
        labels.append(chunk.label)
    answer = RagAnswer(
        found=True,
        chunks=picked,
        sources=labels,
        route=route,
        index_built_at=meta.built_at,
    )
    return Retrieval(answer, len(exact), skipped, lexical_top, vector_top, reason)


def retrieve(
    index: DocIndex, question: str, embedder: Embedder | None = None
) -> RagAnswer:
    """The RagAnswer of `retrieve_detail` (see there)."""
    return retrieve_detail(index, question, embedder).answer


def cap_text(
    text: str, question: str, max_words: int = RAG_CONFIDENTIAL_MAX_WORDS
) -> str:
    """Text of at most `max_words` words: whole when short enough, else the window
    around the first word sharing a token with the question (or the start), with
    "…" marking each cut end."""
    words = text.split()
    if len(words) <= max_words:
        return text
    wanted = set(tokenize(question))
    first = next(
        (i for i, word in enumerate(words) if wanted & set(tokenize(word))), None
    )
    start = 0 if first is None else max(0, first - max_words // 2)
    end = min(len(words), start + max_words)
    start = max(0, end - max_words)
    body = " ".join(words[start:end])
    return (
        (f"{ELLIPSIS} " if start > 0 else "")
        + body
        + (f" {ELLIPSIS}" if end < len(words) else "")
    )


def cap_chunk(
    chunk: _C, question: str, max_words: int = RAG_CONFIDENTIAL_MAX_WORDS
) -> _C:
    """An own-words chunk unchanged; a confidential one (an index Chunk or an
    answer's RetrievedChunk) with its text through `cap_text`."""
    if not chunk.confidential:
        return chunk
    text = cap_text(chunk.text, question, max_words)
    if isinstance(chunk, RetrievedChunk):
        return chunk.model_copy(update={"text": text})
    return replace(chunk, text=text)
