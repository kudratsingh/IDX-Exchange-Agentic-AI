"""Synthetic tests for assembling the private policy-audit overlays."""

import pytest
from scripts.build_enrichment_policy_overlay import (
    apply_overrides,
    dedupe_additions,
    load_decisions,
    replace_decisions,
)


def test_decisions_accumulate_one_per_label_across_files(tmp_path):
    first = tmp_path / "a.tsv"
    second = tmp_path / "b.tsv"
    first.write_text("1\tpool\taffirmed/current\tK\t\n")
    second.write_text(
        "#1\tpool\taffirmed/current\tO\t\n2\tadu\tuncertain/planned\tU\twhy\n"
    )
    decisions = load_decisions([first, second])
    assert decisions[(1, "pool", "affirmed/current")] == [("K", ""), ("O", "")]
    assert decisions[(2, "adu", "uncertain/planned")] == [("U", "why")]


def test_overrides_require_an_exact_match(tmp_path):
    decisions = {(1, "pool", "affirmed/current"): [("K", "")]}
    path = tmp_path / "overrides.tsv"
    path.write_text("1\tpool\taffirmed/current\tK\tO\n")
    assert apply_overrides(decisions, path) == 1
    assert decisions[(1, "pool", "affirmed/current")] == [("O", "")]
    path.write_text("1\tpool\taffirmed/current\tK\tO\n")
    with pytest.raises(ValueError, match="no matching decision"):
        apply_overrides(decisions, path)


def test_missing_override_file_changes_nothing(tmp_path):
    assert apply_overrides({}, tmp_path / "absent.tsv") == 0


def test_additions_already_present_after_removals_are_dropped():
    kept = {"value": "patio", "polarity": "affirmed", "temporality": "current"}
    annotation = {"value": "adu", "polarity": "uncertain", "temporality": "unspecified"}
    planned = dict(annotation, temporality="planned")
    removal = {"operation": "remove", "original": planned, "corrected_annotation": None}
    add = {"operation": "add", "corrected_annotation": annotation, "reason": "first"}
    same_as_kept = {"operation": "add", "corrected_annotation": kept, "reason": "dup"}
    decision = {
        "status": "corrected",
        "changes": [removal, add, dict(add, reason="second"), same_as_kept],
    }
    assert dedupe_additions(decision, [kept, planned])["changes"] == [removal, add]


def test_status_falls_back_when_only_redundant_additions_remain():
    kept = {"value": "patio", "polarity": "affirmed", "temporality": "current"}
    redundant = {"operation": "add", "corrected_annotation": kept, "reason": "dup"}
    decision = {"status": "corrected", "reason": "x", "changes": [redundant]}
    result = dedupe_additions(decision, [kept])
    assert result["changes"] == []
    assert result["status"] == "accepted_unchanged"


def test_a_full_reread_replaces_every_earlier_code(tmp_path):
    reread = tmp_path / "v4.tsv"
    reread.write_text(
        "1\tpool\taffirmed/current\tO\t\n1\tpool\taffirmed/current\tO\t\n"
    )
    decisions = {(1, "pool", "affirmed/current"): [("K", ""), ("K", "")]}
    assert replace_decisions(decisions, [reread]) == 1
    assert decisions[(1, "pool", "affirmed/current")] == [("O", ""), ("O", "")]


def test_an_override_can_record_its_reasoning(tmp_path):
    decisions = {(1, "pool", "affirmed/current"): [("S", "")]}
    path = tmp_path / "resolutions.tsv"
    path.write_text("1\tpool\taffirmed/current\tS\tK\tbackyard pool is explicit\n")
    assert apply_overrides(decisions, path) == 1
    assert decisions[(1, "pool", "affirmed/current")] == [
        ("K", "backyard pool is explicit")
    ]
