"""Build the document index: `python -m idx_agent.rag.build` (WO-012).

Chunks the registered sources into `<out-root>/<route>-<date>/` under data/. Hybrid
embeds every chunk: a paid run (--allow-paid, the key, and a `paid` token minted for
this process's own command line, spent by this run). Prints counts, never text."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from idx_agent.db.pool import env_setting
from idx_agent.rag.chunk import Chunk, DropCounts, build_chunks
from idx_agent.rag.extract import SourceMissing, empty_pages, load_pages
from idx_agent.rag.sources import DEFAULT_DOCS_ROOT, SOURCE_IDS, SOURCES
from idx_agent.rag.store import (
    DATA_ROOT,
    DEFAULT_OUT_ROOT,
    META,
    DocIndexMeta,
    Route,
    write_doc_index,
)
from idx_agent.rag.vectors import embed_chunks, embed_text
from idx_agent.safety import consent
from idx_agent.semantic.build_index import (
    BuildRefused,
    check_output_dir,
    git_ignored,
    paid_refusal,
)
from idx_agent.semantic.embedder import (
    TEST_MODEL,
    Embedder,
    ProviderError,
    embed_settings,
    make_embedder,
    prepare,
    redact_enabled,
)
from idx_agent.semantic.index import REPO_ROOT, file_sha256

__all__ = [
    "CALIBRATION_QUESTIONS",
    "DEFAULT_FLOOR_BM25",
    "DEFAULT_FLOOR_COSINE",
    "OPTIONAL_SOURCES",
    "BuildRefused",
    "Corpus",
    "build_doc_index",
    "calibrate",
    "index_dir_for",
    "load_corpus",
    "main",
    "preflight",
    "source_paths",
    "source_sha256",
]

# scripts/rag_floor_probe.py on the 527 chunks of decision 18 (2026-09-25): 15
# off-topic questions top out at 15.069 and 11 on-topic paraphrases bottom out at
# 4.015, so there is no gap; the floor sits 0.5 above the best off-topic score (it was
# 14.60 on the earlier 625). Paraphrases below it are the vector leg's to find
# (IDX_RAG_FLOOR_BM25 replaces it without a rebuild).
DEFAULT_FLOOR_BM25 = 15.57
# A placeholder until the --calibrate numbers are in (decision 15).
DEFAULT_FLOOR_COSINE = 0.30
# The three set questions and two off-topic ones, own words; only ids reach the meta.
CALIBRATION_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("set_dom", "what does DOM mean"),
    ("set_columns", "which columns does the sold table have"),
    ("set_ratio", "what is the list-to-close ratio"),
    ("off_weather", "will it rain in paris tomorrow"),
    ("off_food", "recommend a pizza place for dinner"),
)
# A failed request is never resent: it aborts the paid run (nothing is written).
BUILD_TIMEOUT_S = 60.0
# Sources a default build skips, with a warning, when missing (the market summaries
# script writes this one); named in --sources, a missing one is refused as any other.
OPTIONAL_SOURCES = ("summaries",)


@dataclass(frozen=True)
class Corpus:
    """Chunked sources: chunks in order, drop counts, pages per source, hashes."""

    chunks: list[Chunk]
    drops: DropCounts
    pages: dict[str, list[str]]
    hashes: dict[str, str]


def source_paths(
    docs_root: Path | None = None, sources: Sequence[str] | None = None
) -> dict[str, Path]:
    """Source id -> path for the chosen ids (all by default), in registry order."""
    chosen = list(sources) if sources else list(SOURCE_IDS)
    unknown = sorted(set(chosen) - set(SOURCES))
    if unknown:
        raise ValueError(f"unknown source ids: {unknown}")
    return {sid: SOURCES[sid].resolve(docs_root) for sid in SOURCE_IDS if sid in chosen}


def source_sha256(path: Path) -> str:
    """A file's sha256; for a folder, one over its sorted `*.txt` names and hashes."""
    path = Path(path)
    if path.is_file():
        return file_sha256(path)
    digest = hashlib.sha256()
    for file in sorted(path.glob("*.txt")):
        digest.update(f"{file.name}\0{file_sha256(file)}\n".encode())
    return digest.hexdigest()


def load_corpus(paths: Mapping[str, Path]) -> Corpus:
    """Read and chunk the sources at `paths` (id -> file or folder).

    Raises SourceMissing for an absent file or folder.
    """
    pages = {sid: load_pages(SOURCES[sid], Path(p)) for sid, p in paths.items()}
    chunks, drops = build_chunks(pages)
    hashes = {sid: source_sha256(Path(p)) for sid, p in paths.items()}
    return Corpus(chunks=chunks, drops=drops, pages=pages, hashes=hashes)


def index_dir_for(out_root: Path, route: str, day: date) -> Path:
    """`<out_root>/<route>-<YYYY-MM-DD>`."""
    return Path(out_root) / f"{route}-{day.isoformat()}"


