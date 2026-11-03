"""Offline enrichment refresh preflight (WO-021): what a refresh would need to do.

Reads the effective store read-only and the listings table in 50-row keyset pages,
writes a private per-listing inventory under data/ (owner-only) and prints counts only.
It never extracts labels, calls a model or API, or writes to any facet store.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from idx_agent.db.refresh_pages import fetch_inventory_counts, iter_listing_rows
from idx_agent.enrichment.effective_store import StoreUnavailable, open_store
from idx_agent.enrichment.refresh_preflight import (
    Inventory,
    ListingRow,
    classify_inventory,
    parse_timestamp,
    summarize,
    to_row,
)

DATA = Path("data")
STORE = DATA / "enrichment" / "full" / "effective-facets-v1.sqlite3"
OUTPUT = DATA / "enrichment" / "refresh" / "preflight-inventory.jsonl"


def checked_output(path: Path, overwrite: bool = False, data: Path = DATA) -> Path:
    """The resolved output path, or ValueError unless it is a new .jsonl under data/."""
    target, root = path.resolve(), data.resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("the inventory must be written under data/")
    if target.suffix != ".jsonl":
        raise ValueError("the inventory must be a .jsonl file")
    if target.exists() and not (overwrite and target.is_file()):
        raise ValueError("the inventory exists; pass --overwrite to replace it")
    return target


def read_store(path: Path) -> tuple[list[str], str]:
    """The store's covered keys and source watermark, opened read-only and validated."""
    store = open_store(path)
    if isinstance(store, StoreUnavailable):
        raise RuntimeError(f"effective store unavailable: {store.reason}")
    try:
        return store.covered_keys(), store.info.source_watermark
    finally:
        store.close()


def scan(conn: Any) -> tuple[dict[str, list[ListingRow]], dict[str, Any]]:
    """Every keyed row grouped by listing ID, checked against counts taken around it."""
    before = fetch_inventory_counts(conn)
    rows: dict[str, list[ListingRow]] = defaultdict(list)
    read = 0
    for key, modified, status in iter_listing_rows(conn):
        rows[key].append(to_row(modified, status))
        read += 1
    if fetch_inventory_counts(conn) != before:
        raise RuntimeError("the listings table changed during the scan")
    if read + before["rows_without_key"] != before["total_rows"]:
        raise RuntimeError("the page scan did not read every keyed row")
    if len(rows) != before["listing_ids"]:
        raise RuntimeError("the page scan did not read every listing ID")
    return dict(rows), before


def write_inventory(
    target: Path, inventory: Inventory, rows: dict[str, list[ListingRow]]
) -> None:
    """Write one JSON line per classified ID atomically, owner-only (0600)."""
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".preflight-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for key, entry in inventory.entries.items():
            times = [r.modified for r in rows.get(key, ()) if r.modified is not None]
            line = {
                "listing_key": key,
                "class": entry.cls,
                "reason": entry.reason,
                "rows": len(rows.get(key, ())),
                "latest_modified": max(times).isoformat(sep=" ") if times else None,
            }
            handle.write(json.dumps(line, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)


def run(
    store_path: Path, output: Path, conn: Any, overwrite: bool = False
) -> dict[str, Any]:
    """Classify, write the private inventory under data/, return aggregate counts."""
    target = checked_output(output, overwrite)
    keys, watermark_text = read_store(store_path)
    watermark = parse_timestamp(watermark_text)
    rows, counts = scan(conn)
    as_of = parse_timestamp(counts["max_modified"])
    if watermark is None or as_of is None:
        raise RuntimeError("no usable watermark or data as-of time")
    inventory = classify_inventory(keys, watermark, rows, as_of)
    write_inventory(target, inventory, rows)
    return {
        "source_watermark": watermark_text,
        "data_as_of": counts["max_modified"],
        "store_listings": len(keys),
        "source_rows": counts["total_rows"],
        "source_listing_ids": counts["listing_ids"],
        "active_listing_ids": counts["active_ids"],
        "rows_without_key": counts["rows_without_key"],
        "rows_without_timestamp": counts["rows_without_timestamp"],
        **summarize(inventory),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        checked_output(args.output, args.overwrite)  # refuse before connecting
    except ValueError as exc:
        raise SystemExit(f"refused: {exc}") from None
    from idx_agent.db.pool import connect

    conn = connect()
    try:
        summary = run(args.store, args.output, conn, args.overwrite)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"refused: {exc}") from None
    finally:
        conn.close()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
