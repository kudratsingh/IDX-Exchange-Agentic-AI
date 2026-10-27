"""Construct a bounded private sample from an approved, paged source."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from idx_agent.enrichment.stratified_plan import CandidateGroup, stratified_plan
from idx_agent.semantic.embedder import prepare

SEED = "20261027"
SAMPLE_SIZE = 250
MIN_CHARS = 200
SOURCE_ID, SOURCE_TYPE, SOURCE_REMARK = "L_ListingID", "L_Type_", "L_Remarks"
Page = list[Mapping[str, Any]]


def _eligible(pages: Iterable[Page]):
    """Yield the first eligible row per listing, with no output or logging."""
    seen = set()
    for rows in pages:
        if len(rows) > 50:
            raise ValueError("source page exceeds 50 rows")
        for row in rows:
            raw_id = row.get(SOURCE_ID)
            key = str(raw_id).strip() if raw_id is not None else ""
            if not key.isascii() or not key.isdigit() or key in seen:
                continue
            seen.add(key)
            remark = row.get(SOURCE_REMARK)
            if not isinstance(remark, str) or len(remark.strip()) < MIN_CHARS:
                continue
            raw_subtype = row.get(SOURCE_TYPE)
            subtype = str(raw_subtype).strip() if raw_subtype is not None else ""
            yield key, subtype or "Unknown", remark


def build_sample(pages: Callable[[], Iterable[Page]]) -> tuple[list[dict], dict]:
    """Select 250 reproducible groups; return redacted rows and private splits."""
    groups = [CandidateGroup(key, subtype) for key, subtype, _ in _eligible(pages())]
    assignment = stratified_plan(groups, SEED, dev=100, test=150)
    rows = []
    expected_types = {
        group.group: group.subtype for group in groups if group.group in assignment
    }
    for key, subtype, remark in _eligible(pages()):
        if key not in assignment:
            continue
        if expected_types[key] != subtype:
            raise ValueError("source changed between sampling passes")
        prepared = prepare(
            remark, max_chars=max(4000, len(remark) * 8 + 100), redact=True
        )
        if prepared.text is None or prepared.truncated:
            raise ValueError("source remark could not be prepared")
        rows.append({"key": key, "subtype": subtype, "remark": prepared.text})
    if len(rows) != SAMPLE_SIZE or {row["key"] for row in rows} != set(assignment):
        raise ValueError("sample incomplete or source changed")
    rows.sort(key=lambda row: row["key"])
    manifest = {
        "version": 1,
        "dataset_id": "remarks-20261027-v1",
        "seed": SEED,
        "splits": assignment,
    }
    return rows, manifest


def write_private(directory: Path, rows: list[dict], manifest: dict) -> None:
    """Write new private artifacts exclusively, never replacing existing files."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    sample, splits = directory / "sample.jsonl", directory / "splits.json"
    if sample.exists() or splits.exists():
        raise FileExistsError("private sample already exists")
    for path, content in (
        (sample, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)),
        (splits, json.dumps(manifest, sort_keys=True) + "\n"),
    ):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
