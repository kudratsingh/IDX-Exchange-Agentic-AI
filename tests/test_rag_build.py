"""The document index build and load (WO-012), and the market summaries script.

Against the own-words fixture corpus in temporary folders standing in for data/; no
PDFs of ours, no provider (the hybrid route uses `test:hashing`), no database.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from idx_agent.rag import build as rag_build
from idx_agent.rag import store as rag_store
from idx_agent.rag.build import (
    CALIBRATION_QUESTIONS,
    DEFAULT_FLOOR_BM25,
    build_doc_index,
    index_dir_for,
    source_paths,
    source_sha256,
)
from idx_agent.rag.store import (
    CHUNKS,
    META,
    VECTORS,
    DocIndexUnavailable,
    in_test_folder,
    load_doc_index,
    write_doc_index,
)
from idx_agent.semantic.embedder import HashingEmbedder

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "docs"
DAY = date(2026, 9, 24)
PATHS = {
    "trestle": FIXTURE / "field_reference.txt",
    "primer": FIXTURE / "primer.txt",
    "schema_notes": ROOT / "docs" / "data" / "schema_notes.md",
    "glossary": ROOT / "docs" / "data" / "glossary.md",
}
SOURCES_ARG = "trestle,primer,schema_notes,glossary"
PATH_ARGS = [
    "--path",
    f"trestle={PATHS['trestle']}",
    "--path",
    f"primer={PATHS['primer']}",
]
# Strings from the fixture's text that no printed line may carry.
FIXTURE_TEXT = ("SENTINEL", "SYSTEM OVERRIDE", "whole number of days")
OPENAI_ENV = {
    "IDX_EMBED_MODEL": "openai:text-embedding-3-small",
    "IDX_EMBED_DIMS": "1536",
    "OPENAI_API_KEY": "",
    "IDX_EMBED_REDACT": "1",
}
HASHING_ENV = {"IDX_EMBED_MODEL": "test:hashing", "IDX_EMBED_DIMS": "64"}


def _build(tmp_path: Path, **kwargs) -> Path:
    out = tmp_path / "data" / "indexes" / "docs" / "bm25-2026-09-24"
    options = {"route": "bm25", "data_root": tmp_path / "data", "built_at": DAY}
    options.update(kwargs)
    build_doc_index(out, paths=PATHS, **options)
    return out


def _main(tmp_path: Path, argv: list[str], environ=None, consent=True):
    lines: list[str] = []
    code = rag_build.main(
        argv,
        environ={} if environ is None else environ,
        consent_check=lambda: consent,
        data_root=tmp_path / "data",
        is_ignored=lambda _: True,
        today=DAY,
        echo=lines.append,
    )
    return code, lines


def _out_root(tmp_path: Path) -> list[str]:
    return ["--out-root", str(tmp_path / "data" / "indexes" / "docs")]


# ----- write and load -----------------------------------------------------------------
def test_build_writes_chunks_and_meta_with_source_hashes(tmp_path: Path) -> None:
    out = _build(tmp_path)
    assert (out / CHUNKS).is_file() and (out / META).is_file()
    assert not (out / VECTORS).exists()
    meta = json.loads((out / META).read_text(encoding="utf-8"))
    assert meta["complete"] is True and meta["route"] == "bm25"
    assert meta["built_at"] == DAY.isoformat()
    assert meta["floor_bm25"] == DEFAULT_FLOOR_BM25 and meta["floor_cosine"] == 0.3
    for sid, path in PATHS.items():
        assert meta["sources"][sid]["sha256"] == source_sha256(path)
    assert meta["sources"]["trestle"]["confidential"] is True
    assert meta["sources"]["glossary"]["confidential"] is False
    assert meta["drops"]["field_chunks_dropped"]["trestle"] >= 2
    index = load_doc_index(out, data_root=tmp_path / "data")
    assert len(index.chunks) == meta["rows"]
    assert sum(s["chunks"] for s in meta["sources"].values()) == meta["rows"]
    assert index.vectors is None
    assert index.meta.built_at == DAY


def test_a_folder_hash_covers_its_text_files(tmp_path: Path) -> None:
    folder = tmp_path / "summaries"
    folder.mkdir()
    (folder / "Pasadena.txt").write_text("Market summary: Pasadena\ncard\n")
    before = source_sha256(folder)
    (folder / "Duarte.txt").write_text("Market summary: Duarte\ncard\n")
    assert source_sha256(folder) != before


def test_a_non_test_index_outside_data_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_doc_index(
            tmp_path / "elsewhere", paths=PATHS, data_root=tmp_path / "data"
        )
    out = _build(tmp_path)
    with pytest.raises(DocIndexUnavailable) as caught:
        load_doc_index(out, data_root=tmp_path / "other")
    assert caught.value.cause == "outside_data"


def test_a_fixture_index_may_live_outside_data(tmp_path: Path) -> None:
    out = tmp_path / "fixture-index"
    build_doc_index(out, paths=PATHS, test_corpus=True, data_root=tmp_path / "data")
    index = load_doc_index(out, data_root=tmp_path / "data")
    assert index.meta.test_corpus and index.meta.is_test


def test_a_test_corpus_is_honoured_only_in_a_test_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test-only flag lets an index sit outside data/ only under the system's
    temporary folder or tests/: written elsewhere it is refused (nothing written),
    and a flagged index found elsewhere does not load."""
    assert in_test_folder(tmp_path) and in_test_folder(ROOT / "tests" / "any")
    assert not in_test_folder(ROOT / "data" / "indexes" / "docs" / "x")
    elsewhere = Path("/nonexistent-idx-root/fixture-index")
    with pytest.raises(ValueError):
        build_doc_index(elsewhere, paths=PATHS, test_corpus=True)
    assert not elsewhere.exists()
    out = tmp_path / "fixture-index"
    build_doc_index(out, paths=PATHS, test_corpus=True, data_root=tmp_path / "data")
    monkeypatch.setattr(rag_store.tempfile, "gettempdir", lambda: "/nonexistent-tmp")
    with pytest.raises(DocIndexUnavailable) as caught:
        load_doc_index(out, data_root=tmp_path / "data")
    assert caught.value.cause == "outside_data"


