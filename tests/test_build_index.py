"""Unit tests for semantic/build_index.py (WO-010): stub connection, no paid call.

The build runs with a HashingEmbedder under a non-test name (the build refuses any
`test:` model) or an OpenAIEmbedder over a stub client, against a fake connection
that answers the as-of and keyset-page statements. Output is checked for leaks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST
from idx_agent.semantic import build_index as bi
from idx_agent.semantic.build_index import (
    PAGE_ROWS,
    BuildRefused,
    BuildStopped,
    build,
    iter_pages,
    main,
    page_sql,
    prepare_rows,
)
from idx_agent.semantic.embedder import HashingEmbedder, OpenAIEmbedder, ProviderError
from idx_agent.semantic.index import META, load_index

UNIT = "unit:hashing"
MARKER = "quokkaberry"  # a unique word inside every invented remark
BASE_TS = datetime(2026, 9, 1, 8, 0)


class UnitHashing(HashingEmbedder):
    """HashingEmbedder under a non-test name; counts texts; can fail on call N."""

    name = UNIT

    def __init__(self, dims: int = 16, fail_on_call: int | None = None) -> None:
        super().__init__(dims)
        self.calls = 0
        self.texts = 0
        self.fail_on_call = fail_on_call

    def embed(self, texts):
        self.calls += 1
        if self.fail_on_call is not None and self.calls >= self.fail_on_call:
            raise ProviderError("failed")
        self.texts += len(texts)
        return super().embed(texts)


def _row(n: int, remarks: str | None = "", **extra: Any) -> dict[str, Any]:
    """One invented active row; remarks default to a unique descriptive sentence."""
    if remarks == "":
        remarks = f"Invented home number {n} with a {MARKER} garden and a quiet street"
    row = {
        "L_ListingID": str(9100000 + n),
        "L_Remarks": remarks,
        "L_City": "Pasadena" if n % 2 else "Glendale",
        "L_SystemPrice": 500_000 + 1000 * n,
        "L_Keyword2": n % 5,
        "L_Type_": "Condominium" if n % 3 == 0 else "SingleFamilyResidence",
        "ModificationTimestamp": BASE_TS + timedelta(minutes=n),
        "L_DisplayId": str(9500000 + n),
        "StandardStatus": "Active",
    }
    row.update(extra)
    return row


def _rows(count: int = 130) -> list[dict[str, Any]]:
    """Invented rows: some empty, short, repeated, non-numeric, redactable, long."""
    rows = [_row(n) for n in range(1, count + 1)]
    rows[4]["L_Remarks"] = None
    rows[5]["L_Remarks"] = "   "
    rows[6]["L_Remarks"] = "tiny"
    rows[7]["L_Remarks"] = f"See www.example.invalid for a {MARKER} tour of this home"
    rows[8]["L_Remarks"] = "long words " * 500
    # A repeated id straddling the first page boundary: the newer row must win.
    rows.append(_row(49, remarks=f"Newer text for home 49 {MARKER} bright rooms",
                     ModificationTimestamp=BASE_TS + timedelta(days=5)))  # fmt: skip
    rows.append(_row(3, L_ListingID="A-17"))
    rows.append(_row(4, StandardStatus="Closed"))
    return rows


class FakeCursor:
    """Answers the as-of statements and keyset pages from the connection's rows."""

    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.result: list[dict[str, Any]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.conn.statements.append((sql, tuple(params)))
        if "active_max" in sql:
            self.result = [{"active_max": self.conn.next_asof()}]
        elif "sold_max" in sql:
            self.result = [{"sold_max": "2026-09-17"}]
        else:
            status, after, limit = params[0], params[-2], params[-1]
            live = [r for r in self.conn.rows if r["StandardStatus"] == status]
            live = [r for r in live if r["L_ListingID"] > after]
            live.sort(key=lambda r: (r["L_ListingID"], -r["ModificationTimestamp"]
                                     .timestamp(), r["L_DisplayId"]))  # fmt: skip
            self.result = [dict(r) for r in live[:limit]]
            self.conn.pages += 1

    def fetchone(self) -> dict[str, Any] | None:
        return self.result[0] if self.result else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.result)


