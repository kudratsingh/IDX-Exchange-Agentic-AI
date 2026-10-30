"""Synthetic tests for conservative offline policy screening."""

from idx_agent.enrichment.policy_audit import categories


def test_candidates_require_both_label_and_screening_signal():
    facets = [{"value": "hardwood"}, {"value": "solar"}]
    assert categories("Engineered oak floors and a solar-heated pool", facets) == [
        "engineered_wood",
        "solar_heating",
    ]
    assert categories("Engineered oak floors and a solar-heated pool", []) == []


def test_broad_screen_keeps_cases_with_other_qualifying_evidence():
    facets = [{"value": "hardwood"}, {"value": "solar"}]
    assert categories(
        "Engineered wood in the den; hardwood floors and paid solar panels; "
        "the pool has solar heating.",
        facets,
    ) == ["engineered_wood", "solar_heating"]
