"""WO-017 step 6: the analysis service and its MCP content, offline (fake executor).

No Docker or database. Each path checks the status, the caveats, and that the text
never carries the code, worker numbers or labels, or row values.
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import zlib
from datetime import date
from typing import Any

import pytest
from mcp.types import ImageContent, TextContent
from pydantic import ValidationError

from idx_agent.alerts import server as alerts_server
from idx_agent.analysis import executor, mcp_result, service
from idx_agent.analysis.chart import ChartSpecError
from idx_agent.analysis.mcp_result import analysis_content, analysis_result
from idx_agent.analysis.png import SIGNATURE
from idx_agent.analysis.service import analyse_sample, run_bounded_analysis
from idx_agent.analysis.stats import mean, pearson
from idx_agent.db import analysis as db_analysis
from idx_agent.db import asof as db_asof
from idx_agent.domain.analysis import make_analysis_sample
from idx_agent.domain.analysis_outcome import DEFAULT_CAVEATS, AnalysisOutcome
from idx_agent.domain.analysis_output import WorkerOutput
from idx_agent.domain.analysis_worker import AnalysisRun, ExecutorConfig, RenderRun
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow
from idx_agent.mcp_server import server

AS_OF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SCOPE = MarketStatsRequest(city="Pasadena", property_subtype="Condominium")
WINDOW = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
CODE = "# CODE_SENTINEL_7f3a\nresult = {'version': 1}\n"
# Distinctive invented prices, so a leaked row value is easy to spot in the text.
PRICES = [612_347 + 9_871 * key for key in range(1, 13)]
AREAS = [911 + 53 * key for key in range(1, 13)]
WORKER_NUMBER = 98_765.4321
CONFIG = ExecutorConfig(image="sha256:" + "a" * 64, docker="/usr/bin/docker")


def _sample(count: int = 12):
    rows = [
        SoldComp(
            listing_key=key,
            address=f"{key} Invented Way",
            city="Pasadena",
            postal_code="91101",
            close_date=date(2026, 9, 1),
            close_price=PRICES[key - 1],
            list_price=PRICES[key - 1] + 4_000,
            living_area=AREAS[key - 1],
            days_on_market=3 * key,
            property_subtype="Condominium",
        )
        for key in range(1, count + 1)
    ]
    return make_analysis_sample(rows, SCOPE, WINDOW, AS_OF, eligible=count)


SAMPLE = _sample()
TRUSTED_MEAN = mean(PRICES)


def _png(width: int = 960, height: int = 600) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = (b"\x00" + b"\xff" * (width * 4)) * height
    return (
        SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )


PNG = _png()


def _output(*figures: dict[str, Any], chart: dict[str, Any] | None = None):
    return WorkerOutput.model_validate(
        {"version": 1, "figures": tuple(figures), "chart": chart}
    )


def _mean(value: float | None, label: str = "secret_label_qz") -> dict[str, Any]:
    return {
        "label": label,
        "kind": "mean",
        "x": "close_price",
        "y": None,
        "value": value,
    }


BINNED = {
    "kind": "binned_median",
    "x": "living_area",
    "y": "close_price",
    "bins": (900.0, 1200.0, 1500.0, 1600.0),
}


class FakeExecutor:
    """Stands in for the container: fixed AnalysisRun / RenderRun, calls recorded."""

    def __init__(self, run: AnalysisRun, render: RenderRun | None = None) -> None:
        self.run = run
        self.render = render or RenderRun(
            status="ok", png=PNG, width=960, height=600, duration_s=0.1
        )
        self.analysis_calls: list[str] = []
        self.render_calls: list[Any] = []
        self.sweeps = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeExecutor:
        monkeypatch.setattr(executor, "run_analysis", self._run_analysis)
        monkeypatch.setattr(executor, "render_chart", self._render_chart)
        monkeypatch.setattr(executor, "sweep_leftovers", self._sweep)
        return self

    def _run_analysis(self, config, sample, code):
        self.analysis_calls.append(code)
        return self.run

    def _render_chart(self, config, chart):
        self.render_calls.append(chart)
        return self.render

    def _sweep(self, config, *args, **kwargs):
        self.sweeps += 1
        return 0


@pytest.fixture(autouse=True)
def _fresh_sweep():
    service.reset_sweep_for_tests()
    yield
    service.reset_sweep_for_tests()


def _ok(output: WorkerOutput) -> AnalysisRun:
    return AnalysisRun(status="ok", output=output, duration_s=0.2)


def _text(outcome: AnalysisOutcome) -> str:
    blocks = analysis_content(outcome)
    assert isinstance(blocks[0], TextContent)
    return blocks[0].text


def _assert_clean(text: str) -> None:
    """No code, worker number, worker label or row value in the model's text."""
    assert "CODE_SENTINEL" not in text and "result =" not in text
    assert "secret_label" not in text
    assert "98765" not in text and "98,765" not in text
    for price in PRICES:
        assert str(price) not in text and f"{price:,}" not in text
    for area in AREAS:
        assert f"{area}," not in text and f"{area} " not in text
    assert "Invented" not in text and "91101" not in text
    for caveat in SAMPLE.caveats():
        assert caveat in text


