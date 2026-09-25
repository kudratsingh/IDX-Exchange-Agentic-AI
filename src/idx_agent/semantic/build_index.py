"""Build the remarks index once, offline: `python -m idx_agent.semantic.build_index`.

A paid run, so only a human starts it (--allow-paid, a `paid` token; never in CI or
for a test model). WO-010. Reads active rows as idx_reader in keyset pages of 50,
writes shards atomically, resumes after the last finished shard, prints counts only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from idx_agent.db.asof import read_asof_dates
from idx_agent.db.listings import _where
from idx_agent.db.pool import connect, env_setting
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.safety.columns import check_column
from idx_agent.safety.consent import paid_consent_active
from idx_agent.semantic.embedder import (
    BATCH_SIZE,
    MAX_CHARS,
    TEXT_PREP_VERSION,
    UNIT_TOLERANCE,
    Embedder,
    ProviderError,
    embed_settings,
    make_embedder,
    prepare,
    redact_enabled,
)
from idx_agent.semantic.index import (
    ATTR_FIELDS,
    DATA_ROOT,
    DEFAULT_INDEX_ROOT,
    META,
    REPO_ROOT,
    IndexAttrs,
    IndexUnavailable,
    file_sha256,
    index_dir_for,
    inside,
    read_meta,
    replace_with,
    write_index,
)

__all__ = [
    "PAGE_ROWS",
    "SHARD_ROWS",
    "BuildRefused",
    "BuildReport",
    "BuildStopped",
    "PageStats",
    "Record",
    "build",
    "check_output_dir",
    "dry_run",
    "git_ignored",
    "iter_pages",
    "main",
    "page_sql",
    "preflight",
    "prepare_rows",
    "records_to_arrays",
]

TABLE = "rets_property"
PAGE_ROWS = 50
# Embeddable rows per shard: a crash loses at most one shard's paid calls.
SHARD_ROWS = 1000
BUILD_DIR, PROGRESS = "build", "progress.json"
# The build waits longer per request than the tool does, and retries twice.
BUILD_TIMEOUT_S, BUILD_RETRIES = 60.0, 2
_ID, _REMARKS = check_column(TABLE, "L_ListingID"), check_column(TABLE, "L_Remarks")
_CITY, _PRICE = check_column(TABLE, "L_City"), check_column(TABLE, "L_SystemPrice")
_BEDS, _TYPE = check_column(TABLE, "L_Keyword2"), check_column(TABLE, "L_Type_")
_MODIFIED = check_column(TABLE, "ModificationTimestamp")
_DISPLAY = check_column(TABLE, "L_DisplayId")


class BuildRefused(RuntimeError):
    """A precondition failed (CI, test model, consent, path); nothing was paid."""


class BuildStopped(RuntimeError):
    """The build stopped part way and wrote no meta.json (e.g. the as-of moved)."""


@dataclass(frozen=True)
class Record:
    """One embeddable row: key, prepared text, and the snapshot filter values."""

    key: int
    text: str
    city: str | None
    list_price: int | None
    bedrooms: int | None
    property_subtype: str | None


@dataclass
class PageStats:
    """Counts over rows read; never a key or a remark."""

    rows_read: int = 0
    skipped_empty: int = 0
    truncated: int = 0
    redacted: int = 0
    duplicates: int = 0
    bad_keys: int = 0
    chars: int = 0

    def add(self, other: PageStats) -> None:
        """Add another set of counts into this one."""
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class BuildReport:
    """What a build did, for the printed summary (counts, timings, sizes)."""

    index_dir: Path
    already_complete: bool = False
    stats: PageStats = field(default_factory=PageStats)
    embedded: int = 0
    usage_tokens: int | None = None
    shards_built: int = 0
    shards_reused: int = 0
    embed_calls: int = 0
    seconds: float = 0.0
    bytes_on_disk: int = 0


def page_sql(after: str) -> tuple[str, tuple[Any, ...]]:
    """One keyset page: active rows with listing id > `after`, at most PAGE_ROWS.

    Allowlisted columns only, every value bound. A repeated id comes newest first.
    """
    where, params = _where(PropertySearchFilters())
    columns = ", ".join((_ID, _REMARKS, _CITY, _PRICE, _BEDS, _TYPE))
    sql = (
        f"SELECT {columns}\nFROM {TABLE}\nWHERE {where} AND {_ID} > %s\n"
        f"ORDER BY {_ID} ASC, {_MODIFIED} DESC, {_DISPLAY} ASC\nLIMIT %s"
    )
    return sql, (*params, after, PAGE_ROWS)


def _fetch(conn: Any, after: str) -> list[dict[str, Any]]:
    """Run one page; raise if the statement returned more than PAGE_ROWS rows."""
    sql, params = page_sql(after)
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = list(cursor.fetchall())
    if len(rows) > PAGE_ROWS:
        raise RuntimeError(f"page returned more than {PAGE_ROWS} rows")
    return rows


def iter_pages(
    conn: Any, after: str = ""
) -> Iterator[tuple[list[dict[str, Any]], str]]:
    """Yield (rows, cursor after them); a page never ends part way through one id.

    A full page gives back its last id's rows so the next page reads them whole;
    that keeps a repeated id together, so the newest row can win.
    """
    while True:
        rows = _fetch(conn, after)
        full = len(rows) == PAGE_ROWS
        if full:
            last = rows[-1][_ID]
            rows = [row for row in rows if row[_ID] != last]
            if not rows:
                raise RuntimeError(f"{PAGE_ROWS} rows share one listing id")
        if rows:
            after = str(rows[-1][_ID])
            yield rows, after
        if not full:  # a short page is the last one
            return


def _as_int(value: Any) -> int | None:
    """A whole number from an int, numeric text, or float; None when unusable."""
    try:
        return None if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return None


def prepare_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_chars: int = MAX_CHARS,
    redact: bool = True,
    max_records: int | None = None,
) -> tuple[list[Record], PageStats, str | None]:
    """Turn page rows into Records: first row per id wins, numeric ids only.

    Stops once `max_records` are in hand. Returns the records, the counts, and the
    last listing id consumed (None when nothing was consumed).
    """
    records: list[Record] = []
    stats = PageStats()
    seen: set[str] = set()
    last: str | None = None
    for row in rows:
        source_id = str(row[_ID])
        if (
            max_records is not None
            and len(records) >= max_records
            and source_id != last
        ):
            break
        last = source_id
        stats.rows_read += 1
        if source_id in seen:
            stats.duplicates += 1
            continue
        seen.add(source_id)
        key = source_id.strip()
        if not (key.isascii() and key.isdigit()):
            stats.bad_keys += 1
            continue
        prepared = prepare(row[_REMARKS], max_chars=max_chars, redact=redact)
        if prepared.text is None:
            stats.skipped_empty += 1
            continue
        stats.truncated += prepared.truncated
        stats.redacted += prepared.redacted
        stats.chars += len(prepared.text)
        records.append(
            Record(
                key=int(key),
                text=prepared.text,
                city=row[_CITY] or None,
                list_price=_as_int(row[_PRICE]),
                bedrooms=_as_int(row[_BEDS]),
                property_subtype=row[_TYPE] or None,
            )
        )
    return records, stats, last


def records_to_arrays(
    records: Sequence[Record], vectors: np.ndarray
) -> tuple[np.ndarray, np.ndarray, IndexAttrs]:
    """Keys, vectors, and attrs for records whose vector is usable (unit length).

    A zero row (text the embedder could not use) is dropped here.
    """
    vectors = np.asarray(vectors, dtype=np.float32)
    usable = np.abs(np.linalg.norm(vectors, axis=1) - 1.0) <= UNIT_TOLERANCE
    kept = [rec for rec, ok in zip(records, usable, strict=True) if ok]
    attrs = IndexAttrs.from_values(
        [r.city for r in kept],
        [r.list_price for r in kept],
        [r.bedrooms for r in kept],
        [r.property_subtype for r in kept],
    )
    keys = np.array([r.key for r in kept], dtype=np.int64)
    return keys, vectors[usable].reshape(len(kept), vectors.shape[1]), attrs


def git_ignored(path: Path, repo_root: Path = REPO_ROOT) -> bool:
    """True when `git check-ignore` reports `path` as ignored in the checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", "--", str(path)],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def check_output_dir(
    path: Path,
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
) -> None:
    """Raise BuildRefused unless `path` is inside data/ and git-ignored."""
    if not inside(Path(path), data_root):
        raise BuildRefused("the output path is not inside the repo's data/ folder")
    if not is_ignored(Path(path)):
        raise BuildRefused(
            "git check-ignore does not report the output path as ignored"
        )


