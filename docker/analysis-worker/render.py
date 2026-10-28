"""Fixed chart renderer for the WO-017 worker image (ADR-0013).

Trusted and fixed: it ships in the image and is never written by a model, and no
model code is present in a render run. It reads `/input/chart.json`, the chart data
that host code built and validated from the trusted sample, draws it with
matplotlib's Agg backend in one fixed style and writes exactly one PNG to stdout.
On any failure it writes a fixed line to stderr, without a traceback or any input,
and exits with code 3.

The same chart data always gives the same bytes: fixed size, fonts, colours and
rcParams, and no software or time stamp in the PNG. Only the standard library and
matplotlib are used here; the host package is not in the image.
"""

import io
import json
import math
import os
import shutil
import sys

INPUT_DIR = "/input"
CHART_PATH = "/input/chart.json"
FONT_CACHE = "/opt/mpl-cache"  # built into the image, read-only
FAILED = 3

WIDTH_IN, HEIGHT_IN, DPI = 8.0, 5.0, 120  # 960 x 600 pixels
KINDS = ("scatter", "binned_median", "histogram")

# Okabe-Ito blue for data (5.1:1 on white), near-black text, light neutral grid.
INK = "#1F1F1F"
MUTED = "#4D4D4D"
DATA = "#0072B2"
GRID = "#DDDDDD"
HATCH = "#8C8C8C"
PAPER = "#FFFFFF"

TITLE_PT = 13
LABEL_PT = 10
TICK_PT = 9
NOTE_PT = 8
CAPTION_PT = 8
CAPTION_LINE_PX = 17
LEFT, RIGHT = 0.155, 0.94  # axes edges as fractions of the width


def _fail() -> None:
    try:
        os.write(2, b"render run failed\n")
    finally:
        os._exit(FAILED)


def _seed_font_cache() -> None:
    """Copy the prebuilt font list into the tmpfs so matplotlib does not rebuild it."""
    target = os.environ.get("MPLCONFIGDIR")
    if target and os.path.isdir(FONT_CACHE):
        try:
            shutil.copytree(FONT_CACHE, target, dirs_exist_ok=True)
        except OSError:
            pass


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _text(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 120:
        raise ValueError
    return value


def _load() -> dict:
    """Read the chart data and check the shape this renderer relies on."""
    if os.listdir(INPUT_DIR) != ["chart.json"]:
        raise ValueError  # a render run never carries code or a sample
    with open(CHART_PATH, encoding="utf-8") as handle:
        chart = json.load(handle)
    if not isinstance(chart, dict) or chart.get("kind") not in KINDS:
        raise ValueError
    for key in ("title", "x_label", "x_unit"):
        _text(chart.get(key))
    if chart["kind"] != "histogram":
        _text(chart.get("y_label"))
        _text(chart.get("y_unit"))
    caption = chart.get("caption")
    if not isinstance(caption, list) or not 1 <= len(caption) <= 8:
        raise ValueError
    for line in caption:
        _text(line)
    points = chart.get("points")
    bars = chart.get("bars")
    if not isinstance(points, list) or not isinstance(bars, list):
        raise ValueError
    if len(points) > 50 or len(bars) > 12:
        raise ValueError
    chart["points"] = [
        (_number(p[0]), _number(p[1]))
        for p in points
        if isinstance(p, list) and len(p) == 2
    ]
    if len(chart["points"]) != len(points):
        raise ValueError
    clean = []
    for bar in bars:
        if not isinstance(bar, dict):
            raise ValueError
        lower, upper = _number(bar.get("lower")), _number(bar.get("upper"))
        n = bar.get("n")
        if not lower < upper or not isinstance(n, int) or isinstance(n, bool):
            raise ValueError
        suppressed = bar.get("suppressed") is True
        value = None if bar.get("value") is None else _number(bar["value"])
        if suppressed != (value is None):
            raise ValueError
        clean.append((lower, upper, n, value))
    chart["bars"] = clean
    if chart["kind"] == "scatter" and clean:
        raise ValueError
    if chart["kind"] != "scatter" and (points or not clean):
        raise ValueError
    return chart


def _formatter(unit: str):
    """Tick text for one display unit: thousands separators, currency or percent."""
    if unit in ("USD", "USD per sqft"):
        return lambda v, _pos: f"-${-v:,.0f}" if v < 0 else f"${v:,.0f}"
    if unit == "percent":
        return lambda v, _pos: f"{v:,.1f}%"
    if unit == "ratio":
        return lambda v, _pos: f"{v:,.2f}"
    return lambda v, _pos: f"{v:,.0f}"


def _edges(chart: dict) -> list[float]:
    bars = chart["bars"]
    return [bars[0][0]] + [b[1] for b in bars] if bars else []


def _rotate_edges(chart: dict) -> int:
    """Extra bottom pixels when the bin-edge labels must tilt to stay apart, else 0."""
    edges = _edges(chart)
    if not edges:
        return 0
    text = _formatter(chart["x_unit"])
    widest_px = 9.5 * max(len(text(edge, None)) for edge in edges)
    axis_px = WIDTH_IN * DPI * (RIGHT - LEFT)
    span = edges[-1] - edges[0]
    narrowest = min(b - a for a, b in zip(edges, edges[1:], strict=False))
    if widest_px <= 0.85 * axis_px * narrowest / span:
        return 0
    return round(0.64 * widest_px)  # height gained by a label tilted 40 degrees


def _axis_label(label: str, unit: str) -> str:
    return f"{label} ({unit})"


def _style(matplotlib) -> None:
    matplotlib.rcdefaults()
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans"],
            "font.size": TICK_PT,
            "text.color": INK,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK,
            "axes.linewidth": 0.8,
            "axes.facecolor": PAPER,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.axisbelow": True,
            "axes.unicode_minus": False,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelsize": TICK_PT,
            "ytick.labelsize": TICK_PT,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "hatch.color": HATCH,
            "hatch.linewidth": 0.8,
            "figure.facecolor": PAPER,
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "savefig.facecolor": PAPER,
            "path.simplify": False,
            "agg.path.chunksize": 0,
        }
    )


