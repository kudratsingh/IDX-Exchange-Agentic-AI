"""Create one local keyword-selected owner-labeling sample; no provider call."""

from __future__ import annotations

import json
import os
from pathlib import Path

from idx_agent.db.pool import connect
from idx_agent.enrichment.full_batch import records
from idx_agent.enrichment.supplementary import SEED, select
from idx_agent.semantic.build_index import iter_pages


def main() -> int:
    root = Path.cwd()
    if not (root / "pyproject.toml").is_file():
        print("Run from the main repository root.")
        return 1
    private = root / "data" / "enrichment"
    out = private / "deal-signals-supplement.json"
    if private.is_symlink() or out.exists():
        print(
            "Invalid private directory or sample already exists; nothing overwritten."
        )
        return 1
    conn = None
    try:
        manifest = json.loads((private / "splits.json").read_text(encoding="utf-8"))
        excluded = set(manifest["splits"])
        if len(excluded) != 250:
            raise ValueError("invalid original split")
        conn = connect()
        conn.autocommit(False)
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        selected, available = select(records(iter_pages(conn)), excluded)
        if len(selected) != 40:
            print(
                json.dumps(
                    {
                        "status": "insufficient",
                        "selected": len(selected),
                        "eligible_by_keyword": available,
                    },
                    sort_keys=True,
                )
            )
            return 1
        sample = {
            "version": 1,
            "dataset_id": SEED,
            "cases": [
                {"id": key, "split": "dev", "text": remark}
                for key, remark, _ in selected
            ],
        }
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(sample, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        counts = {
            name: sum(bucket == name for _, _, bucket in selected) for name in available
        }
        print(
            json.dumps(
                {
                    "status": "ready",
                    "selected": len(selected),
                    "selected_by_bucket": counts,
                    "eligible_by_keyword": available,
                    "seed": SEED,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print("Sample failed; inspect private input and database access locally.")
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
