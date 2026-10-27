"""The proposed grouping contract uses invented IDs and no data source."""

import pytest

from idx_agent.enrichment.synthetic_sampling import plan_synthetic_split


def test_plan_is_reproducible_bounded_and_group_disjoint():
    rows = [f"synthetic-{n}" for n in range(40)] + ["synthetic-1", "synthetic-1"]
    first = plan_synthetic_split(rows, seed="pilot-v1")
    second = plan_synthetic_split(list(reversed(rows)), seed="pilot-v1")
    assert first == second
    assert len(first.development) == 20 and len(first.test) == 10
    assert not set(first.development) & set(first.test)
    assert first.input_rows == 42


def test_smaller_input_stays_smaller_and_keeps_duplicates_together():
    rows = ["synthetic-1", "synthetic-2", "synthetic-3", "synthetic-3"]
    plan = plan_synthetic_split(rows, seed="pilot-v1")
    assert len(plan.development) == 2 and len(plan.test) == 1
    assert set(plan.development + plan.test) == set(rows)


def test_plan_rejects_oversized_inputs_and_real_looking_ids():
    with pytest.raises(ValueError, match="input size"):
        plan_synthetic_split(["synthetic-1"] * 51, seed="pilot-v1")
    with pytest.raises(ValueError, match="group label"):
        plan_synthetic_split(["synthetic-1", "synthetic-2", "12345"], seed="pilot-v1")
    with pytest.raises(ValueError, match="three synthetic"):
        plan_synthetic_split(["synthetic-1", "synthetic-1"], seed="pilot-v1")
    with pytest.raises(ValueError, match="seed"):
        plan_synthetic_split(
            ["synthetic-1", "synthetic-2", "synthetic-3"], seed="bad seed"
        )


def test_plan_rejects_missing_or_noncanonical_input():
    with pytest.raises(ValueError, match="input size"):
        plan_synthetic_split(None, seed="pilot-v1")
    with pytest.raises(ValueError, match="group label"):
        plan_synthetic_split(
            ["synthetic-01", "synthetic-2", "synthetic-3"], seed="pilot-v1"
        )