class FakeConn:
    """A stand-in pymysql connection; `asofs` are returned in turn (last repeats)."""

    def __init__(self, rows: list[dict[str, Any]], asofs=("2026-09-18 17:30:00",)):
        self.rows = rows
        self.asofs = list(asofs)
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.pages = 0
        self.closed = False

    def next_asof(self) -> str:
        return self.asofs.pop(0) if len(self.asofs) > 1 else self.asofs[0]

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def roots(tmp_path):
    """(data root, index root under it)."""
    data = tmp_path / "data"
    return data, data / "indexes" / "remarks"


def _build(conn, embedder, roots, **kwargs):
    """Run build() into the temporary data root, treating it as git-ignored."""
    data, out = roots
    lines: list[str] = []
    options = {"data_root": data, "is_ignored": lambda p: True, "echo": lines.append}
    options.update(kwargs)
    report = build(conn, embedder, out, **options)
    return report, lines


# --- statements and pages ---


def test_page_sql_names_allowlisted_columns_and_binds_every_value():
    sql, params = page_sql("9100049")
    assert "SELECT *" not in sql and "%s" in sql
    assert sql.startswith(
        "SELECT L_ListingID, L_Remarks, L_City, L_SystemPrice, L_Keyword2, L_Type_\n"
    )
    assert "StandardStatus = %s AND L_ListingID > %s" in sql
    assert sql.endswith("LIMIT %s")
    assert params == ("Active", "9100049", PAGE_ROWS)
    for column in AGENT_CONTACT | DENYLIST:
        assert column not in sql


def test_pages_never_split_a_repeated_id_and_stay_within_the_cap():
    conn = FakeConn(_rows())
    pages = list(iter_pages(conn))
    ids = [row["L_ListingID"] for rows, _ in pages for row in rows]
    first_page_ids = {row["L_ListingID"] for row in pages[0][0]}
    assert "9100049" not in first_page_ids  # handed to the next page whole
    assert ids.count("9100049") == 2
    assert all(len(rows) <= PAGE_ROWS for rows, _ in pages)
    assert len(ids) == len([r for r in conn.rows if r["StandardStatus"] == "Active"])


def test_prepare_rows_counts_and_keeps_the_newest_row_per_id():
    rows = [row for rows, _ in iter_pages(FakeConn(_rows())) for row in rows]
    records, stats, last = prepare_rows(rows)
    by_key = {r.key: r for r in records}
    assert "Newer text" in by_key[9100049].text
    assert stats.duplicates == 1 and stats.bad_keys == 1
    assert stats.skipped_empty == 3 and stats.truncated == 1 and stats.redacted == 1
    assert stats.rows_read == len(rows) and last == rows[-1]["L_ListingID"]
    assert by_key[9100002].list_price == 502_000 and by_key[9100002].bedrooms == 2
    few, _, last_few = prepare_rows(rows, max_records=3)
    assert len(few) == 3 and last_few == str(few[-1].key)


# --- the build ---


def test_build_writes_a_loadable_index_and_prints_counts_only(roots, capsys):
    conn = FakeConn(_rows())
    report, lines = _build(conn, UnitHashing(), roots, shard_rows=40)
    path = report.index_dir
    assert path.parts[-2:] == ("unit-hashing-16", "2026-09-18")
    index = load_index(path, UNIT, 16, data_root=roots[0])
    assert index.rows == report.embedded == 127
    assert index.meta.skipped_empty == 3 and index.meta.truncated == 1
    assert index.meta.redacted_inputs == 1 and index.meta.usage_tokens is None
    assert report.stats.duplicates == 1 and report.stats.bad_keys == 1
    assert (path / "build" / "progress.json").exists()
    printed = "\n".join(lines) + capsys.readouterr().out
    assert (
        MARKER not in printed and "91000" not in printed and "Pasadena" not in printed
    )
    meta_text = (path / META).read_text()
    assert MARKER not in meta_text and "91000" not in meta_text


