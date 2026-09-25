"""The fixture document index (WO-012): the own-words corpus under tests/fixtures/docs/.

The invented field reference and primer stand in for the two PDFs, with the tracked
schema notes and glossary; built with the real chunker and store (bm25, or hybrid
with test:hashing) in a temporary folder. No PDF read, nothing paid."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from idx_agent.rag.chunk import Chunk, build_chunks
from idx_agent.rag.sources import SOURCES
from idx_agent.rag.store import META, write_doc_index
from idx_agent.semantic.embedder import HASHING_DIMS, TEST_MODEL, HashingEmbedder
from idx_agent.semantic.index import file_sha256

__all__ = [
    "BUILT_AT",
    "CORPUS",
    "FIXTURE_DIMS",
    "FLOOR_BM25",
    "FLOOR_COSINE",
    "PAGE_BREAK",
    "SENTINELS",
    "build_fixture_index",
    "fixture_chunks",
    "fixture_env",
    "fixture_pages",
]

CORPUS = Path(__file__).resolve().parent / "fixtures" / "docs"
# The fixture files mark a page end with this line (the PDFs' page breaks).
PAGE_BREAK = "---- page break ----"
# Stand-ins for the two PDFs; the other sources are the real tracked files.
FIXTURE_FILES = {"trestle": "field_reference.txt", "primer": "primer.txt"}
FIXTURE_DIMS = HASHING_DIMS
BUILT_AT = date(2026, 9, 24)
# The descriptions of the agent-contact, deny-listed, and agent-related fixture
# entries: never indexed.
SENTINELS = (
    "SENTINEL-AGENT-CONTACT-QX7",
    "SENTINEL-DENY-LISTED-KV3",
    "SENTINEL-AGENT-RELATED-ZP4",
)
# Not-found floors for this corpus (tests/test_rag_cases.py checks the gap): BM25's is
# the midpoint, rounded down, of the off-topic ci questions' best top score (5.352) and
# the lowest top of a found ci question with no exact hit (6.665, rag-ci-008).
FLOOR_BM25 = 6.00
# Hashing cosines follow shared hashed words, not meaning: an off-topic question
# scores above an on-topic one here, so no cosine floor separates them and this one
# is out of reach; on the fixture, exact names and BM25 alone decide "found".
FLOOR_COSINE = 1.01


def _split_pages(text: str) -> list[str]:
    """Pages of a fixture file, split at the PAGE_BREAK lines."""
    pages: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip() == PAGE_BREAK:
            pages.append([])
        else:
            pages[-1].append(line)
    return ["\n".join(page) for page in pages]


def _source_files() -> dict[str, Path]:
    """The file each fixture source is read from."""
    files = {sid: CORPUS / name for sid, name in FIXTURE_FILES.items()}
    files.update({sid: SOURCES[sid].path for sid in ("schema_notes", "glossary")})
    return files


def fixture_pages() -> dict[str, list[str]]:
    """Page texts per source id: the fixture files by page, the markdown files whole."""
    pages: dict[str, list[str]] = {}
    for sid, path in _source_files().items():
        text = path.read_text(encoding="utf-8")
        pages[sid] = _split_pages(text) if sid in FIXTURE_FILES else [text]
    return pages


def fixture_chunks() -> list[Chunk]:
    """The chunks the fixture index holds, in index order."""
    return build_chunks(fixture_pages())[0]


def build_fixture_index(tmp_path: Path, route: str = "bm25") -> Path:
    """Write the fixture index under `tmp_path` and return its folder.

    `route` "hybrid" adds test:hashing vectors (64 dims). Calling again for the same
    `tmp_path` and route returns the same index.
    """
    if route not in ("bm25", "hybrid"):
        raise ValueError(f"unknown route {route!r}")
    path = Path(tmp_path) / f"rag-index-{route}"
    if (path / META).exists():
        return path
    chunks, drops = build_chunks(fixture_pages())
    vectors, model = None, None
    if route == "hybrid":
        embedder = HashingEmbedder(FIXTURE_DIMS)
        # Imported here: the vector helpers are needed for the hybrid route only.
        from idx_agent.rag.vectors import embed_chunks

        vectors, _ = embed_chunks(chunks, embedder)
        model = TEST_MODEL
    write_doc_index(
        path,
        chunks,
        route=route,  # type: ignore[arg-type]
        source_hashes={sid: file_sha256(p) for sid, p in _source_files().items()},
        drops=drops.as_dict(),
        floor_bm25=FLOOR_BM25,
        floor_cosine=FLOOR_COSINE,
        vectors=vectors,
        model=model,
        test_corpus=True,
        built_at=BUILT_AT,
    )
    return path


def fixture_env(path: Path) -> dict[str, str]:
    """The settings that point the tool at a fixture index and keep its own floors:
    the floor settings set empty, so a real floor in .env cannot replace them (the
    environment wins over .env even when empty). A hybrid index's embedder comes
    from its meta."""
    return {
        "IDX_RAG_INDEX_DIR": str(path),
        "IDX_RAG_FLOOR_BM25": "",
        "IDX_RAG_FLOOR_COSINE": "",
    }
