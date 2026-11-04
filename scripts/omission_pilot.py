"""WO-026 omission-risk pilot: sample, packet, record and aggregate (private, offline).

Reads the frozen extraction source and the validated effective store read-only, and
writes only new files in a new private directory (default
`data/enrichment/omission-pilot-v1/`). Prints counts only; never keys or remark text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from idx_agent.enrichment import omission_pilot as op
from idx_agent.enrichment.effective_store import StoreUnavailable, open_store
from idx_agent.enrichment.source_check import (
    EXPECTED_RESULTS_DIGEST,
    EXPECTED_WATERMARK,
    results_digest,
)

REPO = Path(__file__).resolve().parents[1]
SOURCE = Path("full/active-facets-v2.sqlite3")
STORE = Path("full/effective-facets-v1.sqlite3")
PILOT_DIR = Path(op.PILOT_ID)
# Frozen benchmark, supplement and spot-check files whose listings must never be
# sampled, so nothing here is tuned against them.
EXCLUDE_FILES = (
    "splits.json",
    "sample.jsonl",
    "deal-signals-supplement.json",
    "wo021-spot-check-sample.jsonl",
)
CODE_FILES = ("src/idx_agent/enrichment/omission_pilot.py", "scripts/omission_pilot.py")
CHUNK = 50


def readonly(path: Path) -> sqlite3.Connection:
    """Open a private SQLite file read-only; refuse links and group/world access."""
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("invalid private database")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def write_new(path: Path, text: str) -> None:
    """Write a new owner-only file; never replace an existing one or follow a link.

    Created exclusively, relative to the parent opened without following links, so a
    path swapped after `destination` checked it cannot redirect the write.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(path.parent, flags)
    try:
        create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(path.name, create, 0o600, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def pilot_dir(data_root: Path) -> Path:
    """The resolved private pilot directory; refused unless it is a real directory.

    The data root may be reached through a link; the pilot directory may not be one.
    """
    path = data_root.resolve() / PILOT_DIR
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise ValueError("the pilot directory must be a real directory, not a link")
    return path


def destination(out: Path, name: str) -> Path:
    """A named private file strictly inside the pilot directory, or ValueError.

    Only a plain file name is accepted: no absolute path, separator, `..` or link at the
    destination, and the resolved path must sit directly in the resolved directory.
    """
    if (
        not name
        or name in (".", "..")
        or "\0" in name
        or os.sep in name
        or (os.altsep and os.altsep in name)
        or Path(name).is_absolute()
    ):
        raise ValueError("output name must be a plain file name in the pilot directory")
    base = out.resolve(strict=True)
    if not stat.S_ISDIR(os.lstat(out).st_mode) or base != out:
        raise ValueError("the pilot directory must be a real directory, not a link")
    path = base / name
    if path.is_symlink() or path.resolve(strict=False).parent != base:
        raise ValueError("output name must be a plain file name in the pilot directory")
    return path


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def excluded_keys(root: Path, source: sqlite3.Connection) -> tuple[set[str], dict]:
    """Benchmark, supplement, spot-check and diagnostic keys, with counts per source."""
    keys: dict[str, set[str]] = {}
    for name in EXCLUDE_FILES:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"missing exclusion file {name}")
        if name == "splits.json":
            found = set(json.loads(path.read_text())["splits"])
        elif name == "deal-signals-supplement.json":
            found = {str(c["id"]) for c in json.loads(path.read_text())["cases"]}
        else:
            found = {str(r["key"]) for r in read_jsonl(path)}
        keys[name] = found
    keys["diagnostic_471"] = {
        k
        for (k,) in source.execute(
            "SELECT listing_key FROM results WHERE diagnostic_count > 0"
        )
    }
    union = set().union(*keys.values())
    return union, {name: len(found) for name, found in keys.items()}


def store_statuses(path: Path) -> tuple[dict[str, dict[str, str]], dict]:
    """Validate the effective store, then read every status and its meta read-only."""
    store = open_store(path)
    if isinstance(store, StoreUnavailable):
        raise ValueError(f"effective store unavailable: {store.reason}")
    store.close()
    db = readonly(path)
    try:
        meta = dict(db.execute("SELECT name, value FROM meta"))
        statuses: dict[str, dict[str, str]] = {
            k: {} for (k,) in db.execute("SELECT listing_key FROM listings")
        }
        for key, facet, status in db.execute(
            "SELECT listing_key, facet, status FROM facets"
        ):
            statuses[key][facet] = status
    finally:
        db.close()
    return statuses, meta


