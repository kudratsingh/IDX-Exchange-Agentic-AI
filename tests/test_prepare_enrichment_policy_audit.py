"""Synthetic tests for conservative offline policy screening."""

from idx_agent.enrichment.policy_audit import (
    categories,
    screen_hardwood_engineered,
    screen_solar_heating_broad,
    screen_solar_heating_exact,
)


def test_candidates_require_both_label_and_screening_signal():
    facets = [{"value": "hardwood"}, {"value": "solar"}]
    assert categories("Engineered oak floors and a solar-heated pool", facets) == [
        "hardwood_label",
        "solar_label",
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
    ) == ["hardwood_label", "solar_label", "engineered_wood", "solar_heating"]


def test_inventory_covers_labels_without_narrow_signals():
    assert categories(
        "A house with unspecified flooring.", [{"value": "hardwood"}]
    ) == ["hardwood_label"]


def test_inventory_covers_every_policy_facet():
    assert categories("A quiet home.", [{"value": "gated_community"}]) == [
        "gated_community_label"
    ]
    assert categories("A quiet home.", [{"value": "garage"}]) == []


def test_reconstructed_hardwood_screen():
    labeled = [{"value": "hardwood"}]
    assert screen_hardwood_engineered("Engineered white oak floors.", labeled)
    assert not screen_hardwood_engineered("Engineered hardwood floors.", labeled)
    assert not screen_hardwood_engineered("Engineered oak; solid wood doors.", labeled)
    assert not screen_hardwood_engineered("Engineered oak floors.", [])


def test_reconstructed_solar_screens():
    labeled = [{"value": "solar"}]
    heated = "A sparkling solar heated pool."
    assert screen_solar_heating_exact(heated, labeled)
    assert screen_solar_heating_broad(heated, labeled)
    assert not screen_solar_heating_exact(heated + " Owned solar panels too.", labeled)
    assert not screen_solar_heating_exact(heated, [])
    assert screen_solar_heating_broad("Pool with a solar cover.", labeled)
    assert not screen_solar_heating_exact("Pool with a solar cover.", labeled)