def _collect(
    pages: Iterator[tuple[list[dict[str, Any]], str]],
    shard_rows: int,
    remaining: int | None,
    max_chars: int,
    redact: bool,
) -> tuple[list[Record], PageStats, str | None, bool]:
    """Read pages until a shard's worth of records, the end, or the sample limit.

    Returns the records, counts, the last listing id consumed, and whether done.
    """
    records: list[Record] = []
    stats = PageStats()
    cursor: str | None = None
    while len(records) < shard_rows:
        if remaining is not None and len(records) >= remaining:
            return records, stats, cursor, True
        page = next(pages, None)
        if page is None:
            return records, stats, cursor, True
        room = None if remaining is None else remaining - len(records)
        found, counts, last = prepare_rows(
            page[0], max_chars=max_chars, redact=redact, max_records=room
        )
        records.extend(found)
        stats.add(counts)
        cursor = last or cursor
    done = remaining is not None and len(records) >= remaining
    return records, stats, cursor, done


def _embed(
    records: list[Record], embedder: Embedder, batch_size: int
) -> tuple[np.ndarray, list[int | None]]:
    """Embed the records' texts in batches; return the rows and each batch's tokens."""
    parts: list[np.ndarray] = []
    tokens: list[int | None] = []
    for start in range(0, len(records), batch_size):
        batch = [rec.text for rec in records[start : start + batch_size]]
        rows = np.asarray(embedder.embed(batch), dtype=np.float32)
        if rows.shape != (len(batch), embedder.dims):
            raise BuildStopped("the embedder returned rows of the wrong shape")
        parts.append(rows)
        tokens.append(getattr(embedder, "last_usage_tokens", None))
    if not parts:
        return np.zeros((0, embedder.dims), dtype=np.float32), tokens
    return np.vstack(parts), tokens


