"""Validate seeded subtype sampling on invented group identifiers."""

from collections import Counter

import pytest

from idx_agent.enrichment.stratified_plan import CandidateGroup, stratified_plan


def test_exact_splits_strata_reproducibility_and_deduplication():
    groups = [
        CandidateGroup(f"invented-{i}", "house" if i < 240 else "condo")
        for i in range(300)
    ]
    first = stratified_plan(groups + [groups[0]], "seed-one")
    assert first == stratified_plan(list(reversed(groups)), "seed-one")
    assert first != stratified_plan(groups, "seed-two")
    assert Counter(first.values()) == {"dev": 100, "test": 150}
    by_name = {g.group: g.subtype for g in groups}
    assert Counter(by_name[key] for key in first) == {"house": 200, "condo": 50}
    assert Counter(by_name[key] for key, split in first.items() if split == "dev") == {
        "house": 80,
        "condo": 20,
    }


def test_refuses_insufficient_and_conflicting_groups():
    with pytest.raises(ValueError, match="insufficient"):
        stratified_plan([CandidateGroup("one", "house")], "seed")
    with pytest.raises(ValueError, match="conflicting"):
        stratified_plan(
            [CandidateGroup("one", "house"), CandidateGroup("one", "condo")],
            "seed",
            dev=1,
            test=1,
        )
