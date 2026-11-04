"""WO-027: the opt-in bounded_analysis path end to end, offline, over real MCP.

Switch off: default session, tools, skills, prompt. On: tool, instructions, skill.
Stand-ins: the sample reader (the fixture database under `db`) and the docker client
(the executor tests' fake, real pipes); the executor, parser, checks and PNG are real.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import os
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from evals import run as runner
from mcp import Client
from mcp.types import ImageContent, TextContent
from tests.test_analysis_executor import (  # noqa: F401 - fake_docker is a fixture
    DOCKER,
    FakeProcess,
    fake_docker,
)
from tests.test_analysis_service import PNG
from tests.test_openclaw_merge_config import SKILLS

from idx_agent.analysis import executor, service
from idx_agent.analysis import tool as analysis_tool
from idx_agent.channels.format import (
    CHART_IMAGE_FALLBACK,
    CHART_NOT_ATTACHED_LINE,
    format_chart_line,
)
from idx_agent.db import analysis as db_analysis
from idx_agent.domain import analysis_worker
from idx_agent.domain.analysis import ANALYSIS_MAX_ROWS, make_analysis_sample
from idx_agent.domain.analysis_worker import ExecutorConfig
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow
from idx_agent.mcp_server import server

IMAGE = "sha256:" + "b" * 64
BOUNDED = "Bounded input of at most 50 sales; not a representative area sample."
DEFAULT_TOOLS = [
    "draft_email",
    "find_similar_listings",
    "get_market_stats",
    "health",
    "rag_answer",
    "recommend",
    "search_listings",
]
AS_OF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SCOPE = MarketStatsRequest(city="Pasadena")
WINDOW = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
# Invented sales: 50 of 80 eligible, distinctive prices so a leaked row is easy to see.
PRICES = [701_113 + 7_919 * key for key in range(1, 51)]
AREAS = [1_003 + 29 * key for key in range(1, 51)]
# Code the model might send; it would mark the host if it were ever run in-process.
CODE = (
    "import builtins\nbuiltins.WO027_RAN_ON_HOST = True\n"
    "result = {'version': 1, 'figures': [], 'chart': None}\n"
)


def _sample():
    rows = [
        SoldComp(
            listing_key=key,
            address=f"{key} Invented Way",
            city="Pasadena",
            postal_code="91101",
            close_date=date(2026, 9, 1),
            close_price=PRICES[key - 1],
            list_price=PRICES[key - 1] + 5_000,
            living_area=AREAS[key - 1],
            days_on_market=key,
            property_subtype="SingleFamilyResidence",
        )
        for key in range(1, ANALYSIS_MAX_ROWS + 1)
    ]
    return make_analysis_sample(rows, SCOPE, WINDOW, AS_OF, eligible=80)


SAMPLE = _sample()
MEAN = sum(PRICES) / len(PRICES)


def worker_json(chart: dict[str, Any] | None = None, value: float = MEAN) -> bytes:
    """What the bootstrap prints for one mean figure (and an optional chart)."""
    figure = {
        "label": "mean_price",
        "kind": "mean",
        "x": "close_price",
        "y": None,
        "value": value,
    }
    return json.dumps({"version": 1, "figures": [figure], "chart": chart}).encode()


SCATTER = {"kind": "scatter", "x": "living_area", "y": "close_price"}


# --- fixtures: the switch, the sample reader, the docker client ---


@pytest.fixture
def switch_on(monkeypatch, analysis_switch_in_dotenv):
    """IDX_ANALYSIS_TOOL=1 in .env and a pinned image, registered as at server start."""
    monkeypatch.setenv("IDX_ANALYSIS_IMAGE", IMAGE)
    assert server.register_analysis_tool() is True
    yield
    server.reset_analysis_tool_for_tests()


@pytest.fixture
def reader(monkeypatch, switch_on):
    """A configured database whose sample read returns the 50 invented sales."""
    calls = {"fetch": 0}

    class Conn:
        def close(self):
            calls["closed"] = True

    def fetch(request, window, as_of, conn):
        calls["fetch"] += 1
        return SAMPLE

    monkeypatch.setattr(server.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(server.db_pool, "connect", lambda config=None: Conn())
    monkeypatch.setattr(db_analysis, "fetch_analysis_sample", fetch)
    monkeypatch.setattr(service.db_asof, "get_asof_dates", lambda conn: AS_OF)
    service.reset_sweep_for_tests()
    yield calls
    service.reset_sweep_for_tests()


@pytest.fixture
def worker(fake_docker, monkeypatch):  # noqa: F811 - the imported fixture
    """The real executor with the fake docker client on PATH. `set(...)` chooses
    what the analysis run and the render run print; `seen` keeps the input files."""
    monkeypatch.setattr(analysis_worker.shutil, "which", lambda _: DOCKER)
    seen: dict[str, Any] = {}
    # Each run's own argv, per thread: with two runs in flight, the newest entry of
    # the shared call lists can belong to the other run (WO-030's concurrent test).
    own = threading.local()
    fake_popen = executor.subprocess.Popen

    def popen(argv, **kwargs):
        own.argv = list(argv)
        return fake_popen(argv, **kwargs)

    monkeypatch.setattr(executor.subprocess, "Popen", popen)

    def set(analysis: bytes, render: bytes = PNG, hang: bool = False) -> None:
        def factory():
            # Like docker: the inputs are the directory this run's argv mounts.
            argv = own.argv
            directory = Path(mount_source(argv))
            if "/opt/worker/render.py" in argv:
                seen["chart"] = json.loads((directory / "chart.json").read_bytes())
                return FakeProcess(out=render)
            seen["sample"] = json.loads((directory / "sample.json").read_bytes())
            seen["code"] = (directory / "analysis.py").read_text()
            return FakeProcess(out=analysis, hang=hang)

        fake_docker["factory"] = factory

    fake_docker["set"] = set
    fake_docker["seen"] = seen
    yield fake_docker
    # No host fallback anywhere: every process is the docker client, and the code
    # never ran in this interpreter.
    calls = fake_docker["calls"]
    assert all(argv[0] == DOCKER for argv in calls.run + calls.popen)
    assert not hasattr(builtins, "WO027_RAN_ON_HOST")


def mount_source(argv: list[str]) -> str:
    """The host directory a docker argv mounts at /input (its `src=` part)."""
    mount = argv[argv.index("--mount") + 1]
    return dict(part.split("=", 1) for part in mount.split(",") if "=" in part)["src"]


def limits(monkeypatch, **changes: Any) -> None:
    """Lower the worker's limits (they can only go down) for one test."""

    def config(setting):
        return ExecutorConfig(image=IMAGE, docker=DOCKER, **changes), None

    monkeypatch.setattr(analysis_tool, "executor_config", config)


