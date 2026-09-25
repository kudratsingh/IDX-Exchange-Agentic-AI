"""Checks for evals/cases/rag.yaml (WO-012): no model, database, provider, or PDF.

Every `chunks_from` literal is recomputed over the own-words fixture corpus
(requirement 9), the fixture floor is checked against the ci questions' scores, and
the ci cases run through the runner and the real tool body."""

from __future__ import annotations

import importlib.util
import math
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from evals import run as runner

from idx_agent.db import pool as db_pool
from idx_agent.domain.models import Clarification, RagRequest
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

pytest.importorskip("numpy")

from idx_agent.rag.aliases import alias_hits  # noqa: E402
from idx_agent.rag.chunk import IDENT  # noqa: E402
from idx_agent.rag.retrieve import retrieve, retrieve_detail  # noqa: E402
from idx_agent.rag.store import DocIndex, load_doc_index  # noqa: E402
from idx_agent.semantic.embedder import HashingEmbedder  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals" / "cases" / "rag.yaml"
SCHEMA_NOTES = ROOT / "docs" / "data" / "schema_notes.md"
TOOL = "rag_answer"
PROTECTED = DENYLIST | AGENT_CONTACT
INSTRUCTION = "SYSTEM OVERRIDE"
MARK = " (ours, added by the migration)"


def _module(name: str, path: Path) -> ModuleType:
    """Import a file under tests/ by path (the folder is no package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = _module("rag_fixture", ROOT / "tests" / "rag_fixture.py")


def _load() -> tuple[list[runner.Case], list[runner.LoadError]]:
    """Load only rag.yaml, through the runner's own loader."""
    cases, errors = runner.load_cases(CASES_FILE.parent)
    mine = [c for c in cases if c.source == CASES_FILE.name]
    return mine, [e for e in errors if e.source == CASES_FILE.name]


CASES, LOAD_ERRORS = _load()
CI = [c for c in CASES if c.suite == "ci"]
LOCAL = [c for c in CASES if c.suite == "local"]
CHUNKS_FROM = [c for c in CI if c.check == "chunks_from"]
CLARIFY = [c for c in CI if c.check == "clarification"]
# The off-topic cases: a regex on the not-found message.
NOT_FOUND = [
    c
    for c in CI
    if c.check == "regex" and "not in the reference" in c.expect["pattern"]
]
BY_ID = {c.id: c for c in CASES}


def _question(case: runner.Case) -> str:
    return str((case.input_filters or {})["question"])


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> DocIndex:
    """The lexical fixture index, loaded as the tool loads it."""
    return load_doc_index(fixture.build_fixture_index(tmp_path_factory.mktemp("rag")))


@pytest.fixture(scope="module")
def hybrid(tmp_path_factory: pytest.TempPathFactory) -> DocIndex:
    """The same corpus with test:hashing vectors."""
    path = fixture.build_fixture_index(tmp_path_factory.mktemp("rag"), "hybrid")
    return load_doc_index(path)


def sold_columns() -> list[tuple[str, str, str]]:
    """(column, type, flags) of the california_sold table in schema notes section 2."""
    rows: list[tuple[str, str, str]] = []
    inside = False
    for line in SCHEMA_NOTES.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            inside = line.startswith("### california_sold")
            continue
        if inside and line.startswith("## "):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if inside and line.startswith("|") and cells[0] not in ("column", "---"):
            rows.append((cells[0], cells[1], cells[-1]))
    return rows


# --- the case file -----------------------------------------------------------------


def test_file_loads_with_no_errors() -> None:
    assert LOAD_ERRORS == []
    assert all(c.id.startswith("rag-") for c in CASES)
    assert {c.category for c in CASES} == {"rag"}
    assert {c.tool for c in CASES} == {TOOL}
    # About 15 ci cases (no database, no provider) and the WO's 5 local phrasings.
    assert len(CI) >= 15 and len(LOCAL) == 5
    assert all(c.input_filters is not None for c in CI)
    assert all(c.input is not None for c in LOCAL)
    # Every ci literal pins the whole top list, so the recompute below is exact.
    assert CHUNKS_FROM and all(c.expect.get("exact") for c in CHUNKS_FROM)
    # The tool reads no table: nothing is marked fixture-only.
    assert {c.database for c in CASES} == {"any"}


