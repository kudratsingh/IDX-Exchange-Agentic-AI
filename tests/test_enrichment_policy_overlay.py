"""Synthetic tests for assembling policy-audit dispositions."""

import pytest
from scripts.validate_enrichment_review import apply_resolved, validate

from idx_agent.enrichment.policy_overlay import (
    POLICY_VERSION,
    LabelOutcome,
    build_decision,
    evidence_for,
    read_outcome,
    rule_outcome,
)
from idx_agent.enrichment.policy_rules import POLICY_RULES_VERSION, Triage


def label(
    value="pool", polarity="affirmed", temporality="current", group="exterior_lot"
):
    return dict(group=group, value=value, polarity=polarity, temporality=temporality)


def case(remark, *labels):
    return dict(
        sequence=1,
        listing_key="1",
        origin="v2",
        remark=remark,
        stored_facets=list(labels),
    )


def test_keep_is_accepted_unchanged_and_records_method():
    item = case("A backyard pool.", label())
    decision = build_decision(
        item, [LabelOutcome(label(), "keep", "rule", "pool.x", "ok")]
    )
    assert decision["status"] == "accepted_unchanged"
    assert decision["changes"] == []
    assert decision["semantic_reviewed"] is False
    assert decision["label_reviews"][0]["method"] == "rule"
    assert validate([item], [decision]) == {"accepted_unchanged": 1}


def test_read_only_row_is_attested_but_a_rule_row_is_not():
    item = case("A backyard pool.", label())
    read = LabelOutcome(label(), "keep", "read", None, "ok")
    assert build_decision(item, [read])["semantic_reviewed"] is True


def test_remove_produces_exact_evidence_and_applies_in_memory():
    item = case("A relaxing spool outside.", label())
    decision = build_decision(
        item,
        [LabelOutcome(label(), "remove", "rule", "pool.no_mention", "Spool alone.")],
    )
    assert decision["status"] == "corrected"
    assert decision["changes"][0]["evidence_quote"] in item["remark"]
    assert validate([item], [decision]) == {"corrected": 1}
    assert apply_resolved(item["stored_facets"], decision) == []
    assert item["stored_facets"] == [label()]


def test_retag_replaces_axes_and_validates():
    stored = label("adu", "uncertain", "planned")
    item = case("Potential for an ADU.", stored)
    decision = build_decision(
        item,
        [
            LabelOutcome(
                stored,
                "retag",
                "read",
                None,
                "Possibility.",
                ("uncertain", "unspecified"),
            )
        ],
    )
    assert validate([item], [decision]) == {"corrected": 1}
    assert apply_resolved(item["stored_facets"], decision) == [
        label("adu", "uncertain", "unspecified")
    ]


def test_retag_onto_an_existing_label_does_not_duplicate_it():
    planned = label("adu", "uncertain", "planned")
    existing = label("adu", "uncertain", "unspecified")
    item = case("Potential for an ADU.", planned, existing)
    outcomes = [
        LabelOutcome(
            planned, "retag", "read", None, "Possibility.", ("uncertain", "unspecified")
        ),
        LabelOutcome(existing, "keep", "read", None, "ok"),
    ]
    decision = build_decision(item, outcomes)
    assert validate([item], [decision]) == {"corrected": 1}
    assert apply_resolved(item["stored_facets"], decision) == [existing]


def test_identical_duplicate_labels_can_both_be_removed():
    item = case("A relaxing spool.", label(), label())
    outcome = LabelOutcome(label(), "remove", "rule", "pool.no_mention", "Spool alone.")
    decision = build_decision(item, [outcome, outcome])
    assert validate([item], [decision]) == {"corrected": 1}
    assert apply_resolved(item["stored_facets"], decision) == []


def test_unresolved_row_applies_nothing():
    item = case("A pool, perhaps.", label(), label("patio"))
    decision = build_decision(
        item,
        [
            LabelOutcome(
                label(), "unresolved", "read", None, "Cannot tell whose pool."
            ),
            LabelOutcome(
                label("patio"), "remove", "rule", "patio.no_mention", "No patio."
            ),
        ],
    )
    assert decision["status"] == "unresolved"
    assert apply_resolved(item["stored_facets"], decision) == item["stored_facets"]


def test_invalid_action_is_rejected():
    item = case("A pool.", label())
    with pytest.raises(ValueError, match="invalid label action"):
        build_decision(item, [LabelOutcome(label(), "guess", "read", None, "x")])


def test_evidence_falls_back_to_an_exact_excerpt():
    assert (
        evidence_for("Nothing relevant here at all.", "patio")
        in "Nothing relevant here at all."
    )
    assert (
        evidence_for("Nothing relevant here at all.", "garage")
        == "Nothing relevant here at all."[:40]
    )


def test_rule_decisions_record_version_and_evidence():
    item = case("A backyard pool.", label())
    outcome = LabelOutcome(
        label(), "keep", "rule", "pool.x", "ok", evidence="backyard pool"
    )
    review = build_decision(item, [outcome])["label_reviews"][0]
    assert review["rule_version"] == POLICY_RULES_VERSION
    assert review["evidence"] == "backyard pool"


def test_read_decisions_carry_no_rule_version_but_keep_evidence():
    item = case("A backyard pool.", label())
    review = build_decision(item, [LabelOutcome(label(), "keep", "read", None, "ok")])[
        "label_reviews"
    ][0]
    assert review["rule_version"] is None
    assert review["evidence"] in item["remark"]


