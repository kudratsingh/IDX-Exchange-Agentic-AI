"""WO-020 latency benchmark: report shape only; no speed threshold is asserted."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from evals import latency


class FakeConn:
    def cursor(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                self.sql = sql

            def fetchall(self):
                if "VERSION" in self.sql:
                    return [{"v": "8.0.invented"}]
                if "REGEXP" in self.sql:
                    return [{"n": 10, "real_like": 0}]
                return [{"n": 10}]

        return Cursor()

    def close(self):
        pass


class FakeServer:
    """Every tool body answers ok at once; the cache resets are counted."""

    resets = 0

    def __getattr__(self, name):
        if name.startswith("reset_"):
            return self._reset
        return lambda *args: SimpleNamespace(ok=True)

    def _reset(self):
        FakeServer.resets += 1


@pytest.fixture
def fakes(monkeypatch):
    from evals import run as runner

    from idx_agent.db import pool

    monkeypatch.setattr(pool, "connect", lambda: FakeConn())
    for name in ("FixtureIndex", "RagFixtureIndex"):
        monkeypatch.setattr(
            runner,
            name,
            lambda: SimpleNamespace(use=lambda *a: None, close=lambda: None),
        )


def test_a_smoke_run_has_the_documented_report_shape(fakes):
    report = latency.run("fixture", repeat=3, warmup=1, server=FakeServer())
    assert report["report_version"] == latency.REPORT_VERSION
    assert {"cold", "warm", "percentile"} <= set(report["definitions"])
    assert report["rets_property_rows"] == 10 and report["mysql_version"]
    assert report["python"] and "git_commit" in report
    assert set(report["tools"]) == {label for label, *_ in latency.CASES}
    for row in report["tools"].values():
        assert set(row) == {"cold_ms", "warm_n", "p50_ms", "p95_ms", "max_ms", "ok"}
        assert row["warm_n"] == 3 and row["p50_ms"] <= row["p95_ms"] <= row["max_ms"]


def test_a_real_run_skips_fixture_only_cases(fakes):
    report = latency.run("real", repeat=1, warmup=0, server=FakeServer())
    skipped = {k for k, v in report["tools"].items() if "skipped" in v}
    assert skipped == {
        label for label, _, _, kinds in latency.CASES if "real" not in kinds
    }


def test_a_fixture_report_refuses_a_database_that_is_not_the_fixture(monkeypatch):
    from idx_agent.db import pool

    class Big(FakeConn):
        def cursor(self):
            inner = super().cursor()
            fetch = inner.fetchall

            def fetchall():
                rows = fetch()
                return [dict(rows[0], n=55_212)] if "REGEXP" in inner.sql else rows

            inner.fetchall = fetchall
            return inner

    monkeypatch.setattr(pool, "connect", lambda: Big())
    with pytest.raises(ValueError, match="larger than the synthetic fixture"):
        latency.run("fixture", repeat=1, warmup=0, server=FakeServer())


def test_percentiles_are_nearest_rank():
    values = list(range(1, 21))
    assert latency.percentile(values, 0.5) == 10
    assert latency.percentile(values, 0.95) == 19
    assert latency.percentile([7.0], 0.95) == 7.0


def test_reports_stay_out_of_the_tracked_tree(tmp_path):
    assert latency.out_problem(tmp_path / "r.json") is None
    assert latency.out_problem(latency.ROOT / "data" / "r.json") is None
    assert latency.out_problem(latency.ROOT / "evals" / "r.json")
    assert (
        latency.default_out("fixture").resolve().is_relative_to(latency.ROOT) is False
    )


def test_main_writes_the_report_where_asked(fakes, tmp_path, monkeypatch):
    import idx_agent.mcp_server.server as server

    for name in ("health_result", "search_result", "market_result", "recommend_result",
                 "similar_result", "rag_result"):  # fmt: skip
        monkeypatch.setattr(server, name, lambda *a: SimpleNamespace(ok=True))
    out = tmp_path / "latency.json"
    assert (
        latency.main(["--database-kind", "fixture", "--repeat", "2", "--out", str(out)])
        == 0
    )
    assert json.loads(out.read_text())["repeat"] == 2