@pytest.mark.parametrize("case", CHUNKS_FROM, ids=lambda c: c.id)
def test_chunks_from_literals_match_retrieval(
    case: runner.Case, index: DocIndex
) -> None:
    """Requirement 9: each literal is the retrieval's top list over the corpus."""
    got = retrieve(index, _question(case)).chunk_ids()
    top = case.expect["top"]
    assert got[:top] == case.expect["sources"]


def test_the_set_questions_hit_their_named_sources() -> None:
    """The WO's sources per set question lead their lists (exact-name hits)."""
    assert BY_ID["rag-ci-001"].expect["sources"][:2] == [
        "trestle#DaysOnMarket",
        "primer#s8",
    ]
    assert "schema_notes#sec7" in BY_ID["rag-ci-001"].expect["sources"]
    assert BY_ID["rag-ci-002"].expect["sources"][0] == "schema_notes#california_sold"
    ratio = BY_ID["rag-ci-004"].expect["sources"]
    assert ratio[:2] == ["glossary#sale_to_list_ratio", "primer#s3"]
    # The term mismatch: "sale to list" gives the same passages as "list-to-close".
    assert BY_ID["rag-ci-006"].expect["sources"] == ratio[:2]
    assert BY_ID["rag-ci-007"].expect["sources"][0] == "trestle#BathroomsTotalInteger"
    assert "trestle#MlsStatus" in BY_ID["rag-ci-008"].expect["sources"]


@pytest.mark.parametrize("case_id", ["rag-ci-013", "rag-ci-022", "rag-ci-023"])
def test_an_agent_field_question_lands_on_the_agent_entry(
    case_id: str, index: DocIndex
) -> None:
    """The human's decision of 2026-09-25: a question about an agent field gets the
    glossary entry saying such fields are not described first, and no field entry."""
    sources = BY_ID[case_id].expect["sources"]
    assert sources[0] == "glossary#agent_and_office_fields"
    assert not [s for s in sources if s.startswith("trestle#")]
    answer = retrieve(index, _question(BY_ID[case_id]))
    assert answer.chunks[0].match == "exact_name"
    assert not [c for c in answer.chunks if c.source_doc == "trestle"]


def test_the_ratio_pattern_matches_the_own_words_passages(index: DocIndex) -> None:
    """rag-ci-005 pins the definition in the fixture primer and our method in the
    glossary (the list price in force at contract, per sale, then the median)."""
    by_id = {c.chunk_id: c for c in index.chunks}
    pattern = BY_ID["rag-ci-005"].expect["pattern"]
    glossary = by_id["glossary#sale_to_list_ratio"].text
    assert re.search(pattern, by_id["primer#s3"].text + "\n" + glossary)
    assert not re.search(pattern, by_id["primer#s3"].text)
    assert "seller's market" in glossary and '1.030 is "3% over asking"' in glossary


@pytest.mark.parametrize(
    "case",
    [c for c in LOCAL if c.check == "chunks_from"],
    ids=lambda c: c.id,
)
def test_local_literals_follow_the_exact_names(case: runner.Case) -> None:
    """A local case runs against the real index, so its literal may pin only what
    code decides there: the alias targets, else the field named in the words."""
    words = case.input or ""
    named = alias_hits(words) or [
        f"trestle#{w}" for w in re.findall(r"[A-Za-z0-9_]+", words) if IDENT.match(w)
    ]
    assert case.expect["sources"] == named[: case.expect["top"]]


# --- the not-found floor ---------------------------------------------------------


def test_the_floor_separates_off_topic_from_on_topic(index: DocIndex) -> None:
    """The fixture floor sits in the gap between the off-topic ci questions' best
    BM25 top score and the lowest top of a ci question with no exact hit."""
    assert index.meta.floor_bm25 == fixture.FLOOR_BM25
    assert index.meta.floor_cosine == fixture.FLOOR_COSINE > 1.0
    off = [retrieve_detail(index, _question(c)) for c in NOT_FOUND]
    assert len(off) == 2 and all(not r.answer.found and not r.exact_hits for r in off)
    ranked = [retrieve_detail(index, _question(c)) for c in CHUNKS_FROM]
    on = [r.lexical_top for r in ranked if not r.exact_hits]
    assert on, "at least one ci question must be found by BM25 alone"
    high_off, low_on = max(r.lexical_top for r in off), min(on)
    assert high_off < fixture.FLOOR_BM25 <= low_on
    # The numbers the comments in rag.yaml and rag_fixture.py give.
    # The glossary entry's decision-19 wording moved both by a thousandth (2026-09-25).
    assert (round(high_off, 3), round(low_on, 3)) == (5.352, 6.666)
    # The floor is the midpoint of the gap, rounded down to 2 decimals.
    assert fixture.FLOOR_BM25 == math.floor((high_off + low_on) / 2 * 100) / 100


