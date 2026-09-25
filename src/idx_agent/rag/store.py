"""The on-disk document index (WO-012): write, and load with every check.

One folder under the gitignored data/indexes/docs/: chunks.jsonl, vectors.npy (hybrid
only), then meta.json written last. Only a test index (the `test:hashing` model, or a
fixture corpus in a temporary or tests/ folder) may live outside data/. BM25
statistics are rebuilt at load; floor settings may replace the meta's floors.
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError

from idx_agent.db.pool import env_setting
from idx_agent.rag.chunk import Chunk
from idx_agent.rag.lexical import BM25Stats, bm25_stats
from idx_agent.rag.sources import SOURCES
from idx_agent.rag.vectors import unit_rows_ok
from idx_agent.semantic.embedder import TEST_MODEL, TEXT_PREP_VERSION
from idx_agent.semantic.index import REPO_ROOT, file_sha256, inside, replace_with

__all__ = [
    "CHUNKS",
    "DATA_ROOT",
    "DEFAULT_OUT_ROOT",
    "FLOOR_SETTINGS",
    "FORMAT_VERSION",
    "META",
    "VECTORS",
    "DocIndex",
    "DocIndexMeta",
    "DocIndexUnavailable",
    "Route",
    "SourceMeta",
    "floor_settings",
    "load_doc_index",
    "read_doc_meta",
    "in_test_folder",
    "write_doc_index",
]

FORMAT_VERSION = 1
DATA_ROOT = REPO_ROOT / "data"
DEFAULT_OUT_ROOT = DATA_ROOT / "indexes" / "docs"
CHUNKS, META, VECTORS = "chunks.jsonl", "meta.json", "vectors.npy"
Route = Literal["bm25", "hybrid"]
# Optional settings that replace the meta's not-found floors at load (no rebuild).
FLOOR_SETTINGS = {
    "floor_bm25": "IDX_RAG_FLOOR_BM25",
    "floor_cosine": "IDX_RAG_FLOOR_COSINE",
}


class DocIndexUnavailable(RuntimeError):
    """No usable document index at a path; `cause` names the failed check.

    Causes: missing, outside_data, symlink, bad_meta, incomplete, format_version,
    floor_setting, hash, row_count, dims, not_unit.
    """

    def __init__(self, cause: str, message: str | None = None) -> None:
        super().__init__(message or f"document index unavailable: {cause}")
        self.cause = cause


class SourceMeta(BaseModel):
    """One source as built: its file (or folder) hash and its chunk count."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str
    chunks: int
    confidential: bool


class DocIndexMeta(BaseModel):
    """meta.json: how and when the index was built; counts and hashes, never text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int
    route: Route
    built_at: date
    sources: dict[str, SourceMeta]
    drops: dict[str, dict[str, int]]
    floor_bm25: float
    floor_cosine: float
    text_prep_version: int
    model: str | None = None
    dims: int | None = None
    rows: int
    chunks_sha256: str
    vectors_sha256: str | None = None
    usage_tokens: int | None = None
    # Top cosines of the five calibration questions, by question id (numbers only).
    calibration: dict[str, float] | None = None
    # Test-only: a fixture corpus index, honoured in a temporary or tests/ folder only.
    test_corpus: bool = False
    complete: bool

    @property
    def is_test(self) -> bool:
        """A test index (hashing model or fixture corpus): may sit outside data/."""
        return self.test_corpus or self.model == TEST_MODEL


def in_test_folder(path: Path) -> bool:
    """True for a folder a fixture-corpus index may use: under the system's temporary
    folder or this checkout's tests/ (links resolved)."""
    resolved = Path(path).resolve()
    roots = (Path(tempfile.gettempdir()).resolve(), (REPO_ROOT / "tests").resolve())
    return any(resolved.is_relative_to(root) for root in roots)


def floor_settings(environ: Mapping[str, str] | None = None) -> dict[str, float]:
    """The floors IDX_RAG_FLOOR_BM25 and IDX_RAG_FLOOR_COSINE set (environment, then
    .env), by meta field; unset or empty ones are left out. ValueError for a value
    that is not a finite number."""
    floors: dict[str, float] = {}
    for name, setting in FLOOR_SETTINGS.items():
        value = (env_setting(setting, environ) or "").strip()
        if not value:
            continue
        number = float(value)
        if not np.isfinite(number):
            raise ValueError(f"{setting} is not a finite number")
        floors[name] = number
    return floors