# --- every path ---


@pytest.mark.parametrize(
    ("run", "status", "category"),
    [
        (AnalysisRun(status="unavailable"), "unavailable", "internal"),
        (AnalysisRun(status="busy"), "busy", "rate_limit"),
        (AnalysisRun(status="timeout", duration_s=30.0), "timeout", "timeout"),
        (AnalysisRun(status="output_too_large"), "output_too_large", "safety_refusal"),
        (AnalysisRun(status="failed"), "failed", "internal"),
        (
            AnalysisRun(status="invalid_output", reason="output_refused"),
            "invalid_output",
            "safety_refusal",
        ),
        (
            AnalysisRun(status="invalid_code", reason="code_too_long"),
            "invalid_code",
            "validation",
        ),
    ],
)
def test_worker_failures_become_a_status_with_caveats_and_no_image(
    monkeypatch, run, status, category
):
    fake = FakeExecutor(run).install(monkeypatch)
    log: dict[str, Any] = {}
    outcome = analyse_sample(SAMPLE, CODE, CONFIG, trace_id="t" * 16, log_fields=log)
    assert outcome.status == status and outcome.reason == run.reason
    assert outcome.checks == () and outcome.chart is None and outcome.png is None
    assert fake.render_calls == [] and fake.sweeps == 1
    blocks = analysis_content(outcome)
    assert len(blocks) == 1
    payload = json.loads(blocks[0].text)
    assert payload["ok"] is False and payload["error"]["category"] == category
    assert payload["error"]["message"].endswith("(ref tttttt).")
    assert payload["data"]["status"] == status and payload["data"]["figures"] == []
    assert payload["warnings"] == list(SAMPLE.caveats())
    _assert_clean(blocks[0].text)
    assert log["outcome"] == status and log["sample_count"] == 12


def test_no_configured_image_is_unavailable_without_any_run_or_sweep(monkeypatch):
    fake = FakeExecutor(AnalysisRun(status="failed")).install(monkeypatch)
    outcome = analyse_sample(SAMPLE, CODE, None)
    assert outcome.status == "unavailable"
    assert fake.analysis_calls == [] and fake.sweeps == 0
    _assert_clean(_text(outcome))


def test_an_empty_sample_runs_nothing(monkeypatch):
    fake = FakeExecutor(AnalysisRun(status="failed")).install(monkeypatch)
    empty = make_analysis_sample([], SCOPE, WINDOW, AS_OF, eligible=0)
    outcome = analyse_sample(empty, CODE, CONFIG)
    assert outcome.status == "no_sales" and fake.analysis_calls == []
    payload = json.loads(_text(outcome))
    assert payload["ok"] is True and "No eligible sales" in payload["message"]
    assert payload["warnings"] == list(empty.caveats())