def test_the_hybrid_fixture_keeps_exact_hits_first_and_abstains(
    hybrid: DocIndex, index: DocIndex
) -> None:
    """With test:hashing vectors, exact names still lead and the off-topic ci
    questions still abstain (the cosine floor is out of reach)."""
    embedder = HashingEmbedder(fixture.FIXTURE_DIMS)
    for case in CHUNKS_FROM:
        lexical = retrieve_detail(index, _question(case))
        fused = retrieve_detail(hybrid, _question(case), embedder)
        # A question under 20 characters skips the vector leg: BM25 ranked it.
        want = "bm25" if fused.vector_skipped else "hybrid"
        assert fused.answer.route == want and fused.answer.found
        n = lexical.exact_hits
        assert fused.answer.chunk_ids()[:n] == lexical.answer.chunk_ids()[:n]
    for case in NOT_FOUND:
        assert not retrieve(hybrid, _question(case), embedder).found


# --- the corpus --------------------------------------------------------------------


def test_the_corpus_holds_the_sentinels_and_the_index_never_does(
    index: DocIndex,
) -> None:
    corpus = (fixture.CORPUS / "field_reference.txt").read_text(encoding="utf-8")
    assert all(s in corpus for s in fixture.SENTINELS)
    assert INSTRUCTION in corpus
    names = [line.split()[0] for line in corpus.splitlines() if line[:1].isupper()]
    protected = [n for n in names if n in PROTECTED]
    assert sorted(protected) == ["ListAgentEmail", "ShowingInstructions"]
    assert "ListAgentEmail" in AGENT_CONTACT and "ShowingInstructions" in DENYLIST
    for chunk in index.chunks:
        assert not any(s in chunk.text for s in fixture.SENTINELS), chunk.chunk_id
        assert chunk.key not in PROTECTED
    by_id = {c.chunk_id: c for c in index.chunks}
    # The line naming a deny-listed field left the PublicRemarks entry; the
    # instruction-like line stayed (it is data, and the fence carries it).
    remarks = by_id["trestle#PublicRemarks"].text
    assert "ShowingInstructions" not in remarks and INSTRUCTION in remarks
    # The primer line naming an agent field left section 8.
    assert "ListAgentFullName" not in by_id["primer#s8"].text
    assert index.meta.drops["field_chunks_dropped"] == {"trestle": 2}
    # The agent-related entry outside both sets (the human's decision of 2026-09-25).
    assert "ListAgentDesignation" in names
    assert "trestle#ListAgentDesignation" not in by_id
    assert index.meta.drops["agent_related_dropped"] == {"trestle": 1}
    assert index.meta.drops["contact_like_dropped"] == {}
    assert index.meta.drops["lines_removed"]["trestle"] == 1
    assert index.meta.drops["lines_removed"]["primer"] == 1


def test_the_corpus_has_the_structure_the_cases_rely_on(index: DocIndex) -> None:
    fields = [c.key for c in index.chunks if c.doc == "trestle"]
    # One chunk per fixture field entry, the two protected ones left out.
    assert fields == [
        "DaysOnMarket",
        "CumulativeDaysOnMarket",
        "ListPrice",
        "OriginalListPrice",
        "ClosePrice",
        "BathroomsTotalInteger",
        "StandardStatus",
        "MlsStatus",
        "PublicRemarks",
        "LivingArea",
        "YearBuilt",
        "PoolPrivateYN",
    ]
    sections = [c.key for c in index.chunks if c.doc == "primer"]
    # Section 4 is over 350 words and splits; 3 is the ratio, 8 days on market, and
    # 2 the unrelated one, at the positions the alias table names.
    assert sections == ["s1", "s2", "s3", "s4.1", "s4.2", "s5", "s6", "s7", "s8"]
    assert {c.page for c in index.chunks if c.doc == "trestle"} == {1, 2, 3}
    by_id = {c.chunk_id: c for c in index.chunks}
    assert "Back on Market" in by_id["trestle#MlsStatus"].text
    assert "close price over the final list price" in by_id["primer#s3"].text
    assert {c.confidential for c in index.chunks if c.doc in ("trestle", "primer")} == {
        True
    }


