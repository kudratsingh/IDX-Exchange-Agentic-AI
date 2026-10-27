"""Create the approved private 250-remark sample; output counts only."""

from pathlib import Path

from idx_agent.db.pool import connect
from idx_agent.enrichment.sample_builder import SEED, build_sample, write_private
from idx_agent.semantic.build_index import iter_pages


def main() -> int:
    root = Path.cwd()
    if not (root / "pyproject.toml").is_file() or not (root / "src/idx_agent").is_dir():
        print("Run from the main repository root.")
        return 1
    private_dir = root / "data" / "enrichment"
    if (private_dir / "sample.jsonl").exists() or (
        private_dir / "splits.json"
    ).exists():
        print("Sample or split manifest already exists; nothing was overwritten.")
        return 1
    conn = None
    try:
        conn = connect()
        conn.autocommit(False)
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        rows, manifest = build_sample(lambda: (page for page, _ in iter_pages(conn)))
        write_private(private_dir, rows, manifest)
    except Exception:
        print("Sample failed; inspect private files and database access locally.")
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
    print(f"sample_count={len(rows)} dev=100 test=150 seed={SEED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
