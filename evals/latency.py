"""Reproducible latency benchmark for the tool bodies (WO-020 requirement 7).

`python -m evals.latency --database-kind fixture --repeat 20` times each tool body
against the configured database: a cold call (first call after the process's caches
are cleared: as-of dates, the semantic and document indexes) and `--repeat` warm calls
after `--warmup` unrecorded ones, reported as p50, p95 and max in milliseconds. Similar
listings use the `test:hashing` fixture index only and documents the fixture BM25 index;
a real embedder's timing is a separate paid run. No speed threshold is asserted.
Reports go outside the repository by default and are never committed.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_VERSION = 1
# (label, tool body, arguments, database kinds it runs on). Fixture-only rows name
# invented keys or need the fixture indexes.
CASES: tuple[tuple[str, str, dict[str, Any], tuple[str, ...]], ...] = (
    ("health", "health_result", {}, ("fixture", "real")),
    (
        "search_listings city",
        "search_result",
        {"city": "Pasadena"},
        ("fixture", "real"),
    ),
    (
        "search_listings filtered",
        "search_result",
        {"city": "Los Angeles", "min_beds": 3, "max_price": 1_500_000, "limit": 20},
        ("fixture", "real"),
    ),
    ("get_market_stats", "market_result", {"city": "Pasadena"}, ("fixture", "real")),
    (
        "get_market_stats extended",
        "market_result",
        {"city": "Pasadena", "months": 12, "include_extended": True},
        ("fixture", "real"),
    ),
    (
        "recommend price check",
        "recommend_result",
        {"listing_key": 9130001, "k": 0},
        ("fixture",),
    ),
    (
        "find_similar_listings",
        "similar_result",
        {"text": "bright craftsman bungalow with a large yard", "k": 5},
        ("fixture",),
    ),
    (
        "rag_answer bm25",
        "rag_result",
        {"question": "what does days on market mean?"},
        ("fixture", "real"),
    ),
)
COUNT_TABLES = ("rets_property", "california_sold")


def percentile(values: Sequence[float], share: float) -> float:
    """Nearest-rank percentile: the smallest value with `share` at or below it."""
    ordered = sorted(values)
    rank = max(1, math.ceil(share * len(ordered)))
    return ordered[rank - 1]


def summarize(cold_ms: float, warm_ms: Sequence[float]) -> dict[str, float | int]:
    return {
        "cold_ms": round(cold_ms, 2),
        "warm_n": len(warm_ms),
        "p50_ms": round(percentile(warm_ms, 0.50), 2),
        "p95_ms": round(percentile(warm_ms, 0.95), 2),
        "max_ms": round(max(warm_ms), 2),
    }


def manifest(conn: Any) -> dict[str, Any]:
    """Row counts per table and the MySQL version; counts only, never rows."""
    out: dict[str, Any] = {}
    with conn.cursor() as cursor:
        for table in COUNT_TABLES:
            cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
            out[f"{table}_rows"] = int(cursor.fetchall()[0]["n"])
        cursor.execute("SELECT VERSION() AS v")
        out["mysql_version"] = str(cursor.fetchall()[0]["v"])
    return out


def _clear_caches(server: Any) -> None:
    from idx_agent.db import asof

    asof.clear_asof_cache()
    server.reset_semantic_for_tests()
    server.reset_rag_for_tests()


def _timed(call: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = call()
    return (time.perf_counter() - start) * 1000, result


def run(
    database_kind: str, repeat: int, warmup: int, server: Any | None = None
) -> dict[str, Any]:
    """Time every case for this database kind; returns the report body."""
    from evals.run import FixtureIndex, RagFixtureIndex, _git_commit
    from idx_agent.db import pool

    if server is None:
        from idx_agent.mcp_server import server as loaded

        server = loaded
    from evals.ollama import probe_problem

    conn = pool.connect()
    try:
        rows = manifest(conn)
        # A "fixture" report must really be the fixture (few rows, invented keys).
        problem = probe_problem(conn) if database_kind == "fixture" else None
    finally:
        conn.close()
    if problem is not None:
        raise ValueError(f"--database-kind fixture, but {problem}")
    fixture_index, rag_index = FixtureIndex(), RagFixtureIndex()
    tools: dict[str, Any] = {}
    try:
        rag_index.use()
        if database_kind == "fixture":
            fixture_index.use()
        for label, body, args, kinds in CASES:
            if database_kind not in kinds:
                tools[label] = {"skipped": "fixture-only case"}
                continue
            function = getattr(server, body)
            call = (
                (lambda f=function: f())
                if not args
                else (lambda f=function, a=args: f(dict(a)))
            )
            _clear_caches(server)
            if label.startswith("rag_answer"):
                rag_index.use()
            if label.startswith("find_similar"):
                fixture_index.use()
            cold, result = _timed(call)
            for _ in range(warmup):
                call()
            warm = [_timed(call)[0] for _ in range(repeat)]
            tools[label] = {**summarize(cold, warm), "ok": bool(result.ok)}
    finally:
        rag_index.close()
        fixture_index.close()
    return {
        "report_version": REPORT_VERSION,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database_kind": database_kind,
        "repeat": repeat,
        "warmup": warmup,
        "definitions": {
            "cold": "first call after clearing the as-of, semantic and document caches",
            "warm": "each of `repeat` calls after `warmup` unrecorded calls",
            "percentile": "nearest rank over the warm calls",
        },
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        **rows,
        "tools": tools,
    }


def default_out(kind: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.gettempdir()) / "idx-latency" / f"latency-{kind}-{stamp}.json"


def out_problem(path: Path) -> str | None:
    """Reports never land in the tracked tree (only the ignored data/ is allowed)."""
    resolved = path.resolve()
    try:
        inside = resolved.relative_to(ROOT)
    except ValueError:
        return None
    if inside.parts and inside.parts[0] == "data":
        return None
    return "write the latency report outside the repository (or under data/)"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-kind", choices=("fixture", "real"), required=True)
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.repeat < 1 or args.warmup < 0:
        parser.error("--repeat must be at least 1 and --warmup at least 0")
    out = args.out or default_out(args.database_kind)
    if (problem := out_problem(out)) is not None:
        parser.error(problem)
    report = run(args.database_kind, args.repeat, args.warmup)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for label, row in report["tools"].items():
        print(f"{label:28} {json.dumps(row)}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