def test_floor_settings_replace_the_meta_floors_at_load(tmp_path: Path) -> None:
    out = _build(tmp_path)
    data = tmp_path / "data"
    index = load_doc_index(out, data_root=data, environ={"IDX_RAG_FLOOR_BM25": "3.5"})
    assert (index.meta.floor_bm25, index.meta.floor_cosine) == (3.5, 0.3)
    empty = {"IDX_RAG_FLOOR_BM25": " ", "IDX_RAG_FLOOR_COSINE": ""}
    assert (
        load_doc_index(out, data_root=data, environ=empty).meta.floor_bm25
        == DEFAULT_FLOOR_BM25
    )
    for bad in ("high", "nan", "inf"):
        with pytest.raises(DocIndexUnavailable) as caught:
            load_doc_index(out, data_root=data, environ={"IDX_RAG_FLOOR_COSINE": bad})
        assert caught.value.cause == "floor_setting"
    # The file on disk keeps the built floors.
    assert (
        json.loads((out / META).read_text(encoding="utf-8"))["floor_bm25"]
        == DEFAULT_FLOOR_BM25
    )


def test_an_existing_index_is_never_overwritten(tmp_path: Path) -> None:
    out = _build(tmp_path)
    with pytest.raises(ValueError):
        build_doc_index(out, paths=PATHS, data_root=tmp_path / "data")


@pytest.mark.parametrize(
    ("damage", "cause"),
    [
        ("chunks", "hash"),
        ("incomplete", "incomplete"),
        ("format", "format_version"),
        ("rows", "row_count"),
        ("gone", "missing"),
    ],
)
def test_load_names_the_failed_check(tmp_path: Path, damage: str, cause: str) -> None:
    out = _build(tmp_path)
    meta_file = out / META
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    if damage == "chunks":
        with (out / CHUNKS).open("a", encoding="utf-8") as fh:
            fh.write("\n")
    elif damage == "gone":
        out = tmp_path / "data" / "no-such-index"
    else:
        key, value = {
            "incomplete": ("complete", False),
            "format": ("format_version", 99),
            "rows": ("rows", meta["rows"] + 1),
        }[damage]
        meta[key] = value
        meta_file.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(DocIndexUnavailable) as caught:
        load_doc_index(out, data_root=tmp_path / "data")
    assert caught.value.cause == cause