def test_records_distinguish_rule_processed_from_individually_reviewed():
    item = case("A backyard pool and a patio.", label(), label("patio"))
    rule = LabelOutcome(label(), "keep", "rule", "pool.x", "ok")
    read = LabelOutcome(label("patio"), "keep", "read", None, "ok")
    assert build_decision(item, [rule])["review_mode"] == "rule_processed"
    assert build_decision(item, [read])["review_mode"] == "individually_reviewed"
    assert build_decision(item, [rule, read])["review_mode"] == "mixed"


def test_read_codes_map_to_actions_and_targets():
    stored = label("adu", "uncertain", "planned")
    assert read_outcome(stored, "K").action == "keep"
    assert read_outcome(stored, "O").action == "remove"
    assert read_outcome(stored, "U", "why").action == "unresolved"
    retag = read_outcome(stored, "S")
    assert (retag.action, retag.target) == ("retag", ("uncertain", "unspecified"))
    # Choosing the code that matches the stored axes changes nothing.
    assert read_outcome(stored, "H").action == "keep"
    with pytest.raises(ValueError, match="invalid decision code"):
        read_outcome(stored, "Z")


def test_rule_outcomes_carry_rule_identity_and_evidence():
    stored = label()
    kept = rule_outcome(stored, Triage("support", "pool.x", "a pool"))
    assert (kept.action, kept.rule, kept.evidence) == ("keep", "pool.x", "a pool")
    assert rule_outcome(stored, Triage("omit", "pool.y", None)).action == "remove"
    assert rule_outcome(stored, Triage("retemporal", "pool.z", None)).target == (
        "uncertain",
        "unspecified",
    )
    with pytest.raises(ValueError, match="did not decide"):
        rule_outcome(stored, Triage("read", "pool.review", None))


def test_correction_history_is_preserved_and_policy_version_recorded():
    item = case("A backyard pool.", label())
    history = {"pass": "earlier", "status": "corrected", "reason": "x", "changes": []}
    decision = build_decision(
        item, [LabelOutcome(label(), "keep", "read", None, "ok")], history=history
    )
    assert decision["correction_history"] == [history]
    assert decision["policy_version"] == POLICY_VERSION


def test_row_changed_only_by_earlier_additions_still_has_a_reason():
    item = case("A private patio.")
    addition = dict(
        operation="add",
        original=None,
        corrected_annotation=label("patio"),
        evidence_quote="private patio",
        reason="Explicit patio",
    )
    decision = build_decision(item, [], base_changes=[addition])
    assert decision["status"] == "corrected"
    assert decision["reason"]
    assert validate([item], [decision]) == {"corrected": 1}


def test_retag_and_removal_give_the_same_result_in_either_order():
    a = label("adu", "uncertain", "planned")
    t = label("adu", "uncertain", "unspecified")
    item = case("Potential for an ADU.", a, t)
    retag = LabelOutcome(
        a, "retag", "read", None, "Possibility.", ("uncertain", "unspecified")
    )
    drop = LabelOutcome(t, "remove", "read", None, "Duplicate.")
    forward = apply_resolved(item["stored_facets"], build_decision(item, [retag, drop]))
    backward = apply_resolved(
        item["stored_facets"], build_decision(item, [drop, retag])
    )
    assert forward == backward == [t]


def test_swapped_retags_keep_both_labels():
    a = label("adu", "uncertain", "planned")
    t = label("adu", "uncertain", "unspecified")
    item = case("Potential for an ADU.", a, t)
    outcomes = [
        LabelOutcome(a, "retag", "read", None, "x", ("uncertain", "unspecified")),
        LabelOutcome(t, "retag", "read", None, "x", ("uncertain", "planned")),
    ]
    result = apply_resolved(item["stored_facets"], build_decision(item, outcomes))
    assert sorted(x["temporality"] for x in result) == ["planned", "unspecified"]


def test_read_evidence_is_marked_as_an_automatic_locator():
    item = case("A backyard pool.", label())
    read = build_decision(item, [LabelOutcome(label(), "keep", "read", None, "ok")])
    rule = build_decision(
        item, [LabelOutcome(label(), "keep", "rule", "r", "ok", None, "pool")]
    )
    assert read["label_reviews"][0]["evidence_source"] == "auto_locator"
    assert rule["label_reviews"][0]["evidence_source"] == "rule_match"


def test_a_resolution_note_is_kept_in_the_reason():
    stored = label("water_view", group="location_views")
    kept = read_outcome(stored, "K", "explicit ocean view of the parcel")
    assert kept.action == "keep"
    assert "Resolution: explicit ocean view of the parcel" in kept.reason
    assert read_outcome(stored, "K").reason == "Read and supported."


def test_a_resolution_is_recorded_on_a_kept_label():
    item = case("An ocean-view parcel.", label("water_view", group="location_views"))
    outcome = read_outcome(item["stored_facets"][0], "K", "explicit ocean view")
    review = build_decision(item, [outcome])["label_reviews"][0]
    assert review["resolution"] == "explicit ocean view"
    plain = build_decision(item, [read_outcome(item["stored_facets"][0], "K")])
    assert "resolution" not in plain["label_reviews"][0]
