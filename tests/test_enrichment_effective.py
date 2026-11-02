"""Effective facets: overlay application and status resolution, on invented labels."""

import pytest

from idx_agent.enrichment.effective import (
    ELIGIBLE_FACETS,
    MATCHING_STATUS,
    apply_overlay,
    effective_rows,
    facet_status,
    facet_statuses,
)


def lab(value="solar", polarity="affirmed", temporality="current", group="g"):
    return dict(group=group, value=value, polarity=polarity, temporality=temporality)


def change(operation, label):
    if operation == "remove":
        return dict(operation="remove", original=label, corrected_annotation=None)
    return dict(operation="add", original=None, corrected_annotation=label)


@pytest.mark.parametrize(
    ("labels", "status"),
    [
        ([lab()], "present"),
        ([lab(temporality="unspecified")], "present"),
        ([lab(polarity="negated")], "stated_absent"),
        ([lab(polarity="negated", temporality="unspecified")], "stated_absent"),
        ([lab(temporality="planned")], "planned"),
        ([lab(polarity="uncertain", temporality="planned")], "planned"),
        ([lab(polarity="uncertain")], "uncertain"),
        ([lab(polarity="uncertain", temporality="unspecified")], "uncertain"),
        ([lab(temporality="historical")], "historical"),
        ([lab(polarity="negated", temporality="historical")], "historical"),
        ([lab(), lab(polarity="negated")], "contradictory"),
        ([lab(), lab(temporality="planned")], "present"),
        ([lab(), lab(polarity="uncertain")], "present"),
        ([lab(temporality="planned"), lab(polarity="uncertain")], "planned"),
    ],
)
def test_status_resolution(labels, status):
    assert facet_status(labels) == status


def test_only_present_matches():
    assert MATCHING_STATUS == "present"


def test_no_label_is_unknown_not_absent():
    assert facet_status([]) is None
    statuses = facet_statuses([lab("solar")])
    assert "pool" not in statuses
    assert statuses == {"solar": "present"}


def test_unknown_axes_are_refused():
    with pytest.raises(ValueError):
        facet_status([lab(polarity="maybe", temporality="someday")])


def test_ineligible_facets_are_dropped():
    assert "office" not in ELIGIBLE_FACETS
    assert facet_statuses([lab("office"), lab("garage")]) == {"garage": "present"}


def test_overlay_removes_adds_and_never_mutates():
    stored = [lab("solar"), lab("pool")]
    disposition = dict(
        status="corrected",
        changes=[
            change("remove", lab("solar")),
            change("add", lab("solar", "uncertain", "unspecified")),
        ],
    )
    result = apply_overlay(stored, disposition)
    assert result == [lab("pool"), lab("solar", "uncertain", "unspecified")]
    assert stored == [lab("solar"), lab("pool")]


def test_unresolved_overlay_changes_nothing():
    stored = [lab("solar")]
    disposition = dict(status="unresolved", changes=[change("remove", lab("solar"))])
    assert apply_overlay(stored, disposition) == stored


def test_overlay_cannot_remove_a_missing_label():
    with pytest.raises(ValueError, match="not present"):
        apply_overlay([], dict(status="corrected", changes=[change("remove", lab())]))
    bad = dict(status="corrected", changes=[dict(operation="swap")])
    with pytest.raises(ValueError, match="unknown overlay operation"):
        apply_overlay([], bad)


def overlay(key, *changes, status="corrected"):
    return dict(listing_key=key, status=status, changes=list(changes))


def test_effective_rows_apply_each_overlay_once():
    results = [
        (1, "101", [lab("solar")]),
        (2, "102", [lab("hardwood")]),
        (3, "103", [lab("pool"), lab("patio", temporality="planned")]),
        (4, "104", []),
    ]
    diagnostic = {1: overlay("101", change("remove", lab("solar")))}
    dataset = {2: overlay("102", change("remove", lab("hardwood")))}
    rows = dict(effective_rows(results, diagnostic, dataset))
    assert rows == {
        "101": {},
        "102": {},
        "103": {"pool": "present", "patio": "planned"},
        "104": {},
    }


def test_effective_rows_refuse_mismatched_or_orphan_overlays():
    results = [(1, "101", [lab()])]
    with pytest.raises(ValueError, match="listing key differs"):
        list(effective_rows(results, {1: overlay("999")}, {}))
    with pytest.raises(ValueError, match="both a diagnostic and a dataset"):
        list(effective_rows(results, {1: overlay("101")}, {1: overlay("101")}))
    with pytest.raises(ValueError, match="no matching result"):
        list(effective_rows(results, {}, {7: overlay("107")}))
