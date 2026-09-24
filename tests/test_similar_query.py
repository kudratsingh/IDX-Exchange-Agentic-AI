"""Unit tests for semantic/query.py (WO-010): the query path on a stub database.

A tiny `test:hashing`-model index of hand-written 4-dimension vectors is written to a
temporary directory; a stub embedder returns a fixed query vector and a fake
connection answers the candidate SQL from invented rows. No key, network, or MySQL.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from idx_agent.db.listings import build_candidate_sql
from idx_agent.domain.models import (
    PropertySearchFilters,
    SimilarListingsRequest,
    SimilarResult,
)
from idx_agent.semantic import query as query_module
from idx_agent.semantic.embedder import TEST_MODEL
from idx_agent.semantic.index import IndexAttrs, load_index, write_index
from idx_agent.semantic.query import (
    FETCH_BATCH,
    MAX_RANKED_KEYS,
    MAX_STATEMENTS,
    SimilarOutcome,
    UnusableText,
    find_similar,
)

AS_OF = date(2026, 9, 18)
DIMS = 4
# Invented remarks: the fetched rows carry them, and no match may.
REMARK = "invented remark with the word marigold-5c1e"
TEXT = "a quiet home with a big yard near good schools"


def _unit(*values: float) -> np.ndarray:
    """A float32 unit vector from the given values."""
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


QUERY = _unit(1, 0, 0, 0)


def _write(
    tmp_path: Path,
    vectors: list[np.ndarray],
    keys: list[int],
    cities: list[str] | None = None,
    prices: list[int] | None = None,
    beds: list[int] | None = None,
    subtypes: list[str] | None = None,
) -> Any:
    """Write and load a test:hashing index of the given rows (defaults: Pasadena)."""
    n = len(keys)
    attrs = IndexAttrs.from_values(
        cities or ["Pasadena"] * n,
        prices or [900_000] * n,
        beds or [3] * n,
        subtypes or ["SingleFamilyResidence"] * n,
    )
    path = tmp_path / "index"
    write_index(
        path,
        vectors=np.vstack(vectors),
        keys=np.array(keys, dtype=np.int64),
        attrs=attrs,
        model=TEST_MODEL,
        active_as_of=AS_OF,
    )
    return load_index(path, TEST_MODEL, DIMS)


class StubEmbedder:
    """Returns one fixed vector per text and records every call."""

    name = TEST_MODEL
    dims = DIMS

    def __init__(self, vector: np.ndarray = QUERY) -> None:
        self.vector = vector
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.vstack([self.vector for _ in texts]).astype(np.float32)


def _row(key: int, price: int = 900_000, city: str = "Pasadena") -> dict[str, Any]:
    """An invented rets_property row in source column names."""
    return {
        "L_ListingID": str(key),
        "L_DisplayId": f"TST{key}",
        "L_Address": "100 Example Way",
        "L_City": city,
        "L_Zip": "91106",
        "L_SystemPrice": price,
        "L_Keyword2": 3,
        "LM_Dec_3": 2.0,
        "LM_Int2_3": 1600,
        "L_Type_": "SingleFamilyResidence",
        "StandardStatus": "Active",
        "L_Remarks": REMARK,
    }


class FakeDb:
    """Answers candidate statements from invented rows: a row comes back when its key
    is among the bound parameters and it is still "alive" (SQL would pass it)."""

    def __init__(self, keys: list[int], *, reverse: bool = False) -> None:
        self.rows = {key: _row(key) for key in keys}
        self.reverse = reverse
        self.extra_rows: list[dict[str, Any]] = []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeDb:
        return self

    def __enter__(self) -> FakeDb:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))
        asked = {p for p in params if isinstance(p, str)}
        self.result = [r for k, r in self.rows.items() if str(k) in asked]
        self.result += self.extra_rows
        if self.reverse:
            self.result.reverse()

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.result)

    def batch_keys(self) -> list[list[str]]:
        """The keys bound in each executed statement (the params after the filters)."""
        return [[p for p in params[1:-1] if p.isdigit()] for _, params in self.executed]


def _request(**raw: Any) -> SimilarListingsRequest:
    request = SimilarListingsRequest.from_input({"text": TEXT, **raw})
    assert isinstance(request, SimilarListingsRequest), request
    return request


def _expected_order(vectors: list[np.ndarray], keys: list[int]) -> list[int]:
    """The ranking written out independently: score (6 decimals) desc, then key asc."""
    scores = [round(float(np.float32(v @ QUERY)), 6) for v in vectors]
    return [k for _, k in sorted(zip((-s for s in scores), keys, strict=True))]


# Eight rows whose similarity to QUERY falls with the key's position here.
EIGHT_KEYS = [805, 301, 907, 102, 650, 444, 999, 120]
EIGHT = [_unit(1, 0.1 * i, 0, 0.05) for i in range(8)]


def test_matches_follow_rank_order_and_stop_at_k(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    db = FakeDb(EIGHT_KEYS)
    embedder = StubEmbedder()
    outcome = find_similar(_request(k=3), index, embedder, db)
    assert isinstance(outcome, SimilarOutcome)
    assert [m.listing.listing_key for m in outcome.matches] == EIGHT_KEYS[:3]
    assert [m.rank for m in outcome.matches] == [1, 2, 3]
    assert (outcome.rows_ranked, outcome.keys_fetched, outcome.dropped) == (8, 8, 0)
    assert outcome.index_as_of == AS_OF
    assert embedder.calls == [[TEXT]]
    assert len(db.executed) == 1


def test_the_ranking_matches_an_independent_sort(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    outcome = find_similar(_request(k=8), index, StubEmbedder(), FakeDb(EIGHT_KEYS))
    ranked = [m.listing.listing_key for m in outcome.matches]
    assert ranked == _expected_order(EIGHT, EIGHT_KEYS) == EIGHT_KEYS


def test_rank_order_is_kept_when_sql_returns_rows_reversed(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    db = FakeDb(EIGHT_KEYS, reverse=True)
    outcome = find_similar(_request(k=5), index, StubEmbedder(), db)
    assert [m.listing.listing_key for m in outcome.matches] == EIGHT_KEYS[:5]


def test_keys_sql_drops_are_counted_and_skipped(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    # SQL no longer returns the top key and the third one (price or status changed).
    alive = [k for k in EIGHT_KEYS if k not in (EIGHT_KEYS[0], EIGHT_KEYS[2])]
    outcome = find_similar(_request(k=3), index, StubEmbedder(), FakeDb(alive))
    assert [m.listing.listing_key for m in outcome.matches] == [301, 102, 650]
    assert [m.rank for m in outcome.matches] == [1, 2, 3]
    assert outcome.dropped == 2 and outcome.keys_fetched == 8
    assert outcome.skipped_rows == 0


def test_rows_that_fail_validation_count_as_dropped_and_skipped(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    db = FakeDb(EIGHT_KEYS)
    # The top key's row comes back without a price: to_listing refuses it.
    db.rows[EIGHT_KEYS[0]] = {**_row(EIGHT_KEYS[0]), "L_SystemPrice": None}
    outcome = find_similar(_request(k=3), index, StubEmbedder(), db)
    assert [m.listing.listing_key for m in outcome.matches] == EIGHT_KEYS[1:4]
    assert outcome.dropped == 1 and outcome.skipped_rows == 1


def test_sql_dropping_every_candidate_gives_no_match(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    outcome = find_similar(_request(), index, StubEmbedder(), FakeDb([]))
    assert outcome.matches == []
    assert (outcome.rows_ranked, outcome.keys_fetched, outcome.dropped) == (8, 8, 8)


def test_an_exact_tie_is_broken_by_the_lower_key(tmp_path):
    same = _unit(1, 1, 0, 0)
    index = _write(tmp_path, [same, same, _unit(0, 1, 0, 0)], [30, 20, 10])
    outcome = find_similar(_request(), index, StubEmbedder(), FakeDb([10, 20, 30]))
    assert [m.listing.listing_key for m in outcome.matches] == [20, 30, 10]
    assert outcome.matches[0].score == outcome.matches[1].score == 0.7071


def test_scores_are_rounded_and_no_match_carries_remarks(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    outcome = find_similar(_request(k=4), index, StubEmbedder(), FakeDb(EIGHT_KEYS))
    for match in outcome.matches:
        assert match.score == round(match.score, 4)
        assert match.listing.remarks is None
    result = SimilarResult(
        matches=outcome.matches,
        applied_filters=_request().hard_filters(),
        k=4,
        rows_ranked=outcome.rows_ranked,
        index_as_of=outcome.index_as_of,
        model="test:hashing@4",
    )
    dumped = result.model_dump_json()
    assert "marigold" not in dumped and TEXT not in dumped


def test_hard_filters_mask_the_index_and_go_to_sql(tmp_path):
    cities = ["Pasadena", "Glendale"] * 4
    prices = [700_000, 1_200_000] * 4
    index = _write(tmp_path, EIGHT, EIGHT_KEYS, cities=cities, prices=prices)
    db = FakeDb(EIGHT_KEYS)
    request = _request(city="glendale", max_price=1_500_000, k=10)
    outcome = find_similar(request, index, StubEmbedder(), db)
    glendale = [k for k, c in zip(EIGHT_KEYS, cities, strict=True) if c == "Glendale"]
    assert [m.listing.listing_key for m in outcome.matches] == glendale
    assert outcome.rows_ranked == 4 and outcome.keys_fetched == 4
    # The statement is exactly build_candidate_sql for the same filters and keys.
    query = build_candidate_sql(request.hard_filters(), glendale)
    assert db.executed == [(query.sql, query.params)]
    assert "Glendale" in query.params and 1_500_000 in query.params


def test_each_hard_filter_changes_the_ranked_set(tmp_path):
    index = _write(
        tmp_path,
        EIGHT,
        EIGHT_KEYS,
        prices=[500_000, 900_000, 1_300_000, 1_700_000] * 2,
        beds=[1, 2, 3, 4] * 2,
        subtypes=["Condominium", "SingleFamilyResidence"] * 4,
    )
    cases = {
        "max_price": (1_000_000, 4),
        "min_beds": (3, 4),
        "property_subtype": ("Condominium", 4),
        "city": ("Glendale", 0),
    }
    for name, (value, survivors) in cases.items():
        outcome = find_similar(
            _request(**{name: value}, k=10), index, StubEmbedder(), FakeDb(EIGHT_KEYS)
        )
        assert outcome.rows_ranked == survivors, name
        assert len(outcome.matches) == survivors, name


def test_a_mask_that_leaves_nothing_runs_no_sql(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    db = FakeDb(EIGHT_KEYS)
    outcome = find_similar(_request(city="Glendale"), index, StubEmbedder(), db)
    assert outcome.matches == [] and db.executed == []
    assert (outcome.rows_ranked, outcome.keys_fetched, outcome.dropped) == (0, 0, 0)


# 230 rows: more than the 200 ranked keys the path may fetch.
MANY_KEYS = list(range(5000, 5230))
MANY = [_unit(1, 0.001 * i, 0.5, 0) for i in range(230)]


def test_batches_of_fifty_at_most_four_statements(tmp_path):
    index = _write(tmp_path, MANY, MANY_KEYS)
    # Only the 199th ranked key survives SQL, so every batch is needed.
    order = _expected_order(MANY, MANY_KEYS)
    db = FakeDb([order[198]])
    outcome = find_similar(_request(k=5), index, StubEmbedder(), db)
    assert [m.listing.listing_key for m in outcome.matches] == [order[198]]
    assert len(db.executed) == MAX_STATEMENTS == 4
    batches = db.batch_keys()
    assert [len(b) for b in batches] == [FETCH_BATCH] * 4
    assert [int(k) for b in batches for k in b] == order[:MAX_RANKED_KEYS]
    assert outcome.keys_fetched == 200 and outcome.dropped == 199
    assert outcome.rows_ranked == 230


def test_early_stop_once_k_listings_are_in_hand(tmp_path):
    index = _write(tmp_path, MANY, MANY_KEYS)
    order = _expected_order(MANY, MANY_KEYS)
    # The first batch yields 2, the second the rest: two statements, not four.
    db = FakeDb([order[0], order[10], order[60], order[70], order[80], order[150]])
    outcome = find_similar(_request(k=4), index, StubEmbedder(), db)
    keys = [m.listing.listing_key for m in outcome.matches]
    assert keys == [order[0], order[10], order[60], order[70]]
    assert len(db.executed) == 2
    # 100 keys fetched, 5 came back (the fifth is past k, not dropped), 95 dropped.
    assert outcome.keys_fetched == 100 and outcome.dropped == 95


def test_more_than_fifty_rows_from_one_statement_raises(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    db = FakeDb(EIGHT_KEYS)
    db.extra_rows = [_row(EIGHT_KEYS[0])] * 51
    with pytest.raises(ValueError):
        find_similar(_request(), index, StubEmbedder(), db)


def test_more_than_two_hundred_ranked_keys_raises(tmp_path, monkeypatch):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    too_many = [(k, 0.5) for k in range(1, 252)]
    monkeypatch.setattr(query_module, "rank", lambda *a, **kw: too_many)
    db = FakeDb([])
    with pytest.raises(ValueError):
        find_similar(_request(), index, StubEmbedder(), db)
    assert db.executed == []


def test_more_than_k_matches_is_refused_by_the_result(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    outcome = find_similar(_request(k=3), index, StubEmbedder(), FakeDb(EIGHT_KEYS))
    with pytest.raises(ValueError):
        SimilarResult(
            matches=outcome.matches,
            applied_filters=PropertySearchFilters(),
            k=2,
            rows_ranked=8,
            index_as_of=AS_OF,
            model="test:hashing@4",
        )


@pytest.mark.parametrize(
    "vector",
    [np.zeros(DIMS, dtype=np.float32), _unit(1, 0, 0, 0, 0)],
    ids=["zero", "wrong-width"],
)
def test_an_unusable_query_vector_raises_before_any_sql(tmp_path, vector):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    db = FakeDb(EIGHT_KEYS)
    with pytest.raises(ValueError):
        find_similar(_request(), index, StubEmbedder(vector), db)
    assert db.executed == []


EMAIL = "someone" + "@" + "example.invalid"
PHONE = "555" + "-010-" + "0199"


def test_the_query_text_is_redacted_before_the_embedder_sees_it(tmp_path, monkeypatch):
    """The paid path gets the build's text rule: an email or phone in the description
    never reaches the embedder (IDX_EMBED_REDACT on, the default)."""
    monkeypatch.setenv("IDX_EMBED_REDACT", "1")
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    embedder = StubEmbedder()
    text = f"quiet   home near schools, write {EMAIL} or call {PHONE}"
    find_similar(_request(text=text), index, embedder, FakeDb(EIGHT_KEYS))
    ((sent,),) = embedder.calls
    assert EMAIL not in sent and PHONE not in sent
    assert "[email]" in sent and "[phone]" in sent
    assert "   " not in sent


def test_text_under_twenty_characters_raises_before_any_embedding_call(tmp_path):
    """Two words and eight letters pass validation; under 20 characters once prepared
    is UnusableText (the tool's Clarification) with no call and no SQL."""
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)
    embedder = StubEmbedder()
    db = FakeDb(EIGHT_KEYS)
    with pytest.raises(UnusableText):
        find_similar(_request(text="cozy   yards"), index, embedder, db)
    assert embedder.calls == [] and db.executed == []


def test_an_embedder_returning_two_rows_raises(tmp_path):
    index = _write(tmp_path, EIGHT, EIGHT_KEYS)

    class TwoRows(StubEmbedder):
        def embed(self, texts):
            return np.vstack([QUERY, QUERY])

    with pytest.raises(ValueError):
        find_similar(_request(), index, TwoRows(), FakeDb(EIGHT_KEYS))


def test_the_semantic_package_does_not_import_session_memory():
    """Stateless (requirement 14): importing the query path pulls in no memory code."""
    code = (
        "import sys\n"
        "import idx_agent.semantic.query, idx_agent.semantic.index\n"
        "import idx_agent.semantic.embedder\n"
        "bad = sorted(m for m in sys.modules if m.startswith('idx_agent.memory'))\n"
        "print(','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(src), "PATH": ""},
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_find_similar_takes_no_sender_id():
    """The query path has no sender argument to read or write a session with."""
    params = find_similar.__code__.co_varnames[: find_similar.__code__.co_argcount]
    assert params == ("request", "index", "embedder", "conn")
