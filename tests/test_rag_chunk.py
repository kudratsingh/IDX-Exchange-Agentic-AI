"""Extraction and chunking (WO-012): no PDFs of ours, no model, no database.

The field-reference and primer inputs are the own-words fixture corpus under
tests/fixtures/docs/ (or invented inline text); schema notes and the glossary are
the real tracked files. A one-page PDF is written byte by byte here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from idx_agent.rag.chunk import (
    MAX_CHUNK_CHARS,
    MIGRATION_MARK,
    PART_WORDS,
    agent_related,
    build_chunks,
    contact_like,
    is_field_start,
    names_protected,
    page_lines,
)
from idx_agent.rag.extract import (
    SourceMissing,
    empty_pages,
    load_pages,
    read_pdf_pages,
    read_text_pages,
)
from idx_agent.rag.sources import SOURCES
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "docs"
SCHEMA_NOTES = ROOT / "docs" / "data" / "schema_notes.md"
GLOSSARY = ROOT / "docs" / "data" / "glossary.md"
PROTECTED = DENYLIST | AGENT_CONTACT
SOLD_MIGRATION = ("close_date_d", "purchase_contract_date_d", "listing_contract_date_d")


def _pdf(pages: list[str]) -> bytes:
    """A minimal PDF, one Helvetica text line per page ("" for a blank page)."""
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode() if text else b""
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _fixture_pages() -> dict[str, list[str]]:
    return {
        "trestle": load_pages(SOURCES["trestle"], FIXTURE / "field_reference.txt"),
        "primer": load_pages(SOURCES["primer"], FIXTURE / "primer.txt"),
        "schema_notes": load_pages(SOURCES["schema_notes"], SCHEMA_NOTES),
        "glossary": load_pages(SOURCES["glossary"], GLOSSARY),
    }


@pytest.fixture(scope="module")
def fixture_chunks():
    return build_chunks(_fixture_pages())


# ----- extraction ---------------------------------------------------------------------
def test_pdf_page_text_comes_back_through_pypdf(tmp_path: Path) -> None:
    pdf = tmp_path / "one.pdf"
    pdf.write_bytes(_pdf(["Invented words on one page"]))
    pages = read_pdf_pages(pdf)
    assert len(pages) == 1
    assert "Invented words on one page" in pages[0]
    assert empty_pages(pages) == []


def test_a_page_without_text_is_reported(tmp_path: Path) -> None:
    pdf = tmp_path / "two.pdf"
    pdf.write_bytes(_pdf(["Some invented text", ""]))
    pages = read_pdf_pages(pdf)
    assert len(pages) == 2
    assert empty_pages(pages) == [2]


def test_a_missing_file_raises_source_missing(tmp_path: Path) -> None:
    with pytest.raises(SourceMissing) as caught:
        load_pages(SOURCES["trestle"], tmp_path / "absent.pdf")
    assert caught.value.source_id == "trestle"
    with pytest.raises(SourceMissing):
        load_pages(SOURCES["summaries"], tmp_path / "no-folder")


def test_text_pages_split_at_page_breaks(tmp_path: Path) -> None:
    file = tmp_path / "pages.txt"
    file.write_text("one\n---- page break ----\ntwo\fthree\n", encoding="utf-8")
    pages = read_text_pages(file)
    assert [p.strip() for p in pages] == ["one", "two", "three"]


def test_running_headers_and_footers_are_removed() -> None:
    bodies = ["alpha words", "beta words", "gamma words", "delta words"]
    pages = [f"Invented Guide header\n{b}\nPage {n} of 4" for n, b in enumerate(bodies)]
    lines, removed = page_lines(pages)
    assert removed == 8
    assert [line for _, line in lines] == bodies
    assert [page for page, _ in lines] == [1, 2, 3, 4]


# ----- the field-entry rule -----------------------------------------------------------
@pytest.mark.parametrize(
    ("line", "following", "expected"),
    [
        ("HeatingKind String 50", "", True),
        ("RoofKind RoofKind Enum", "", True),
        ("RoofKind RoofKind", "Enum", True),
        ("SellerMember Member", "", True),
        ("LotShape", "Int32", True),
        ("PatioSurface Hardscape", "String", True),
        ("PatioSurface Hardscape", "covers the yard", False),
        ("The count begins on day one", "String", False),
        ("lowercase String", "", False),
    ],
)
def test_field_start_rule(line: str, following: str, expected: bool) -> None:
    assert is_field_start(line.split(), following.split()) is expected


def test_contact_like_names() -> None:
    assert contact_like("BuyerOfficeFax")
    assert contact_like("ListAgentURL")
    assert contact_like("ShowingContactPhone")
    assert not contact_like("OfficeCount")
    assert not contact_like("PhoneCount")


def test_agent_related_names() -> None:
    """Whole camel-case parts decide (invented names): Agent or Office anywhere,
    Showing, Lock then Box, or Access then Code or Instructions."""
    for name in (
        "OfficeKey",
        "CoListOfficeKey",
        "BuyerAgentRank",
        "ShowingWindow",
        "LockBoxColor",
        "GateAccessCode",
        "AccessInstructionsNote",
    ):
        assert agent_related(name), name
    # Home facts: Owner and Occupant names, Access in another sense, and a person
    # word inside a longer part.
    for name in (
        "OwnerPays",
        "OwnershipKind",
        "YearsCurrentOwner",
        "OccupantKind",
        "AccessibilityFeatures",
        "AccessRoad",
        "Agentive",
        "Officer",
        "PhoneCount",
        "officecount",
    ):
        assert not agent_related(name), name
    # An owner's contact detail is contact-like, so the chunker still drops it.
    assert contact_like("OwnerMobilePhone") and not agent_related("OwnerMobilePhone")


def test_home_fields_with_person_words_stay_indexed() -> None:
    """The coordinator's refinement of 2026-09-25: Owner, Occupant, and non-code
    Access names are home facts and keep their chunks (invented entries)."""
    pages = {
        "trestle": [
            "OwnerPays String 50\nWho pays which bills.\n"
            "OccupantKind String 25\nWho lives in the home.\n"
            "AccessibilityFeatures String 25\nFeatures for easier access.\n"
            "OwnerMobilePhone String 25\nInvented placeholder words.\n"
            "GateAccessCode String 25\nInvented placeholder words."
        ]
    }
    chunks, drops = build_chunks(pages)
    assert [c.key for c in chunks] == [
        "OwnerPays",
        "OccupantKind",
        "AccessibilityFeatures",
    ]
    assert drops.contact_like_dropped == {"trestle": 1}
    assert drops.agent_related_dropped == {"trestle": 1}


def test_names_protected_matches_whole_names_in_any_case() -> None:
    assert names_protected("see ShowingInstructions for this")
    assert names_protected("LISTAGENTEMAIL, in capitals")
    assert not names_protected("ShowingInstructionsCount is another field")


# ----- Trestle chunks from the fixture corpus -----------------------------------------
def test_one_chunk_per_fixture_field(fixture_chunks) -> None:
    chunks, _ = fixture_chunks
    keys = [c.key for c in chunks if c.doc == "trestle"]
    assert len(keys) == len(set(keys))
    for name in (
        "DaysOnMarket",
        "ClosePrice",
        "ListPrice",
        "OriginalListPrice",
        "BathroomsTotalInteger",
    ):
        assert name in keys
    dom = next(c for c in chunks if c.chunk_id == "trestle#DaysOnMarket")
    assert dom.confidential is True
    assert dom.label.startswith("Trestle field DaysOnMarket, p. ")
    assert dom.text.startswith("DaysOnMarket")


def test_protected_fields_and_sentinels_reach_no_chunk(fixture_chunks) -> None:
    chunks, drops = fixture_chunks
    assert not {c.key for c in chunks} & PROTECTED
    for chunk in chunks:
        assert "SENTINEL" not in chunk.text
        if chunk.key not in {"california_sold"}:
            assert not names_protected(chunk.text), chunk.chunk_id
    assert drops.deny_listed_dropped["trestle"] >= 1
    assert drops.agent_contact_dropped["trestle"] >= 1
    assert drops.field_chunks_dropped["trestle"] == (
        drops.deny_listed_dropped["trestle"] + drops.agent_contact_dropped["trestle"]
    )


def test_contact_like_entries_are_dropped_and_counted() -> None:
    pages = {
        "trestle": [
            "HeatingKind String 50\nHow the home is heated.\n"
            "BuyerOfficeFax String 25\nInvented placeholder words.\n"
            "OfficeCount Int32\nHow many offices a firm keeps."
        ]
    }
    chunks, drops = build_chunks(pages)
    assert [c.key for c in chunks] == ["HeatingKind"]
    assert drops.contact_like_dropped == {"trestle": 1}
    assert drops.agent_related_dropped == {"trestle": 1}


def test_agent_related_entries_are_dropped_and_counted_apart() -> None:
    """The human's decision of 2026-09-25: an entry whose name holds a person word
    and is neither protected nor contact-like is dropped too, in its own count."""
    pages = {
        "trestle": [
            "HeatingKind String 50\nHow the home is heated.\n"
            "ListAgentEmail String 80\nInvented placeholder words.\n"
            "ShowingWindow String 25\nInvented placeholder words.\n"
            "BuyerAgentRank Int32\nInvented placeholder words.\n"
            "ListOfficeUrl String 25\nInvented placeholder words.\n"
            "RoofKind RoofKind Enum\nWhat covers the roof."
        ]
    }
    chunks, drops = build_chunks(pages)
    assert [c.key for c in chunks] == ["HeatingKind", "RoofKind"]
    assert drops.agent_contact_dropped == {"trestle": 1}
    assert drops.field_chunks_dropped == {"trestle": 1}
    assert drops.contact_like_dropped == {"trestle": 1}
    assert drops.agent_related_dropped == {"trestle": 2}
    assert "agent_related_dropped" in drops.as_dict()


def test_fixture_drop_counts(fixture_chunks) -> None:
    """One entry per kind in the fixture field reference; none contact-like."""
    _, drops = fixture_chunks
    assert drops.deny_listed_dropped == {"trestle": 1}
    assert drops.agent_contact_dropped == {"trestle": 1}
    assert drops.field_chunks_dropped == {"trestle": 2}
    assert drops.agent_related_dropped == {"trestle": 1}
    assert drops.contact_like_dropped == {}


def test_a_line_naming_a_protected_field_is_removed_and_counted() -> None:
    pages = {
        "primer": [
            "1. Invented section\nA first line about homes.\n"
            "A line that names OwnerName and must go.\nA last line about homes."
        ]
    }
    chunks, drops = build_chunks(pages)
    assert len(chunks) == 1
    assert "OwnerName" not in chunks[0].text
    assert "A last line about homes." in chunks[0].text
    assert drops.lines_removed == {"primer": 1}


def test_a_long_section_splits_into_parts() -> None:
    body = "\n".join(f"line {n} " + "word " * 20 for n in range(40))
    chunks, drops = build_chunks({"primer": [f"1. Long invented section\n{body}"]})
    assert [c.key for c in chunks] == ["s1.1", "s1.2", "s1.3"]
    assert all(len(c.text.split()) <= PART_WORDS for c in chunks)
    assert chunks[1].label == "Primer section 1, part 2"
    assert drops.split_chunks == {"primer": 1}


def test_primer_sections_are_keyed_by_position(fixture_chunks) -> None:
    chunks, _ = fixture_chunks
    keys = [c.key for c in chunks if c.doc == "primer"]
    assert keys[0].startswith("s1")
    assert all(k.startswith("s") for k in keys)
    first = next(c for c in chunks if c.doc == "primer")
    assert first.label.startswith("Primer section 1")


# ----- schema notes: sections and the table summaries ---------------------------------
def test_sold_summary_lists_all_49_names_in_order(fixture_chunks) -> None:
    chunks, _ = fixture_chunks
    summary = next(c for c in chunks if c.chunk_id == "schema_notes#california_sold")
    assert summary.label == "Schema notes: california_sold"
    assert summary.confidential is False
    lines = summary.text.splitlines()[1:]
    assert len(lines) == 49
    names = [line.removesuffix(MIGRATION_MARK) for line in lines]
    assert names[:3] == ["ListingKey", "ViewYN", "WaterfrontYN"]
    assert "ClosePrice" in names and "CloseDate" in names
    marked = [line for line in lines if line.endswith(MIGRATION_MARK)]
    assert [m.removesuffix(MIGRATION_MARK) for m in marked] == list(SOLD_MIGRATION)
    # Decision 8: the contact column names are listed, with nothing beyond the name.
    for name in ("ListAgentFirstName", "BuyerOfficeName"):
        assert name in lines


def test_active_summary_withholds_contact_names_and_counts_them(fixture_chunks) -> None:
    chunks, _ = fixture_chunks
    summary = next(c for c in chunks if c.chunk_id == "schema_notes#rets_property")
    assert not names_protected(summary.text)
    assert summary.text.splitlines()[-1].startswith("11 more columns hold agent")


def test_schema_sections_split_over_the_length_limit(fixture_chunks) -> None:
    chunks, drops = fixture_chunks
    notes = [c for c in chunks if c.doc == "schema_notes"]
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    keys = {c.key for c in notes}
    assert {"sec2.1", "sec2.2", "sec7", "california_sold", "rets_property"} <= keys
    assert "sec2" not in keys
    assert drops.split_chunks["schema_notes"] >= 1
    sec7 = next(c for c in notes if c.key == "sec7")
    assert sec7.label == "Schema notes section 7"
    assert sec7.page is None


def test_an_empty_chunk_is_dropped_and_counted() -> None:
    text = (
        "# Invented\n\n## kept term\nSome words.\n\n## ListAgentEmail\nListAgentEmail\n"
    )
    chunks, drops = build_chunks({"glossary": [text]})
    assert [c.key for c in chunks] == ["kept_term"]
    assert drops.empty_dropped == {"glossary": 1}


# ----- glossary and market summaries --------------------------------------------------
def test_glossary_has_one_chunk_per_term(fixture_chunks) -> None:
    chunks, _ = fixture_chunks
    terms = {c.key: c for c in chunks if c.doc == "glossary"}
    assert {"days_on_market", "sale_to_list_ratio", "price_per_square_foot"} <= set(
        terms
    )
    ratio = terms["sale_to_list_ratio"]
    assert ratio.label == "Glossary: sale-to-list ratio"
    assert ratio.confidential is False
    assert "ClosePrice" in ratio.text and "ListPrice" in ratio.text


def test_market_summaries_are_keyed_by_city() -> None:
    pages = ["Market summary: San Marino\nAn invented card.", "No header here."]
    chunks, _ = build_chunks({"summaries": pages})
    assert [c.chunk_id for c in chunks] == [
        "summaries#summary:San_Marino",
        "summaries#summary:2",
    ]
    assert chunks[0].label == "Market summary: San Marino"


def test_a_saved_on_line_keeps_the_city_key_and_stays_in_the_text() -> None:
    """The script writes "Saved on <date>" first; the city still keys the chunk and
    the date travels with the passage, so an answer citing it is dated."""
    page = "Saved on 2026-09-24\nMarket summary: Duarte\nAn invented card."
    (chunk,), _ = build_chunks({"summaries": [page]})
    assert chunk.chunk_id == "summaries#summary:Duarte"
    assert chunk.text.splitlines()[0] == "Saved on 2026-09-24"


def test_a_protected_name_in_another_case_counts_as_its_own_kind() -> None:
    """A deny-listed entry written in another case is dropped and counted as
    deny-listed, not as agent contact."""
    page = "\n".join(
        ["SHOWINGINSTRUCTIONS String", "An invented note.", "ListPrice Decimal", "x"]
    )
    chunks, drops = build_chunks({"trestle": [page]})
    assert [c.key for c in chunks] == ["ListPrice"]
    assert drops.deny_listed_dropped == {"trestle": 1}
    assert drops.agent_contact_dropped == {}


def test_unknown_source_is_refused() -> None:
    with pytest.raises(ValueError):
        build_chunks({"handbook": ["text"]})


def test_drop_counts_as_dict_holds_numbers_only(fixture_chunks) -> None:
    _, drops = fixture_chunks
    counts = drops.as_dict()
    assert "field_chunks_dropped" in counts
    assert all(isinstance(n, int) for per in counts.values() for n in per.values())