def calibrate(vectors: np.ndarray, embedder: Embedder) -> dict[str, float]:
    """Top cosine per calibration question against the chunk vectors (one request).

    A question under prepare's 20-character floor is embedded as written: at query
    time its vector leg is skipped, so its number is for reference only.
    """
    texts = [
        prepare(text).text or " ".join(text.split())
        for _, text in CALIBRATION_QUESTIONS
    ]
    rows = np.asarray(embedder.embed(texts), dtype=np.float32)
    tops = (vectors @ rows.T).max(axis=0)
    return {
        qid: round(float(top), 6)
        for (qid, _), top in zip(CALIBRATION_QUESTIONS, tops, strict=True)
    }


def build_doc_index(
    out_dir: Path,
    *,
    paths: Mapping[str, Path],
    route: Route = "bm25",
    embedder: Embedder | None = None,
    floor_bm25: float = DEFAULT_FLOOR_BM25,
    floor_cosine: float = DEFAULT_FLOOR_COSINE,
    run_calibration: bool = False,
    test_corpus: bool = False,
    redact: bool = True,
    data_root: Path = DATA_ROOT,
    built_at: date | None = None,
    echo: Callable[[str], None] | None = None,
) -> DocIndexMeta:
    """Chunk the sources, embed them (hybrid), and write the index to `out_dir`.

    Refuses (ValueError) a hybrid route without an embedder, calibration off the
    hybrid route, and whatever `write_doc_index` refuses.
    """
    if route == "hybrid" and embedder is None:
        raise ValueError("the hybrid route needs an embedder")
    if run_calibration and route != "hybrid":
        raise ValueError("calibration needs the hybrid route")
    corpus = load_corpus(paths)
    vectors = None
    usage = None
    calibration = None
    if route == "hybrid" and embedder is not None:
        vectors, stats = embed_chunks(corpus.chunks, embedder, redact=redact)
        usage = stats.usage_tokens
        if echo:
            echo(f"embedded {stats.texts:,} chunks in {stats.requests} requests")
            echo(
                f"  cut at the length limit {stats.truncated}; masked {stats.redacted}"
            )
        if run_calibration:
            calibration = calibrate(vectors, embedder)
    return write_doc_index(
        out_dir,
        corpus.chunks,
        route=route,
        source_hashes=corpus.hashes,
        drops=corpus.drops.as_dict(),
        floor_bm25=floor_bm25,
        floor_cosine=floor_cosine,
        vectors=vectors,
        model=embedder.name if route == "hybrid" and embedder else None,
        usage_tokens=usage,
        calibration=calibration,
        test_corpus=test_corpus,
        data_root=data_root,
        built_at=built_at,
    )


def print_counts(corpus: Corpus, echo: Callable[[str], None] = print) -> None:
    """Counts per source: pages, empty pages, chunks, words, parts, and every drop."""
    per_source = Counter(chunk.doc for chunk in corpus.chunks)
    echo("source         pages  empty  chunks   words  max_chars  parts")
    for sid, pages in corpus.pages.items():
        mine = [c for c in corpus.chunks if c.doc == sid]
        words = sum(len(c.text.split()) for c in mine)
        longest = max((len(c.text) for c in mine), default=0)
        parts = sum(1 for c in mine if ", part " in c.label)
        echo(
            f"{sid:<13} {len(pages):>6} {len(empty_pages(pages)):>6} "
            f"{per_source.get(sid, 0):>7} {words:>7} {longest:>10} {parts:>6}"
        )
    echo(f"total chunks {len(corpus.chunks):,}")
    for name, per in corpus.drops.as_dict().items():
        if per:
            detail = ", ".join(f"{sid} {n}" for sid, n in per.items())
            echo(f"  {name}: {sum(per.values())} ({detail})")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m idx_agent.rag.build",
        description="Build the document index (hybrid is paid; a human starts it).",
    )
    parser.add_argument("--dry-run", action="store_true", help="counts only")
    parser.add_argument("--route", choices=("bm25", "hybrid"), default="hybrid")
    parser.add_argument("--allow-paid", action="store_true", help="permit paid calls")
    parser.add_argument("--calibrate", action="store_true",
                        help="hybrid: top cosines of five set questions")  # fmt: skip
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--docs-root", type=Path, default=DEFAULT_DOCS_ROOT,
                        help="folder holding the PDFs and summaries/")  # fmt: skip
    parser.add_argument("--sources", default=None,
                        help="comma-separated source ids (default: all)")  # fmt: skip
    parser.add_argument("--path", action="append", default=[], metavar="ID=PATH",
                        help="read one source from another file")  # fmt: skip
    parser.add_argument("--floor-bm25", type=float, default=DEFAULT_FLOOR_BM25)
    parser.add_argument("--floor-cosine", type=float, default=DEFAULT_FLOOR_COSINE)
    return parser


def _path_overrides(
    items: Sequence[str], chosen: Mapping[str, Path]
) -> dict[str, Path]:
    """`ID=PATH` pairs for chosen sources; ValueError for a bad or unchosen one."""
    overrides: dict[str, Path] = {}
    for item in items:
        sid, sep, value = item.partition("=")
        if not sep or not value or sid not in chosen:
            raise ValueError(f"--path needs ID=PATH for a chosen source: {sid!r}")
        overrides[sid] = Path(value)
    return overrides


