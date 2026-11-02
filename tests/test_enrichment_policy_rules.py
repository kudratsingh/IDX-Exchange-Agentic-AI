"""Synthetic tests for deterministic triage against the approved review policy."""

import pytest

from idx_agent.enrichment.policy_rules import (
    POLICY_FACETS,
    POLICY_RULES_VERSION,
    triage,
)


def label(value, polarity="affirmed", temporality="current"):
    return {
        "group": "x",
        "value": value,
        "polarity": polarity,
        "temporality": temporality,
    }


@pytest.mark.parametrize(
    ("value", "text", "outcome"),
    [
        # Hardwood: explicit word, engineered hardwood and listed species qualify.
        ("hardwood", "Invented home with hardwood floors throughout.", "support"),
        ("hardwood", "Invented home with engineered hardwood flooring.", "support"),
        ("hardwood", "Invented home with white oak floors.", "support"),
        ("hardwood", "Invented home with Brazilian walnut floors.", "support"),
        ("hardwood", "Invented home with oak parquet in the den.", "support"),
        # Hardwood: generic, real and unlisted woods have no qualifying wording.
        ("hardwood", "Invented home with engineered wood floors.", "omit"),
        ("hardwood", "Invented home with real wood floors.", "omit"),
        ("hardwood", "Invented home with natural wood flooring.", "omit"),
        ("hardwood", "Invented home with bamboo floors.", "omit"),
        ("hardwood", "Invented home with pine floors.", "omit"),
        ("hardwood", "Invented home with parquet floors.", "omit"),
        # Hardwood: a species or the word in other roles needs an individual reading.
        ("hardwood", "Invented home with engineered oak floors.", "read"),
        ("hardwood", "Invented home with oak-look vinyl floors.", "read"),
        ("hardwood", "Oak cabinets and tile floors.", "read"),
        ("hardwood", "Invented home with hardwood cabinets and tile.", "read"),
        ("hardwood", "Original HW floors throughout.", "read"),
        ("hardwood", "Invented home with solid wood flooring.", "support"),
        ("hardwood", "Invented home with solid pine wood floors.", "read"),
        ("hardwood", "Bamboo hardwood floors in the den.", "read"),
        ("hardwood", "Hardwood floor plan B with tile.", "read"),
        # Solar: electric wording is kept; any non-electric mention gets read.
        ("solar", "Invented home with owned solar panels.", "support"),
        ("solar", "Solar has covered the usage every year.", "support"),
        ("solar", "Invented home with a solar heated pool.", "read"),
        ("solar", "Solar tubes and a separate panel array.", "read"),
        ("solar", "Includes leased solr array units.", "read"),
        ("solar", "Solar powered gate and owned solar panels.", "read"),
        ("solar", "Solar panels heat the pool.", "read"),
        ("solar", "Roof is ready for solar panels.", "read"),
        # ADU: an explicit existing claim suffices; anything else is read.
        ("adu", "Detached ADU with its own kitchen.", "support"),
        ("adu", "Detached guest house with a bedroom and bath.", "read"),
        ("adu", "Quiet street near the park.", "read"),
        ("adu", "Lot is zoned for an ADU.", "read"),
        ("adu", "The ADU is under construction.", "read"),
        ("patio", "Covered patio in the back yard.", "support"),
        ("patio", "New sliding patio doors in the den.", "omit"),
        ("patio", "Private balcony facing the garden.", "omit"),
        ("patio", "Aluminum patio cover over the yard.", "read"),
        ("mountain_view", "Enjoy mountain views from the deck.", "support"),
        ("mountain_view", "Enjoy foothill views from the deck.", "omit"),
        ("mountain_view", "Windows framing the mountains beyond.", "read"),
        ("water_view", "Sweeping ocean views from the bedroom.", "support"),
        ("water_view", "A waterfront home by the lake.", "read"),
        # Open plan: only explicit plan wording or connected rooms are automatic.
        ("open_plan", "A bright open floor plan.", "support"),
        ("open_plan", "An open-concept layout.", "support"),
        ("open_plan", "The kitchen flows into the dining room.", "support"),
        ("open_plan", "A large open living area.", "read"),
        ("open_plan", "An open kitchen with a large island.", "read"),
        ("open_plan", "A bright, open feel.", "read"),
        ("open_plan", "Open-concept kitchen with an island.", "read"),
        ("open_plan", "The kitchen opens to a great backyard.", "read"),
        ("bonus_room", "Upstairs bonus room for play.", "support"),
        ("walk_in_closet", "Primary suite with a walk-in closet.", "support"),
        ("walk_in_closet", "An invented walk-in steam shower nook.", "omit"),
        ("walk_in_closet", "A walk-in dressing area.", "read"),
        ("pool", "Backyard with a sparkling pool.", "support"),
        ("pool", "Relax poolside on the terrace.", "read"),
        ("pool", "Community amenities include a pool.", "read"),
        ("community_pool", "Community amenities include a pool.", "support"),
        ("community_pool", "Townhome near a public pool and park.", "read"),
        ("community_pool", "Community offers swimming and tennis.", "read"),
        ("gated_community", "Located in a guard-gated community.", "support"),
        ("gated_community", "Located in the gatedcommunity of Example.", "read"),
        ("gated_community", "Amenities include a gated entry and spa.", "read"),
        ("gated_community", "An estate behind private gates.", "read"),
        ("gated_community", "Staffed around the clock by security.", "omit"),
        ("clubhouse", "Community clubhouse for residents.", "support"),
        ("clubhouse", "Optional country club membership with a clubhouse.", "read"),
        ("clubhouse", "A resident clubroom with a full kitchen.", "read"),
        ("clubhouse", "Near the community clubhouse of a golf course.", "read"),
        ("gated_community", "Gated property in a great community.", "read"),
        ("gated_community", "A non-gated community near the park.", "read"),
        ("water_view", "Home on Ocean View Blvd with city views.", "read"),
        ("fitness_center", "Amenities include a fitness center.", "support"),
        ("fitness_center", "Private home gym in the garage.", "read"),
        ("fitness_center", "Residents enjoy a wellness studio.", "read"),
    ],
)
def test_outcomes(value, text, outcome):
    assert triage(text, label(value)).outcome == outcome


def test_rule_version_is_recorded():
    assert POLICY_RULES_VERSION


def test_rules_that_failed_calibration_are_read_not_decided():
    negated = triage("No solar lease here.", label("solar", "negated"))
    assert negated.outcome == "read"
    possible = "The lot has potential for an ADU, buyer to verify."
    assert triage(possible, label("adu", "uncertain", "planned")).outcome == "read"
    assert triage(possible, label("adu", "uncertain", "unspecified")).outcome == "read"


def test_pool_possibility_moves_to_unspecified():
    text = "The lot has room for a pool."
    assert triage(text, label("pool", "uncertain", "planned")).outcome == "retemporal"
    assert triage(text, label("pool", "uncertain", "unspecified")).outcome == "support"
    assert triage(text, label("pool", "affirmed", "planned")).outcome == "read"


def test_pool_proposal_goes_to_individual_reading():
    text = "Approved plans for a pool are ready to issue."
    assert triage(text, label("pool", "uncertain", "planned")).outcome == "read"


def test_planned_new_construction_is_not_redated():
    text = "This new home to be built has a covered patio and an open floor plan."
    assert triage(text, label("patio", "affirmed", "planned")).outcome == "read"
    assert triage(text, label("open_plan", "affirmed", "planned")).outcome == "read"


def test_rejects_facets_outside_scope():
    with pytest.raises(ValueError):
        triage("Example", label("garage"))
    assert "garage" not in POLICY_FACETS
