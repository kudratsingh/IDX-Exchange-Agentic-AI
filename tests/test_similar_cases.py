"""Checks for evals/cases/semantic_retrieval.yaml (WO-010): no model, no database.

Every `ranked_keys` literal is recomputed with HashingEmbedder and `rank` over the CI
fixture index of the generator's rows (requirement 16); the ci cases then run through
the real tool body with only the SQL replaced by a Python reference. No provider."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from evals import run as runner

from idx_agent.db import asof as db_asof
from idx_agent.db import pool as db_pool
from idx_agent.db.listings import SearchOutcome
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.fieldmap import to_listing
from idx_agent.domain.models import (
    Clarification,
    PropertySearchFilters,
    SimilarListingsRequest,
)
from idx_agent.safety.columns import AGENT_CONTACT

pytest.importorskip("numpy")

from idx_agent.semantic import query as semantic_query  # noqa: E402
from idx_agent.semantic.embedder import HashingEmbedder  # noqa: E402
from idx_agent.semantic.index import load_index, rank  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals" / "cases" / "semantic_retrieval.yaml"
CATEGORY = "semantic_retrieval"
TOOL = "find_similar_listings"
FILTER_NAMES = ("city", "max_price", "min_beds", "property_subtype")


def _module(name: str, path: Path) -> ModuleType:
    """Import a file under tests/ by path (the folder is no package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _module("make_synthetic", ROOT / "tests" / "fixtures" / "make_synthetic.py")
FIXTURE = _module("semantic_fixture", ROOT / "tests" / "semantic_fixture.py")
ROWS = GEN.active_rows()
AS_OF = AsOfDates(sold=GEN.SOLD_ASOF, active=GEN.ACTIVE_ASOF.date())


def _load() -> tuple[list[runner.Case], list[runner.LoadError]]:
    """Load only semantic_retrieval.yaml, through the runner's own loader."""
    cases, errors = runner.load_cases(CASES_FILE.parent)
    mine = [c for c in cases if c.source == CASES_FILE.name]
    return mine, [e for e in errors if e.source == CASES_FILE.name]


CASES, LOAD_ERRORS = _load()
CI = [c for c in CASES if c.suite == "ci"]
LOCAL = [c for c in CASES if c.suite == "local"]
RANKED = [c for c in CI if c.check == "ranked_keys"]
CLARIFY = [c for c in CI if c.check == "clarification"]
JUDGED = [c for c in LOCAL if c.check == "recall_at_k"]
PHRASING = [c for c in LOCAL if c.input is not None]
BY_ID = {c.id: c for c in CASES}


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The CI fixture index, loaded as the tool loads it."""
    path = FIXTURE.build_fixture_index(tmp_path_factory.mktemp("index"))
    return load_index(path, FIXTURE.TEST_MODEL, FIXTURE.FIXTURE_DIMS)


def _request(case: runner.Case) -> SimilarListingsRequest:
    request = SimilarListingsRequest.from_input(case.input_filters or {})
    assert isinstance(request, SimilarListingsRequest), case.id
    return request


def reference_keys(index: Any, request: SimilarListingsRequest) -> list[int]:
    """The top k keys: the request text embedded as the tool embeds it, masked by the
    hard filters and ranked (score, then key). The fixture's SQL drops no key."""
    vector = HashingEmbedder(FIXTURE.FIXTURE_DIMS).embed([request.text])[0]
    ranked = rank(index, vector, request.hard_filters(), semantic_query.MAX_RANKED_KEYS)
    return [key for key, _ in ranked[: request.k]]


# --- the case file ---------------------------------------------------------------


def test_file_loads_with_no_errors() -> None:
    assert LOAD_ERRORS == []
    assert all(c.id.startswith("semantic-") for c in CASES)
    assert {c.category for c in CASES} == {CATEGORY}
    assert {c.tool for c in CASES} == {TOOL}
    # About 12 ci cases; the 10 judged queries and about 4 phrasing cases.
    assert len(CI) >= 12 and len(RANKED) >= 6
    assert len(JUDGED) == 10 and len(PHRASING) == 4
    assert len(LOCAL) == len(JUDGED) + len(PHRASING)


def test_fixture_bound_cases_are_marked_fixture_only() -> None:
    """Every ci case that reaches the index holds only for the fixture rows: the CI
    fixture index holds fixture keys, so on a real database SQL drops them all and
    an absence or at-most check would pass on zero matches."""
    fixture = {c.id for c in CASES if c.database == "fixture"}
    bound = {c.id for c in CI if c.check != "clarification"}
    assert fixture == bound
    assert {"semantic-ci-007", "semantic-ci-014", "semantic-ci-017"} <= fixture
    assert "semantic-ci-018" in fixture
    assert all(c.database == "any" for c in CLARIFY + LOCAL)


def test_each_absence_case_has_a_ranked_companion_with_matches() -> None:
    """A fields_absent case passes on an empty result too; a ranked_keys case on the
    same input shows the matches exist (semantic-ci-018 with semantic-ci-003)."""
    absent = [c for c in CI if c.check == "fields_absent"]
    assert {c.id for c in absent} == {
        "semantic-ci-014",
        "semantic-ci-017",
        "semantic-ci-018",
    }
    for case in absent:
        twins = [c for c in RANKED if c.input_filters == case.input_filters]
        assert twins and all(t.expect["keys"] for t in twins), case.id
    assert (
        BY_ID["semantic-ci-003"].input_filters == BY_ID["semantic-ci-018"].input_filters
    )


def test_every_ci_query_text_embeds() -> None:
    """Text under 20 characters embeds to a zero vector with the hashing embedder;
    only the cases written to be refused may be that short."""
    embedder = HashingEmbedder(FIXTURE.FIXTURE_DIMS)
    for case in CI:
        text = (case.input_filters or {}).get("text", "")
        if case.check != "clarification":
            assert len(" ".join(text.split())) >= 20, case.id
            assert abs(float((embedder.embed([text])[0] ** 2).sum()) - 1) < 1e-3


def test_the_generator_holds_the_semantic_group() -> None:
    group = [r for r in ROWS if r["L_City"] == "Sierra Madre"]
    assert [int(r["L_ListingID"]) for r in group] == [k for k, *_ in GEN.SIERRA_MADRE]
    assert {r["L_Type_"] for r in group} == {"SingleFamilyResidence", "Condominium"}
    assert len(group) == 8 and len(ROWS) == 79
    # Every group row is older than the as-of row, so the as-of date is unchanged.
    assert max(r["ModificationTimestamp"] for r in ROWS) == GEN.ACTIVE_ASOF
    assert all(r["ModificationTimestamp"] < GEN.ACTIVE_ASOF for r in group)
    injection = [r for r in ROWS if GEN.INJECTION in (r["L_Remarks"] or "")]
    assert [int(r["L_ListingID"]) for r in injection] == [9100001]


@pytest.mark.parametrize("case", RANKED, ids=lambda c: c.id)
def test_ranked_keys_literals_match_the_ranking(
    case: runner.Case, fixture_index: Any
) -> None:
    """Requirement 16: each literal equals HashingEmbedder + rank over the rows."""
    assert reference_keys(fixture_index, _request(case)) == case.expect["keys"]


def test_each_hard_filter_changes_the_ranked_keys() -> None:
    base = BY_ID["semantic-ci-001"].expect["keys"]
    city = BY_ID["semantic-ci-003"].expect["keys"]
    assert city != base
    for case_id in ("semantic-ci-004", "semantic-ci-005", "semantic-ci-006"):
        case = BY_ID[case_id]
        assert case.expect["keys"] != city, case_id
        # Each case adds exactly one filter to the Sierra Madre base (text aside).
        added = set(case.input_filters or {}) - {"text", "city"}
        assert len(added) == 1 and added <= set(FILTER_NAMES), case_id
    by_key = {int(r["L_ListingID"]): r for r in ROWS}

    def rows(case_id: str) -> list[dict[str, Any]]:
        return [by_key[k] for k in BY_ID[case_id].expect["keys"]]

    assert all(r["L_SystemPrice"] <= 1_000_000 for r in rows("semantic-ci-004"))
    assert all(r["L_Keyword2"] >= 4 for r in rows("semantic-ci-005"))
    subtypes = {r["L_Type_"] for r in rows("semantic-ci-006")}
    assert subtypes == {"SingleFamilyResidence"}


def test_the_injection_case_ranks_the_injection_row() -> None:
    assert BY_ID["semantic-ci-016"].expect["keys"] == [9100001]
    absent = BY_ID["semantic-ci-017"].expect["fields"]
    assert any(f.lower() in GEN.INJECTION.lower() for f in absent)
    agent = set(BY_ID["semantic-ci-014"].expect["fields"])
    assert agent and agent <= AGENT_CONTACT


def test_the_long_text_is_one_over_the_limit() -> None:
    text = BY_ID["semantic-ci-012"].input_filters["text"]
    assert len(" ".join(text.split())) == 501


@pytest.mark.parametrize("case", CLARIFY, ids=lambda c: c.id)
def test_clarification_cases_through_from_input(case: runner.Case) -> None:
    got = SimilarListingsRequest.from_input(case.input_filters or {})
    want = case.expect["clarification"]
    assert isinstance(got, Clarification), case.id
    assert (got.field, got.reason) == (want["field"], want["reason"])


def test_judged_queries_mix_filters_and_styles() -> None:
    """Five carry exactly one hard filter and five none; two are written to match
    nothing; each says its style and intent in a note."""
    with_filter = [c for c in JUDGED if set(c.input_filters or {}) & set(FILTER_NAMES)]
    assert len(with_filter) == 5
    for case in with_filter:
        assert len(set(case.input_filters or {}) & set(FILTER_NAMES)) == 1, case.id
    assert sum(bool(c.expect.get("none_relevant")) for c in JUDGED) == 2
    for case in JUDGED:
        assert case.expect["query_id"] == case.id and case.expect["k"] == 5
        assert isinstance(_request(case), SimilarListingsRequest)
    notes = [e.get("note") for e in _raw_entries() if e["id"] in {c.id for c in JUDGED}]
    assert all(isinstance(n, str) and n for n in notes)


def _raw_entries() -> list[dict[str, Any]]:
    return yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", PHRASING, ids=lambda c: c.id)
def test_phrasing_expectations_are_valid_requests(case: runner.Case) -> None:
    filters = case.expect["filters"]
    got = SimilarListingsRequest.from_input(
        {"text": "a quiet home with a yard", **filters}
    )
    assert isinstance(got, SimilarListingsRequest), case.id
    dumped = got.model_dump(exclude_defaults=True)
    assert {k: dumped.get(k) for k in filters} == filters


# --- the ci cases through the runner and the real tool body ----------------------


def _passes(row: dict[str, Any], filters: PropertySearchFilters) -> bool:
    """The hard filters as the SQL applies them (every fixture row is active)."""
    checks = (
        filters.city is None or row["L_City"] == filters.city,
        filters.max_price is None or row["L_SystemPrice"] <= filters.max_price,
        filters.min_beds is None or (row["L_Keyword2"] or 0) >= filters.min_beds,
        filters.property_subtype is None or row["L_Type_"] == filters.property_subtype,
    )
    return all(checks)


def fake_candidates(
    filters: PropertySearchFilters, keys: list[int], conn: Any
) -> SearchOutcome:
    """fetch_candidates over the generator's rows, returned in reverse key order so
    the tool must restore rank order itself."""
    assert 1 <= len(keys) <= 50
    wanted = set(keys)
    rows = [r for r in ROWS if int(r["L_ListingID"]) in wanted and _passes(r, filters)]
    listings = [to_listing(r) for r in rows]
    return SearchOutcome(sorted(listings, key=lambda x: -x.listing_key))


def test_ci_cases_pass_through_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the SQL is replaced: validation, the fixture index the runner builds,
    embedding, ranking, the card, the warnings, and the checks are the real code."""
    monkeypatch.setattr(db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(db_pool, "connect", lambda *a, **k: object())
    monkeypatch.setattr(db_asof, "get_asof_dates", lambda conn: AS_OF)
    monkeypatch.setattr(semantic_query, "fetch_candidates", fake_candidates)
    for name in runner.SEMANTIC_ENV:
        monkeypatch.delenv(name, raising=False)
    ctx = runner.RunContext(require_database=True)
    try:
        records = [runner.run_case(case, ctx) for case in CI]
    finally:
        ctx.close()
    failed = {r["id"]: r["detail"] for r in records if r["result"] != runner.PASS}
    assert failed == {}
    # The run put the settings back.
    assert all(name not in runner.os.environ for name in runner.SEMANTIC_ENV)
    details = " ".join(r["detail"] for r in records)
    assert not re.search(r"9\d{6}", details)
