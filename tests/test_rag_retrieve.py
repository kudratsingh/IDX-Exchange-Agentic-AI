"""Retrieval (WO-012): exact names, BM25, cosine, fusion, floors, and the quote cap.

Against the own-words fixture corpus (tests/fixtures/docs/) plus the tracked schema
notes and glossary, indexed in memory; no model, no database, no network.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from idx_agent.domain.models import RAG_CONFIDENTIAL_MAX_WORDS as CAP_WORDS
from idx_agent.domain.models import RetrievedChunk
from idx_agent.rag.aliases import ALIASES, PREFIX_MARK, alias_hits, normalize
from idx_agent.rag.chunk import Chunk, agent_related, build_chunks, contact_like
from idx_agent.rag.extract import load_pages
from idx_agent.rag.lexical import bm25_scores, bm25_stats, tokenize
from idx_agent.rag.retrieve import (
    RRF_K,
    TOP_K,
    cap_chunk,
    cap_text,
    fuse,
    lookup_exact,
    rank_lexical,
    rank_vector,
    retrieve,
    retrieve_detail,
)
from idx_agent.rag.sources import SOURCES
from idx_agent.rag.store import DocIndex, DocIndexMeta
from idx_agent.rag.vectors import embed_chunks
from idx_agent.semantic.embedder import HashingEmbedder, ProviderError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "docs"
BUILT = date(2026, 9, 24)


def _chunks() -> list[Chunk]:
    pages = {
        "trestle": load_pages(SOURCES["trestle"], FIXTURE / "field_reference.txt"),
        "primer": load_pages(SOURCES["primer"], FIXTURE / "primer.txt"),
        "schema_notes": load_pages(
            SOURCES["schema_notes"], ROOT / "docs" / "data" / "schema_notes.md"
        ),
        "glossary": load_pages(
            SOURCES["glossary"], ROOT / "docs" / "data" / "glossary.md"
        ),
    }
    return build_chunks(pages)[0]


def _index(
    chunks: list[Chunk],
    floor_bm25: float = 8.84,
    floor_cosine: float = 0.30,
    embedder: HashingEmbedder | None = None,
) -> DocIndex:
    """An in-memory index; hybrid when an embedder is given."""
    vectors = embed_chunks(chunks, embedder)[0] if embedder else None
    meta = DocIndexMeta(
        format_version=1,
        route="hybrid" if embedder else "bm25",
        built_at=BUILT,
        sources={},
        drops={},
        floor_bm25=floor_bm25,
        floor_cosine=floor_cosine,
        text_prep_version=1,
        model=embedder.name if embedder else None,
        dims=embedder.dims if embedder else None,
        rows=len(chunks),
        chunks_sha256="0" * 64,
        complete=True,
    )
    return DocIndex(chunks, meta, bm25_stats([c.text for c in chunks]), vectors, ROOT)


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return _chunks()


@pytest.fixture(scope="module")
def index(chunks) -> DocIndex:
    return _index(chunks)


# ----- BM25 ---------------------------------------------------------------------------
def test_bm25_matches_a_hand_computation() -> None:
    # N 3, avg len 7/3; idf(red) = ln(1.5/2.5 + 1) = 0.470004, idf(boat) = 0.980829.
    # norm = 1.5 * (0.25 + 0.75 * len / (7/3)): 1.339286 at len 2, 1.821429 at len 3.
    # red: .470004*2.5/2.339286 = .502294, .470004*5/3.821429 = .614958; boat 1.048214.
    stats = bm25_stats(["red house", "red red car", "blue boat"])
    assert stats.idf["red"] == pytest.approx(0.470004, abs=1e-6)
    scores = bm25_scores(stats, ["red"])
    assert scores == pytest.approx([0.502294, 0.614958, 0.0], abs=1e-6)
    assert bm25_scores(stats, ["boat"])[2] == pytest.approx(1.048214, abs=1e-6)


def test_tokens_split_camel_case_and_drop_function_words() -> None:
    assert tokenize("What is DaysOnMarket?") == ["daysonmarket", "days", "market"]
    assert tokenize("california_sold") == ["california", "sold"]


def test_rank_lexical_leaves_out_zero_scores(index) -> None:
    assert rank_lexical(index, "zzzqqq xyzzy", 10) == []
    ranked = rank_lexical(index, "bathrooms", 3)
    assert ranked and all(score > 0 for _, score in ranked)


# ----- exact names and aliases --------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "first"),
    [
        ("what does DOM mean", "trestle#DaysOnMarket"),
        ("what is days-on-market", "trestle#DaysOnMarket"),
        ("what does sale to list mean", "glossary#sale_to_list_ratio"),
        ("what is the list-to-close ratio", "glossary#sale_to_list_ratio"),
        ("which columns does the sold table have", "schema_notes#california_sold"),
        ("columns of rets_property", "schema_notes#rets_property"),
    ],
)
def test_aliases_put_their_chunk_first(index, question: str, first: str) -> None:
    answer = retrieve(index, question)
    assert answer.found
    assert answer.chunk_ids()[0] == first
    assert answer.chunks[0].match == "exact_name"
    assert answer.chunks[0].score == 1.0


def test_dom_alias_keeps_the_table_order(chunks) -> None:
    ids = [c.chunk_id for c in lookup_exact("DOM?", chunks)]
    targets = dict(ALIASES)["dom"]
    present = {c.chunk_id for c in chunks}
    assert ids == [cid for cid in targets if cid in present]


def test_term_mismatch_gives_the_same_sources(index) -> None:
    a = retrieve(index, "what is the list-to-close ratio")
    b = retrieve(index, "what is the sale to list ratio")
    assert a.chunk_ids()[:2] == b.chunk_ids()[:2]


def test_field_names_match_as_written_or_in_any_case(chunks) -> None:
    hits = lookup_exact("closeprice then BathroomsTotalInteger", chunks)
    assert [c.chunk_id for c in hits] == [
        "trestle#ClosePrice",
        "trestle#BathroomsTotalInteger",
    ]
    assert lookup_exact("nothing named here", chunks) == []


def _field(key: str) -> Chunk:
    """An invented field chunk (own words), for the exact-name rules."""
    return Chunk("trestle", key, 1, f"An invented note on {key}.", True, f"T {key}")


ONE_WORD_FIELDS = [_field(k) for k in ("City", "View", "Roof", "DaysOnMarket")]


@pytest.mark.parametrize(
    ("question", "want"),
    [
        # A one-word field name hits only as written, never folded from prose.
        ("which city has the best schools", []),
        ("does the home have a view of the hills", []),
        ("my roof is leaking", []),
        ("what does the View field hold", ["trestle#View"]),
        ("City and Roof", ["trestle#City", "trestle#Roof"]),
        # A multi-part camel-case name hits as written or in any case.
        ("what is DaysOnMarket", ["trestle#DaysOnMarket"]),
        ("what is daysonmarket", ["trestle#DaysOnMarket"]),
        ("DAYSONMARKET please", ["trestle#DaysOnMarket"]),
    ],
)
def test_one_word_field_names_hit_only_as_written(question: str, want) -> None:
    got = [c.chunk_id for c in lookup_exact(question, ONE_WORD_FIELDS)]
    assert got == want


def test_alias_targets_missing_from_the_index_are_skipped() -> None:
    only = [c for c in _chunks() if c.doc == "glossary"]
    ids = [c.chunk_id for c in lookup_exact("what does DOM mean", only)]
    assert ids == []
    assert alias_hits("DOM") == list(dict(ALIASES)["dom"])


def test_protected_field_names_have_no_chunk_to_hit(chunks) -> None:
    """No field chunk exists for either name; the "ListAgent" prefix alias names the
    glossary entry that says agent fields are not described (decision of 2026-09-25)."""
    hits = lookup_exact("what is ListAgentEmail or ShowingInstructions", chunks)
    assert [c.chunk_id for c in hits] == ["glossary#agent_and_office_fields"]
    assert lookup_exact("what are the ShowingInstructions", chunks) == []


@pytest.mark.parametrize(
    ("question", "hit"),
    [
        ("which agent fields are there", True),
        ("is there an office field", True),
        ("who is the listing agent", True),
        ("which is the listing office", True),
        ("who was the buyer agent", True),
        ("who was the buyer's agent", True),
        ("who was the buyer’s agent", True),
        ("who was the buyers agent", True),
        ("who are the listing agents", True),
        ("who is the list agent", True),
        ("which is the list office", True),
        ("what does ListAgentDesignation hold", True),
        ("what is listoffice", True),
        ("what does listofficekey hold", True),
        ("what is the agent fieldwork", False),
        ("what is the list price", False),
        ("who was the buyer", False),
    ],
)
def test_agent_aliases_and_name_prefixes(question: str, hit: bool) -> None:
    want = ["glossary#agent_and_office_fields"] if hit else []
    assert alias_hits(question) == want


def test_normalize_folds_a_curly_apostrophe() -> None:
    assert normalize("The Buyer’s-Agent") == "the buyer's agent"


AGENT_PREFIXES = (
    "ListAgent",
    "ListOffice",
    "BuyerAgent",
    "BuyerOffice",
    "CoListAgent",
    "CoListOffice",
    "CoBuyerAgent",
    "CoBuyerOffice",
    # Decision 19 (2026-09-25): the team families too.
    "ListTeam",
    "BuyerTeam",
)


def test_the_prefix_aliases_are_the_agent_and_office_families() -> None:
    prefixes = [
        p.removesuffix(PREFIX_MARK) for p, _ in ALIASES if p.endswith(PREFIX_MARK)
    ]
    assert sorted(prefixes) == sorted(AGENT_PREFIXES)


@pytest.mark.parametrize("prefix", AGENT_PREFIXES)
@pytest.mark.parametrize("suffix", ["", "Zephyr", "QuillRank", "Id"])
def test_every_agent_family_name_lands_on_the_agent_entry(
    prefix: str, suffix: str, chunks, index
) -> None:
    """A field name of any agent or office family, with an invented suffix, is an
    exact hit on the glossary's agent-and-office entry and on no field entry; no
    agent or office field entry returns. (BM25 may still fill the later places with
    an unrelated entry, such as ClosePrice for "buyer": ranked, never exact.)"""
    question = f"what does {prefix}{suffix} hold?"
    hits = lookup_exact(question, chunks)
    assert [c.chunk_id for c in hits] == ["glossary#agent_and_office_fields"]
    answer = retrieve(index, question)
    assert answer.chunks[0].section_or_field == "agent_and_office_fields"
    assert [c.match for c in answer.chunks].count("exact_name") == 1
    fields = [c.section_or_field for c in answer.chunks if c.source_doc == "trestle"]
    assert not [f for f in fields if agent_related(f) or contact_like(f)]


# ----- the answer ---------------------------------------------------------------------
def test_no_pair_twice_and_at_most_top_k(index) -> None:
    answer = retrieve(index, "DOM days on market DaysOnMarket CumulativeDaysOnMarket")
    ids = answer.chunk_ids()
    assert len(ids) == len(set(ids)) <= TOP_K
    assert answer.sources == [
        next(c.label for c in index.chunks if c.chunk_id == cid) for cid in ids
    ]
    assert answer.route == "bm25"
    assert answer.index_built_at == BUILT


def test_confidential_flag_comes_from_the_registry(index) -> None:
    answer = retrieve(index, "what is the list-to-close ratio")
    for chunk in answer.chunks:
        assert chunk.confidential is SOURCES[chunk.source_doc].confidential


def test_off_topic_questions_abstain(index) -> None:
    for question in ("will it rain in paris tomorrow", "recommend a pizza place"):
        answer = retrieve(index, question)
        assert not answer.found
        assert answer.chunks == [] and answer.sources == []


def test_the_bm25_floor_just_under_and_at(chunks) -> None:
    question = "how are homes compared by size"
    top = rank_lexical(_index(chunks), question, 1)[0][1]
    assert lookup_exact(question, chunks) == []
    at = retrieve_detail(_index(chunks, floor_bm25=top), question)
    assert at.answer.found and at.exact_hits == 0
    above = retrieve_detail(_index(chunks, floor_bm25=top + 1e-6), question)
    assert not above.answer.found


def test_an_exact_hit_is_found_under_any_floor(chunks) -> None:
    answer = retrieve(_index(chunks, floor_bm25=1e9), "what does DOM mean")
    assert answer.found and answer.chunks[0].match == "exact_name"


# ----- fusion and ties ----------------------------------------------------------------
def test_fuse_is_reciprocal_rank_with_k_60() -> None:
    fused = fuse([(3, 9.0), (1, 5.0)], [(1, 0.9), (2, 0.8)])
    expected_one = round(1 / (RRF_K + 2) + 1 / (RRF_K + 1), 6)
    assert fused[0] == (1, expected_one)
    assert [i for i, _ in fused] == [1, 3, 2]


def test_ties_break_by_chunk_index() -> None:
    fused = fuse([(5, 1.0)], [(2, 1.0)])
    assert fused == [(2, round(1 / 61, 6)), (5, round(1 / 61, 6))]
    stats_chunks = [
        Chunk("glossary", f"t{i}", None, "same words here", False, f"Glossary: t{i}")
        for i in range(3)
    ]
    ranked = rank_lexical(_index(stats_chunks, floor_bm25=0.0), "words", 3)
    assert [i for i, _ in ranked] == [0, 1, 2]


# ----- the hybrid route ---------------------------------------------------------------
def test_hybrid_route_with_an_embedder(chunks) -> None:
    embedder = HashingEmbedder(64)
    index = _index(chunks, floor_cosine=2.0, embedder=embedder)
    detail = retrieve_detail(index, "what is the list-to-close ratio", embedder)
    assert detail.answer.route == "hybrid"
    assert detail.vector_top is not None and not detail.vector_skipped
    assert retrieve(index, "what is the list-to-close ratio").route == "bm25"


def test_short_question_skips_the_vector_leg(chunks) -> None:
    embedder = HashingEmbedder(64)
    index = _index(chunks, embedder=embedder)
    detail = retrieve_detail(index, "DOM?", embedder)
    assert detail.vector_skipped and detail.vector_top is None
    # The route names what ranked: BM25 alone, since the vector leg did not run.
    assert detail.answer.route == "bm25"
    assert detail.answer.chunk_ids()[0] == "trestle#DaysOnMarket"


def test_the_cosine_floor_can_find_a_chunk(chunks) -> None:
    embedder = HashingEmbedder(64)
    question = "tell me about the pool at the home"
    loose = _index(chunks, floor_bm25=1e9, floor_cosine=-1.0, embedder=embedder)
    tight = _index(chunks, floor_bm25=1e9, floor_cosine=1.01, embedder=embedder)
    assert retrieve(loose, question, embedder).found
    assert not retrieve(tight, question, embedder).found


def test_rank_vector_orders_by_cosine(chunks) -> None:
    embedder = HashingEmbedder(64)
    index = _index(chunks, embedder=embedder)
    ranked = rank_vector(index, index.vectors[3], 2)
    assert ranked[0] == (3, 1.0)
    with pytest.raises(ValueError):
        rank_vector(index, np.zeros(64, dtype=np.float32), 2)
    with pytest.raises(ValueError):
        rank_vector(index, np.ones(8, dtype=np.float32), 2)


class _FailingEmbedder(HashingEmbedder):
    def embed(self, texts):  # noqa: D401 - a stub
        raise ProviderError("no_consent")


def test_a_provider_error_propagates_for_the_tool_to_degrade(chunks) -> None:
    good = HashingEmbedder(64)
    index = _index(chunks, embedder=good)
    with pytest.raises(ProviderError):
        retrieve(index, "what is the list-to-close ratio", _FailingEmbedder(64))


def test_degrade_keeps_the_lexical_ranks_and_names_the_reason(chunks) -> None:
    """Asked to degrade, a refused embedding leaves BM25 alone in one pass: the
    same answer as a lexical run, route bm25, the reason code kept."""
    index = _index(chunks, embedder=HashingEmbedder(64))
    question = "what is the list-to-close ratio"
    detail = retrieve_detail(index, question, _FailingEmbedder(64), degrade=True)
    lexical = retrieve_detail(index, question)
    assert detail.provider_reason == "no_consent" and not detail.vector_skipped
    assert detail.answer == lexical.answer and detail.answer.route == "bm25"
    assert detail.exact_hits == lexical.exact_hits and detail.vector_top is None


def test_exact_hits_passed_in_are_used_as_given(chunks, index) -> None:
    question = "what does DOM mean"
    exact = lookup_exact(question, chunks)
    assert retrieve_detail(index, question, exact=exact) == retrieve_detail(
        index, question
    )
    detail = retrieve_detail(_index(chunks, floor_bm25=0.0), question, exact=[])
    assert detail.exact_hits == 0 and detail.answer.chunks[0].match == "ranked"


def test_an_embedder_of_another_model_is_refused(chunks) -> None:
    index = _index(chunks, embedder=HashingEmbedder(64))
    with pytest.raises(ValueError):
        retrieve(index, "what is the list-to-close ratio", HashingEmbedder(32))


# ----- the confidential cap -----------------------------------------------------------
def test_cap_keeps_short_text_whole() -> None:
    text = "one two three"
    assert cap_text(text, "two") == text


def test_cap_windows_around_the_first_match() -> None:
    words = [f"w{n}" for n in range(300)]
    words[200] = "DaysOnMarket"
    capped = cap_text(" ".join(words), "what is days on market")
    body = capped.removeprefix("… ").removesuffix(" …").split()
    assert len(body) == CAP_WORDS
    assert "DaysOnMarket" in body
    assert capped.startswith("… ") and capped.endswith(" …")


def test_cap_takes_the_start_when_nothing_matches() -> None:
    text = " ".join(f"w{n}" for n in range(300))
    capped = cap_text(text, "unrelated question")
    assert capped.split()[:2] == ["w0", "w1"]
    assert capped.endswith(" …") and not capped.startswith("…")


def test_cap_chunk_trims_only_confidential_chunks() -> None:
    long_text = " ".join(f"w{n}" for n in range(300))
    own = Chunk("glossary", "t", None, long_text, False, "Glossary: t")
    secret = replace(own, doc="primer", key="s1", confidential=True)
    assert cap_chunk(own, "q") is own
    assert len(cap_chunk(secret, "q").text.split()) == CAP_WORDS + 1
    # The same rule for an answer's chunk (what the tool trims).
    returned = RetrievedChunk(
        text=long_text,
        source_doc="primer",
        section_or_field="s1",
        score=0.5,
        match="ranked",
        confidential=True,
    )
    capped = cap_chunk(returned, "q")
    assert isinstance(capped, RetrievedChunk)
    assert len(capped.text.split()) == CAP_WORDS + 1
    assert cap_chunk(returned.model_copy(update={"confidential": False}), "q").text == (
        long_text
    )