def _skip_missing_optional(
    paths: dict[str, Path], echo: Callable[[str], None]
) -> list[str]:
    """Drop each missing optional source from `paths` (in place) with a warning;
    return the ids skipped."""
    skipped = [
        sid for sid in OPTIONAL_SOURCES if sid in paths and not paths[sid].exists()
    ]
    for sid in skipped:
        del paths[sid]
        echo(
            f"warning: source {sid!r} is missing and was skipped "
            "(scripts/market_summaries.py writes it)"
        )
    return skipped


def preflight(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    today: date,
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
) -> tuple[str, int] | None:
    """Every refusal before a source is read; returns (model, dims) for hybrid.

    Order: CI, flags, (dry run stops here), model, --allow-paid, key (the paid
    checks for the OpenAI model only), output folder, an existing index. The paid
    run itself starts in main(), once the sources are read."""
    if (environ.get("CI") or "").strip():
        raise BuildRefused("CI is set; the document index build never runs in CI")
    if args.calibrate and args.route != "hybrid":
        raise BuildRefused("--calibrate needs --route hybrid")
    if args.calibrate and args.dry_run:
        raise BuildRefused("choose --dry-run or --calibrate, not both")
    if args.dry_run:
        return None
    model_dims = None
    if args.route == "hybrid":
        try:
            model_dims = embed_settings(environ)
        except ValueError as exc:
            raise BuildRefused(str(exc)) from None
        if model_dims[0] != TEST_MODEL:
            if not args.allow_paid:
                raise BuildRefused("this is a paid run; a human passes --allow-paid")
            if not (env_setting("OPENAI_API_KEY", environ) or "").strip():
                raise BuildRefused(
                    "OPENAI_API_KEY is set neither in the environment nor in .env"
                )
    out_dir = index_dir_for(args.out_root, args.route, today)
    check_output_dir(out_dir, data_root, is_ignored)
    if (out_dir / META).exists():
        raise BuildRefused("an index already exists there; it is never overwritten")
    return model_dims


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
    today: date | None = None,
    echo: Callable[[str], None] = print,
) -> int:
    """Run the CLI; 0 done, 1 stopped (nothing written), 2 refused.

    A paid hybrid build spends the `paid` token minted for this process's own
    command line (never `argv`) once every local check passed and the sources are
    read, before the first request."""
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    day = today or datetime.now(UTC).date()
    try:
        model_dims = preflight(args, env, day, data_root, is_ignored)
        chosen = args.sources.split(",") if args.sources else None
        paths = source_paths(args.docs_root, chosen)
        paths.update(_path_overrides(args.path, paths))
        skipped = [] if chosen else _skip_missing_optional(paths, echo)
        corpus = load_corpus(paths)
        if model_dims is not None and model_dims[0] != TEST_MODEL:
            try:
                consent.start_paid_run()
            except consent.PaidRunRefused as exc:
                raise BuildRefused(paid_refusal(exc)) from None
    except (BuildRefused, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except SourceMissing as exc:
        print(
            f"refused: source {exc.source_id!r} is missing (--docs-root, --sources)",
            file=sys.stderr,
        )
        return 2
    if skipped:
        echo(f"skipped sources: {len(skipped)} ({', '.join(skipped)})")
    if args.dry_run:
        echo("dry run: nothing embedded, nothing written")
        print_counts(corpus, echo)
        if args.route == "hybrid":
            chars = sum(len(embed_text(c)[0]) for c in corpus.chunks)
            echo(f"  texts to embed {len(corpus.chunks):,}; characters {chars:,}")
        return 0
    embedder = None
    if model_dims is not None:
        embedder = make_embedder(*model_dims, environ=env, timeout=BUILD_TIMEOUT_S)
    out_dir = index_dir_for(args.out_root, args.route, day)
    try:
        meta = build_doc_index(
            out_dir,
            paths=paths,
            route=args.route,
            embedder=embedder,
            floor_bm25=args.floor_bm25,
            floor_cosine=args.floor_cosine,
            run_calibration=args.calibrate,
            redact=redact_enabled(env),
            data_root=data_root,
            built_at=day,
            echo=echo,
        )
    except ProviderError as exc:
        print(
            f"stopped: {exc}; nothing was written (the run's token is spent)",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    try:
        where = out_dir.relative_to(REPO_ROOT)
    except ValueError:
        where = out_dir
    echo(f"index written to {where}")
    print_counts(corpus, echo)
    echo(f"  floors: bm25 {meta.floor_bm25}, cosine {meta.floor_cosine}")
    if meta.route == "hybrid":
        tokens = (
            "not reported" if meta.usage_tokens is None else f"{meta.usage_tokens:,}"
        )
        echo(f"  model {meta.model} at {meta.dims}; tokens reported: {tokens}")
        echo("  dollars: read them from the provider's usage page, never computed here")
    for qid, score in (meta.calibration or {}).items():
        echo(f"  calibration {qid}: top cosine {score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