def test_resume_after_two_shards_matches_an_uninterrupted_build(tmp_path):
    whole_roots = (tmp_path / "a" / "data", tmp_path / "a" / "data" / "i")
    part_roots = (tmp_path / "b" / "data", tmp_path / "b" / "data" / "i")
    options = {"shard_rows": 30, "batch_size": 500}  # one embed call per shard
    whole, _ = _build(FakeConn(_rows()), UnitHashing(), whole_roots, **options)

    failing = UnitHashing(fail_on_call=3)
    with pytest.raises(ProviderError):
        _build(FakeConn(_rows()), failing, part_roots, **options)
    part_dir = part_roots[1] / "unit-hashing-16" / "2026-09-18"
    progress = json.loads((part_dir / "build" / "progress.json").read_text())
    assert len(progress["shards"]) == 2 and not (part_dir / META).exists()
    done_texts = failing.texts

    resumed_embedder = UnitHashing()
    resumed, _ = _build(FakeConn(_rows()), resumed_embedder, part_roots, **options)
    assert resumed.shards_reused == 2
    assert resumed_embedder.texts == whole.embedded - done_texts
    a = load_index(whole.index_dir, UNIT, 16, data_root=whole_roots[0])
    b = load_index(resumed.index_dir, UNIT, 16, data_root=part_roots[0])
    assert a.meta.vectors_sha256 == b.meta.vectors_sha256
    assert a.meta.keys_sha256 == b.meta.keys_sha256
    assert np.array_equal(a.keys, b.keys) and np.array_equal(a.vectors, b.vectors)


def test_a_second_run_on_a_complete_index_embeds_nothing(roots):
    _build(FakeConn(_rows()), UnitHashing(), roots)
    again = UnitHashing()
    report, _ = _build(FakeConn(_rows()), again, roots)
    assert report.already_complete is True
    assert again.calls == 0


def test_a_changed_as_of_at_the_end_leaves_no_meta(roots):
    conn = FakeConn(_rows(), asofs=("2026-09-18 17:30:00", "2026-09-19 08:00:00"))
    with pytest.raises(BuildStopped, match="as-of"):
        _build(conn, UnitHashing(), roots)
    path = roots[1] / "unit-hashing-16" / "2026-09-18"
    assert not (path / META).exists()
    assert (path / "build" / "progress.json").exists()


def test_the_build_refuses_test_models_and_bad_paths(roots, tmp_path):
    conn = FakeConn(_rows())
    with pytest.raises(BuildRefused, match="test models"):
        _build(conn, HashingEmbedder(), roots)
    with pytest.raises(BuildRefused, match="data/"):
        build(conn, UnitHashing(), tmp_path / "elsewhere", data_root=roots[0],
              is_ignored=lambda p: True, echo=lambda s: None)  # fmt: skip
    with pytest.raises(BuildRefused, match="ignored"):
        _build(conn, UnitHashing(), roots, is_ignored=lambda p: False)
    assert not roots[0].exists()


def test_usage_tokens_are_kept_per_batch_and_in_meta(roots):
    stub = SimpleNamespace(calls=[])

    def create(**kwargs):
        stub.calls.append(len(kwargs["input"]))
        data = [SimpleNamespace(index=i, embedding=[1.0] + [0.5] * 511)
                for i in range(len(kwargs["input"]))]  # fmt: skip
        return SimpleNamespace(data=data, usage=SimpleNamespace(total_tokens=11))

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    embedder = OpenAIEmbedder(
        dims=512, client=client, environ={"OPENAI_API_KEY": "test-only"},
        consent_check=lambda: True, batch_size=50,
    )  # fmt: skip
    report, lines = _build(FakeConn(_rows()), embedder, roots, batch_size=50)
    progress = json.loads((report.index_dir / "build" / "progress.json").read_text())
    batches = [t for shard in progress["shards"] for t in shard["batch_tokens"]]
    assert batches == [11] * len(stub.calls)
    meta = json.loads((report.index_dir / META).read_text())
    assert meta["usage_tokens"] == report.usage_tokens == 11 * len(stub.calls)
    assert max(stub.calls) <= 50


# --- the command line ---


def _main(args, environ=None, consent=True, ignored=True, data_root=None, conn=None):
    """Run main() with every outside dependency injected; returns (code, conn used)."""
    opened: list[FakeConn] = []

    def connect():
        opened.append(conn or FakeConn(_rows()))
        return opened[-1]

    code = main(
        args,
        environ={} if environ is None else environ,
        connect_fn=connect,
        consent_check=lambda: consent,
        data_root=data_root or Path("/nonexistent-data-root"),
        is_ignored=lambda p: ignored,
        echo=lambda s: None,
    )
    return code, opened


KEY_ENV = {"OPENAI_API_KEY": "test-only"}


