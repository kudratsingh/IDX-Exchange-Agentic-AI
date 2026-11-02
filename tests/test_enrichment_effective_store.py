"""Effective-facet store: write, validate on open, fail closed; invented rows."""

import json
import sqlite3
import stat

import pytest
from scripts.build_enrichment_effective_store import verify_manifest

from idx_agent.enrichment import effective_store as store_module
from idx_agent.enrichment.effective_store import (
    FacetStore,
    StoreUnavailable,
    configured_store_path,
    open_store,
    write_store,
)

META = {
    "source_watermark": "2026-09-18 06:58:44",
    "policy_version": "v4",
    "rules_version": "2026-11-01.4",
    "built_from": json.dumps({"overlay": "abc"}),
}
ROWS = [
    ("101", {"solar": "present", "pool": "present"}),
    ("102", {"solar": "planned", "pool": "present"}),
    ("103", {"solar": "uncertain"}),
    ("104", {"solar": "stated_absent"}),
    ("105", {"solar": "historical", "pool": "contradictory"}),
    ("106", {}),
]


@pytest.fixture
def store_path(tmp_path):
    path = tmp_path / "effective.sqlite3"
    assert write_store(path, ROWS, META) == len(ROWS)
    return path


def test_written_store_is_private_and_opens(store_path):
    assert stat.S_IMODE(store_path.stat().st_mode) == 0o600
    store = open_store(store_path)
    assert isinstance(store, FacetStore)
    assert store.info.listing_count == 6
    assert store.info.source_watermark == META["source_watermark"]
    assert store.info.policy_version == "v4"
    store.close()


def test_only_present_features_match_and_all_must_match(store_path):
    store = open_store(store_path)
    assert store.keys_with_all(["solar"]) == ["101"]
    assert store.keys_with_all(["pool"]) == ["101", "102"]
    assert store.keys_with_all(["pool", "solar"]) == ["101"]
    assert store.keys_with_all(["garage"]) == []
    with pytest.raises(ValueError):
        store.keys_with_all([])
    with pytest.raises(ValueError):
        store.keys_with_all(["office"])
    store.close()


def test_missing_labels_stay_unknown(store_path):
    store = open_store(store_path)
    assert store.statuses("106") == {}
    assert store.statuses("999") == {}
    assert "pool" not in store.statuses("103")
    store.close()


def test_store_is_opened_read_only(store_path):
    store = open_store(store_path)
    with pytest.raises(sqlite3.OperationalError):
        store._db.execute("DELETE FROM facets")
    store.close()


def test_unconfigured_or_missing_store_is_unavailable(tmp_path):
    assert open_store(None) == StoreUnavailable("not_configured")
    assert open_store(tmp_path / "absent.sqlite3") == StoreUnavailable("missing")
    junk = tmp_path / "junk.sqlite3"
    junk.write_text("not a database")
    assert isinstance(open_store(junk), StoreUnavailable)


def test_other_schema_versions_are_unavailable(store_path):
    with sqlite3.connect(store_path) as db:
        db.execute("UPDATE meta SET value='0' WHERE name='schema_version'")
    assert open_store(store_path) == StoreUnavailable("schema_mismatch")


def test_incomplete_store_is_unavailable(store_path):
    with sqlite3.connect(store_path) as db:
        db.execute("DELETE FROM facets WHERE listing_key='106'")
        db.execute("DELETE FROM listings WHERE listing_key='106'")
    assert open_store(store_path) == StoreUnavailable("incomplete")


def test_missing_provenance_or_bad_status_is_unavailable(store_path, tmp_path):
    with sqlite3.connect(store_path) as db:
        db.execute("DELETE FROM meta WHERE name='source_watermark'")
    assert open_store(store_path) == StoreUnavailable("incomplete")
    other = tmp_path / "other.sqlite3"
    write_store(other, ROWS, META)
    with sqlite3.connect(other) as db:
        db.execute("UPDATE facets SET status='maybe' WHERE listing_key='101'")
    assert open_store(other) == StoreUnavailable("malformed")


def test_bad_watermark_is_unavailable(tmp_path):
    path = tmp_path / "bad.sqlite3"
    write_store(path, ROWS, dict(META, source_watermark="yesterday"))
    assert open_store(path) == StoreUnavailable("malformed")


def test_write_refuses_ineligible_facets_or_unknown_statuses(tmp_path):
    with pytest.raises(ValueError):
        write_store(tmp_path / "a.sqlite3", [("1", {"office": "present"})], META)
    with pytest.raises(ValueError):
        write_store(tmp_path / "b.sqlite3", [("1", {"solar": "maybe"})], META)


def test_configured_path(tmp_path):
    assert configured_store_path({}) is None
    assert configured_store_path({"IDX_ENRICHMENT_STORE": " "}) is None
    absolute = tmp_path / "x.sqlite3"
    assert configured_store_path({"IDX_ENRICHMENT_STORE": str(absolute)}) == absolute
    relative = configured_store_path({"IDX_ENRICHMENT_STORE": "data/x.sqlite3"})
    assert relative == store_module._REPO_ROOT / "data/x.sqlite3"


def test_build_refuses_artifacts_that_drifted_from_the_freeze(tmp_path):
    artifact = tmp_path / "overlay.jsonl"
    artifact.write_text("frozen")
    import hashlib

    manifest = {"overlay": hashlib.sha256(b"frozen").hexdigest()}
    verify_manifest(manifest, {"overlay": artifact})
    artifact.write_text("edited")
    with pytest.raises(ValueError, match="no longer matches"):
        verify_manifest(manifest, {"overlay": artifact})
    with pytest.raises(ValueError, match="different artifacts"):
        verify_manifest({}, {"overlay": artifact})
