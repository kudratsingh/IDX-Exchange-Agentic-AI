"""Chunk vectors for the hybrid route (WO-012), with WO-010's text rule and embedders.

Each chunk is embedded as its label (no page) then its text, through `prepare` (links,
emails, phones masked; cut at MAX_CHARS); rows are unit float32. The OpenAI embedder
checks the key and spends one call of the build's paid budget per request; no logs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from idx_agent.rag.chunk import Chunk
from idx_agent.semantic.embedder import (
    BATCH_SIZE,
    UNIT_TOLERANCE,
    Embedder,
    prepare,
)

__all__ = ["EmbedStats", "embed_chunks", "embed_text", "unit_rows_ok"]

_PAGE_SUFFIX = re.compile(r", p\. \d+$")


@dataclass(frozen=True)
class EmbedStats:
    """Counts from one embedding pass: texts, cut, masked, requests, reported tokens."""

    texts: int
    truncated: int
    redacted: int
    requests: int
    usage_tokens: int | None


def embed_text(chunk: Chunk, redact: bool = True) -> tuple[str, bool, bool]:
    """(text to embed, truncated, redacted) for one chunk; never None (the label
    alone passes prepare's 20-character floor)."""
    label = _PAGE_SUFFIX.sub("", chunk.label)
    prepared = prepare(f"{label}. {chunk.text}", redact=redact)
    if prepared.text is None:  # a label under 20 characters and no text
        raise ValueError("a chunk is too short to embed")
    return prepared.text, prepared.truncated, prepared.redacted


def unit_rows_ok(vectors: np.ndarray) -> bool:
    """True when every row has length 1 within UNIT_TOLERANCE (a NaN row fails)."""
    norms = np.linalg.norm(np.asarray(vectors, dtype=np.float32), axis=1)
    return bool(np.all(np.abs(norms - 1.0) <= UNIT_TOLERANCE))


def embed_chunks(
    chunks: Sequence[Chunk],
    embedder: Embedder,
    *,
    batch_size: int = BATCH_SIZE,
    redact: bool = True,
) -> tuple[np.ndarray, EmbedStats]:
    """Unit float32 rows for the chunks, in order, embedded in batches.

    Raises ProviderError from the embedder, or ValueError for a row of the wrong
    shape or not unit length.
    """
    prepared = [embed_text(chunk, redact) for chunk in chunks]
    texts = [text for text, _, _ in prepared]
    parts: list[np.ndarray] = []
    tokens: list[int | None] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        rows = np.asarray(embedder.embed(batch), dtype=np.float32)
        if rows.shape != (len(batch), embedder.dims):
            raise ValueError("the embedder returned rows of the wrong shape")
        parts.append(rows)
        tokens.append(getattr(embedder, "last_usage_tokens", None))
    vectors = (
        np.vstack(parts) if parts else np.zeros((0, embedder.dims), dtype=np.float32)
    )
    if not unit_rows_ok(vectors):
        raise ValueError("a chunk embedded to a vector that is not unit length")
    usage = None if any(t is None for t in tokens) else sum(t or 0 for t in tokens)
    stats = EmbedStats(
        texts=len(texts),
        truncated=sum(1 for _, cut, _ in prepared if cut),
        redacted=sum(1 for _, _, masked in prepared if masked),
        requests=len(tokens),
        usage_tokens=usage,
    )
    return np.ascontiguousarray(vectors, dtype=np.float32), stats
