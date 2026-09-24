"""Semantic search over listing remarks (WO-010): embedders, the on-disk index, ranking.

Imported only when the similar-listings tool is first called, so the server starts
without NumPy or `openai`. Remark text is data for ranking only: never logged,
returned, or shown. The package never imports `idx_agent.memory` (stateless).
"""

from idx_agent.semantic.embedder import (
    DEFAULT_DIMS,
    DEFAULT_MODEL,
    MAX_CHARS,
    TEST_MODEL,
    Embedder,
    HashingEmbedder,
    OpenAIEmbedder,
    ProviderError,
    embed_settings,
    make_embedder,
    model_label,
    prepare_text,
)
from idx_agent.semantic.index import (
    IndexMeta,
    IndexUnavailable,
    SemanticIndex,
    configured_index_dir,
    load_index,
    rank,
    rows_after_mask,
    write_index,
)

__all__ = [
    "DEFAULT_DIMS",
    "DEFAULT_MODEL",
    "MAX_CHARS",
    "TEST_MODEL",
    "Embedder",
    "HashingEmbedder",
    "IndexMeta",
    "IndexUnavailable",
    "OpenAIEmbedder",
    "ProviderError",
    "SemanticIndex",
    "configured_index_dir",
    "embed_settings",
    "load_index",
    "make_embedder",
    "model_label",
    "prepare_text",
    "rank",
    "rows_after_mask",
    "write_index",
]
