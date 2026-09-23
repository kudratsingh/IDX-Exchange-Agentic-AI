"""The commit gates must work before anything else does."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "gates"))

import confidential_text  # noqa: E402
import forbidden_paths  # noqa: E402
import pii_scan  # noqa: E402


def test_forbidden_paths_blocks_data_context_coordination_and_dumps():
    for p in [
        "data/rets_property.sql",
        "context/handbook.pdf",
        "coordination/notes.md",
        "exports/listings.csv",
        ".env",
        ".env.local",
        "embeddings/index.faiss",
        "notes/dump.sql",
        "docs/handbook.pdf",
        "logs/app.log",
    ]:
        assert forbidden_paths.check(p), p


def test_forbidden_paths_allows_code_docs_migrations_fixtures():
    for p in [
        ".env.example",
        "src/idx_agent/db/pool.py",
        "docs/ARCHITECTURE.md",
        "scripts/migrations/001_dates_and_indexes.sql",
        "tests/fixtures/synthetic.sql",
        "docs/diagram.svg",
        "evals/cases/property_search.yaml",
    ]:
        assert forbidden_paths.check(p) is None, p


def test_confidential_text_matches_a_ten_word_window_only():
    window = "the quick brown fox jumps over the lazy dog tonight"
    fps = {confidential_text.h(window)}
    assert confidential_text.find_matches("intro " + window + " outro", fps)
    assert not confidential_text.find_matches(
        "the quick brown fox jumps over a lazy dog tonight", fps
    )
    assert not confidential_text.find_matches("the quick brown fox jumps", fps)


def test_confidential_text_honours_allowed_hashes():
    window = "one two three four five six seven eight nine ten"
    digest = confidential_text.h(window)
    assert not confidential_text.find_matches(window, {digest}, allowed={digest})


def test_pii_scan_blocks_real_looking_contacts_and_allows_placeholders():
    # Built at runtime so this file never contains a literal address or number.
    real_email = "agent" + "@" + "brokerage.com"
    real_phone = "310" + "-555-" + "0100"
    text = " ".join(
        [
            real_email,
            "replace-me@example.com",
            real_phone,
            "555-010-0100",
            "(555) 010-0199",
        ]
    )
    hits = pii_scan.find_pii(text)
    assert ("email", real_email) in hits
    assert ("phone", real_phone) in hits
    assert len(hits) == 2