def session_call(**arguments: Any):
    """One tools/call over a real in-process MCP session; (payload, other blocks)."""

    async def go():
        async with Client(server.server) as client:
            return await client.call_tool("bounded_analysis", arguments)

    result = asyncio.run(go())
    blocks = list(result.content)
    assert isinstance(blocks[0], TextContent)
    return json.loads(blocks[0].text), blocks[1:]


def text_only(payload: dict[str, Any]) -> str:
    """What a client that shows no images keeps: the relayed message alone."""
    return payload["message"]


# --- one switch: defaults byte for byte, then everything together ---


def test_with_the_switch_unset_the_session_is_the_default():
    """No tool, the base instructions over a real session, the eight skills, and a
    routing prompt with no trace of the analysis tool or skill."""
    assert server.register_analysis_tool() is False

    async def go():
        async with Client(server.server) as client:
            return client.instructions, [
                t.name for t in (await client.list_tools()).tools
            ]

    instructions, tools = asyncio.run(go())
    assert instructions == server.BASE_INSTRUCTIONS
    assert sorted(tools) == DEFAULT_TOOLS
    assert runner.configured_skills() == SKILLS
    assert "bounded" not in runner.routing_prompt(runner.configured_skills())
    assert {t["function"]["name"] for t in runner.all_tool_schemas()} >= set(
        DEFAULT_TOOLS
    )
    assert "bounded_analysis" not in {
        t["function"]["name"] for t in runner.all_tool_schemas()
    }


def test_with_the_switch_on_tool_instructions_and_skill_arrive_together(switch_on):
    async def go():
        async with Client(server.server) as client:
            return client.instructions, [
                t.name for t in (await client.list_tools()).tools
            ]

    instructions, tools = asyncio.run(go())
    assert instructions == server.ANALYSIS_INSTRUCTIONS
    assert "bounded_analysis (a one-off analysis" in instructions
    assert sorted(tools) == sorted([*DEFAULT_TOOLS, "bounded_analysis"])
    assert runner.configured_skills() == [*SKILLS, "bounded-analysis"]
    prompt = runner.routing_prompt(runner.configured_skills())
    assert "## Skill: bounded-analysis" in prompt and instructions in prompt


