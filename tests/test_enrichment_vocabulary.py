"""The schema references candidates only, with no live listing evidence."""

import pytest
from pydantic import ValidationError

from idx_agent.domain.enrichment import FacetGroup, FacetRef
from idx_agent.enrichment.vocabulary import FACETS


def test_eight_groups_cover_every_reference_and_have_nonempty_values():
    assert len(FACETS) == len(FacetGroup) == 8
    assert set(FACETS) == {group.value for group in FacetGroup}
    pairs = [(group, value) for group, values in FACETS.items() for value in values]
    assert len(pairs) == len(set(pairs))
    for group, value in pairs:
        assert FacetRef(group=group, value=value).value == value


@pytest.mark.parametrize(
    "fields",
    [
        {"group": "unknown", "value": "adu"},
        {"group": "style", "value": "adu"},
        {"group": "exterior_lot", "value": "invented"},
        {"group": "exterior_lot", "value": "adu", "verified": True},
    ],
)
def test_unknown_pairs_and_truth_assertions_are_refused(fields):
    with pytest.raises(ValidationError):
        FacetRef.model_validate(fields)


def test_vocabulary_and_references_cannot_be_mutated():
    with pytest.raises(TypeError):
        FACETS["new"] = frozenset()
    with pytest.raises(AttributeError):
        FACETS["style"].add("new")
    ref = FacetRef(group="exterior_lot", value="adu")
    with pytest.raises(ValidationError):
        ref.value = "pool"
