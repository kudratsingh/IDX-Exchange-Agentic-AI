"""Invented tests for bounded sample creation and private writes."""

import json
from collections import Counter

import pytest

from idx_agent.enrichment.sample_builder import build_sample, write_private


def test_stratified_sample_private_shape_and_redaction(tmp_path):
    rows = [
        {
            "L_ListingID": str(i),
            "L_Type_": "house" if i < 240 else "condo",
            "L_Remarks": "A home with a garden. " * 12
            + "Visit https://example.invalid",
        }
        for i in range(300)
    ]
    pages = [rows[i : i + 50] for i in range(0, len(rows), 50)]
    sample, manifest = build_sample(lambda: iter(pages))
    assert len(sample) == 250
    assert Counter(manifest["splits"].values()) == {"dev": 100, "test": 150}
    assert all(set(row) == {"key", "subtype", "remark"} for row in sample)
    assert all(
        "https://" not in row["remark"] and "[link]" in row["remark"] for row in sample
    )
    assert build_sample(lambda: iter(pages)) == (sample, manifest)
    write_private(tmp_path, sample, manifest)
    assert len((tmp_path / "sample.jsonl").read_text().splitlines()) == 250
    assert json.loads((tmp_path / "splits.json").read_text()) == manifest
    with pytest.raises(FileExistsError):
        write_private(tmp_path, sample, manifest)


def test_rejects_large_page_or_insufficient_groups():
    with pytest.raises(ValueError, match="50"):
        build_sample(lambda: iter([[{}] * 51]))
    with pytest.raises(ValueError, match="insufficient"):
        build_sample(lambda: iter([]))


def test_source_change_between_passes_is_rejected():
    rows = [
        {
            "L_ListingID": str(i),
            "L_Type_": "house",
            "L_Remarks": "Invented property text. " * 12,
        }
        for i in range(260)
    ]
    passes = 0

    def source():
        nonlocal passes
        passes += 1
        current = rows if passes == 1 else rows[:-20]
        return iter([current[i : i + 50] for i in range(0, len(current), 50)])

    with pytest.raises(ValueError, match="sample incomplete"):
        build_sample(source)