def test_hybrid_with_the_hashing_model(tmp_path: Path) -> None:
    out = tmp_path / "hybrid"
    meta = build_doc_index(
        out,
        paths=PATHS,
        route="hybrid",
        embedder=HashingEmbedder(64),
        run_calibration=True,
        data_root=tmp_path / "data",
    )
    assert meta.model == "test:hashing" and meta.dims == 64
    assert set(meta.calibration or {}) == {qid for qid, _ in CALIBRATION_QUESTIONS}
    index = load_doc_index(out, data_root=tmp_path / "data")
    assert index.vectors is not None
    assert index.vectors.shape == (len(index.chunks), 64)
    norms = np.linalg.norm(index.vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)
    np.save(out / VECTORS, np.zeros_like(index.vectors))
    with pytest.raises(DocIndexUnavailable) as caught:
        load_doc_index(out, data_root=tmp_path / "data")
    assert caught.value.cause == "hash"


def test_route_and_vectors_must_agree(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_doc_index(tmp_path / "x", paths=PATHS, route="hybrid", test_corpus=True)
    with pytest.raises(ValueError):
        write_doc_index(
            tmp_path / "y",
            [],
            route="bm25",
            source_hashes={},
            drops={},
            floor_bm25=1.0,
            floor_cosine=0.3,
            vectors=np.zeros((0, 4), dtype=np.float32),
            test_corpus=True,
        )
    with pytest.raises(ValueError):
        build_doc_index(tmp_path / "z", paths=PATHS, run_calibration=True)


def test_source_paths_follow_the_registry(tmp_path: Path) -> None:
    paths = source_paths(tmp_path, ["glossary", "trestle"])
    assert list(paths) == ["trestle", "glossary"]
    assert paths["trestle"] == tmp_path / "Trestle_Property_MetaData.pdf"
    assert paths["glossary"] == ROOT / "docs" / "data" / "glossary.md"
    with pytest.raises(ValueError):
        source_paths(tmp_path, ["handbook"])


# ----- the command line ---------------------------------------------------------------
def test_cli_builds_once_and_prints_counts_only(tmp_path: Path) -> None:
    argv = [
        "--route",
        "bm25",
        "--sources",
        SOURCES_ARG,
        *PATH_ARGS,
        *_out_root(tmp_path),
    ]
    code, lines = _main(tmp_path, argv)
    assert code == 0
    out = index_dir_for(tmp_path / "data" / "indexes" / "docs", "bm25", DAY)
    assert (out / META).is_file()
    printed = "\n".join(lines)
    assert "total chunks" in printed and "field_chunks_dropped" in printed
    assert not any(text in printed for text in FIXTURE_TEXT)
    again, _ = _main(tmp_path, argv)
    assert again == 2


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    argv = ["--dry-run", "--sources", SOURCES_ARG, *PATH_ARGS, *_out_root(tmp_path)]
    code, lines = _main(tmp_path, argv)
    assert code == 0
    assert not (tmp_path / "data").exists()
    printed = "\n".join(lines)
    assert "texts to embed" in printed
    assert not any(text in printed for text in FIXTURE_TEXT)


@pytest.mark.parametrize(
    ("argv", "environ", "consent"),
    [
        (["--route", "bm25"], {"CI": "true"}, True),
        (["--route", "bm25", "--calibrate"], {}, True),
        (["--route", "hybrid"], OPENAI_ENV, True),
        (["--route", "hybrid", "--allow-paid"], OPENAI_ENV, False),
        (["--route", "hybrid", "--allow-paid"], OPENAI_ENV, True),
        (["--route", "bm25", "--path", "handbook=x.pdf"], {}, True),
    ],
)
def test_cli_refusals(tmp_path: Path, argv, environ, consent) -> None:
    full = [*argv, "--sources", SOURCES_ARG, *_out_root(tmp_path)]
    if "--path" not in argv:
        full += PATH_ARGS
    code, _ = _main(tmp_path, full, environ=environ, consent=consent)
    assert code == 2
    assert not (tmp_path / "data").exists()


def test_cli_default_sources_skip_missing_summaries_with_a_warning(
    tmp_path: Path,
) -> None:
    """With no --sources, a missing summaries folder is a counted skip (the
    summaries script runs first, against the database); named, it is refused."""
    docs = ["--docs-root", str(tmp_path / "no-knowledge"), *PATH_ARGS]
    code, lines = _main(tmp_path, ["--dry-run", *docs, *_out_root(tmp_path)])
    assert code == 0
    assert any(line.startswith("warning: source 'summaries'") for line in lines)
    assert "skipped sources: 1 (summaries)" in lines
    assert not any(line.startswith("summaries ") for line in lines)
    named = ["--dry-run", "--sources", f"{SOURCES_ARG},summaries", *docs]
    code, _ = _main(tmp_path, [*named, *_out_root(tmp_path)])
    assert code == 2


def test_cli_refuses_outside_data_and_unignored(tmp_path: Path) -> None:
    base = ["--route", "bm25", "--sources", SOURCES_ARG, *PATH_ARGS]
    code, _ = _main(tmp_path, [*base, "--out-root", str(tmp_path / "elsewhere")])
    assert code == 2
    lines: list[str] = []
    code = rag_build.main(
        [*base, *_out_root(tmp_path)],
        environ={},
        data_root=tmp_path / "data",
        is_ignored=lambda _: False,
        today=DAY,
        echo=lines.append,
    )
    assert code == 2


def test_cli_refuses_a_missing_source(tmp_path: Path) -> None:
    argv = ["--route", "bm25", "--docs-root", str(tmp_path), *_out_root(tmp_path)]
    code, _ = _main(tmp_path, [*argv, "--sources", "primer"])
    assert code == 2


def test_cli_hybrid_with_the_hashing_model_calibrates(tmp_path: Path) -> None:
    argv = ["--route", "hybrid", "--calibrate", "--sources", SOURCES_ARG, *PATH_ARGS]
    code, lines = _main(tmp_path, [*argv, *_out_root(tmp_path)], environ=HASHING_ENV)
    assert code == 0
    printed = "\n".join(lines)
    assert sum("calibration" in line for line in lines) == len(CALIBRATION_QUESTIONS)
    assert not any(text in printed for text in FIXTURE_TEXT)
    out = index_dir_for(tmp_path / "data" / "indexes" / "docs", "hybrid", DAY)
    assert (out / VECTORS).is_file()


# ----- scripts/market_summaries.py ----------------------------------------------------
def _summaries_script() -> ModuleType:
    path = ROOT / "scripts" / "market_summaries.py"
    spec = importlib.util.spec_from_file_location("market_summaries", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MarketStats:  # the script checks the class name only
    pass


def _result(ok: bool, message: str = "", data=None):
    error = None if ok else SimpleNamespace(category="db")
    return SimpleNamespace(ok=ok, message=message, data=data, error=error)


def test_market_summaries_writes_one_card_per_city(tmp_path: Path) -> None:
    script = _summaries_script()
    out = tmp_path / "data" / "knowledge" / "summaries"
    cards = {"Pasadena": "Invented card one.", "San Marino": "Invented card two."}

    def fake(raw):
        city = raw["city"]
        if city in cards:
            return _result(True, cards[city], MarketStats())
        return _result(False)

    echoed: list[str] = []
    written = script.write_summaries(
        out,
        ["Pasadena", "San Marino", "Nowhere"],
        fake,
        data_root=tmp_path / "data",
        is_ignored=lambda _: True,
        echo=echoed.append,
        saved_on=DAY,
    )
    assert written == 2
    text = (out / "San_Marino.txt").read_text(encoding="utf-8")
    assert text == (
        "Saved on 2026-09-24\nMarket summary: San Marino\nInvented card two.\n"
    )
    assert any(line == "skipped Nowhere: db" for line in echoed)


def test_market_summaries_refuses_outside_data(tmp_path: Path) -> None:
    script = _summaries_script()
    with pytest.raises(script.BuildRefused):
        script.write_summaries(
            tmp_path / "elsewhere",
            ["Pasadena"],
            lambda raw: _result(True, "card", MarketStats()),
            data_root=tmp_path / "data",
            is_ignored=lambda _: True,
        )
