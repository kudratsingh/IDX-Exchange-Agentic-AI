"""WO-017 step 5: the fixed renderer against a real Docker engine and the pinned image.

No mocks; skips without IDX_ANALYSIS_IMAGE, fails under IDX_REQUIRE_CONTAINER=1.
Set IDX_RENDER_SAMPLES_DIR to keep one PNG per chart kind for a person to look at.
"""

import hashlib
import importlib.util
import os
import subprocess
import zlib
from datetime import date
from pathlib import Path

import pytest

from idx_agent.analysis import executor
from idx_agent.analysis.chart import build_chart
from idx_agent.analysis.executor import render_chart, run_worker
from idx_agent.analysis.png import check_png, png_size
from idx_agent.domain.analysis import make_analysis_sample
from idx_agent.domain.analysis_chart import ChartData
from idx_agent.domain.analysis_worker import ExecutorConfig
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow

pytestmark = pytest.mark.container
RENDER = (
    Path(__file__).resolve().parents[1] / "docker" / "analysis-worker" / "render.py"
)


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


# sha256 of each fixed chart's PNG from the pinned image. The renderer and its
# pinned wheels are deterministic across builds, so any change here is a change to
# what is drawn: update these on purpose, after looking at the new images.
PINNED = {
    "scatter": "8c2e7d7eb529f618f2c212ab582dc72e2238ee9d69f186e5482173e080e59ed6",
    "binned_median": "d50ae2c43392677e47f07f3d153011d858129b50f7925ddf8b6b66bbb22b0439",
    "histogram": "0fbc764e9b228848f9eef37148c0263bf145cf6f482c452661089adf9336eb36",
}


@pytest.mark.parametrize("kind", sorted(CHARTS))
def test_each_fixed_chart_draws_exactly_the_pinned_image(worker, kind):
    run = render_chart(worker, CHARTS[kind])
    assert run.status == "ok"
    assert hashlib.sha256(run.png).hexdigest() == PINNED[kind]


def _pixels(data: bytes) -> list[bytes]:
    """RGBA rows of a checked 8-bit RGBA PNG (test-only decoder, stdlib)."""
    width, height = png_size(data)
    offset, stream = 8, b""
    while offset < len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        if data[offset + 4 : offset + 8] == b"IDAT":
            stream += data[offset + 8 : offset + 8 + length]
        offset += 12 + length
    raw = zlib.decompress(stream)
    stride, rows, prior = width * 4, [], bytearray(width * 4)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b = prior[i]
            c = prior[i - 4] if i >= 4 else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                line[i] = (line[i] + pred) & 0xFF
        rows.append(bytes(line))
        prior = line
    return rows


def _count(rows, xs: range, ys: range, test) -> int:
    return sum(
        1
        for y in ys
        for x in xs
        if test(rows[y][4 * x], rows[y][4 * x + 1], rows[y][4 * x + 2])
    )


def _hatch(r: int, g: int, b: int) -> bool:
    return r == g == b and 0x70 <= r <= 0xB8


def _ink(r: int, g: int, b: int) -> bool:
    return max(r, g, b) < 0xA0


def _plot_rows(chart: ChartData) -> range:
    spec = importlib.util.spec_from_file_location("idx_worker_render", RENDER)
    render = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render)
    edges = [chart.bars[0].lower] + [bar.upper for bar in chart.bars]
    _labels, tilt = render._edge_labels(edges, chart.x_unit)
    bottom = 600 - (78 + 17 * len(chart.caption) + tilt)
    return range(62 + 4, bottom - 4)


def _bin_columns(chart: ChartData, lower: float, upper: float) -> range:
    first, last = chart.bars[0].lower, chart.bars[-1].upper
    left, axis = 0.155 * 960, (0.94 - 0.155) * 960
    x0 = left + axis * (lower - first) / (last - first)
    x1 = left + axis * (upper - first) / (last - first)
    return range(round(x0) + 4, round(x1) - 4)


