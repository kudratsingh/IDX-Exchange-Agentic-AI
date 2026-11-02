"""WO-017 Phase C: the `bounded_analysis` MCP tool, off by default.

Calls go through the real MCP layer (`server.call_tool`); only the sample reader and the
container are replaced, with the service tests' fakes. The real worker image runs in
tests/test_analysis_service_e2e.py and the container-marked case at the end."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest
from mcp.types import ImageContent, TextContent
from tests.test_analysis_service import (
    CODE,
    PNG,
    SAMPLE,
    TRUSTED_MEAN,
    WORKER_NUMBER,
    FakeExecutor,
    _mean,
    _ok,
    _output,
)

from idx_agent.analysis import executor, service
from idx_agent.analysis import tool as analysis_tool
from idx_agent.analysis.png import check_png
from idx_agent.db import analysis as db_analysis
from idx_agent.domain.analysis_worker import AnalysisRun, RenderRun
from idx_agent.domain.asof import AsOfDates
from idx_agent.mcp_server import server

IMAGE = "sha256:" + "a" * 64
CHART = {
    "kind": "binned_median",
    "x": "living_area",
    "y": "close_price",
    "bins": (900.0, 1300.0, 1700.0),
}


class FakeConn:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def registered(monkeypatch):
    """The tool registered as the server does at start with the switch on."""
    monkeypatch.setenv(analysis_tool.TOOL_SETTING, "1")
    monkeypatch.setenv("IDX_ANALYSIS_IMAGE", IMAGE)
    assert server.register_analysis_tool() is True
    yield
    server.server.remove_tool(analysis_tool.TOOL_NAME)


@pytest.fixture
def world(monkeypatch, registered):
    """A configured database whose sample read returns the invented SAMPLE."""
    calls = {"connect": 0, "fetch": [], "conn": None}

    def connect(config=None):
        calls["connect"] += 1
        calls["conn"] = FakeConn()
        return calls["conn"]

    def fetch(request, window, as_of, conn):
        calls["fetch"].append(request)
        return SAMPLE

    monkeypatch.setattr(server.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(server.db_pool, "connect", connect)
    monkeypatch.setattr(db_analysis, "fetch_analysis_sample", fetch)
    monkeypatch.setattr(
        service.db_asof,
        "get_asof_dates",
        lambda conn: AsOfDates(sold=SAMPLE.as_of.sold, active=SAMPLE.as_of.active),
    )
    service.reset_sweep_for_tests()
    return calls


def call(**arguments: Any):
    result = asyncio.run(server.server.call_tool("bounded_analysis", arguments))
    blocks = list(result.content)
    assert isinstance(blocks[0], TextContent)
    return json.loads(blocks[0].text), blocks[1:]


# --- discovery: off by default, typed when on ---


def test_off_by_default_the_tool_list_is_unchanged(monkeypatch):
    monkeypatch.delenv(analysis_tool.TOOL_SETTING, raising=False)
    for value in (None, "", "0", "true", "yes", " 1", "1\n"):
        if value is not None:
            monkeypatch.setenv(analysis_tool.TOOL_SETTING, value)
        assert server.register_analysis_tool() is False
        assert analysis_tool.TOOL_NAME not in server.tool_names()


def test_registered_tool_takes_only_place_arguments_and_code(registered):
    tools = {t.name: t for t in asyncio.run(server.server.list_tools())}
    tool = tools["bounded_analysis"]
    assert set(tool.input_schema["properties"]) == {
        "city",
        "postal_code",
        "property_subtype",
        "months",
        "code",
    }
    assert "rows" in tool.description and "isolated worker" in tool.description
    assert server.register_analysis_tool() is True  # idempotent
    assert server.tool_names().count("bounded_analysis") == 1


# --- argument validation: before any database read ---


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"city": "Atlantis"}, "unknown_city"),
        ({"city": "Pasadena", "postal_code": "91101"}, None),
        ({}, "missing_location"),
        ({"city": "Pasadena", "months": 30}, None),
    ],
)
def test_bad_place_arguments_ask_and_read_nothing(world, arguments, reason):
    payload, images = call(code=CODE, **arguments)
    assert payload["ok"] is True and images == []
    assert payload["data"]["question"]
    if reason:
        assert payload["data"]["reason"] == reason
    assert world["connect"] == 0


@pytest.mark.parametrize(
    "code", [None, "", "   ", "x" * 20_001, "a\x00b", "result = 1\n# \ud800"]
)
def test_refused_code_never_reaches_the_database_or_the_worker(world, code):
    arguments = {"city": "Pasadena"}
    if code is not None:
        arguments["code"] = code
    payload, images = call(**arguments)
    assert payload["ok"] is False and payload["error"]["category"] == "validation"
    assert images == [] and world["connect"] == 0


# --- trusted numeric results and the chart ---


def test_trusted_figures_and_a_checked_png_come_back(world, monkeypatch):
    fake = FakeExecutor(
        _ok(_output(_mean(WORKER_NUMBER, "mean_price"), chart=CHART))
    ).install(monkeypatch)
    payload, images = call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and payload["provenance"]["tool"] == "bounded_analysis"
    message = payload["message"]
    assert "the worker's number did not match" in message
    assert f"${TRUSTED_MEAN:,.2f}" in message and f"{WORKER_NUMBER:,.2f}" not in message
    assert "Chart: attached." in message and "Caveats:" in message
    assert CODE not in json.dumps(payload)
    assert [type(b) for b in images] == [ImageContent]
    assert images[0].mime_type == "image/png"
    assert fake.analysis_calls == [CODE] and len(fake.render_calls) == 1
    assert world["conn"].closed


def test_a_bad_png_is_never_attached(world, monkeypatch):
    bad = RenderRun(status="ok", png=PNG[:-8], width=960, height=600, duration_s=0.1)
    FakeExecutor(_ok(_output(_mean(1.0), chart=CHART)), render=bad).install(monkeypatch)
    payload, images = call(city="Pasadena", code=CODE)
    assert payload["ok"] is True and images == []
    assert "Chart: could not be drawn this time." in payload["message"]


def test_content_blocks_attach_images_only_to_ok_results():
    assert check_png(PNG)
    assert len(analysis_tool.content_blocks({"ok": True}, PNG)) == 2
    assert len(analysis_tool.content_blocks({"ok": False}, PNG)) == 1
    assert len(analysis_tool.content_blocks({"ok": True}, b"\x89PNG junk")) == 1


# --- unavailable worker and failures: no host fallback ---


@pytest.mark.parametrize("image", [None, "worker:latest"])
def test_no_pinned_image_is_unavailable_and_nothing_runs(world, monkeypatch, image):
    if image is None:
        monkeypatch.delenv("IDX_ANALYSIS_IMAGE", raising=False)
    else:
        monkeypatch.setenv("IDX_ANALYSIS_IMAGE", image)

    def never(*args, **kwargs):
        raise AssertionError("analysis code ran without a pinned image")

    monkeypatch.setattr(executor, "run_analysis", never)
    payload, images = call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and images == []
    assert payload["error"]["category"] == "internal"
    assert payload["message"].startswith("Analysis is not available on this server")
    assert world["connect"] == 0 and world["fetch"] == []  # no database read


@pytest.mark.parametrize(
    ("status", "category"),
    [
        ("unavailable", "internal"),
        ("busy", "rate_limit"),
        ("timeout", "timeout"),
        ("output_too_large", "safety_refusal"),
        ("failed", "internal"),
        ("invalid_output", "safety_refusal"),
    ],
)
def test_worker_failures_map_to_fixed_errors_without_images(
    world, monkeypatch, status, category
):
    FakeExecutor(AnalysisRun(status=status, duration_s=0.1)).install(monkeypatch)
    payload, images = call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and images == []
    assert payload["error"]["category"] == category
    assert CODE not in json.dumps(payload)


def test_database_failures_are_db_errors(world, monkeypatch):
    def broken(config=None):
        raise OSError("database down")

    monkeypatch.setattr(server.db_pool, "connect", broken)
    payload, _ = call(city="Pasadena", code=CODE)
    assert payload["ok"] is False and payload["error"]["category"] == "db"
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    payload, _ = call(city="Pasadena", code=CODE)
    assert payload["error"]["category"] == "db"


def test_a_slow_sample_read_is_a_timeout(world, monkeypatch):
    def slow(request, window, as_of, conn):
        raise db_analysis.AnalysisDeadlineExceeded()

    monkeypatch.setattr(db_analysis, "fetch_analysis_sample", slow)
    payload, _ = call(city="Pasadena", code=CODE)
    assert payload["error"]["category"] == "timeout"
    assert world["conn"].closed


# --- the real worker through the tool (CI: fixture database plus pinned image) ---


@pytest.mark.db
@pytest.mark.container
def test_the_registered_tool_runs_the_real_worker_end_to_end(monkeypatch):
    from tests.test_analysis_service_e2e import CODE as E2E_CODE

    from idx_agent.domain.analysis_worker import ExecutorConfig

    required = os.environ.get("IDX_REQUIRE_CONTAINER") == "1"
    try:
        config = ExecutorConfig.from_env(os.environ)
    except ValueError:
        config = None
    if (
        config is None
        or not executor.available(config)
        or not os.environ.get("MYSQL_HOST")
    ):
        if required:
            pytest.fail("IDX_REQUIRE_CONTAINER=1 but the image or database is missing")
        pytest.skip("needs the fixture database and the pinned worker image")
    monkeypatch.setenv(analysis_tool.TOOL_SETTING, "1")
    service.reset_sweep_for_tests()
    server.db_asof.clear_asof_cache()
    assert server.register_analysis_tool()
    try:
        payload, images = call(city="San Gabriel", code=E2E_CODE)
    finally:
        server.server.remove_tool(analysis_tool.TOOL_NAME)
        server.db_asof.clear_asof_cache()
    assert payload["ok"] is True, payload
    assert payload["data"]["n"] == 50
    assert [type(b) for b in images] == [ImageContent]
    import base64

    assert check_png(base64.b64decode(images[0].data))


# --- routing: the skill, checked with the routing contract's own rules ---


def test_the_skill_passes_the_routing_rules_alongside_the_configured_skills():
    """Not yet in the idx agent's skill list (activation is the owner's step), so the
    contract tests skip it; run their checks over the configured skills plus it."""
    from evals import run as runner
    from tests import test_routing_contract as contract

    names = [*runner.configured_skills(), "bounded-analysis"]
    assert "bounded-analysis" not in runner.configured_skills()
    skills = contract.load_skills(contract.SKILLS_DIR, names)
    assert skills["bounded-analysis"].triggers
    assert contract.overlap_problems(skills, contract.OVERLAP_ALLOWLIST) == []
    assert contract.not_for_problems(skills) == []
    assert contract.show_more_problems(skills) == []
    assert contract.email_and_data_problems(skills) == []
    one = contract.one_tool_problems(
        {"bounded-analysis": skills["bounded-analysis"]},
        {"bounded-analysis": "bounded_analysis"},
    )
    assert one == []
