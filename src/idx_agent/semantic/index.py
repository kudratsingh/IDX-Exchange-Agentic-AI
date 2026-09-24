"""The on-disk remarks index: write, load with every check, and a pure ranking (WO-010).

One directory per model, dimension, and active as-of date, under the repo's gitignored
`data/` folder: vectors.npy, keys.npy, attrs.npz, then meta.json written last. Only a
`test:hashing` index (invented rows, a temporary directory) may live elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import BinaryIO, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError

from idx_agent.db.pool import env_setting
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.semantic.embedder import (
    MAX_CHARS,
    TEST_MODEL,
    TEXT_PREP_VERSION,
    UNIT_TOLERANCE,
)

__all__ = [
    "BUILDER_VERSION",
    "DATA_ROOT",
    "DEFAULT_INDEX_ROOT",
    "FORMAT_VERSION",
    "IndexAttrs",
    "IndexMeta",
    "IndexUnavailable",
    "SemanticIndex",
    "configured_index_dir",
    "file_sha256",
    "index_dir_for",
    "inside",
    "load_index",
    "rank",
    "read_meta",
    "replace_with",
    "rows_after_mask",
    "write_index",
]

FORMAT_VERSION = 1
BUILDER_VERSION = 1
# Rows per unit-length check: the check's temporaries stay a few MB, not a matrix copy.
UNIT_CHECK_ROWS = 4096
# The checkout root (src/idx_agent/semantic/index.py -> three levels up), as in pool.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / "data"
DEFAULT_INDEX_ROOT = DATA_ROOT / "indexes" / "remarks"
VECTORS, KEYS, ATTRS, META = "vectors.npy", "keys.npy", "attrs.npz", "meta.json"
ATTR_FIELDS = ("city", "list_price", "bedrooms", "property_subtype")
# The filters the index can mask; page and limit are paging, not filters.
_MASKED = {"city", "min_price", "max_price", "min_beds", "property_subtype"}
_PAGING = {"page", "limit"}
_SLUG = re.compile(r"[^a-z0-9.]+")


class IndexUnavailable(RuntimeError):
    """No usable index at a path; `cause` names the failed check (never a key or text).

    Causes: missing, outside_data, symlink, bad_meta, incomplete, format_version,
    model, dims, row_count, keys_order, hash, not_unit.
    """

    def __init__(self, cause: str, message: str) -> None:
        super().__init__(message)
        self.cause = cause


class IndexMeta(BaseModel):
    """meta.json: how and when the index was built; no remark and no listing key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int
    model: str
    dims: int
    rows: int
    source_table: Literal["rets_property"] = "rets_property"
    source_column: Literal["L_Remarks"] = "L_Remarks"
    active_as_of: date
    built_at: datetime
    skipped_empty: int
    truncated: int
    redacted_inputs: int = 0
    usage_tokens: int | None = None
    max_chars: int
    text_prep_version: int
    vectors_sha256: str
    keys_sha256: str
    builder_version: int
    complete: bool


@dataclass(frozen=True)
class IndexAttrs:
    """Snapshot values beside each vector, for the in-memory filter mask.

    city and property_subtype are unicode arrays ("" when unknown); list_price and
    bedrooms are int64 (-1 when unknown). Same order as the keys.
    """

    city: np.ndarray
    list_price: np.ndarray
    bedrooms: np.ndarray
    property_subtype: np.ndarray

    @classmethod
    def from_values(
        cls,
        city: list[str | None],
        list_price: list[int | None],
        bedrooms: list[int | None],
        property_subtype: list[str | None],
    ) -> IndexAttrs:
        """Build the arrays from per-row values, filling unknowns with "" or -1."""
        return cls(
            city=np.array([c or "" for c in city], dtype=str),
            list_price=np.array([-1 if p is None else p for p in list_price], np.int64),
            bedrooms=np.array([-1 if b is None else b for b in bedrooms], np.int64),
            property_subtype=np.array([s or "" for s in property_subtype], dtype=str),
        )

    def take(self, order: np.ndarray) -> IndexAttrs:
        """The same attrs reordered (or subset) by an index array."""
        return IndexAttrs(*(getattr(self, name)[order] for name in ATTR_FIELDS))

    def lengths(self) -> set[int]:
        """The row count of each array (one value when they agree)."""
        return {len(getattr(self, name)) for name in ATTR_FIELDS}