def test_a_verified_figure_shows_the_trusted_value(monkeypatch):
    FakeExecutor(_ok(_output(_mean(TRUSTED_MEAN)))).install(monkeypatch)
    outcome = analyse_sample(SAMPLE, CODE, CONFIG)
    assert outcome.status == "ok" and outcome.checks[0].status == "verified"
    payload = json.loads(_text(outcome))
    figure = payload["data"]["figures"][0]
    assert figure == {
        "index": 1,
        "kind": "mean",
        "x": "close_price",
        "y": None,
        "status": "verified",
        "reason": None,
        "trusted": TRUSTED_MEAN,
        "n": 12,
    }
    assert f"${TRUSTED_MEAN:,.2f}, verified (n=12)" in payload["message"]
    assert payload["data"]["chart"]["status"] == "not_requested"


def test_a_mismatch_shows_only_the_trusted_value(monkeypatch):
    pairs = {
        "label": "secret_label_r",
        "kind": "pearson",
        "x": "living_area",
        "y": "close_price",
        "value": 0.25,
    }
    other = {"label": "secret_label_o", "kind": "other", "x": None, "y": None}
    output = _output(_mean(WORKER_NUMBER), pairs, {**other, "value": WORKER_NUMBER})
    FakeExecutor(_ok(output)).install(monkeypatch)
    outcome = analyse_sample(SAMPLE, CODE, CONFIG)
    statuses = [check.status for check in outcome.checks]
    assert statuses == ["mismatch", "mismatch", "unverified"]
    assert outcome.checks[0].reported == WORKER_NUMBER  # kept host-side only
    text = _text(outcome)
    _assert_clean(text)
    payload = json.loads(text)
    figures = payload["data"]["figures"]
    assert [f["trusted"] for f in figures] == [
        TRUSTED_MEAN,
        pytest.approx(pearson(AREAS, PRICES)),
        None,
    ]
    assert all("reported" not in f and "label" not in f for f in figures)
    assert "did not match (value_differs)" in payload["message"]
    assert "3. other of ?: not checked; no trusted value." in payload["message"]
    assert "0.25" not in text


def test_an_unavailable_figure_has_no_value(monkeypatch):
    small = _sample(8)
    pairs = {
        "label": "r",
        "kind": "spearman",
        "x": "living_area",
        "y": "close_price",
        "value": 1.0,
    }
    FakeExecutor(_ok(_output(pairs))).install(monkeypatch)
    outcome = analyse_sample(small, CODE, CONFIG)
    payload = json.loads(_text(outcome))
    assert payload["data"]["figures"][0]["trusted"] is None
    assert "unavailable (too_few_pairs, n=8)" in payload["message"]
    assert "Fewer than 10 sales" in " ".join(payload["warnings"])


def test_ok_with_a_chart_attaches_one_checked_png(monkeypatch):
    fake = FakeExecutor(_ok(_output(_mean(TRUSTED_MEAN), chart=BINNED)))
    fake.install(monkeypatch)
    outcome = analyse_sample(SAMPLE, CODE, CONFIG)
    assert outcome.chart_status == "rendered" and outcome.png == PNG
    assert len(fake.render_calls) == 1
    chart = fake.render_calls[0]
    assert (chart.kind, chart.x_field, chart.y_field) == (
        "binned_median",
        "living_area",
        "close_price",
    )
    assert [bar.n for bar in chart.bars] == [5, 6, 1]  # from the trusted areas
    blocks = analysis_content(outcome)
    assert [type(block) for block in blocks] == [TextContent, ImageContent]
    assert base64.b64decode(blocks[1].data) == PNG
    assert blocks[1].model_dump(by_alias=True)["mimeType"] == "image/png"
    text = blocks[0].text
    _assert_clean(text)
    view = json.loads(text)["data"]["chart"]
    assert view["status"] == "rendered" and view["image_attached"] is True
    assert view["title"] == "Median sale price by living area"
    assert "points" not in view and "bars" not in view
    assert "Chart: attached." in json.loads(text)["message"]
    assert base64.b64encode(PNG).decode()[:40] not in text
    assert "png" not in outcome.model_dump() and "png" not in outcome.model_dump_json()


