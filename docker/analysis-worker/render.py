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
AXIS_PX = WIDTH_IN * DPI * (RIGHT - LEFT)

# Estimated text sizes in pixels at DPI, for spacing decisions only.
TICK_CHAR_PX = 9.5  # one character of tick text
NOTE_CHAR_PX = 8.5  # one character of note text
NOTE_HEIGHT_PX = 14  # one line of note text
TILTED_PITCH_PX = 24  # spacing that keeps 40-degree tick labels apart
EDGE_DECIMALS_CAP = 6

# Decimal places a value tick shows, per display unit (others: 0).
_PLACES = {"USD": 0, "USD per sqft": 0, "percent": 1, "ratio": 2}


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


def _number_text(value: float, unit: str, places: int) -> str:
    """One number in a unit: thousands separators, then currency or percent."""
    digits = f"{abs(value):,.{places}f}"
    sign = "-" if value < 0 and digits.strip("0.,") else ""
    if unit in ("USD", "USD per sqft"):
        return f"{sign}${digits}"
    if unit == "percent":
        return f"{sign}{digits}%"
    return sign + digits


def _formatter(unit: str):
    """Automatic value ticks: the unit's fixed display precision."""
    places = _PLACES.get(unit, 0)
    return lambda v, _pos: _number_text(v, unit, places)


def _edge_text(value: float, unit: str) -> str:
    """A bin edge exactly as given: the unit's precision, or more if it needs it.

    Edges are bin boundaries, so they are never rounded to a different number: the
    fewest decimals that give the same float back, up to a fixed cap.
    """
    places = _PLACES.get(unit, 0)
    while places < EDGE_DECIMALS_CAP and float(f"{value:.{places}f}") != value:
        places += 1
    return _number_text(value, unit, places)


def _edges(chart: dict) -> list[float]:
    bars = chart["bars"]
    return [bars[0][0]] + [b[1] for b in bars] if bars else []


def _positions(edges: list[float]) -> list[float]:
    """Pixel offset of each edge from the left end of the x axis."""
    span = edges[-1] - edges[0]
    return [AXIS_PX * (edge - edges[0]) / span for edge in edges]


def _edge_labels(edges: list[float], unit: str) -> tuple[dict[float, str], int]:
    """Text per bin edge and the extra bottom pixels for tilted labels.

    Level labels when every gap fits the widest one; otherwise the labels tilt 40
    degrees and an edge keeps its label only when it is a fixed pitch from the last
    labelled edge (the first and last edges are always labelled). Unlabelled edges
    keep their tick mark.
    """
    if not edges:
        return {}, 0
    texts = [_edge_text(edge, unit) for edge in edges]
    widest_px = TICK_CHAR_PX * max(len(text) for text in texts)
    xs = _positions(edges)
    narrowest = min(b - a for a, b in zip(xs, xs[1:], strict=False))
    if widest_px <= 0.85 * narrowest:
        return dict(zip(edges, texts, strict=True)), 0
    keep = [0]
    for index in range(1, len(xs) - 1):
        clear_left = xs[index] - xs[keep[-1]] >= TILTED_PITCH_PX
        if clear_left and xs[-1] - xs[index] >= TILTED_PITCH_PX:
            keep.append(index)
    keep.append(len(xs) - 1)
    labels = {edge: texts[i] if i in keep else "" for i, edge in enumerate(edges)}
    return labels, round(0.64 * widest_px)  # height gained by a 40-degree tilt


def _suppressed_runs(bars: list) -> list[tuple[float, float, int]]:
    """Adjacent suppressed bins merged into (lower, upper, summed n) placeholders."""
    runs: list[tuple[float, float, int]] = []
    for lower, upper, n, value in bars:
        if value is not None:
            continue
        if runs and runs[-1][1] == lower:
            runs[-1] = (runs[-1][0], upper, runs[-1][2] + n)
        else:
            runs.append((lower, upper, n))
    return runs


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
            "text.parse_math": False,  # every string is drawn as plain text
            "text.usetex": False,
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
    edge_labels, tilt_px = _edge_labels(_edges(chart), chart["x_unit"])
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
        _bars(ax, chart, edge_labels, tilt_px > 0, FixedLocator, FuncFormatter)

    buffer = io.BytesIO()
    figure.savefig(
        buffer, format="png", dpi=DPI, facecolor=PAPER, metadata={"Software": None}
    )
    return buffer.getvalue()


def _bars(
    ax, chart: dict, labels: dict, rotate: bool, FixedLocator, FuncFormatter
) -> None:
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
    edges = _edges(chart)
    px_per_unit = AXIS_PX / (edges[-1] - edges[0])
    # One hatched placeholder and one note per run of adjacent suppressed bins; the
    # note is left out only when the run is too narrow to hold it (the caption
    # still says that small bins show no median).
    for lower, upper, n in _suppressed_runs(bars):
        centre, width = (lower + upper) / 2, upper - lower
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
        if width * px_per_unit >= NOTE_HEIGHT_PX:
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
    for lower, upper, n, value in bars:
        if value is None:
            continue
        centre, width = (lower + upper) / 2, upper - lower
        ax.bar(centre, value, width=width, color=DATA, edgecolor=PAPER, linewidth=1.0)
        note = f"n={n}"
        width_px = width * px_per_unit
        if not histogram and width_px >= NOTE_HEIGHT_PX:
            level = width_px >= NOTE_CHAR_PX * len(note)  # else upright, rotated
            ax.text(
                centre,
                value + ceiling * 0.01,
                note,
                rotation=0 if level else 90,
                ha="center",
                va="bottom",
                fontsize=NOTE_PT,
                color=MUTED,
            )
    if histogram and top > 0 and top <= 10:
        ax.yaxis.set_major_locator(FixedLocator(list(range(int(ceiling) + 1))))
    ax.set_xlim(edges[0], edges[-1])
    ax.xaxis.set_major_locator(FixedLocator(edges))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _pos: labels.get(v, "")))
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
