"""WO-017 step 6 end to end: fixture database, real worker image, no mocks.

Marked `db` and `container`: it runs where both the synthetic fixture (San Gabriel
group) and the pinned image are configured, as in CI's db step. Without the image it
skips, unless IDX_REQUIRE_CONTAINER=1, when it fails instead.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from typing import Any

import pytest
from mcp.types import ImageContent, TextContent

from idx_agent.analysis import executor, service
from idx_agent.analysis.mcp_result import analysis_content
from idx_agent.analysis.png import check_png, png_size
from idx_agent.analysis.service import run_bounded_analysis
from idx_agent.db import asof as db_asof
from idx_agent.db.pool import DbConfig, connect
from idx_agent.domain.analysis_worker import ExecutorConfig
from idx_agent.domain.models import MarketStatsRequest

pytestmark = [pytest.mark.db, pytest.mark.container]

# Model-style code: plain Python over `rows`, reporting four checkable figures and a
# binned-median chart request. Only the standard library is used.
CODE = """
import statistics

prices = [r["close_price"] for r in rows]
dom = [r["days_on_market"] for r in rows if r["days_on_market"] is not None]
pairs = [(r["living_area"], r["close_price"]) for r in rows
         if r["living_area"] is not None]
result = {
    "version": 1,
    "figures": [
        {"label": "sales", "kind": "count", "x": "close_price", "y": None,
         "value": float(len(prices))},
        {"label": "mean_price", "kind": "mean", "x": "close_price", "y": None,
         "value": statistics.fmean(prices)},
        {"label": "median_dom", "kind": "median", "x": "days_on_market", "y": None,
         "value": float(statistics.median(dom))},
        {"label": "area_price_r", "kind": "pearson", "x": "living_area",
         "y": "close_price",
         "value": statistics.correlation([a for a, _ in pairs],
                                         [p for _, p in pairs])},
    ],
    "chart": {"kind": "binned_median", "x": "living_area", "y": "close_price",
              "bins": [1200, 1400, 1600, 1800, 2000]},
}
"""


@pytest.fixture(scope="module")
def worker() -> ExecutorConfig:
    required = os.environ.get("IDX_REQUIRE_CONTAINER") == "1"
    reason = None
    config = None
    try:
        config = ExecutorConfig.from_env(os.environ)
    except ValueError:
        reason = "IDX_ANALYSIS_IMAGE is not pinned by digest"
    if config is None and reason is None:
        reason = "IDX_ANALYSIS_IMAGE is unset"
    elif config is not None and not executor.available(config):
        reason = "the pinned analysis image or the docker engine is unavailable"
    if reason is not None:
        if required:
            pytest.fail(f"IDX_REQUIRE_CONTAINER=1 but {reason}")
        pytest.skip(reason)
    return config


@pytest.fixture(scope="module")
def conn() -> Iterator[Any]:
    db_asof.clear_asof_cache()
    connection = connect(DbConfig.from_env())
    try:
        yield connection
    finally:
        connection.close()
        db_asof.clear_asof_cache()


def _leftovers(config: ExecutorConfig) -> str:
    done = subprocess.run(
        [config.docker, "ps", "-a", "-q", "--filter", "name=idx-analysis-"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return done.stdout.strip()


def test_san_gabriel_end_to_end_gives_verified_figures_and_a_valid_png(worker, conn):
    service.reset_sweep_for_tests()
    log: dict[str, Any] = {}
    outcome = run_bounded_analysis(
        MarketStatsRequest(city="San Gabriel"), CODE, conn, worker, log_fields=log
    )
    assert outcome.status == "ok", log
    assert outcome.n == 50 and outcome.eligible == 60
    assert [check.status for check in outcome.checks] == ["verified"] * 4
    assert outcome.checks[0].trusted == 50.0
    assert outcome.chart_status == "rendered"
    assert check_png(outcome.png) and png_size(outcome.png) == (960, 600)
    assert outcome.chart is not None and outcome.chart.n_used == 48  # 2 lack area
    assert _leftovers(worker) == ""

    blocks = analysis_content(outcome)
    assert [type(block) for block in blocks] == [TextContent, ImageContent]
    payload = json.loads(blocks[0].text)
    assert payload["ok"] is True
    assert payload["data"]["city"] == "San Gabriel"
    assert payload["data"]["window_end"] == "2026-09-17"
    assert "50 most recent of 60 eligible" in " ".join(payload["warnings"])
    assert payload["message"].endswith("\nCaveats: " + " ".join(payload["warnings"]))
    assert "statistics" not in blocks[0].text and "mean_price" not in blocks[0].text
    assert log["figure_statuses"] == {"verified": 4}
