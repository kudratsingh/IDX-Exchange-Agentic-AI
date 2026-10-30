"""Build a private review packet without changing extraction evidence."""

from __future__ import annotations

import collections
import json
import os
import sqlite3
from pathlib import Path

from idx_agent.enrichment.dev_extraction import parse_response
from idx_agent.enrichment.v2 import parse_v2

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/enrichment"


def readonly(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("invalid private database")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def prepare(db, old, responses):
    """Match saved responses by usage and replay, requiring one match per case."""
    by_usage = collections.defaultdict(list)
    for origin, response in responses:
        by_usage[(origin, json.dumps(response.get("usage"), sort_keys=True))].append(
            response
        )
    for sequence, key, remark, encoded, count, usage, origin in db.execute(
        "SELECT i.sequence,i.listing_key,i.remark,r.facets,r.diagnostic_count,"
        "r.usage,o.extractor FROM inputs i JOIN results r USING(sequence) "
        "JOIN result_origins o USING(sequence) WHERE r.diagnostic_count>0 "
        "ORDER BY i.sequence"
    ):
        comparison = json.loads(encoded)
        if origin == "v1":
            previous = old.execute(
                "SELECT facets,diagnostic_count,usage FROM results WHERE listing_key=?",
                (key,),
            ).fetchone()
            if not previous:
                raise ValueError("v1 original missing")
            comparison, count, usage = json.loads(previous[0]), previous[1], previous[2]
        if origin not in {"v1", "v2"}:
            raise ValueError("unknown provenance")
        matches = []
        usage_key = (origin, json.dumps(json.loads(usage), sort_keys=True))
        for response in by_usage[usage_key]:
            annotations, errors = (
                parse_response(response, remark)
                if origin == "v1"
                else parse_v2(response, remark)
            )
            facets = [
                {k: a[k] for k in ("group", "value", "polarity", "temporality")}
                for a in annotations
                if origin == "v2" or a["kind"] == "facet"
            ]
            if facets == comparison and len(errors) == count:
                matches.append((response, errors))
        if len(matches) != 1:
            raise ValueError("response cannot be uniquely matched")
        yield {
            "sequence": sequence,
            "listing_key": key,
            "origin": origin,
            "remark": remark,
            "response": matches[0][0],
            "diagnostics": matches[0][1],
            "stored_facets": json.loads(encoded),
        }


def main():
    debug = PRIVATE / "debug"
    directory = PRIVATE / "full"
    if debug.is_symlink() or not debug.is_dir() or debug.stat().st_mode & 0o077:
        raise ValueError("invalid private debug directory")
    responses = []
    for pattern, origin in (("full-*.json", "v1"), ("v2-batch-*.json", "v2")):
        for path in debug.glob(pattern):
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError("invalid private response")
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError("invalid response")
            responses.append((origin, value))
    db = readonly(directory / "active-facets-v2.sqlite3")
    old = readonly(directory / "active-facets-v1.sqlite3")
    try:
        cases = list(prepare(db, old, responses))
    finally:
        db.close()
        old.close()
    if len(cases) != 471:
        raise ValueError("unexpected diagnostic case count")
    path = PRIVATE / "diagnostic-review-packet.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(json.dumps({"review_cases": len(cases)}))


if __name__ == "__main__":
    main()
