"""Prepare a private candidate packet for the offline policy audit."""

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from idx_agent.enrichment.policy_audit import candidates


def main():
    root = Path("data/enrichment")
    source = root / "full/active-facets-v2.sqlite3"
    output = root / "policy-audit-packet.jsonl"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as db:
        rows = list(candidates(db))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(output, flags, 0o600), "w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = Counter(category for row in rows for category in row["categories"])
    print(json.dumps({"candidates": len(rows), "categories": dict(counts)}))


if __name__ == "__main__":
    main()
