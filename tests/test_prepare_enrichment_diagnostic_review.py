import sqlite3

import pytest
from scripts import prepare_enrichment_diagnostic_review as review


def test_review_packet_requires_unique_matching_response(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE inputs(sequence INTEGER,listing_key TEXT,remark TEXT);
        CREATE TABLE results(sequence INTEGER,facets TEXT,
                             diagnostic_count INTEGER,usage TEXT);
        CREATE TABLE result_origins(sequence INTEGER,extractor TEXT);
        INSERT INTO inputs VALUES (1,'synthetic','synthetic remark');
        INSERT INTO results VALUES (1,'[]',1,'{"input_tokens":1}');
        INSERT INTO result_origins VALUES (1,'v2');
    """)
    old = sqlite3.connect(":memory:")
    response = {"usage": {"input_tokens": 1}}
    monkeypatch.setattr(review, "parse_v2", lambda *_: ([], [{"rule": "synthetic"}]))
    cases = list(review.prepare(db, old, [("v2", response)]))
    assert len(cases) == 1
    assert cases[0]["diagnostics"] == [{"rule": "synthetic"}]
    assert cases[0]["stored_facets"] == []
    with pytest.raises(ValueError, match="uniquely"):
        list(review.prepare(db, old, []))
    with pytest.raises(ValueError, match="uniquely"):
        list(review.prepare(db, old, [("v2", response), ("v2", response)]))
