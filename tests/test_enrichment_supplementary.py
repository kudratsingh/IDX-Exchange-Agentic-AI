"""Keyword sampling tests with invented text and identifiers."""

from idx_agent.enrichment.supplementary import select


def test_keyword_sample_is_deterministic_unique_and_excludes_original():
    data = [
        (str(i), ["sold as-is", "back on market", "price reduced"][i % 3])
        for i in range(90)
    ]
    result, available = select(data, {"1", "2"})
    again, _ = select(reversed(data), {"1", "2"})
    assert result == again and len(result) == 40
    assert len({key for key, _, _ in result}) == 40
    assert not {"1", "2"} & {key for key, _, _ in result}
    assert sum(available.values()) == 88
    counts = {
        kind: sum(bucket == kind for _, _, bucket in result) for kind in available
    }
    assert sorted(counts.values()) == [13, 13, 14]


def test_sample_does_not_duplicate_overlapping_signals():
    data = [(str(i), "as is, back on the market, price reduced") for i in range(45)]
    result, _ = select(data, set())
    assert len(result) == len({key for key, _, _ in result}) == 40


def test_insufficient_candidates_returns_short_selection():
    result, _ = select([("1", "as-is")], set())
    assert len(result) == 1
