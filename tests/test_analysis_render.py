"""WO-017 step 5: the fixed renderer against a real Docker engine and the pinned image.

No mocks; skips without IDX_ANALYSIS_IMAGE, fails under IDX_REQUIRE_CONTAINER=1.
Set IDX_RENDER_SAMPLES_DIR to keep one PNG per chart kind for a person to look at.
"""

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from idx_agent.analysis import executor
from idx_agent.analysis.chart import build_chart
from idx_agent.analysis.executor import render_chart, run_worker
from idx_agent.analysis.png import check_png, png_size
from idx_agent.domain.analysis import make_analysis_sample
from idx_agent.domain.analysis_worker import ExecutorConfig
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow

pytestmark = pytest.mark.container


def _sample():
    dates = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
    scope = MarketStatsRequest(city="Pasadena", property_subtype="Condominium")
    window = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
    rows = [
        SoldComp(
            listing_key=key,
            address=f"{key} Invented Way",
            city="Pasadena",
            postal_code="91101",
            close_date=date(2026, 9, 1),
            close_price=550_000 + 17_000 * ((key * 7) % 23) + 9_000 * key,
            list_price=560_000 + 15_000 * ((key * 5) % 19) + 9_000 * key,
            original_list_price=None if key % 4 else 600_000 + 12_000 * key,
            living_area=750 + 41 * ((key * 11) % 29),
            days_on_market=(key * 13) % 70,
            property_subtype="Condominium",
        )
        for key in range(1, 41)
    ]
    return make_analysis_sample(rows, scope, window, dates)


SAMPLE = _sample()
CHARTS = {
    "scatter": build_chart(SAMPLE, "scatter", "living_area", "close_price"),
    # The 700-760 bin holds one sale, so its median is suppressed.
    "binned_median": build_chart(
        SAMPLE,
        "binned_median",
        "living_area",
        "price_per_sqft",
        [700, 760, 900, 1100, 1300, 1500, 1800, 2000],
    ),
    "histogram": build_chart(
        SAMPLE,
        "histogram",
        "close_price",
        None,
        [500_000 + 100_000 * step for step in range(8)],
    ),
}


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


def _leftovers(config: ExecutorConfig) -> str:
    done = subprocess.run(
        [config.docker, "ps", "-a", "-q", "--filter", "name=idx-analysis-"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def no_container_left(worker):
    assert _leftovers(worker) == ""
    yield
    assert _leftovers(worker) == ""


def test_the_sample_charts_cover_the_cases():
    assert CHARTS["binned_median"].bars[0].suppressed
    assert not any(bar.suppressed for bar in CHARTS["binned_median"].bars[1:])
    assert CHARTS["histogram"].outside > 0
    assert len(CHARTS["scatter"].points) == 40


@pytest.mark.parametrize("kind", sorted(CHARTS))
def test_each_kind_renders_a_checked_deterministic_png(worker, kind):
    first = render_chart(worker, CHARTS[kind])
    second = render_chart(worker, CHARTS[kind])
    assert first.status == "ok" and second.status == "ok"
    assert (first.width, first.height) == (960, 600)
    assert check_png(first.png) and png_size(first.png) == (960, 600)
    assert first.png == second.png
    assert b"tEXt" not in first.png and b"tIME" not in first.png
    assert first.duration_s < 15
    keep = os.environ.get("IDX_RENDER_SAMPLES_DIR")
    if keep:
        Path(keep, f"{kind}.png").write_bytes(first.png)


def test_different_data_gives_a_different_image(worker):
    other = build_chart(SAMPLE, "scatter", "days_on_market", "close_price")
    one = render_chart(worker, CHARTS["scatter"])
    two = render_chart(worker, other)
    assert one.status == two.status == "ok"
    assert one.png != two.png


def test_empty_and_fully_suppressed_charts_still_render(worker):
    sparse = build_chart(
        SAMPLE, "binned_median", "living_area", "close_price", [700, 720, 740, 760]
    )
    assert all(bar.suppressed for bar in sparse.bars)
    empty = build_chart(SAMPLE, "histogram", "days_on_market", None, [1000, 2000])
    assert empty.n_used == 0
    for chart in (sparse, empty):
        run = render_chart(worker, chart)
        assert run.status == "ok" and check_png(run.png)


@pytest.mark.parametrize(
    "payload",
    [b"", b"{}", b"[1, 2]", b'{"kind": "pie"}', b"\xff\xfe", b"x" * 5000],
)
def test_bad_chart_input_fails_with_the_fixed_exit(worker, payload):
    run = run_worker(worker, "render.py", {"chart.json": payload})
    assert (run.status, run.exit_code, run.stdout) == ("failed", 3, None)


def test_render_timeout_still_cleans_up(worker):
    fast = worker.model_copy(update={"wall_clock_s": 0.2})
    run = render_chart(fast, CHARTS["scatter"])
    assert (run.status, run.png) == ("timeout", None)
    assert run.duration_s < 0.2 + 12


def test_render_output_cap_still_cleans_up(worker):
    small = worker.model_copy(update={"render_stdout_cap": 2048})
    run = render_chart(small, CHARTS["histogram"])
    assert (run.status, run.png) == ("output_too_large", None)