# --- the other literals --------------------------------------------------------------


def test_the_absence_lists_name_every_protected_field_and_three_sentinels() -> None:
    every = PROTECTED | set(fixture.SENTINELS)
    for case_id in ("rag-ci-011", "rag-ci-014"):
        fields = BY_ID[case_id].expect["fields"]
        assert len(fields) == len(set(fields)) and set(fields) == every, case_id
    # The sold summary lists its own contact columns by name (decision 8), so the
    # case whose passages include it leaves exactly those seven out.
    sold_contact = {
        name for name, _, flags in sold_columns() if "agent contact" in flags
    }
    assert len(sold_contact) == 7
    assert set(BY_ID["rag-ci-012"].expect["fields"]) == every - sold_contact
    assert "schema_notes#california_sold" in BY_ID["rag-ci-013"].expect["sources"]
    assert BY_ID["rag-ci-012"].input_filters == BY_ID["rag-ci-013"].input_filters
    # The agent-related case also lists the fixture entry's own name.
    fields = BY_ID["rag-ci-021"].expect["fields"]
    assert len(fields) == len(set(fields))
    assert set(fields) == (every - sold_contact) | {"ListAgentDesignation"}
    assert "schema_notes#california_sold" in BY_ID["rag-ci-022"].expect["sources"]
    assert BY_ID["rag-ci-021"].input_filters == BY_ID["rag-ci-022"].input_filters


def test_the_sold_summary_pattern_lists_the_notes_columns_in_order() -> None:
    columns = sold_columns()
    assert len(columns) == 49
    want = [
        name + (MARK if name.endswith("_d") and kind == "date" else "")
        for name, kind, _ in columns
    ]
    assert sum(MARK in line for line in want) == 3
    pattern = BY_ID["rag-ci-003"].expect["pattern"]
    body = pattern.split("]*\\n", 1)[1].rsplit("\\n```", 1)[0]
    listed = [
        line.replace("\\(", "(").replace("\\)", ")") for line in body.split("\\n")
    ]
    assert listed == want


def test_the_instruction_case_and_its_twin_share_the_question() -> None:
    assert INSTRUCTION in BY_ID["rag-ci-015"].expect["pattern"]
    assert BY_ID["rag-ci-015"].input_filters == BY_ID["rag-ci-016"].input_filters
    assert BY_ID["rag-ci-016"].expect["sources"][0] == "trestle#PublicRemarks"


def test_the_long_question_is_one_over_the_limit() -> None:
    text = _question(BY_ID["rag-ci-018"])
    assert len(" ".join(text.split())) == 301


@pytest.mark.parametrize("case", CLARIFY, ids=lambda c: c.id)
def test_clarification_cases_through_from_input(case: runner.Case) -> None:
    got = RagRequest.from_input(case.input_filters or {})
    want = case.expect["clarification"]
    assert isinstance(got, Clarification), case.id
    assert (got.field, got.reason) == (want["field"], want["reason"])


# --- the ci cases through the runner and the real tool body ---------------------------


def test_ci_cases_pass_through_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is replaced but the database, which must never be touched: the
    fixture index the runner builds, retrieval, the cap, the format, and the checks
    are the real code."""

    def no_database(*_: Any, **__: Any) -> Any:
        raise AssertionError("a rag case touched the database")

    monkeypatch.setattr(db_pool, "database_configured", no_database)
    monkeypatch.setattr(db_pool, "connect", no_database)
    for name in ("IDX_RAG_INDEX_DIR", "IDX_RAG_FLOOR_BM25", "IDX_RAG_FLOOR_COSINE"):
        monkeypatch.delenv(name, raising=False)
    ctx = runner.RunContext(require_database=True)
    try:
        records = [runner.run_case(case, ctx) for case in CI]
    finally:
        ctx.close()
    failed = {r["id"]: r["detail"] for r in records if r["result"] != runner.PASS}
    assert failed == {}
    # The run put the setting back, and no detail carries corpus text.
    for name in ("IDX_RAG_INDEX_DIR", "IDX_RAG_FLOOR_BM25", "IDX_RAG_FLOOR_COSINE"):
        assert name not in runner.os.environ, name
    details = " ".join(r["detail"] for r in records)
    assert INSTRUCTION not in details
    assert not any(s in details for s in fixture.SENTINELS)