def test_a_scatter_chart_sends_no_points_to_the_model(monkeypatch):
    scatter = {"kind": "scatter", "x": "living_area", "y": "close_price"}
    FakeExecutor(_ok(_output(chart=scatter))).install(monkeypatch)
    outcome = analyse_sample(SAMPLE, CODE, CONFIG)
    assert len(outcome.chart.points) == 12
    text = _text(outcome)
    _assert_clean(text)
    assert json.loads(text)["data"]["chart"]["n_used"] == 12


def test_a_refused_chart_spec_keeps_the_figures(monkeypatch):
    fake = FakeExecutor(_ok(_output(_mean(TRUSTED_MEAN), chart=BINNED)))
    fake.install(monkeypatch)

    def refuse(*args, **kwargs):
        raise ChartSpecError("unsupported chart field")

    monkeypatch.setattr(service, "build_chart", refuse)
    outcome = analyse_sample(SAMPLE, CODE, CONFIG)
    assert outcome.status == "ok" and outcome.chart_status == "refused"
    assert outcome.chart is None and fake.render_calls == []
    blocks = analysis_content(outcome)
    assert len(blocks) == 1
    payload = json.loads(blocks[0].text)
    assert payload["ok"] is True and payload["data"]["figures"][0]["status"] == (
        "verified"
    )
    assert "none was drawn" in payload["message"]


@pytest.mark.parametrize(
    ("render", "status"),
    [
        (RenderRun(status="timeout", duration_s=30.0), "timeout"),
        (RenderRun(status="failed"), "failed"),
        (RenderRun(status="invalid_png"), "invalid_png"),
        (RenderRun(status="busy"), "busy"),
        (RenderRun(status="ok", png=b"junk", width=960, height=600), "invalid_png"),
        (
            RenderRun(status="ok", png=PNG + b"tail", width=960, height=600),
            "invalid_png",
        ),
    ],
)
def test_a_failed_render_gives_figures_and_no_image(monkeypatch, render, status):
    FakeExecutor(_ok(_output(_mean(TRUSTED_MEAN), chart=BINNED)), render).install(
        monkeypatch
    )
    outcome = analyse_sample(SAMPLE, CODE, CONFIG)
    assert outcome.status == "ok" and outcome.chart_status == status
    assert outcome.png is None and outcome.chart is not None
    blocks = analysis_content(outcome)
    assert len(blocks) == 1
    payload = json.loads(blocks[0].text)
    assert payload["ok"] is True and payload["data"]["chart"]["status"] == status
    assert payload["data"]["chart"]["image_attached"] is False
    assert "could not be drawn" in payload["message"]


def test_the_sweep_runs_once_per_process_and_a_failing_sweep_is_ignored(monkeypatch):
    fake = FakeExecutor(_ok(_output())).install(monkeypatch)
    for _ in range(3):
        analyse_sample(SAMPLE, CODE, CONFIG)
    assert fake.sweeps == 1 and len(fake.analysis_calls) == 3

    service.reset_sweep_for_tests()

    def broken(config, *args, **kwargs):
        raise OSError("docker is gone")

    monkeypatch.setattr(executor, "sweep_leftovers", broken)
    assert analyse_sample(SAMPLE, CODE, CONFIG).status == "ok"


def test_the_log_holds_codes_and_counts_only(monkeypatch):
    output = _output(_mean(WORKER_NUMBER), chart=BINNED)
    FakeExecutor(_ok(output)).install(monkeypatch)
    log: dict[str, Any] = {}
    analyse_sample(SAMPLE, CODE, CONFIG, log_fields=log)
    assert log == {
        "outcome": "ok",
        "reason": None,
        "sample_count": 12,
        "eligible": 12,
        "figure_count": 1,
        "figure_statuses": {"mismatch": 1},
        "chart_status": "rendered",
    }


# --- the reader wrapper ---