def test_the_two_instruction_strings_differ_by_one_clause_only():
    """The "can't help" line and every other sentence are shared."""
    base, on = server.BASE_INSTRUCTIONS, server.ANALYSIS_INSTRUCTIONS
    clause = on.replace(base[: base.index(" The separate idx_alerts")], "", 1)
    assert on.startswith(base[: base.index("). The separate idx_alerts")])
    assert on.endswith(base[base.index(" The separate idx_alerts") :])
    assert "bounded_analysis" in clause and "I can't help with that" in base
    assert len(on) - len(base) < 220


# --- the request path: session -> tool -> reader -> worker -> checks -> content ---


def test_a_text_only_result_has_trusted_figures_caveats_and_no_image(reader, worker):
    worker["set"](worker_json())
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    message = payload["message"]
    assert f"${MEAN:,.2f}, verified (n=50)" in message
    assert "Chart:" not in message and BOUNDED in message
    assert BOUNDED in payload["warnings"]
    assert "Uses the 50 most recent of 80 eligible" in " ".join(payload["warnings"])
    # The worker got the code and numeric fields only, for exactly 50 sales.
    rows = worker["seen"]["sample"]
    assert len(rows) == 50 == payload["data"]["n"]
    assert set(rows[0]) == {
        "close_price",
        "list_price",
        "original_list_price",
        "living_area",
        "days_on_market",
    }
    assert worker["seen"]["code"] == CODE
    assert CODE not in json.dumps(payload) and str(PRICES[0]) not in json.dumps(payload)
    assert reader["fetch"] == 1 and reader["closed"]


def test_a_chart_comes_back_as_text_caption_plus_one_checked_png(reader, worker):
    worker["set"](worker_json(chart=SCATTER))
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True
    assert [type(b) for b in images] == [ImageContent]
    assert images[0].mime_type == "image/png"
    chart = payload["data"]["chart"]
    assert chart["status"] == "rendered" and chart["image_attached"] is True
    line = format_chart_line(chart["title"], chart["n_used"], chart["n_rows"])
    assert line in payload["message"] and line.endswith(CHART_IMAGE_FALLBACK)
    # The renderer got trusted chart data built on the host, never worker numbers.
    assert worker["seen"]["chart"]["kind"] == "scatter"


def test_a_client_that_shows_no_image_still_gets_the_whole_answer(reader, worker):
    """MCP has no client capability for showing images, and OpenClaw passes a tool's
    image to the model only, so the text must stand alone: the figures, the chart
    caption with its fallback sentence, and the caveats, with no promise of delivery."""
    worker["set"](worker_json(chart=SCATTER))
    payload, _ = session_call(city="Pasadena", code=CODE)
    text = text_only(payload)
    assert f"${MEAN:,.2f}, verified (n=50)" in text
    assert CHART_IMAGE_FALLBACK in text and "Caveats: " + BOUNDED in text
    assert not re.search(r"\b(attached|sent|delivered)\b", text, re.IGNORECASE)


def test_an_image_that_fails_the_last_check_is_not_attached_and_the_text_says_so(
    reader, worker, monkeypatch
):
    worker["set"](worker_json(chart=SCATTER))
    monkeypatch.setattr(analysis_tool, "check_png", lambda png: False)
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    assert CHART_NOT_ATTACHED_LINE in payload["message"]
    assert "returned as an image" not in payload["message"]
    assert payload["data"]["chart"]["image_attached"] is False
    assert BOUNDED in payload["message"]


def test_a_render_that_is_not_a_png_draws_no_chart(reader, worker):
    worker["set"](worker_json(chart=SCATTER), render=b"\x89PNG not really")
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    assert payload["data"]["chart"]["status"] == "invalid_png"
    assert "Chart: could not be drawn this time." in payload["message"]


@pytest.mark.parametrize(
    "stdout",
    [b"not json {", b'{"version": 1, "figures": [], "chart": null, "extra": 1}', b""],
)
def test_malformed_worker_output_is_refused_without_figures_or_image(
    reader, worker, stdout
):
    worker["set"](stdout)
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and images == []
    assert payload["error"]["category"] == "safety_refusal"
    assert payload["message"].startswith("The analysis output was refused")
    assert BOUNDED in payload["warnings"]


def test_a_run_past_the_deadline_is_stopped_and_removed(reader, worker, monkeypatch):
    limits(monkeypatch, wall_clock_s=0.3)
    worker["set"](worker_json(), hang=True)
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and images == []
    assert payload["error"]["category"] == "timeout"
    assert worker["process"].killed
    name = worker["calls"].popen[0][worker["calls"].popen[0].index("--name") + 1]
    assert [DOCKER, "rm", "-f", name] in worker["calls"].run
    assert BOUNDED in payload["warnings"]


