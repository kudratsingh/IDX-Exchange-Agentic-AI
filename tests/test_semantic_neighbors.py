"""Neighbor ranking over the index (WO-011) on tiny hand-written unit vectors.

The subject's own stored vector is the query: no embedder is built. Checks the
subject's removal, the city, subtype, and both price edges of the mask, WO-010's
rounding and tiebreak, and SubjectNotIndexed for a key with no vector."""

from datetime import date

import numpy as np
import pytest

from idx_agent.db.listings import SearchOutcome
from idx_agent.domain.models import Listing, PropertySearchFilters
from idx_agent.semantic.index import IndexAttrs, load_index, rank, write_index
from idx_agent.semantic.neighbors import (
    SubjectNotIndexed,
    neighbor_filters,
    rank_neighbors,
    subject_row,
    subject_vector,
)
from idx_agent.semantic.query import fetch_in_rank_order

SUBJECT = 100
SFR = "SingleFamilyResidence"
# The subject's band at 1,000,000: 750,000 to 1,250,000, both ends included.
LOW, HIGH = 750_000, 1_250_000
# key -> (vector, city, subtype, list price). 3-4-5 triangles keep rows unit length.
ROWS = {
    99: ([0.0, 1.0, 0.0], "Pasadena", SFR, 1_000_000),  # score 0, last
    100: ([1.0, 0.0, 0.0], "Pasadena", SFR, 1_000_000),  # the subject
    101: ([0.8, 0.6, 0.0], "Pasadena", SFR, LOW),  # lower edge, in; score 0.8
    102: ([0.6, 0.8, 0.0], "Pasadena", SFR, HIGH),  # upper edge, in; score 0.6
    103: ([1.0, 0.0, 0.0], "Pasadena", SFR, LOW - 1),  # below the band
    104: ([1.0, 0.0, 0.0], "Pasadena", SFR, HIGH + 1),  # above the band
    105: ([1.0, 0.0, 0.0], "Monrovia", SFR, 1_000_000),  # another city
    106: ([1.0, 0.0, 0.0], "Pasadena", "Condominium", 1_000_000),  # another type
    107: ([0.8, 0.0, 0.6], "Pasadena", SFR, 900_000),  # ties 101 at 0.8
    108: ([1.0, 0.0, 0.0], "Pasadena", SFR, None),  # unknown price never passes
}


@pytest.fixture
def index(tmp_path):
    keys = sorted(ROWS)
    write_index(
        tmp_path / "idx",
        vectors=np.array([ROWS[k][0] for k in keys], dtype=np.float32),
        keys=keys,
        attrs=IndexAttrs.from_values(
            city=[ROWS[k][1] for k in keys],
            list_price=[ROWS[k][3] for k in keys],
            bedrooms=[3] * len(keys),
            property_subtype=[ROWS[k][2] for k in keys],
        ),
        model="test:hashing",
        active_as_of=date(2026, 9, 18),
    )
    return load_index(tmp_path / "idx", "test:hashing", 3)


def _neighbors(index, top=200, key=SUBJECT):
    return rank_neighbors(index, key, "Pasadena", SFR, LOW, HIGH, top)


def test_the_ranking_is_masked_ordered_and_leaves_out_the_subject(index):
    assert _neighbors(index) == [(101, 0.8), (107, 0.8), (102, 0.6), (99, 0.0)]


def test_the_subject_is_never_in_its_own_result(index):
    """It passes its own mask and scores 1.0, the best possible; it is removed."""
    assert SUBJECT not in [key for key, _ in _neighbors(index)]
    assert rank(index, subject_vector(index, SUBJECT), _filters(), 1) == [
        (SUBJECT, 1.0)
    ]


def _filters():
    return neighbor_filters("Pasadena", SFR, LOW, HIGH)


def test_both_price_edges_are_in_and_one_dollar_past_each_is_out(index):
    keys = [key for key, _ in _neighbors(index)]
    assert 101 in keys and 102 in keys
    assert 103 not in keys and 104 not in keys