def _draw(chart: dict) -> bytes:
    import matplotlib

    matplotlib.use("Agg", force=True)
    _style(matplotlib)
    from matplotlib.figure import Figure
    from matplotlib.ticker import FixedLocator, FuncFormatter

    figure = Figure(figsize=(WIDTH_IN, HEIGHT_IN), dpi=DPI)
    height_px = HEIGHT_IN * DPI
    caption = chart["caption"]
    tilt_px = _rotate_edges(chart)
    bottom_px = 78 + CAPTION_LINE_PX * len(caption) + tilt_px
    figure.subplots_adjust(
        left=LEFT, right=RIGHT, top=1 - 62 / height_px, bottom=bottom_px / height_px
    )
    ax = figure.add_subplot(1, 1, 1)
    figure.text(
        0.02,
        1 - 14 / height_px,
        chart["title"],
        fontsize=TITLE_PT,
        fontweight="bold",
        va="top",
        ha="left",
    )
    for index, line in enumerate(caption):
        figure.text(
            0.02,
            (12 + CAPTION_LINE_PX * (len(caption) - 1 - index)) / height_px,
            line,
            fontsize=CAPTION_PT,
            color=MUTED,
            va="bottom",
            ha="left",
        )

    kind = chart["kind"]
    ax.set_xlabel(_axis_label(chart["x_label"], chart["x_unit"]), fontsize=LABEL_PT)
    ax.xaxis.set_major_formatter(FuncFormatter(_formatter(chart["x_unit"])))
    if kind == "scatter":
        ax.grid(True, axis="both")
        ax.set_ylabel(_axis_label(chart["y_label"], chart["y_unit"]), fontsize=LABEL_PT)
        ax.yaxis.set_major_formatter(FuncFormatter(_formatter(chart["y_unit"])))
        if chart["points"]:
            xs = [p[0] for p in chart["points"]]
            ys = [p[1] for p in chart["points"]]
            ax.scatter(
                xs, ys, s=30, color=DATA, alpha=0.85, edgecolors=PAPER, linewidths=0.6
            )
        else:
            ax.text(
                0.5,
                0.5,
                "No sales to plot",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=MUTED,
                fontsize=LABEL_PT,
            )
    else:
        _bars(ax, chart, tilt_px > 0, FixedLocator, FuncFormatter)

    buffer = io.BytesIO()
    figure.savefig(
        buffer, format="png", dpi=DPI, facecolor=PAPER, metadata={"Software": None}
    )
    return buffer.getvalue()


def _bars(ax, chart: dict, rotate: bool, FixedLocator, FuncFormatter) -> None:
    bars = chart["bars"]
    histogram = chart["kind"] == "histogram"
    ax.grid(True, axis="y")
    if histogram:
        ax.set_ylabel("Number of sales", fontsize=LABEL_PT)
        ax.yaxis.set_major_formatter(FuncFormatter(_formatter("count")))
    else:
        label = "Median " + chart["y_label"][0].lower() + chart["y_label"][1:]
        ax.set_ylabel(_axis_label(label, chart["y_unit"]), fontsize=LABEL_PT)
        ax.yaxis.set_major_formatter(FuncFormatter(_formatter(chart["y_unit"])))
    shown = [b for b in bars if b[3] is not None]
    top = max((b[3] for b in shown), default=0.0)
    ceiling = top * 1.15 if top > 0 else 1.0
    ax.set_ylim(0, ceiling)
    for lower, upper, n, value in bars:
        centre, width = (lower + upper) / 2, upper - lower
        if value is None:
            ax.bar(
                centre,
                ceiling,
                width=width,
                bottom=0,
                fill=False,
                hatch="///",
                edgecolor=HATCH,
                linewidth=0.0,
            )
            ax.text(
                centre,
                ceiling / 2,
                f"suppressed (n={n})",
                rotation=90,
                ha="center",
                va="center",
                fontsize=NOTE_PT,
                color=MUTED,
                backgroundcolor=PAPER,
            )
            continue
        ax.bar(centre, value, width=width, color=DATA, edgecolor=PAPER, linewidth=1.0)
        if not histogram:
            ax.text(
                centre,
                value + ceiling * 0.01,
                f"n={n}",
                ha="center",
                va="bottom",
                fontsize=NOTE_PT,
                color=MUTED,
            )
    if histogram and top > 0 and top <= 10:
        ax.yaxis.set_major_locator(FixedLocator(list(range(int(ceiling) + 1))))
    edges = _edges(chart)
    ax.set_xlim(edges[0], edges[-1])
    ax.xaxis.set_major_locator(FixedLocator(edges))
    if rotate:
        for label in ax.get_xticklabels():
            label.set_rotation(40)
            label.set_ha("right")


def main() -> None:
    try:
        chart = _load()
        _seed_font_cache()
        data = _draw(chart)
        out = sys.stdout.buffer
        out.write(data)
        out.flush()
    except BaseException:  # noqa: B036 - any failure is the same fixed exit
        _fail()
    os._exit(0)


if __name__ == "__main__":
    main()
