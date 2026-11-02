"""scripts/refresh_preflight.py (WO-021): a synthetic store and SQLite listings table,
the private inventory (0600, under data/ only), counts-only output, no store write."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.test_enrichment_refresh_preflight import SqliteConn, engine

from idx_agent.enrichment.effective_store import write_store

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_preflight.py"
WATERMARK = "2026-09-18 06:58:44"
OLD, NEW = "2026-09-01 00:00:00", "2026-09-18 07:00:00"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_preflight_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load()


def _store(path: Path, keys) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "source_watermark": WATERMARK,
        "policy_version": "synthetic",
        "rules_version": "synthetic",
        "source_rows": len(keys),
        "built_from": "{}",
    }
    write_store(path, [(k, {}) for k in keys], meta)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    full = tmp_path / "data" / "enrichment" / "full"
    store = _store(full / "effective-facets-v1.sqlite3", ["100", "101", "102", "103"])
    frozen = full / "active-facets-v2.sqlite3"
    frozen.write_bytes(b"frozen source stand-in")
    return tmp_path, store, frozen


def _listings():
    return SqliteConn(
        engine(
            [
                ("100", OLD, "Active"),  # unchanged
                ("101", OLD, "Active"),  # changed through a newer row
                ("101", NEW, "Active"),
                ("103", OLD, "Closed"),  # no longer active; 102 is absent
                ("200", NEW, "Active"),  # new
                ("201", OLD, "Active"),  # never extracted
                ("202", OLD, "Active"),  # ambiguous: two rows, same time
                ("202", OLD, "Active"),
                ("300", OLD, "Closed"),  # out of scope
            ]
        )
    )


def test_run_writes_a_private_inventory_and_returns_counts(workdir):
    tmp, store, frozen = workdir
    before = (_digest(store), _digest(frozen))
    output = Path("data/enrichment/refresh/preflight-inventory.jsonl")
    conn = _listings()
    summary = script.run(
        Path("data/enrichment/full/effective-facets-v1.sqlite3"), output, conn
    )
    assert summary["classes"] == {
        "unchanged": 1,
        "changed": 1,
        "new": 1,
        "never_extracted": 1,
        "no_longer_active": 2,
        "ambiguous": 1,
    }
    assert summary["usable"] == 1 and summary["out_of_scope"] == 1
    assert summary["data_as_of"] == NEW and summary["source_watermark"] == WATERMARK
    assert summary["store_listings"] == 4 and summary["source_listing_ids"] == 7
    assert "100" not in json.dumps(summary)  # counts only, never a key
    target = tmp / output
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    lines = [json.loads(x) for x in target.read_text().splitlines()]
    by_key = {line["listing_key"]: line for line in lines}
    assert by_key["101"]["class"] == "changed" and by_key["101"]["rows"] == 2
    assert by_key["102"]["reason"] == "absent_from_source"
    assert by_key["202"]["reason"] == "unordered_duplicate"
    assert set(by_key) == {"100", "101", "102", "103", "200", "201", "202"}
    assert (_digest(store), _digest(frozen)) == before
    assert all(sql.lstrip().startswith("SELECT") for sql, _ in conn.statements)
    assert all(params[-1] <= 50 for sql, params in conn.statements if "LIMIT" in sql)
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]


def test_an_existing_inventory_is_kept_unless_overwrite_is_given(workdir):
    tmp, store, _ = workdir
    output = Path("data/enrichment/refresh/preflight-inventory.jsonl")
    script.run(store, output, _listings())
    with pytest.raises(ValueError, match="exists"):
        script.run(store, output, _listings())
    script.run(store, output, _listings(), overwrite=True)


@pytest.mark.parametrize(
    "output",
    [
        "inventory.jsonl",
        "../outside.jsonl",
        "data/../escape.jsonl",
        "data",
        "/tmp/preflight-inventory.jsonl",
        "data/enrichment/full/active-facets-v2.sqlite3",
        "data/enrichment/full/effective-facets-v1.sqlite3",
    ],
)
def test_the_script_refuses_to_write_outside_data(workdir, monkeypatch, output):
    def no_connect():
        raise AssertionError("must refuse before connecting")

    monkeypatch.setattr("idx_agent.db.pool.connect", no_connect)
    with pytest.raises(SystemExit, match="refused"):
        script.main(["--output", output])
    with pytest.raises(ValueError):
        script.checked_output(Path(output))


def test_a_symlink_out_of_data_is_refused(workdir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "data" / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="under data"):
        script.checked_output(Path("data/link/inventory.jsonl"))


def test_an_unavailable_store_is_refused(workdir):
    with pytest.raises(RuntimeError, match="unavailable: missing"):
        script.run(Path("data/none.sqlite3"), Path("data/x.jsonl"), _listings())
    assert not Path("data/x.jsonl").exists()


def test_a_table_that_changes_during_the_scan_is_refused(workdir):
    _, store, _ = workdir
    conn = _listings()
    original = conn.cursor

    def cursor():
        if len(conn.statements) == 2:  # after the counts and the first page
            conn.engine.execute(
                "INSERT INTO rets_property VALUES ('050', ?, 'Active', '')", (OLD,)
            )
        return original()

    conn.cursor = cursor
    with pytest.raises(RuntimeError, match="changed during the scan"):
        script.run(store, Path("data/x.jsonl"), conn)
    assert not Path("data/x.jsonl").exists()


def test_the_script_imports_no_model_client_extractor_or_store_writer():
    allowed = {
        "__future__",
        "argparse",
        "collections",
        "json",
        "os",
        "pathlib",
        "sys",
        "tempfile",
        "typing",
        "idx_agent.db.pool",
        "idx_agent.db.refresh_pages",
        "idx_agent.enrichment.effective_store",
        "idx_agent.enrichment.refresh_preflight",
    }
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
            if node.module == "idx_agent.enrichment.effective_store":
                names = {alias.name for alias in node.names}
                assert names == {"StoreUnavailable", "open_store"}
    assert imported <= allowed