@dataclass(frozen=True)
class DocIndex:
    """A loaded, checked index: chunks in order, meta, BM25 stats, vectors or None."""

    chunks: list[Chunk]
    meta: DocIndexMeta
    lexical: BM25Stats
    vectors: np.ndarray | None
    path: Path


def _chunk_line(chunk: Chunk) -> str:
    record = {
        "doc": chunk.doc,
        "key": chunk.key,
        "page": chunk.page,
        "text": chunk.text,
        "confidential": chunk.confidential,
        "label": chunk.label,
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def write_doc_index(
    path: Path,
    chunks: Sequence[Chunk],
    *,
    route: Route,
    source_hashes: Mapping[str, str],
    drops: Mapping[str, Mapping[str, int]],
    floor_bm25: float,
    floor_cosine: float,
    vectors: np.ndarray | None = None,
    model: str | None = None,
    usage_tokens: int | None = None,
    calibration: Mapping[str, float] | None = None,
    test_corpus: bool = False,
    data_root: Path = DATA_ROOT,
    built_at: date | None = None,
) -> DocIndexMeta:
    """Write chunks.jsonl, vectors.npy (hybrid), then meta.json last; return meta.

    Refuses (ValueError): a non-test index outside data_root, a test corpus outside
    a temporary or tests/ folder, an existing meta.json, vectors on a bm25 index or
    none on a hybrid one, rows that disagree or are not unit length, a source hash
    missing for a source with chunks.
    """
    path = Path(path)
    is_test = test_corpus or model == TEST_MODEL
    if not is_test and not inside(path, data_root):
        raise ValueError("the index path is not inside the repo's data/ folder")
    if test_corpus and not in_test_folder(path):
        raise ValueError("a test-corpus index lives in a temporary or tests/ folder")
    if (path / META).exists():
        raise ValueError("an index already exists here; it is never overwritten")
    if (route == "hybrid") != (vectors is not None) or (route == "hybrid") != bool(
        model
    ):
        raise ValueError("a hybrid index has vectors and a model; a bm25 one neither")
    counts = Counter(chunk.doc for chunk in chunks)
    if set(counts) - set(source_hashes):
        raise ValueError("every source with chunks needs its hash")
    dims = None
    if vectors is not None:
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
            raise ValueError("vectors and chunks disagree in row count")
        if not unit_rows_ok(vectors):
            raise ValueError("every vector must be unit length")
        dims = int(vectors.shape[1])
    path.mkdir(parents=True, exist_ok=True)
    text = "".join(_chunk_line(chunk) + "\n" for chunk in chunks)
    replace_with(path / CHUNKS, lambda fh: fh.write(text.encode("utf-8")))
    if vectors is not None:
        replace_with(
            path / VECTORS, lambda fh: np.save(fh, vectors, allow_pickle=False)
        )
    meta = DocIndexMeta(
        format_version=FORMAT_VERSION,
        route=route,
        built_at=built_at or datetime.now(UTC).date(),
        sources={
            source_id: SourceMeta(
                sha256=sha,
                chunks=counts.get(source_id, 0),
                confidential=SOURCES[source_id].confidential,
            )
            for source_id, sha in source_hashes.items()
        },
        drops={name: dict(per) for name, per in drops.items()},
        floor_bm25=float(floor_bm25),
        floor_cosine=float(floor_cosine),
        text_prep_version=TEXT_PREP_VERSION,
        model=model,
        dims=dims,
        rows=len(chunks),
        chunks_sha256=file_sha256(path / CHUNKS),
        vectors_sha256=file_sha256(path / VECTORS) if vectors is not None else None,
        usage_tokens=usage_tokens,
        calibration=dict(calibration) if calibration is not None else None,
        test_corpus=test_corpus,
        complete=True,
    )
    body = json.dumps(meta.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    replace_with(path / META, lambda fh: fh.write(body.encode("utf-8")))
    return meta


def read_doc_meta(path: Path) -> DocIndexMeta:
    """Parse `<path>/meta.json`; DocIndexUnavailable (missing, bad_meta, incomplete,
    format_version) otherwise."""
    try:
        raw = json.loads((Path(path) / META).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DocIndexUnavailable("missing", "index has no meta.json") from None
    except (OSError, ValueError):
        raise DocIndexUnavailable("bad_meta", "meta.json is unreadable") from None
    if isinstance(raw, dict) and raw.get("complete") is not True:
        raise DocIndexUnavailable("incomplete", "index is not marked complete")
    if isinstance(raw, dict) and raw.get("format_version") != FORMAT_VERSION:
        raise DocIndexUnavailable("format_version", "unknown index format version")
    try:
        return DocIndexMeta.model_validate(raw)
    except ValidationError:
        raise DocIndexUnavailable(
            "bad_meta", "meta.json does not match the format"
        ) from None


def _read_chunks(file: Path) -> list[Chunk]:
    """Chunks from chunks.jsonl; `confidential` is taken from the registry."""
    chunks: list[Chunk] = []
    try:
        for line in file.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            source = SOURCES.get(record["doc"])
            if source is None:
                raise DocIndexUnavailable("bad_meta", "a chunk names an unknown source")
            page = record.get("page")
            chunks.append(
                Chunk(
                    doc=source.id,
                    key=str(record["key"]),
                    page=int(page) if page is not None else None,
                    text=str(record["text"]),
                    confidential=source.confidential,
                    label=str(record["label"]),
                )
            )
    except (OSError, ValueError, KeyError, TypeError):
        raise DocIndexUnavailable("bad_meta", "chunks.jsonl is unreadable") from None
    return chunks


def load_doc_index(
    path: Path,
    data_root: Path = DATA_ROOT,
    environ: Mapping[str, str] | None = None,
) -> DocIndex:
    """Load and check an index; raise DocIndexUnavailable naming the first failed check.

    Order: folder, meta, floor settings (applied over the meta's), place, files,
    hashes, row counts, vectors (shape, type, unit). Causes are listed on the class.
    """
    path = Path(path)
    if not path.is_dir():
        raise DocIndexUnavailable("missing", "index directory not found")
    meta = read_doc_meta(path)
    try:
        meta = meta.model_copy(update=floor_settings(environ))
    except ValueError:
        raise DocIndexUnavailable(
            "floor_setting", "a floor setting is not a number"
        ) from None
    if meta.test_corpus and not in_test_folder(path):
        raise DocIndexUnavailable("outside_data", "a test corpus outside a test folder")
    if not meta.is_test:
        if not inside(path, data_root):
            raise DocIndexUnavailable("outside_data", "index path is not inside data/")
        if path.is_symlink():
            raise DocIndexUnavailable("symlink", "index path is a symbolic link")
    names = [CHUNKS, META] + ([VECTORS] if meta.route == "hybrid" else [])
    for name in names:
        file = path / name
        if not meta.is_test and file.is_symlink():
            raise DocIndexUnavailable("symlink", "an index file is a symbolic link")
        if not file.is_file():
            raise DocIndexUnavailable("missing", "an index file is missing")
    if file_sha256(path / CHUNKS) != meta.chunks_sha256:
        raise DocIndexUnavailable("hash", "chunks.jsonl does not match its hash")
    chunks = _read_chunks(path / CHUNKS)
    counts = Counter(chunk.doc for chunk in chunks)
    by_meta = {sid: s.chunks for sid, s in meta.sources.items() if s.chunks}
    if len(chunks) != meta.rows or dict(counts) != by_meta:
        raise DocIndexUnavailable("row_count", "chunk counts disagree with meta")
    vectors = None
    if meta.route == "hybrid":
        if file_sha256(path / VECTORS) != meta.vectors_sha256:
            raise DocIndexUnavailable("hash", "vectors.npy does not match its hash")
        try:
            vectors = np.load(path / VECTORS, allow_pickle=False)
        except (OSError, ValueError):
            raise DocIndexUnavailable("bad_meta", "vectors.npy is unreadable") from None
        if vectors.dtype != np.float32 or vectors.ndim != 2:
            raise DocIndexUnavailable("bad_meta", "vectors.npy has the wrong type")
        if vectors.shape[0] != meta.rows:
            raise DocIndexUnavailable("row_count", "vectors and chunks disagree")
        if vectors.shape[1] != meta.dims:
            raise DocIndexUnavailable("dims", "vectors have another dimension")
        if not unit_rows_ok(vectors):
            raise DocIndexUnavailable("not_unit", "a vector is not unit length")
    lexical = bm25_stats([chunk.text for chunk in chunks])
    return DocIndex(
        chunks=chunks, meta=meta, lexical=lexical, vectors=vectors, path=path
    )
