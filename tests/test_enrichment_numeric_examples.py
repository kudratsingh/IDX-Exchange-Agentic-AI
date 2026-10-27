"""Invented examples for the numeric annotation contract, not extractor scores."""

import json
from pathlib import Path


def test_numeric_examples_cover_all_count_and_amount_rules():
    path = Path(__file__).parent / "fixtures/enrichment/numeric_dev.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    by_rule = {case["rule"]: case for case in cases}
    assert len(by_rule) == len(cases)
    assert all(case["source"] == "synthetic" for case in cases)
    assert by_rule["partial_bedrooms"]["expected"] == {}
    assert by_rule["auxiliary_counts"]["expected"] == {"bedrooms": 3}
    assert by_rule["auxiliary_only"]["expected"] == {}
    assert by_rule["first_count"]["expected"] == {"bedrooms": 3}
    assert by_rule["half_baths"]["expected"] == {"bathrooms": 2.5}
    assert by_rule["living_area"]["expected"] == {"living_area_sqft": 1500}
    assert by_rule["asking_price"]["expected"] == {"asking_price_usd": 900000}
    assert by_rule["other_amounts"]["expected"] == {}