@dataclass(frozen=True)
class SemanticIndex:
    """A loaded, checked index: meta, unit float32 vectors, int64 keys, attrs."""

    meta: IndexMeta
    vectors: np.ndarray
    keys: np.ndarray
    attrs: IndexAttrs
    path: Path

    @property
    def rows(self) -> int:
        """Number of indexed listings."""
        return int(self.keys.shape[0])


def index_dir_for(root: Path, model: str, dims: int, as_of: date) -> Path:
    """`<root>/<model-slug>-<dims>/<active-as-of>` (slug: lowercase, ":" -> "-")."""
    slug = _SLUG.sub("-", model.lower()).strip("-")
    return root / f"{slug}-{dims}" / as_of.isoformat()


def inside(path: Path, root: Path) -> bool:
    """True when `path` is `root` or below it, as written and with links resolved."""
    plain = Path(os.path.abspath(path)).is_relative_to(Path(os.path.abspath(root)))
    return plain and Path(path).resolve().is_relative_to(Path(root).resolve())


def configured_index_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """IDX_SEMANTIC_INDEX_DIR as a path; a relative one resolves from the repo root."""
    value = (env_setting("IDX_SEMANTIC_INDEX_DIR", environ) or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def file_sha256(path: Path) -> str:
    """Hex sha256 of a file's bytes, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_with(path: Path, write: Callable[[BinaryIO], object]) -> None:
    """Write via `<name>.tmp` then rename, so a reader never sees half a file."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        write(handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _check_place(path: Path, model: str, data_root: Path) -> None:
    """Raise IndexUnavailable unless a non-test index is inside data_root, no link."""
    if model == TEST_MODEL:
        return
    if not inside(path, data_root):
        raise IndexUnavailable("outside_data", "index path is not inside data/")
    if Path(path).is_symlink():
        raise IndexUnavailable("symlink", "index path is a symbolic link")


def _unit_ok(vectors: np.ndarray) -> bool:
    """True when every row's length is 1 within UNIT_TOLERANCE.

    Checked UNIT_CHECK_ROWS rows at a time, stopping at the first bad chunk, so the
    peak memory stays near the vectors' own size. A NaN row fails.
    """
    for start in range(0, vectors.shape[0], UNIT_CHECK_ROWS):
        norms = np.linalg.norm(vectors[start : start + UNIT_CHECK_ROWS], axis=1)
        if not np.all(np.abs(norms - 1.0) <= UNIT_TOLERANCE):
            return False
    return True


def write_index(
    path: Path,
    *,
    vectors: np.ndarray,
    keys: np.ndarray,
    attrs: IndexAttrs,
    model: str,
    active_as_of: date,
    skipped_empty: int = 0,
    truncated: int = 0,
    redacted_inputs: int = 0,
    usage_tokens: int | None = None,
    max_chars: int = MAX_CHARS,
    text_prep_version: int = TEXT_PREP_VERSION,
    data_root: Path = DATA_ROOT,
    built_at: datetime | None = None,
) -> IndexMeta:
    """Write the arrays (sorted by key), hash them, then meta.json last; return meta.

    Refuses (ValueError) duplicate keys, non-unit rows, mismatched lengths, a
    non-test model outside data_root, and a directory that already has meta.json.
    """
    path = Path(path)
    try:
        _check_place(path, model, data_root)
    except IndexUnavailable as exc:
        raise ValueError(str(exc)) from None
    if (path / META).exists():
        raise ValueError("an index already exists here; it is never overwritten")
    vectors = np.ascontiguousarray(vectors, dtype=np.float32)
    keys = np.asarray(keys, dtype=np.int64)
    if vectors.ndim != 2 or keys.ndim != 1 or attrs.lengths() != {len(keys)}:
        raise ValueError("vectors, keys, and attrs disagree in shape")
    if vectors.shape[0] != len(keys):
        raise ValueError("vectors and keys disagree in row count")
    if not _unit_ok(vectors):
        raise ValueError("every vector must be unit length")
    order = np.argsort(keys, kind="stable")
    keys, vectors, attrs = keys[order], vectors[order], attrs.take(order)
    if len(keys) > 1 and not np.all(np.diff(keys) > 0):
        raise ValueError("listing keys must be unique")
    path.mkdir(parents=True, exist_ok=True)
    replace_with(path / VECTORS, lambda fh: np.save(fh, vectors, allow_pickle=False))
    replace_with(path / KEYS, lambda fh: np.save(fh, keys, allow_pickle=False))
    arrays = {name: getattr(attrs, name) for name in ATTR_FIELDS}
    replace_with(path / ATTRS, lambda fh: np.savez(fh, **arrays))
    meta = IndexMeta(
        format_version=FORMAT_VERSION,
        model=model,
        dims=int(vectors.shape[1]),
        rows=int(len(keys)),
        active_as_of=active_as_of,
        built_at=built_at or datetime.now(UTC),
        skipped_empty=skipped_empty,
        truncated=truncated,
        redacted_inputs=redacted_inputs,
        usage_tokens=usage_tokens,
        max_chars=max_chars,
        text_prep_version=text_prep_version,
        vectors_sha256=file_sha256(path / VECTORS),
        keys_sha256=file_sha256(path / KEYS),
        builder_version=BUILDER_VERSION,
        complete=True,
    )
    text = json.dumps(meta.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    replace_with(path / META, lambda fh: fh.write(text.encode("utf-8")))
    return meta


def read_meta(path: Path) -> IndexMeta:
    """Parse `<path>/meta.json`; IndexUnavailable (missing or bad_meta) otherwise."""
    try:
        raw = json.loads((Path(path) / META).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise IndexUnavailable("missing", "index has no meta.json") from None
    except (OSError, ValueError):
        raise IndexUnavailable("bad_meta", "meta.json is unreadable") from None
    if isinstance(raw, dict) and raw.get("complete") is not True:
        raise IndexUnavailable("incomplete", "index is not marked complete")
    if isinstance(raw, dict) and raw.get("format_version") != FORMAT_VERSION:
        raise IndexUnavailable("format_version", "unknown index format version")
    try:
        return IndexMeta.model_validate(raw)
    except ValidationError:
        raise IndexUnavailable(
            "bad_meta", "meta.json does not match the format"
        ) from None


def load_index(
    path: Path, expect_model: str, expect_dims: int, *, data_root: Path = DATA_ROOT
) -> SemanticIndex:
    """Load and check an index; raise IndexUnavailable naming the first failed check.

    Order: place (inside data/, no links; test:hashing exempt), files present, meta
    (complete, format, model, dims), row counts, key order, hashes, unit rows.
    """
    path = Path(path)
    _check_place(path, expect_model, data_root)
    if not path.is_dir():
        raise IndexUnavailable("missing", "index directory not found")
    for name in (VECTORS, KEYS, ATTRS, META):
        file = path / name
        if expect_model != TEST_MODEL and file.is_symlink():
            raise IndexUnavailable("symlink", "an index file is a symbolic link")
        if not file.is_file():
            raise IndexUnavailable("missing", "an index file is missing")
    meta = read_meta(path)
    if meta.model != expect_model:
        raise IndexUnavailable("model", "index was built with another model")
    if meta.dims != expect_dims:
        raise IndexUnavailable("dims", "index has another dimension")
    if file_sha256(path / VECTORS) != meta.vectors_sha256:
        raise IndexUnavailable("hash", "vectors.npy does not match its hash")
    if file_sha256(path / KEYS) != meta.keys_sha256:
        raise IndexUnavailable("hash", "keys.npy does not match its hash")
    try:
        vectors = np.load(path / VECTORS, allow_pickle=False)
        keys = np.load(path / KEYS, allow_pickle=False)
        with np.load(path / ATTRS, allow_pickle=False) as npz:
            attrs = IndexAttrs(*(npz[name] for name in ATTR_FIELDS))
    except (OSError, ValueError, KeyError):
        raise IndexUnavailable("bad_meta", "an index file is unreadable") from None
    rows = meta.rows
    shapes_ok = (
        vectors.ndim == 2
        and vectors.shape == (rows, meta.dims)
        and keys.shape == (rows,)
        and attrs.lengths() == {rows}
    )
    if not shapes_ok:
        raise IndexUnavailable("row_count", "index files disagree in row count")
    if vectors.dtype != np.float32 or keys.dtype != np.int64:
        raise IndexUnavailable("bad_meta", "index arrays have the wrong type")
    if rows > 1 and not np.all(np.diff(keys) > 0):
        raise IndexUnavailable("keys_order", "listing keys are not strictly ascending")
    if not _unit_ok(vectors):
        raise IndexUnavailable("not_unit", "a vector is not unit length")
    return SemanticIndex(meta=meta, vectors=vectors, keys=keys, attrs=attrs, path=path)


def _mask(index: SemanticIndex, filters: PropertySearchFilters) -> np.ndarray:
    """Boolean mask of rows passing the hard filters, from the index's snapshot values.

    Unknown values (-1, "") never pass a filter on that field, as NULL fails in SQL.
    Raises ValueError for a set filter the index cannot mask.
    """
    extra = {
        name
        for name, value in filters.model_dump(exclude=_PAGING).items()
        if value is not None and name not in _MASKED
    }
    if extra:
        raise ValueError(f"filters the index cannot apply: {sorted(extra)}")
    a = index.attrs
    mask = np.ones(index.rows, dtype=bool)
    if filters.city is not None:
        mask &= a.city == filters.city
    if filters.property_subtype is not None:
        mask &= a.property_subtype == filters.property_subtype
    if filters.min_price is not None:
        mask &= (a.list_price >= 0) & (a.list_price >= filters.min_price)
    if filters.max_price is not None:
        mask &= (a.list_price >= 0) & (a.list_price <= filters.max_price)
    if filters.min_beds is not None:
        mask &= (a.bedrooms >= 0) & (a.bedrooms >= filters.min_beds)
    return mask


def rank(
    index: SemanticIndex,
    query: np.ndarray,
    filters: PropertySearchFilters,
    top: int,
) -> list[tuple[int, float]]:
    """Pure cosine ranking: mask by the hard filters, then score the survivors.

    Scores are float32 dot products rounded to 6 decimals; order is score desc, then
    listing key asc. Returns up to `top` (listing_key, score) pairs. Raises
    ValueError for a query of the wrong width or not unit length (a zero row).
    """
    query = np.asarray(query, dtype=np.float32).reshape(-1)
    if query.shape[0] != index.meta.dims:
        raise ValueError("query vector width does not match the index")
    if abs(float(np.linalg.norm(query)) - 1.0) > UNIT_TOLERANCE:
        raise ValueError("query vector is not unit length (unusable text)")
    if top <= 0:
        return []
    rows = np.flatnonzero(_mask(index, filters))
    if rows.size == 0:
        return []
    # Score every row (one matrix-vector product, no copy of the matrix), then keep
    # the survivors; float32 products, rounded in float64 so ties are exact.
    scores = np.round((index.vectors @ query)[rows].astype(np.float64), 6)
    keys = index.keys[rows]
    order = np.lexsort((keys, -scores))[:top]
    return [(int(keys[i]), float(scores[i])) for i in order]


def rows_after_mask(index: SemanticIndex, filters: PropertySearchFilters) -> int:
    """How many index rows pass the hard filters (the result's rows_ranked)."""
    return int(np.count_nonzero(_mask(index, filters)))