def test_another_city_another_type_and_an_unknown_price_are_masked(index):
    keys = [key for key, _ in _neighbors(index)]
    assert not {105, 106, 108} & set(keys)


def test_equal_scores_break_by_key_ascending(index):
    ranked = _neighbors(index)
    assert ranked[0][1] == ranked[1][1] == 0.8
    assert [ranked[0][0], ranked[1][0]] == [101, 107]


def test_scores_are_float32_dot_products_rounded_to_six_decimals(index):
    """The same arithmetic as WO-010's rank: no rescoring, no other rounding."""
    subject = np.asarray(ROWS[SUBJECT][0], dtype=np.float32)
    for key, score in _neighbors(index):
        raw = np.asarray(ROWS[key][0], dtype=np.float32) @ subject
        assert score == round(float(raw), 6)


def test_top_counts_neighbors_not_the_subject(index):
    assert _neighbors(index, top=1) == [(101, 0.8)]
    assert _neighbors(index, top=2) == [(101, 0.8), (107, 0.8)]
    assert _neighbors(index, top=0) == []


def test_the_subject_vector_is_read_by_key(index):
    for key in (99, SUBJECT, 108):
        row = subject_row(index, key)
        assert int(index.keys[row]) == key
        assert subject_vector(index, key).tolist() == pytest.approx(ROWS[key][0])


@pytest.mark.parametrize("key", [1, 98, 150, 109, 10**12])
def test_a_key_with_no_vector_raises_subject_not_indexed(index, key):
    with pytest.raises(SubjectNotIndexed):
        subject_vector(index, key)
    with pytest.raises(SubjectNotIndexed):
        _neighbors(index, key=key)
    with pytest.raises(SubjectNotIndexed):
        _neighbors(index, top=0, key=key)


def test_the_filters_are_the_four_hard_filters_only():
    assert _filters() == PropertySearchFilters(
        city="Pasadena", property_subtype=SFR, min_price=LOW, max_price=HIGH
    )


def test_neighbors_builds_no_embedder(index, monkeypatch):
    """The query is the stored vector: any embedder construction fails the test."""
    from idx_agent.semantic import embedder

    def boom(*args, **kwargs):
        raise AssertionError("no embedder may be built for neighbors")

    monkeypatch.setattr(embedder, "make_embedder", boom)
    monkeypatch.setattr(embedder.HashingEmbedder, "embed", boom)
    monkeypatch.setattr(embedder.OpenAIEmbedder, "embed", boom)
    assert _neighbors(index, top=1) == [(101, 0.8)]


def test_the_shared_fetch_loop_keeps_rank_order_stops_at_k_and_counts_drops():
    """fetch_in_rank_order, used by find_similar and recommend: 50 keys a statement,
    none after k survive; a key missing from a fetched batch is dropped, even past k."""
    ranked = [(key, round(1 - key / 1000, 6)) for key in range(1, 121)]  # 3 batches
    calls: list[list[int]] = []

    def fetch(filters, keys, conn):
        assert filters == _filters() and conn == "conn"
        calls.append(list(keys))
        kept = [k for k in reversed(keys) if k % 2]  # SQL keeps odd keys, any order
        listings = [
            Listing(listing_key=k, listing_id=str(k), list_price=1) for k in kept
        ]
        return SearchOutcome(listings=listings, skipped_rows=1)

    out = fetch_in_rank_order(ranked, _filters(), 30, "conn", fetch=fetch)
    assert calls == [list(range(1, 51)), list(range(51, 101))]
    assert [(x.listing_key, s) for x, s in out.found] == [
        (k, round(1 - k / 1000, 6)) for k in range(1, 60, 2)
    ]
    # 25 even keys in each fetched batch, including the 20 after k was reached.
    assert (out.keys_fetched, out.dropped, out.skipped_rows) == (100, 50, 2)
    assert fetch_in_rank_order([], _filters(), 5, "conn", fetch=fetch).found == []
    assert len(calls) == 2
