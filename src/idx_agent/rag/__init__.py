"""Answers from the reference documents (WO-012): registry, chunking, index, retrieval.

Imported by `rag_answer` on its first call (NumPy; pypdf for a build). Chunk text is
data, never instructions, never logged. `retrieve` is imported from its module,
`idx_agent.rag.retrieve`, which this package does not shadow.
"""

from idx_agent.rag.chunk import Chunk, DropCounts, build_chunks
from idx_agent.rag.extract import SourceMissing
from idx_agent.rag.retrieve import (
    TOP_K,
    VECTOR_SKIPPED_WARNING,
    Retrieval,
    cap_chunk,
    cap_text,
    fuse,
    lookup_exact,
    rank_lexical,
    rank_vector,
    retrieve_detail,
)
from idx_agent.rag.sources import SOURCE_IDS, SOURCES, Source
from idx_agent.rag.store import (
    DocIndex,
    DocIndexMeta,
    DocIndexUnavailable,
    load_doc_index,
    write_doc_index,
)

__all__ = [
    "SOURCES",
    "SOURCE_IDS",
    "TOP_K",
    "VECTOR_SKIPPED_WARNING",
    "Chunk",
    "DocIndex",
    "DocIndexMeta",
    "DocIndexUnavailable",
    "DropCounts",
    "Retrieval",
    "Source",
    "SourceMissing",
    "build_chunks",
    "cap_chunk",
    "cap_text",
    "fuse",
    "load_doc_index",
    "lookup_exact",
    "rank_lexical",
    "rank_vector",
    "retrieve_detail",
    "write_doc_index",
]