def _reader(monkeypatch, sample=None, error: Exception | None = None):
    seen: dict[str, Any] = {}
    monkeypatch.setattr(db_asof, "get_asof_dates", lambda conn: AS_OF)

    def fetch(request, window, as_of, conn):
        seen.update(request=request, window=window, as_of=as_of, conn=conn)
        if error is not None:
            raise error
        return sample

    monkeypatch.setattr(db_analysis, "fetch_analysis_sample", fetch)
    return seen


def test_the_window_counts_back_from_the_sold_asof(monkeypatch):
    seen = _reader(monkeypatch, SAMPLE)
    FakeExecutor(_ok(_output(_mean(TRUSTED_MEAN)))).install(monkeypatch)
    outcome = run_bounded_analysis(SCOPE, CODE, "conn", CONFIG, trace_id="a" * 16)
    assert seen["window"] == WINDOW and seen["as_of"] == AS_OF
    assert seen["conn"] == "conn" and outcome.trace_id == "a" * 16
    assert outcome.status == "ok" and outcome.window == WINDOW


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (db_analysis.AnalysisDeadlineExceeded("statement exceeded"), "db_timeout"),
        (RuntimeError("Pasadena 612347 secret"), "db_error"),
    ],
)
def test_reader_failures_are_status_codes(monkeypatch, error, status):
    _reader(monkeypatch, error=error)
    fake = FakeExecutor(_ok(_output())).install(monkeypatch)
    log: dict[str, Any] = {}
    outcome = run_bounded_analysis(SCOPE, CODE, None, CONFIG, log_fields=log)
    assert outcome.status == status and outcome.caveats == DEFAULT_CAVEATS
    assert fake.analysis_calls == [] and fake.sweeps == 0
    text = _text(outcome)
    assert "612347" not in text and "secret" not in text and "exceeded" not in text
    payload = json.loads(text)
    assert payload["ok"] is False and payload["warnings"] == list(DEFAULT_CAVEATS)
    assert "612347" not in json.dumps(log)


# --- the outcome model ---


def test_an_image_must_pass_the_check_and_match_the_chart_status():
    base = dict(
        trace_id="x" * 16,
        status="ok",
        caveats=SAMPLE.caveats(),
        n=12,
    )
    with pytest.raises(ValidationError):
        AnalysisOutcome(**base, png=PNG)  # not rendered
    with pytest.raises(ValidationError):
        AnalysisOutcome(**base, chart_status="rendered", png=b"\x89PNG junk")
    with pytest.raises(ValidationError):
        AnalysisOutcome(**{**base, "status": "timeout"}, chart_status="rendered")
    with pytest.raises(ValidationError):
        AnalysisOutcome(**{**base, "caveats": ()})


def test_the_result_envelope_names_the_table_and_asof(monkeypatch):
    FakeExecutor(_ok(_output())).install(monkeypatch)
    result = analysis_result(analyse_sample(SAMPLE, CODE, CONFIG, trace_id="b" * 16))
    dumped = result.model_dump(mode="json")
    assert dumped["provenance"] == {
        "tables": ["california_sold"],
        "as_of": {"sold": "2026-09-17", "active": "2026-09-18"},
        "tool": mcp_result.ANALYSIS_TOOL,
        "trace_id": "b" * 16,
    }
    assert dumped["data"]["city"] == "Pasadena" and dumped["data"]["n"] == 12


# --- nothing is registered ---

TOOLS = [
    "draft_email",
    "find_similar_listings",
    "get_market_stats",
    "health",
    "rag_answer",
    "recommend",
    "search_listings",
]
ALERT_TOOLS = ["delete_saved_search", "forget_me", "list_saved_searches", "save_search"]


def test_the_server_tool_lists_are_unchanged():
    assert server.tool_names() == TOOLS
    alerts = sorted(t.name for t in asyncio.run(alerts_server.server.list_tools()))
    assert alerts == ALERT_TOOLS
    assert mcp_result.ANALYSIS_TOOL not in TOOLS + ALERT_TOOLS


def test_the_analysis_modules_register_nothing():
    for module in (service, mcp_result):
        source = open(module.__file__, encoding="utf-8").read()
        assert ".tool(" not in source and "mcp_server" not in source
