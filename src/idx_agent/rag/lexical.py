"""In-process BM25 over the chunks (WO-012): no dependency, statistics built at load.

Tokens are the spike's: runs of letters and digits, lowercased; a camel-case name
also yields its parts (DaysOnMarket gives daysonmarket, days, on, market); common
function words are dropped; no stemming.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "B",
    "K1",
    "STOPWORDS",
    "BM25Stats",
    "bm25_scores",
    "bm25_stats",
    "camel_parts",
    "tokenize",
]

K1 = 1.5
B = 0.75
_WORD = re.compile(r"[A-Za-z0-9]+")
_CAMEL_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by do does for from has have how i in is it its me of on or"
    " the this to was what when which who why with you".split()
)


def camel_parts(word: str) -> list[str]:
    """The camel-case parts of one word, as written (DaysOnMarket: Days, On, Market;
    City: City alone)."""
    return _CAMEL_PART.findall(word)


def tokenize(text: str) -> list[str]:
    """Lowercased words plus camel-case parts, stopwords dropped, in text order."""
    out: list[str] = []
    for word in _WORD.findall(text):
        out.append(word.lower())
        parts = camel_parts(word)
        if len(parts) > 1:
            out += [part.lower() for part in parts]
    return [token for token in out if token not in STOPWORDS]


@dataclass(frozen=True)
class BM25Stats:
    """Per-chunk term counts and lengths, the average length, and each term's idf."""

    tf: tuple[Counter[str], ...]
    lengths: tuple[int, ...]
    avg_length: float
    idf: dict[str, float]
    k1: float = K1
    b: float = B


def bm25_stats(texts: Sequence[str], k1: float = K1, b: float = B) -> BM25Stats:
    """Statistics for `texts`; idf = ln((N - df + 0.5) / (df + 0.5) + 1)."""
    docs = [tokenize(text) for text in texts]
    n = len(docs)
    df = Counter(token for doc in docs for token in set(doc))
    return BM25Stats(
        tf=tuple(Counter(doc) for doc in docs),
        lengths=tuple(len(doc) for doc in docs),
        avg_length=sum(len(doc) for doc in docs) / max(n, 1),
        idf={t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()},
        k1=k1,
        b=b,
    )


def bm25_scores(stats: BM25Stats, query: Sequence[str]) -> list[float]:
    """One score per chunk for the query tokens (a repeated token counts again).

    score = sum over query tokens t in the chunk of
            idf(t) * f * (k1 + 1) / (f + k1 * (1 - b + b * len / avg_len)).
    """
    scores: list[float] = []
    avg = stats.avg_length or 1.0
    for tf, length in zip(stats.tf, stats.lengths, strict=True):
        norm = stats.k1 * (1 - stats.b + stats.b * length / avg)
        score = 0.0
        for token in query:
            f = tf.get(token, 0)
            if f:
                score += stats.idf[token] * f * (stats.k1 + 1) / (f + norm)
        scores.append(score)
    return scores
