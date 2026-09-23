"""Unit tests for the path, confidential-text and PII gates in scripts/gates/.

Calls each gate's pure check function directly; no git, no database, no files.
These gates run at pre-commit and in CI, so a regression here weakens both.
"""

import sys
from pathlib import Path

# The gates are scripts, not a package; import them from their directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "gates"))

import confidential_text  # noqa: E402
import forbidden_paths  # noqa: E402
import pii_scan  # noqa: E402


def test_forbidden_paths_blocks_data_context_coordination_and_dumps():
    """Each path matches a RULES entry or the .sql rule, so check() returns a reason."""
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
    """Code, docs, .env.example and .sql under the allowed dirs return None."""
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
    """An exact 10-word window matches; one changed word or a shorter run does not."""
    window = "the quick brown fox jumps over the lazy dog tonight"
    fps = {confidential_text.h(window)}
    assert confidential_text.find_matches("intro " + window + " outro", fps)
    assert not confidential_text.find_matches(
        "the quick brown fox jumps over a lazy dog tonight", fps
    )
    assert not confidential_text.find_matches("the quick brown fox jumps", fps)


def test_confidential_text_honours_allowed_hashes():
    """A fingerprint hash also listed in `allowed` is not reported."""
    window = "one two three four five six seven eight nine ten"
    digest = confidential_text.h(window)
    assert not confidential_text.find_matches(window, {digest}, allowed={digest})


def test_pii_scan_blocks_real_looking_contacts_and_allows_placeholders():
    """One real-looking email and phone are reported; the three placeholders are not."""
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