def test_oversized_output_is_stopped_and_refused(reader, worker, monkeypatch):
    limits(monkeypatch, analysis_stdout_cap=100)
    worker["set"](b"x" * 101, hang=True)
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and images == []
    assert payload["error"]["category"] == "safety_refusal"
    assert payload["message"].startswith("The analysis printed more than allowed")
    assert worker["process"].killed


def test_no_docker_engine_is_unavailable_and_nothing_runs(reader, worker, monkeypatch):
    monkeypatch.setattr(analysis_worker.shutil, "which", lambda _: None)
    worker["set"](worker_json())
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and images == []
    assert payload["message"].startswith("Analysis is not available on this server")
    assert worker["calls"].run == [] and worker["calls"].popen == []
    assert BOUNDED in payload["warnings"]


def test_an_image_missing_from_the_engine_is_unavailable(reader, worker):
    worker["available"] = False
    worker["set"](worker_json())
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["message"].startswith("Analysis is not available on this server")
    assert images == [] and worker["calls"].popen == []
    # Only lookups (the image check, the leftover sweep): no container was run.
    assert not any("run" in argv[1:2] for argv in worker["calls"].run)
    assert ["image", "inspect"] in [argv[1:3] for argv in worker["calls"].run]


@pytest.mark.parametrize("image", [None, "idx-analysis-worker:latest"])
def test_no_pinned_image_never_reads_or_runs(reader, worker, monkeypatch, image):
    if image is None:
        monkeypatch.delenv("IDX_ANALYSIS_IMAGE", raising=False)
    else:
        monkeypatch.setenv("IDX_ANALYSIS_IMAGE", image)
    worker["set"](worker_json())
    payload, images = session_call(city="Pasadena", code=CODE)
    assert payload["message"].startswith("Analysis is not available on this server")
    assert images == [] and reader["fetch"] == 0
    assert worker["calls"].run == [] and worker["calls"].popen == []
    assert payload["warnings"] == [BOUNDED]


# --- the eval runner follows the same switch ---


def _opt_in_case() -> runner.Case:
    cases, errors = runner.load_cases(runner.ROOT / "evals" / "cases")
    assert errors == []
    return next(c for c in cases if c.id == "routing-local-041")


def test_the_opt_in_routing_case_is_skipped_and_costs_nothing_while_off():
    case = _opt_in_case()

    def never(*args, **kwargs):
        raise AssertionError("the model was asked with the switch off")

    result, detail = runner.run_route(case, runner.RunContext(route=never))
    assert result == runner.SKIPPED and "IDX_ANALYSIS_TOOL" in detail
    assert runner.paid_ceiling([case]) == (0, 0)


def test_the_opt_in_routing_case_runs_with_the_switch_on(analysis_switch_in_dotenv):
    case = _opt_in_case()
    seen = {}

    def route(text, history=(), trace=None):
        seen["tools"] = {t["function"]["name"] for t in runner.all_tool_schemas()}
        return [
            runner.ToolCall(name="bounded_analysis", arguments={"city": "Pasadena"})
        ]

    try:
        result, _ = runner.run_route(case, runner.RunContext(route=route))
    finally:
        server.reset_analysis_tool_for_tests()
    assert result == runner.PASS and "bounded_analysis" in seen["tools"]
    assert runner.paid_ceiling([case]) == (runner.ROUTE_MAX_CALLS, 0)


# --- the fixture database (CI): the real reader under the same path ---


@pytest.mark.db
def test_the_fixture_reader_feeds_at_most_50_numeric_rows_through_the_session(
    switch_on, worker
):
    """Real reader over the synthetic fixture (San Gabriel group), fake docker
    client: the worker gets at most 50 numeric rows and the reply its caveats."""
    if not os.environ.get("MYSQL_HOST"):
        pytest.skip("needs the fixture database")
    service.reset_sweep_for_tests()
    server.db_asof.clear_asof_cache()
    worker["set"](worker_json(value=1.0))
    try:
        payload, _ = session_call(city="San Gabriel", code=CODE)
    finally:
        server.db_asof.clear_asof_cache()
    assert payload["ok"] is True, payload
    rows = worker["seen"]["sample"]
    assert 0 < len(rows) <= 50 and len(rows) == payload["data"]["n"]
    assert all(set(row) <= set(rows[0]) for row in rows)
    assert "listing_key" not in rows[0] and "address" not in rows[0]
    assert BOUNDED in payload["message"]
