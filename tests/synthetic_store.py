"""Synthetic effective-facet stores for tests (WO-035).

A synthetic store never carries the approved digest: it carries a synthetic digest,
paired with its own row count and trusted for the current test only.
"""

# Production trusts one (results digest, source rows) pair, the approved source
# (`source_check.TRUSTED_SOURCES`), and refuses a store carrying that digest with any
# other count. `tests/conftest.py` gives every test a fresh copy of the production
# pairs, and the helpers below add to that copy. Production checks are never relaxed:
# an unregistered or mismatched pair is refused exactly as in production.

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from idx_agent.enrichment import source_check
from idx_agent.enrichment.effective_store import write_store


def synthetic_digest(rows: int) -> str:
    """A stand-in results digest for a synthetic source of `rows` rows."""
    return hashlib.sha256(
        f"synthetic-effective-store-source:{rows}".encode()
    ).hexdigest()


def trust_source(digest: str, rows: int) -> str:
    """Trust (digest, rows) for the current test; never the approved digest."""
    if digest == source_check.EXPECTED_RESULTS_DIGEST:
        raise AssertionError("tests never re-pair the approved digest")
    trusted = source_check.TRUSTED_SOURCES
    if not isinstance(trusted, dict):
        raise AssertionError("tests/conftest.py did not give this test its own pairs")
    if trusted.get(digest, rows) != rows:
        raise AssertionError("a synthetic digest is already paired with another count")
    trusted[digest] = rows
    return digest


def trust_synthetic(rows: int) -> str:
    """Trust the synthetic digest for `rows` rows; return it."""
    return trust_source(synthetic_digest(rows), rows)


def synthetic_meta(meta: Mapping, rows: int) -> dict:
    """`meta` with a trusted synthetic digest and `source_rows` for `rows` rows."""
    return dict(meta, results_digest=trust_synthetic(rows), source_rows=rows)


def write_synthetic_store(
    path: Path, rows: Iterable[tuple[str, Mapping[str, str]]], meta: Mapping
) -> int:
    """`write_store` for a synthetic store whose digest and count are trusted here."""
    rows = list(rows)
    return write_store(path, rows, synthetic_meta(meta, len(rows)))
