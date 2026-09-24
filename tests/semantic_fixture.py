"""The CI fixture index (WO-010): a tiny `test:hashing` index of the fixture's own rows.

Rows come from tests/fixtures/make_synthetic.py (the same rows as synthetic.sql, no
database read), prepared exactly as the build prepares them, embedded with
HashingEmbedder, and written to a temporary directory. Never committed; not build_index.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from idx_agent.semantic.build_index import prepare_rows, records_to_arrays
from idx_agent.semantic.embedder import HASHING_DIMS, TEST_MODEL, HashingEmbedder
from idx_agent.semantic.index import META, write_index

__all__ = ["FIXTURE_DIMS", "build_fixture_index", "fixture_env", "fixture_rows"]

FIXTURE_DIMS = HASHING_DIMS
_GENERATOR = Path(__file__).resolve().parent / "fixtures" / "make_synthetic.py"


def _generator() -> ModuleType:
    """Load make_synthetic.py by path (tests/ is not a package)."""
    spec = importlib.util.spec_from_file_location("make_synthetic_rows", _GENERATOR)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load tests/fixtures/make_synthetic.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_rows() -> list[dict]:
    """Every active row the fixture writes, as column-name dicts."""
    return _generator().active_rows()


def build_fixture_index(tmp_path: Path) -> Path:
    """Write the fixture index under `tmp_path` and return its directory.

    Model `test:hashing` at 64 dims; meta carries the fixture's active as-of date
    (2026-09-18). Calling again for the same `tmp_path` returns the same index.
    """
    path = Path(tmp_path) / "semantic-index"
    if (path / META).exists():
        return path
    generator = _generator()
    records, stats, _ = prepare_rows(generator.active_rows())
    embedder = HashingEmbedder(FIXTURE_DIMS)
    keys, vectors, attrs = records_to_arrays(
        records, embedder.embed([r.text for r in records])
    )
    write_index(
        path,
        vectors=vectors,
        keys=keys,
        attrs=attrs,
        model=TEST_MODEL,
        active_as_of=generator.ACTIVE_ASOF.date(),
        skipped_empty=stats.skipped_empty + len(records) - len(keys),
        truncated=stats.truncated,
        redacted_inputs=stats.redacted,
    )
    return path


def fixture_env(path: Path) -> dict[str, str]:
    """The settings that point the tool at a fixture index."""
    return {
        "IDX_SEMANTIC_INDEX_DIR": str(path),
        "IDX_EMBED_MODEL": TEST_MODEL,
        "IDX_EMBED_DIMS": str(FIXTURE_DIMS),
    }
