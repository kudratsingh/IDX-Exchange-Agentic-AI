"""Store-count and v5-provenance hardening at open (WO-035); invented rows only.

These stores carry the real approved digest on purpose: the point is that the digest
alone no longer admits a store. Only the public write/open API is used, so the same
tests run unchanged against the code before the hardening (where they fail).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from idx_agent.enrichment.effective_store import (
    FacetStore,
    StoreUnavailable,
    open_store,
    write_store,
)
from idx_agent.enrichment.source_check import EXPECTED_RESULTS_DIGEST, EXPECTED_ROWS

META = {
    "source_watermark": "2026-09-18 06:58:44",
    "policy_version": "v4",
    "rules_version": "2026-11-01.4",
    "results_digest": EXPECTED_RESULTS_DIGEST,
    "built_from": json.dumps({"overlay": "invented"}),
}


@pytest.fixture(scope="module")
def full_store(tmp_path_factory):
    """An invented store with exactly the approved source's row count."""
    path = tmp_path_factory.mktemp("full") / "full.sqlite3"
    rows = [
        (f"{900000 + i}", {"solar": "present"} if i % 7 == 0 else {})
        for i in range(EXPECTED_ROWS)
    ]
    write_store(path, rows, dict(META, source_rows=EXPECTED_ROWS))
    return path


def _copy(full_store, tmp_path, *statements):
    path = tmp_path / "copy.sqlite3"
    shutil.copyfile(full_store, path)
    with sqlite3.connect(path) as db:
        for statement, params in statements:
            db.execute(statement, params)
    return path


def _set_meta(name, value):
    return ("UPDATE meta SET value = ? WHERE name = ?", (value, name))


def test_the_approved_digest_with_the_trusted_count_opens(full_store):
    store = open_store(full_store)
    assert isinstance(store, FacetStore)
    assert store.info.listing_count == EXPECTED_ROWS
    store.close()


def test_the_approved_digest_with_a_smaller_count_is_refused(tmp_path):
    """Before WO-035 a six-listing store with the approved digest opened, because its
    own three counts agreed with one another."""
    path = tmp_path / "small.sqlite3"
    rows = [(str(100 + i), {"solar": "present"}) for i in range(6)]
    write_store(path, rows, dict(META, source_rows=len(rows)))
    assert open_store(path) == StoreUnavailable("source_count_mismatch")


def test_the_approved_digest_with_a_larger_count_is_refused(full_store, tmp_path):
    bigger = str(EXPECTED_ROWS + 1)
    path = _copy(
        full_store,
        tmp_path,
        ("INSERT INTO listings VALUES (?)", ("999999999",)),
        _set_meta("listing_count", bigger),
        _set_meta("source_rows", bigger),
    )
    assert open_store(path) == StoreUnavailable("source_count_mismatch")


def test_a_store_labelled_v5_without_v5_provenance_is_refused(full_store, tmp_path):
    path = _copy(full_store, tmp_path, _set_meta("policy_version", "v5"))
    assert open_store(path) == StoreUnavailable("provenance_mismatch")


def test_a_v4_store_claiming_v5_provenance_is_refused(full_store, tmp_path):
    claim = json.dumps({"format": "effective-store-built-from-v5/1"})
    path = _copy(full_store, tmp_path, _set_meta("built_from", claim))
    assert open_store(path) == StoreUnavailable("provenance_mismatch")


def test_production_trusts_exactly_the_approved_pair_read_only():
    from idx_agent.enrichment import source_check

    assert source_check.trusted_source_rows(EXPECTED_RESULTS_DIGEST) == 54888
    assert source_check.trusted_source_rows("0" * 64) is None
    # In a fresh process (no tests/conftest.py copy) the pairs are read-only.
    probe = (
        "from types import MappingProxyType as P\n"
        "from idx_agent.enrichment import source_check as s\n"
        "assert isinstance(s.TRUSTED_SOURCES, P)\n"
        "assert dict(s.TRUSTED_SOURCES) == {s.EXPECTED_RESULTS_DIGEST: 54888}\n"
    )
    subprocess.run([sys.executable, "-c", probe], check=True, env=_src_env())


def _src_env():
    src = str(Path(__file__).resolve().parents[1] / "src")
    return dict(
        os.environ, PYTHONPATH=os.pathsep.join([src, os.environ.get("PYTHONPATH", "")])
    )