def _settings(embedder: Embedder, as_of: date, **options: Any) -> dict[str, Any]:
    """What a resumed build must share with the unfinished one it continues."""
    return {
        "model": embedder.name,
        "dims": embedder.dims,
        "active_as_of": as_of.isoformat(),
        "text_prep_version": TEXT_PREP_VERSION,
        **options,
    }


def _load_progress(build_dir: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """The progress record, or a fresh one; BuildRefused if its settings differ."""
    file = build_dir / PROGRESS
    if not file.exists():
        return {"settings": settings, "cursor": "", "done": False, "shards": []}
    state = json.loads(file.read_text(encoding="utf-8"))
    if state.get("settings") != settings:
        raise BuildRefused(
            "the unfinished build here used other settings; a human moves it aside"
        )
    return state


def _save_progress(build_dir: Path, state: dict[str, Any]) -> None:
    """Rewrite progress.json atomically (temporary file, then rename)."""
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"
    replace_with(build_dir / PROGRESS, lambda fh: fh.write(text.encode("utf-8")))


def _write_shard(
    path: Path, keys: np.ndarray, vectors: np.ndarray, attrs: IndexAttrs
) -> None:
    """One shard file (keys, vectors, attrs), written atomically."""
    arrays = {name: getattr(attrs, name) for name in ATTR_FIELDS}
    replace_with(path, lambda fh: np.savez(fh, keys=keys, vectors=vectors, **arrays))


def _read_shards(
    build_dir: Path, shards: list[dict[str, Any]], dims: int
) -> tuple[np.ndarray, np.ndarray, IndexAttrs]:
    """Concatenate the finished shards after checking each file's hash."""
    keys, vectors, attrs = [], [], {name: [] for name in ATTR_FIELDS}
    for entry in shards:
        file = build_dir / entry["file"]
        if file_sha256(file) != entry["sha256"]:
            raise BuildStopped("a finished shard changed on disk; no meta.json written")
        with np.load(file, allow_pickle=False) as npz:
            keys.append(npz["keys"])
            vectors.append(npz["vectors"].reshape(-1, dims))
            for name in ATTR_FIELDS:
                attrs[name].append(npz[name])
    return (
        np.concatenate(keys).astype(np.int64),
        np.vstack(vectors).astype(np.float32),
        IndexAttrs(*(np.concatenate(attrs[name]) for name in ATTR_FIELDS)),
    )


def _totals(shards: list[dict[str, Any]]) -> PageStats:
    """Sum the counts recorded for each shard."""
    totals = PageStats()
    for entry in shards:
        totals.add(
            PageStats(**{name: entry[name] for name in PageStats.__dataclass_fields__})
        )
    return totals


def build(
    conn: Any,
    embedder: Embedder,
    out_root: Path,
    *,
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
    shard_rows: int = SHARD_ROWS,
    batch_size: int = BATCH_SIZE,
    max_chars: int = MAX_CHARS,
    redact: bool = True,
    limit: int | None = None,
    echo: Callable[[str], None] = print,
) -> BuildReport:
    """Build (or resume, or confirm) the index for the data's active as-of date.

    Directory: `<out_root>/<model>-<dims>/<as-of>` (`<as-of>-first<N>` with a
    limit). Refuses test models and paths outside data/ or not ignored. The as-of
    date is read at the start and the end; a change leaves no meta.json.
    """
    started = time.perf_counter()
    if embedder.name.startswith("test:"):
        raise BuildRefused("test models never build an index")
    if limit is not None and limit < 1:
        raise BuildRefused("the sample size must be at least 1")
    as_of = read_asof_dates(conn).active
    index_dir = index_dir_for(Path(out_root), embedder.name, embedder.dims, as_of)
    if limit is not None:
        index_dir = index_dir.with_name(f"{as_of.isoformat()}-first{limit}")
    check_output_dir(index_dir, data_root, is_ignored)
    report = BuildReport(index_dir=index_dir)
    if (index_dir / META).exists():
        try:
            meta = read_meta(index_dir)
        except IndexUnavailable:
            raise BuildRefused(
                "meta.json here is not a complete index; left as is"
            ) from None
        if (meta.model, meta.dims, meta.active_as_of) != (
            embedder.name,
            embedder.dims,
            as_of,
        ):
            raise BuildRefused("another index already sits in this directory")
        report.already_complete = True
        report.seconds = time.perf_counter() - started
        return report

    build_dir = index_dir / BUILD_DIR
    build_dir.mkdir(parents=True, exist_ok=True)
    options = {"max_chars": max_chars, "redact": redact, "shard_rows": shard_rows}
    state = _load_progress(
        build_dir, _settings(embedder, as_of, limit=limit, **options)
    )
    report.shards_reused = len(state["shards"])
    embedded = sum(entry["embedded"] for entry in state["shards"])
    pages = iter_pages(conn, state["cursor"])
    while not state["done"]:
        t0 = time.perf_counter()
        remaining = None if limit is None else limit - embedded
        records, stats, cursor, done = _collect(
            pages, shard_rows, remaining, max_chars, redact
        )
        vectors, tokens = _embed(records, embedder, batch_size)
        keys, vectors, attrs = records_to_arrays(records, vectors)
        stats.skipped_empty += len(records) - len(keys)
        name = f"shard-{len(state['shards']):05d}.npz"
        _write_shard(build_dir / name, keys, vectors, attrs)
        seconds = round(time.perf_counter() - t0, 2)
        entry = {
            "file": name,
            "sha256": file_sha256(build_dir / name),
            "embedded": len(keys),
        }
        entry.update(batch_tokens=tokens, seconds=seconds, **stats.__dict__)
        state["shards"].append(entry)
        state["cursor"] = cursor or state["cursor"]
        state["done"] = done
        _save_progress(build_dir, state)
        embedded += len(keys)
        report.shards_built += 1
        report.embed_calls += len(tokens)
        echo(
            f"shard {len(state['shards'])}: {stats.rows_read} rows read, "
            f"{len(keys)} embedded, {seconds:.1f} s"
        )

    keys, vectors, attrs = _read_shards(build_dir, state["shards"], embedder.dims)
    # Two listing ids with the same number (e.g. a leading zero) keep the first.
    _, first = np.unique(keys, return_index=True)
    order = np.sort(first)
    totals = _totals(state["shards"])
    totals.duplicates += len(keys) - len(order)
    keys, vectors, attrs = keys[order], vectors[order], attrs.take(order)
    if read_asof_dates(conn).active != as_of:
        raise BuildStopped(
            "the active as-of date changed during the build; no meta.json"
        )
    batch_tokens = [t for entry in state["shards"] for t in entry["batch_tokens"]]
    usage = None if any(t is None for t in batch_tokens) else sum(batch_tokens)
    write_index(
        index_dir,
        vectors=vectors,
        keys=keys,
        attrs=attrs,
        model=embedder.name,
        active_as_of=as_of,
        skipped_empty=totals.skipped_empty,
        truncated=totals.truncated,
        redacted_inputs=totals.redacted,
        usage_tokens=usage,
        max_chars=max_chars,
        data_root=data_root,
    )
    report.stats = totals
    report.embedded = int(len(keys))
    report.usage_tokens = usage
    report.bytes_on_disk = sum(
        (index_dir / name).stat().st_size
        for name in ("vectors.npy", "keys.npy", "attrs.npz", META)
    )
    report.seconds = time.perf_counter() - started
    return report


def dry_run(
    conn: Any,
    *,
    dims: int,
    max_chars: int = MAX_CHARS,
    redact: bool = True,
    echo: Callable[[str], None] = print,
) -> tuple[PageStats, int]:
    """Read every page, embed nothing, print counts; return (counts, embeddable)."""
    started = time.perf_counter()
    as_of = read_asof_dates(conn).active
    stats, embeddable = PageStats(), 0
    for rows, _ in iter_pages(conn):
        records, counts, _ = prepare_rows(rows, max_chars=max_chars, redact=redact)
        stats.add(counts)
        embeddable += len(records)
    # float32 vectors plus the int64 key, price, and beds beside each one.
    projected = embeddable * (dims * 4 + 3 * 8)
    echo(
        f"dry run: active as-of {as_of.isoformat()}; nothing embedded, nothing written"
    )
    echo(f"  active rows read      {stats.rows_read:,}")
    echo(f"  empty or too short    {stats.skipped_empty:,}")
    echo(f"  over MAX_CHARS ({max_chars:,}) {stats.truncated:,}")
    echo(f"  changed by redaction  {stats.redacted:,}")
    echo(f"  repeated listing ids  {stats.duplicates:,} (newest row kept)")
    echo(f"  non-numeric ids       {stats.bad_keys:,}")
    echo(f"  embeddable            {embeddable:,}")
    echo(f"  total characters      {stats.chars:,}")
    echo(f"  projected bytes       {projected:,} (vectors, keys, numeric attrs)")
    echo(f"  seconds               {time.perf_counter() - started:.1f}")
    return stats, embeddable


def _parser() -> argparse.ArgumentParser:
    """The command-line options."""
    parser = argparse.ArgumentParser(
        prog="python -m idx_agent.semantic.build_index",
        description="Build the remarks index (a paid run; a human starts it).",
    )
    parser.add_argument("--dry-run", action="store_true", help="counts only")
    parser.add_argument("--allow-paid", action="store_true", help="permit paid calls")
    parser.add_argument("--sample", type=int, default=None, metavar="N",
                        help="embed only the first N embeddable rows")  # fmt: skip
    parser.add_argument("--out-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--shard-rows", type=int, default=SHARD_ROWS)
    return parser


def preflight(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    consent_check: Callable[[], bool],
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
) -> tuple[str, int]:
    """Every refusal before a connection opens; returns (model, dims).

    Order: CI, model setting, test model, flags, --allow-paid, consent, key, path.
    """
    if (environ.get("CI") or "").strip():
        raise BuildRefused("CI is set; the index build never runs in CI")
    try:
        model, dims = embed_settings(environ)
    except ValueError as exc:
        raise BuildRefused(str(exc)) from None
    if model.startswith("test:"):
        raise BuildRefused("test models never build an index")
    if args.dry_run and args.sample is not None:
        raise BuildRefused("choose --dry-run or --sample, not both")
    if args.shard_rows < 1:
        raise BuildRefused("--shard-rows must be at least 1")
    if args.dry_run:
        return model, dims
    if not args.allow_paid:
        raise BuildRefused("this is a paid run; a human passes --allow-paid")
    if not consent_check():
        raise BuildRefused("no valid `paid` consent token; a human grants one first")
    if not (env_setting("OPENAI_API_KEY", environ) or "").strip():
        raise BuildRefused(
            "OPENAI_API_KEY is set neither in the environment nor in .env"
        )
    root = Path(args.out_root) / "samples" if args.sample else Path(args.out_root)
    check_output_dir(root, data_root, is_ignored)
    return model, dims


def _summary(report: BuildReport, echo: Callable[[str], None]) -> None:
    """Print the finished build's counts, tokens, time, and size."""
    try:
        where = report.index_dir.relative_to(REPO_ROOT)
    except ValueError:
        where = report.index_dir
    if report.already_complete:
        echo(f"index already complete at {where}; nothing embedded")
        return
    s = report.stats
    echo(f"index written to {where}")
    echo(f"  shards built {report.shards_built}, reused {report.shards_reused}")
    echo(f"  rows read {s.rows_read:,}; embedded {report.embedded:,}")
    echo(f"  empty or too short {s.skipped_empty:,}; truncated {s.truncated:,}")
    echo(f"  changed by redaction {s.redacted:,}; non-numeric ids {s.bad_keys:,}")
    echo(f"  repeated listing ids {s.duplicates:,} (newest ModificationTimestamp kept)")
    tokens = (
        "not reported" if report.usage_tokens is None else f"{report.usage_tokens:,}"
    )
    echo(f"  tokens reported by the API: {tokens}")
    echo(f"  minutes {report.seconds / 60:.2f}; bytes on disk {report.bytes_on_disk:,}")
    echo("  dollars: read them from the provider's usage page, never computed here")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    connect_fn: Callable[[], Any] = connect,
    consent_check: Callable[[], bool] = paid_consent_active,
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
    echo: Callable[[str], None] = print,
) -> int:
    """Run the CLI; 0 done, 1 stopped part way (progress kept), 2 refused."""
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        model, dims = preflight(args, env, consent_check, data_root, is_ignored)
    except BuildRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    redact = redact_enabled(env)
    conn = connect_fn()
    try:
        if args.dry_run:
            dry_run(conn, dims=dims, redact=redact, echo=echo)
            return 0
        embedder = make_embedder(
            model,
            dims,
            environ=env,
            consent_check=consent_check,
            timeout=BUILD_TIMEOUT_S,
            max_retries=BUILD_RETRIES,
        )
        root = Path(args.out_root) / "samples" if args.sample else Path(args.out_root)
        report = build(
            conn,
            embedder,
            root,
            data_root=data_root,
            is_ignored=is_ignored,
            shard_rows=args.shard_rows,
            redact=redact,
            limit=args.sample,
            echo=echo,
        )
    except BuildRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except BuildStopped as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    except ProviderError as exc:
        print(
            f"stopped: {exc}; finished shards are kept, rerun to resume",
            file=sys.stderr,
        )
        return 1
    finally:
        conn.close()
    _summary(report, echo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
