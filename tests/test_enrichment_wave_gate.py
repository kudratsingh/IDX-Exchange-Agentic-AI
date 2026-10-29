from decimal import Decimal

import pytest

from idx_agent.enrichment.wave_gate import check_wave, next_wave


def args():
    return dict(
        expected=100,
        collected=100,
        statuses=["complete"],
        source_verified=True,
        misses=2,
        estimated_spend=Decimal("20"),
        projected_remaining=Decimal("70"),
    )


def test_gate_accepts_thresholds():
    check_wave(**args())


@pytest.mark.parametrize(
    "change",
    [
        {"collected": 99},
        {"statuses": []},
        {"statuses": ["partial"]},
        {"statuses": ["uncertain"]},
        {"source_verified": False},
        {"misses": 3},
        {"projected_remaining": Decimal("70.01")},
        {"projected_remaining": Decimal("NaN")},
        {"estimated_spend": None},
    ],
)
def test_gate_rejects_unknown_or_failed_evidence(change):
    values = args()
    values.update(change)
    with pytest.raises(ValueError):
        check_wave(**values)


def test_schedule_and_human_checkpoints():
    assert next_wave(8000) == 10000
    assert next_wave(18000) == 8000
    with pytest.raises(ValueError, match="human checkpoint"):
        next_wave(26000)
    assert next_wave(26000, checkpoint_approved=True) == 10000
    assert next_wave(36000) == 10000
    with pytest.raises(ValueError, match="human checkpoint"):
        next_wave(46000)
    assert next_wave(46000, checkpoint_approved=True) == 2000
    assert next_wave(54000) == 888
    assert next_wave(54888) == 0
