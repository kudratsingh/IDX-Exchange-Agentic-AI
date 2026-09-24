"""Unit tests for semantic/index.py (WO-010): write, load, every refusal, and ranking.

Tiny hand-written vectors (3 or 4 dims) and a temporary `data/` root; no database.
Also checks the CI fixture index helper (tests/semantic_fixture.py) end to end.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from tests.semantic_fixture import FIXTURE_DIMS, build_fixture_index, fixture_env

from idx_agent.domain.models import PropertySearchFilters
from idx_agent.semantic.index import (
    IndexAttrs,
    IndexUnavailable,
    configured_index_dir,
    file_sha256,
    index_dir_for,
    load_index,
    rank,
    rows_after_mask,
    write_index,
)

REAL = "openai:text-embedding-3-small"
AS_OF = date(2026, 9, 18)
SFR, CONDO = "SingleFamilyResidence", "Condominium"


def _unit(*values: float) -> list[float]:
    """A unit row from raw values."""
    row = np.asarray(values, dtype=np.float32)
    return list(row / np.linalg.norm(row))


# Five invented listings: key, vector, city, price, beds, subtype.
ROWS = [
    (105, _unit(1, 0, 0), "Pasadena", 900_000, 3, SFR),
    (101, _unit(0.9, 0.1, 0), "Pasadena", 1_400_000, 4, SFR),
    (103, _unit(0, 1, 0), "Glendale", 650_000, 2, CONDO),
    (102, _unit(1, 0, 0), "Glendale", None, None, SFR),
    (104, _unit(0.6, 0.8, 0), "Pasadena", 700_000, 2, CONDO),
]


def _parts(rows=ROWS):
    """Arrays for write_index from ROWS-shaped tuples."""
    keys = np.array([r[0] for r in rows], dtype=np.int64)
    vectors = np.array([r[1] for r in rows], dtype=np.float32)
    attrs = IndexAttrs.from_values(
        [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows],
        [r[5] for r in rows],
    )  # fmt: skip
    return keys, vectors, attrs


def _write(path: Path, model: str = "test:hashing", data_root: Path | None = None):
    """Write the ROWS index at `path`; returns its meta."""
    keys, vectors, attrs = _parts()
    extra = {} if data_root is None else {"data_root": data_root}
    return write_index(
        path, vectors=vectors, keys=keys, attrs=attrs, model=model,
        active_as_of=AS_OF, skipped_empty=2, truncated=1, **extra,
    )  # fmt: skip


@pytest.fixture
def index(tmp_path):
    """A loaded test:hashing index of ROWS (3 dims)."""
    _write(tmp_path / "idx")
    return load_index(tmp_path / "idx", "test:hashing", 3)


# --- write and load ---


def test_round_trip_sorts_by_key_and_keeps_attrs(index):
    assert index.keys.tolist() == [101, 102, 103, 104, 105]
    assert index.vectors.dtype == np.float32 and index.vectors.shape == (5, 3)
    assert index.attrs.city.tolist()[:3] == ["Pasadena", "Glendale", "Glendale"]
    assert index.attrs.list_price.tolist()[1] == -1
    assert index.attrs.bedrooms.tolist()[1] == -1
    meta = index.meta
    assert (meta.rows, meta.dims, meta.model) == (5, 3, "test:hashing")
    assert meta.active_as_of == AS_OF and meta.complete is True
    assert (meta.skipped_empty, meta.truncated, meta.format_version) == (2, 1, 1)
    assert meta.source_table == "rets_property" and meta.source_column == "L_Remarks"


def test_meta_json_holds_no_key_and_no_text(tmp_path):
    _write(tmp_path / "idx")
    raw = (tmp_path / "idx" / "meta.json").read_text(encoding="utf-8")
    # The two hashes and the timestamp are random digits that can spell a short
    # key by chance, so the key scan runs over every other field's text.
    meta = json.loads(raw)
    scanned = json.dumps(
        {
            k: v
            for k, v in meta.items()
            if k not in ("vectors_sha256", "keys_sha256", "built_at")
        },
        separators=(",", ":"),
    )
    for key, *_ in ROWS:
        assert str(key) not in scanned
    for city in ("Pasadena", "Glendale"):
        assert city not in raw
    assert set(json.loads(raw)) == {
        "format_version", "model", "dims", "rows", "source_table", "source_column",
        "active_as_of", "built_at", "skipped_empty", "truncated", "redacted_inputs",
        "usage_tokens", "max_chars", "text_prep_version", "vectors_sha256",
        "keys_sha256", "builder_version", "complete",
    }  # fmt: skip


def test_real_model_round_trip_inside_data(tmp_path):
    data = tmp_path / "data"
    path = index_dir_for(data / "indexes" / "remarks", REAL, 3, AS_OF)
    _write(path, REAL, data)
    assert path.parts[-2:] == ("openai-text-embedding-3-small-3", "2026-09-18")
    loaded = load_index(path, REAL, 3, data_root=data)
    assert loaded.rows == 5


def test_write_refuses_bad_input(tmp_path):
    keys, vectors, attrs = _parts()
    common = {"model": "test:hashing", "active_as_of": AS_OF}
    with pytest.raises(ValueError, match="unique"):
        write_index(tmp_path / "a", vectors=vectors, keys=np.array([1, 1, 2, 3, 4]),
                    attrs=attrs, **common)  # fmt: skip
    with pytest.raises(ValueError, match="unit"):
        write_index(
            tmp_path / "b", vectors=vectors * 2, keys=keys, attrs=attrs, **common
        )
    with pytest.raises(ValueError, match="shape"):
        write_index(
            tmp_path / "c", vectors=vectors, keys=keys[:4], attrs=attrs, **common
        )
    with pytest.raises(ValueError, match="data/"):
        _write(tmp_path / "d", REAL, tmp_path / "data")
    _write(tmp_path / "e")
    with pytest.raises(ValueError, match="never overwritten"):
        _write(tmp_path / "e")


# --- every IndexUnavailable cause ---


def _cause(path, model="test:hashing", dims=3, **kwargs) -> str:
    """The cause load_index raises for `path`."""
    with pytest.raises(IndexUnavailable) as info:
        load_index(path, model, dims, **kwargs)
    return info.value.cause


def _edit_meta(path: Path, **changes) -> None:
    """Rewrite fields of meta.json in place."""
    meta = json.loads((path / "meta.json").read_text())
    meta.update(changes)
    (path / "meta.json").write_text(json.dumps(meta))


def _replace_array(path: Path, name: str, array: np.ndarray) -> None:
    """Swap one array file and fix its hash, so a later check is reached."""
    np.save(path / name, array, allow_pickle=False)
    field = "vectors_sha256" if name == "vectors.npy" else "keys_sha256"
    _edit_meta(path, **{field: file_sha256(path / name)})


def test_missing_directory_or_file(tmp_path):
    assert _cause(tmp_path / "nowhere") == "missing"
    _write(tmp_path / "idx")
    (tmp_path / "idx" / "attrs.npz").rename(tmp_path / "attrs.npz")
    assert _cause(tmp_path / "idx") == "missing"


def test_real_model_outside_data_or_through_a_link(tmp_path):
    data = tmp_path / "data"
    outside = tmp_path / "elsewhere"
    _write(outside, "test:hashing")
    _edit_meta(outside, model=REAL)
    assert _cause(outside, REAL, data_root=data) == "outside_data"
    data.mkdir()
    (data / "link").symlink_to(outside)
    assert _cause(data / "link", REAL, data_root=data) == "outside_data"
    inner = data / "real"
    _write(inner, REAL, data)
    (data / "alias").symlink_to(inner)
    assert _cause(data / "alias", REAL, data_root=data) == "symlink"


@pytest.mark.parametrize(
    ("changes", "cause"),
    [
        ({"complete": False}, "incomplete"),
        ({"format_version": 2}, "format_version"),
        ({"model": "openai:other"}, "model"),
        ({"dims": 4}, "dims"),
        ({"rows": 6}, "row_count"),
        ({"vectors_sha256": "0" * 64}, "hash"),
        ({"keys_sha256": "0" * 64}, "hash"),
    ],
)
def test_meta_checks(tmp_path, changes, cause):
    _write(tmp_path / "idx")
    _edit_meta(tmp_path / "idx", **changes)
    assert _cause(tmp_path / "idx") == cause


def test_dims_mismatch_against_the_configured_value(tmp_path):
    _write(tmp_path / "idx")
    assert _cause(tmp_path / "idx", dims=1536) == "dims"


def test_unreadable_meta(tmp_path):
    _write(tmp_path / "idx")
    (tmp_path / "idx" / "meta.json").write_text("{not json")
    assert _cause(tmp_path / "idx") == "bad_meta"


def test_row_counts_that_disagree_across_files(tmp_path):
    path = tmp_path / "idx"
    _write(path)
    _replace_array(path, "keys.npy", np.array([101, 102, 103, 104], dtype=np.int64))
    assert _cause(path) == "row_count"


def test_keys_not_strictly_ascending(tmp_path):
    path = tmp_path / "idx"
    _write(path)
    _replace_array(path, "keys.npy", np.array([101, 103, 102, 104, 105], np.int64))
    assert _cause(path) == "keys_order"
    _replace_array(path, "keys.npy", np.array([101, 101, 102, 104, 105], np.int64))
    assert _cause(path) == "keys_order"


def test_a_vector_that_is_not_unit_length(tmp_path):
    path = tmp_path / "idx"
    _write(path)
    vectors = np.load(path / "vectors.npy")
    vectors[2] *= 1.01
    _replace_array(path, "vectors.npy", vectors)
    assert _cause(path) == "not_unit"


def test_a_changed_vector_file_fails_its_hash(tmp_path):
    path = tmp_path / "idx"
    _write(path)
    vectors = np.load(path / "vectors.npy")
    np.save(path / "vectors.npy", vectors[::-1].copy(), allow_pickle=False)
    assert _cause(path) == "hash"


# --- ranking ---

NO_FILTERS = PropertySearchFilters()


def test_known_order_with_a_tie_broken_by_the_lower_key(index):
    ranked = rank(index, np.array(_unit(1, 0, 0)), NO_FILTERS, 5)
    # 102 and 105 are identical vectors: the lower key comes first.
    assert [k for k, _ in ranked] == [102, 105, 101, 104, 103]
    assert ranked[0][1] == ranked[1][1] == 1.0
    assert ranked[-1][1] == 0.0
    assert all(round(s, 6) == s for _, s in ranked)


def test_ranking_is_the_same_on_every_run(index):
    query = np.array(_unit(0.3, 0.7, 0.1))
    assert rank(index, query, NO_FILTERS, 5) == rank(index, query, NO_FILTERS, 5)


@pytest.mark.parametrize(
    ("filters", "keys"),
    [
        ({"city": "glendale"}, [102, 103]),
        ({"max_price": 900_000}, [105, 104, 103]),
        ({"min_price": 800_000}, [105, 101]),
        ({"min_beds": 3}, [105, 101]),
        ({"min_beds": 0}, [105, 101, 104, 103]),
        ({"property_subtype": CONDO}, [104, 103]),
        ({"city": "Pasadena", "max_price": 950_000, "min_beds": 3}, [105]),
    ],
)
def test_each_hard_filter_masks_rows(index, filters, keys):
    applied = PropertySearchFilters(**filters)
    ranked = rank(index, np.array(_unit(1, 0, 0)), applied, 10)
    assert [k for k, _ in ranked] == keys
    assert rows_after_mask(index, applied) == len(keys)


def test_a_mask_that_leaves_nothing_and_top_limits(index):
    query = np.array(_unit(1, 0, 0))
    empty = PropertySearchFilters(city="Pasadena", property_subtype=CONDO, min_beds=5)
    assert rank(index, query, empty, 5) == []
    assert rows_after_mask(index, empty) == 0
    assert len(rank(index, query, NO_FILTERS, 50)) == 5
    assert len(rank(index, query, NO_FILTERS, 2)) == 2
    assert rank(index, query, NO_FILTERS, 0) == []


def test_rank_refuses_an_unusable_query_or_filter(index):
    with pytest.raises(ValueError, match="unit"):
        rank(index, np.zeros(3, dtype=np.float32), NO_FILTERS, 5)
    with pytest.raises(ValueError, match="width"):
        rank(index, np.array(_unit(1, 0, 0, 0)), NO_FILTERS, 5)
    with pytest.raises(ValueError, match="cannot apply"):
        rank(index, np.array(_unit(1, 0, 0)), PropertySearchFilters(pool=True), 5)


def test_page_and_limit_are_not_filters(index):
    paged = PropertySearchFilters(page=3, limit=40)
    assert len(rank(index, np.array(_unit(1, 0, 0)), paged, 5)) == 5


# --- settings and the CI fixture index ---


def test_configured_index_dir(tmp_path):
    assert configured_index_dir({}) is None
    assert configured_index_dir({"IDX_SEMANTIC_INDEX_DIR": str(tmp_path)}) == tmp_path
    relative = configured_index_dir({"IDX_SEMANTIC_INDEX_DIR": "data/indexes/x"})
    assert relative is not None and relative.is_absolute()
    assert relative.parts[-3:] == ("data", "indexes", "x")


def test_fixture_index_loads_with_the_fixture_as_of(tmp_path):
    path = build_fixture_index(tmp_path)
    assert build_fixture_index(tmp_path) == path  # a second call reuses it
    loaded = load_index(path, "test:hashing", FIXTURE_DIMS)
    assert loaded.meta.active_as_of == date(2026, 9, 18)
    assert loaded.meta.model == "test:hashing" and loaded.rows > 0
    env = fixture_env(path)
    assert env["IDX_EMBED_MODEL"] == "test:hashing"
    assert env["IDX_SEMANTIC_INDEX_DIR"] == str(path)