def test_the_suppressed_bin_shows_a_hatched_placeholder(worker):
    chart = CHARTS["binned_median"]
    rows = _pixels(render_chart(worker, chart).png)
    plot = _plot_rows(chart)
    top_quarter = range(plot.start, plot.start + len(plot) // 4)  # above the note
    low_quarter = range(plot.stop - len(plot) // 4, plot.stop)  # below it
    hidden = _bin_columns(chart, chart.bars[0].lower, chart.bars[0].upper)
    shown = _bin_columns(chart, chart.bars[1].lower, chart.bars[1].upper)
    assert _count(rows, hidden, top_quarter, _hatch) > 40
    assert _count(rows, hidden, low_quarter, _hatch) > 40
    assert _count(rows, shown, low_quarter, _hatch) == 0  # a drawn bar is solid
    middle = range(plot.start + len(plot) // 3, plot.stop - len(plot) // 3)
    assert _count(rows, hidden, middle, _ink) > 40  # the "suppressed (n=1)" note


def test_a_fully_suppressed_chart_is_hatched_across_the_axis(worker):
    sparse = build_chart(
        SAMPLE, "binned_median", "living_area", "close_price", [700, 720, 740, 760]
    )
    rows = _pixels(render_chart(worker, sparse).png)
    plot = _plot_rows(sparse)
    for bar in sparse.bars:
        assert _count(rows, _bin_columns(sparse, bar.lower, bar.upper), plot, _hatch)


@pytest.mark.parametrize("kind", sorted(CHARTS))
def test_every_caption_line_is_drawn_under_the_plot(worker, kind):
    chart = CHARTS[kind]
    rows = _pixels(render_chart(worker, chart).png)
    for index in range(len(chart.caption)):
        base = 600 - 12 - 17 * (len(chart.caption) - 1 - index)
        assert _count(rows, range(10, 600), range(base - 13, base), _ink) > 30, index


@pytest.mark.parametrize(
    "title", ["Bad $\\frac{$ x", "Price $\\sqrt{x}$ check", "Cost $1 to $2"]
)
def test_dollar_signs_are_plain_text_not_markup(worker, title):
    plain = render_chart(worker, CHARTS["scatter"])
    chart = ChartData(**{**CHARTS["scatter"].model_dump(), "title": title})
    run = render_chart(worker, chart)
    assert run.status == "ok" and check_png(run.png) and run.png != plain.png


@pytest.mark.parametrize(
    ("x", "y", "bins", "digest"),
    [
        # Edges 2.5 and 7.5 read as written; two suppressed bins, two notes.
        (
            "days_on_market",
            "close_price",
            [0, 2.5, 7.5, 10, 30, 70],
            "1ec9342fe69390b057e6491371c89e2ccf0c59bbd7cc91424d9b3f22882c92bb",
        ),
        # Four narrow suppressed bins: thinned edge labels and one merged note.
        (
            "living_area",
            "close_price",
            [700, 1000, 1010, 1020, 1030, 1040, 1300, 1600, 2000],
            "7fb7b372c05780d63940fda6af2bc2090b8f07afcb9b74b26857a9fc94b249d4",
        ),
    ],
)
def test_fractional_and_narrow_bins_draw_the_pinned_image(worker, x, y, bins, digest):
    run = render_chart(worker, build_chart(SAMPLE, "binned_median", x, y, bins))
    assert run.status == "ok" and check_png(run.png)
    keep = os.environ.get("IDX_RENDER_SAMPLES_DIR")
    if keep:
        Path(keep, f"binned_{x}.png").write_bytes(run.png)
    assert hashlib.sha256(run.png).hexdigest() == digest
    keep = os.environ.get("IDX_RENDER_SAMPLES_DIR")
    if keep:
        Path(keep, f"binned_{x}_{len(bins)}.png").write_bytes(run.png)