def code_state() -> dict:
    """The commit the code ran at, and whether the pilot's own files were modified."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()

    return {
        "code_commit": git("rev-parse", "HEAD"),
        "code_files_modified": bool(git("status", "--porcelain", "--", *CODE_FILES)),
        "code_sha256": {
            name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
            for name in CODE_FILES
        },
    }


def cmd_sample(args) -> None:
    root = args.data_root
    (root.resolve() / PILOT_DIR).mkdir(mode=0o700, exist_ok=False)
    out = pilot_dir(root)
    source = readonly(root / SOURCE)
    try:
        if results_digest(source) != EXPECTED_RESULTS_DIGEST:
            raise ValueError("extraction results differ from the approved digest")
        excluded, excluded_counts = excluded_keys(root, source)
        statuses, meta = store_statuses(root / STORE)
        if meta.get("results_digest") != EXPECTED_RESULTS_DIGEST:
            raise ValueError("store was not built from the approved results")
        rows = []
        for key, input_hash, remark in source.execute(
            "SELECT listing_key, input_hash, remark FROM inputs ORDER BY sequence"
        ):
            if hashlib.sha256(remark.encode()).hexdigest() != input_hash:
                raise ValueError("remark differs from its recorded hash")
            if key not in statuses:
                raise ValueError("store does not cover a source listing")
            rows.append((key, remark, statuses[key]))
    finally:
        source.close()
    population = op.build_population(rows, excluded)
    items = op.draw_sample(population, args.seed)
    for item in items:
        item["status_at_sampling"] = statuses[item["listing_key"]].get(item["facet"])
    text = op.canonical_jsonl(items)
    manifest = {
        "pilot_id": op.PILOT_ID,
        "work_order": "WO-026",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": args.seed,
        "method": op.METHOD,
        "unit": "listing x facet whose effective status is not present",
        "strata_definition": {
            "labeled_non_present": "store has a non-present status for the facet",
            "cue": "no status for the facet; remark matches the facet's lexical cue",
            "no_cue": "no status for the facet; no cue match",
        },
        "allocation": {f: op.allocation(f) for f in sorted(op.ELIGIBLE_FACETS)},
        "limited_facets": sorted(op.LIMITED_FACETS),
        "population_counts": op.population_counts(population),
        "source_rows": len(rows),
        "excluded_listings": len(excluded),
        "excluded_by_source": excluded_counts,
        "items": len(items),
        "sample_sha256": op.sha256_text(text),
        "store": {
            "file_sha256": hashlib.sha256((root / STORE).read_bytes()).hexdigest(),
            **{
                k: meta[k]
                for k in (
                    "source_watermark",
                    "policy_version",
                    "rules_version",
                    "results_digest",
                    "listing_count",
                )
            },
        },
        "source_watermark_expected": EXPECTED_WATERMARK,
        "guide_version": op.GUIDE_VERSION,
        **code_state(),
        "scope_note": "pilot sample; not a dataset-wide estimate",
    }
    write_new(destination(out, "sample.jsonl"), text)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True)
    write_new(destination(out, "manifest.json"), manifest_text)
    print(json.dumps({"items": len(items), "sample_sha256": manifest["sample_sha256"]}))


def load_sample(out: Path) -> tuple[list[dict], dict]:
    """The frozen sample, refused when it differs from its manifest hash."""
    manifest = json.loads((out / "manifest.json").read_text())
    text = (out / "sample.jsonl").read_text(encoding="utf-8")
    if op.sha256_text(text) != manifest["sample_sha256"]:
        raise ValueError("sample differs from its manifest")
    return [json.loads(line) for line in text.splitlines() if line], manifest


def verified_remarks(source: sqlite3.Connection, sample: list[dict]) -> dict[str, str]:
    """Each sampled listing's remark, verified against its frozen source-text hash.

    The frozen hash is `results.input_hash`, covered by the approved digest. Any missing
    or changed remark refuses the packet, naming item ids, never keys or text.
    """
    if results_digest(source) != EXPECTED_RESULTS_DIGEST:
        raise ValueError("extraction results differ from the approved digest")
    keys = sorted({item["listing_key"] for item in sample})
    found: dict[str, list[tuple]] = {}
    for start in range(0, len(keys), CHUNK):
        chunk = keys[start : start + CHUNK]
        marks = ", ".join("?" * len(chunk))
        for key, frozen, input_key, input_hash, remark in source.execute(
            "SELECT r.listing_key, r.input_hash, i.listing_key, i.input_hash, i.remark "
            "FROM results r LEFT JOIN inputs i USING(sequence) "
            f"WHERE r.listing_key IN ({marks})",
            chunk,
        ):
            found.setdefault(key, []).append((frozen, input_key, input_hash, remark))
    remarks: dict[str, str] = {}
    refused = []
    for position, item in enumerate(sample, 1):
        key = item["listing_key"]
        rows = found.get(key, [])
        if len(rows) == 1:
            frozen, input_key, input_hash, remark = rows[0]
            if (
                isinstance(remark, str)
                and input_key == key
                and input_hash == frozen
                and hashlib.sha256(remark.encode()).hexdigest() == frozen
            ):
                remarks[key] = remark
                continue
        refused.append(f"{item['item_id']} (#{position})")
    if refused:
        raise ValueError(
            f"source text missing or changed for {len(refused)} sampled item(s): "
            + ", ".join(refused)
        )
    return remarks


def cmd_packet(args) -> None:
    out = pilot_dir(args.data_root)
    target = destination(out, args.name)
    sample, _ = load_sample(out)
    source = readonly(args.data_root / SOURCE)
    try:
        remarks = verified_remarks(source, sample)
    finally:
        source.close()
    packet = [
        {
            "item_id": item["item_id"],
            "facet": item["facet"],
            "stratum": item["stratum"],
            "status_at_sampling": item["status_at_sampling"],
            "cue_spans": op.cue_spans(item["facet"], remarks[item["listing_key"]]),
            "remark": remarks[item["listing_key"]],
        }
        for item in sample
    ]
    write_new(target, op.canonical_jsonl(packet))
    print(json.dumps({"packet_items": len(packet)}))


def cmd_record(args) -> None:
    out = pilot_dir(args.data_root)
    target = destination(out, args.name)
    sample, manifest = load_sample(out)
    records = op.validate_judgments(read_jsonl(args.draft), sample, args.kind)
    for record in records:
        record["sample_sha256"] = manifest["sample_sha256"]
    write_new(target, op.canonical_jsonl(records))
    print(json.dumps({"recorded": len(records), "of": len(sample)}))


def cmd_aggregate(args) -> None:
    out = pilot_dir(args.data_root)
    target = destination(out, args.name) if args.name else None
    sample, manifest = load_sample(out)
    model = read_jsonl(destination(out, args.judgments))
    human = read_jsonl(destination(out, args.human)) if args.human else []
    for records, kind in ((model, "model"), (human, "human")):
        op.validate_judgments(records, sample, kind)
        if any(r.get("sample_sha256") != manifest["sample_sha256"] for r in records):
            raise ValueError("judgments were recorded against another sample")
    result = op.aggregate(
        sample, op.merge_reviews(model, human), manifest["population_counts"]
    )
    result["sample_sha256"] = manifest["sample_sha256"]
    text = json.dumps(result, indent=2, sort_keys=True)
    if target is not None:
        write_new(target, text)
    print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=REPO / "data/enrichment")
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample", help="draw and freeze the stratified sample")
    sample.add_argument("--seed", default=op.SEED)
    packet = sub.add_parser("packet", help="export the private review packet")
    packet.add_argument("--name", default="packet.jsonl")
    record = sub.add_parser("record", help="validate and record review judgments")
    record.add_argument("--draft", type=Path, required=True)
    record.add_argument("--kind", choices=op.REVIEW_TYPES, required=True)
    record.add_argument("--name", default="judgments.jsonl")
    agg = sub.add_parser("aggregate", help="compute aggregate counts and rates")
    agg.add_argument("--judgments", default="judgments.jsonl")
    agg.add_argument("--human", default=None)
    agg.add_argument("--name", default=None)
    args = parser.parse_args(argv)
    handlers = {
        "sample": cmd_sample,
        "packet": cmd_packet,
        "record": cmd_record,
        "aggregate": cmd_aggregate,
    }
    handlers[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