@pytest.mark.parametrize(
    ("args", "environ", "consent", "ignored", "message"),
    [
        (["--allow-paid"], {**KEY_ENV, "CI": "true"}, True, True, "CI is set"),
        (["--dry-run"], {"CI": "1"}, True, True, "CI is set"),
        (["--allow-paid"], {**KEY_ENV, "IDX_EMBED_MODEL": "test:hashing"}, True, True,
         "test models"),
        ([], KEY_ENV, True, True, "--allow-paid"),
        (["--allow-paid"], KEY_ENV, False, True, "consent token"),
        (["--allow-paid"], {}, True, True, "OPENAI_API_KEY"),
        (["--allow-paid", "--out-root", "/tmp/not-data"], KEY_ENV, True, True, "data/"),
        (["--allow-paid"], KEY_ENV, True, False, "ignored"),
        (["--dry-run", "--sample", "5"], {}, True, True, "not both"),
    ],
)  # fmt: skip
def test_main_refuses_before_connecting(
    tmp_path, capsys, args, environ, consent, ignored, message
):
    data = tmp_path / "data"
    if "--out-root" not in args:
        args = [*args, "--out-root", str(data / "indexes" / "remarks")]
    code, opened = _main(args, environ, consent, ignored, data)
    assert code == 2
    assert opened == []
    assert message in capsys.readouterr().err


def test_dry_run_counts_without_consent_and_writes_nothing(tmp_path):
    lines: list[str] = []
    conn = FakeConn(_rows())
    code = main(
        ["--dry-run", "--out-root", str(tmp_path / "data" / "i")],
        environ={}, connect_fn=lambda: conn, consent_check=lambda: False,
        data_root=tmp_path / "data", is_ignored=lambda p: False, echo=lines.append,
    )  # fmt: skip
    text = "\n".join(lines)
    assert code == 0 and conn.closed
    assert "embeddable            127" in text
    assert "repeated listing ids  1" in text
    assert MARKER not in text and "91000" not in text
    assert not (tmp_path / "data").exists()


def _stub_openai(monkeypatch):
    """Make main() build an OpenAIEmbedder over a stub client (never a real one)."""
    calls: list[int] = []

    def create(**kwargs):
        calls.append(len(kwargs["input"]))
        data = [SimpleNamespace(index=i, embedding=[0.0, 1.0] + [0.0] * 1534)
                for i in range(len(kwargs["input"]))]  # fmt: skip
        return SimpleNamespace(data=data, usage=SimpleNamespace(total_tokens=3))

    real = bi.make_embedder

    def fake(model, dims, **kwargs):
        client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
        return real(model, dims, **{**kwargs, "client": client})

    monkeypatch.setattr(bi, "make_embedder", fake)
    return calls


def test_main_real_run_path_with_a_stub_client(tmp_path, monkeypatch):
    calls = _stub_openai(monkeypatch)
    data = tmp_path / "data"
    out = data / "indexes" / "remarks"
    code, opened = _main(["--allow-paid", "--out-root", str(out)], KEY_ENV,
                         data_root=data)  # fmt: skip
    assert code == 0 and opened[0].closed
    path = out / "openai-text-embedding-3-small-1536" / "2026-09-18"
    meta = json.loads((path / META).read_text())
    assert meta["rows"] == 127 and meta["usage_tokens"] == 3 * len(calls)
    assert max(calls) <= 100


def test_main_sample_goes_to_its_own_directory(tmp_path, monkeypatch):
    _stub_openai(monkeypatch)
    data = tmp_path / "data"
    out = data / "indexes" / "remarks"
    code, _ = _main(["--allow-paid", "--sample", "7", "--out-root", str(out)],
                    KEY_ENV, data_root=data)  # fmt: skip
    assert code == 0
    path = out / "samples" / "openai-text-embedding-3-small-1536" / "2026-09-18-first7"
    assert json.loads((path / META).read_text())["rows"] == 7
    assert not (out / "openai-text-embedding-3-small-1536").exists()


def test_main_reports_a_provider_failure_and_keeps_progress(
    tmp_path, monkeypatch, capsys
):
    def fake(model, dims, **kwargs):
        return UnitHashing(fail_on_call=1)

    monkeypatch.setattr(bi, "make_embedder", fake)
    data = tmp_path / "data"
    code, opened = _main(["--allow-paid", "--out-root", str(data / "i")], KEY_ENV,
                         data_root=data)  # fmt: skip
    assert code == 1 and opened[0].closed
    assert "rerun to resume" in capsys.readouterr().err
