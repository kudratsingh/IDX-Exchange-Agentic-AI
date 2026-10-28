"""WO-017 step 5: the renderer's layout helpers, on the host without matplotlib.

render.py imports matplotlib only inside `_draw`, so these pure helpers load here.
"""

import importlib.util
from pathlib import Path

import pytest

RENDER = (
    Path(__file__).resolve().parents[1] / "docker" / "analysis-worker" / "render.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("idx_worker_render", RENDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load()


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (2.5, "days", "2.5"),
        (7.5, "days", "7.5"),
        (10.0, "days", "10"),
        (0.975, "ratio", "0.975"),
        (1.0, "ratio", "1.00"),
        (1.005, "ratio", "1.005"),
        (500_000.0, "USD", "$500,000"),
        (512.25, "USD per sqft", "$512.25"),
        (-1250.5, "USD", "-$1,250.5"),
        (12.5, "percent", "12.5%"),
        (12.25, "percent", "12.25%"),
        (1234.0, "sqft", "1,234"),
    ],
)
def test_edge_labels_show_the_edge_exactly(value, unit, text):
    assert render._edge_text(value, unit) == text


def test_distinct_edges_never_share_a_label():
    for edges, unit in (
        ([0.975, 0.985, 0.995, 1.0, 1.005], "ratio"),
        ([0, 2.5, 7.5, 10, 30, 70], "days"),
        ([0.1 + 0.2, 0.4, 0.45], "ratio"),
    ):
        texts = [render._edge_text(float(edge), unit) for edge in edges]
        assert len(set(texts)) == len(texts), texts
        for edge, text in zip(edges, texts, strict=True):
            plain = text.replace("$", "").replace("%", "").replace(",", "")
            assert abs(float(plain) - edge) < 10**-render.EDGE_DECIMALS_CAP


def test_value_ticks_keep_the_unit_precision():
    assert render._formatter("USD")(1234.6, None) == "$1,235"
    assert render._formatter("ratio")(0.975, None) == "0.97"
    assert render._formatter("days")(-0.2, None) == "0"


def test_wide_bins_label_every_edge_level():
    edges = [700.0, 900.0, 1100.0, 1300.0, 1500.0]
    labels, tilt = render._edge_labels(edges, "sqft")
    assert tilt == 0
    assert list(labels.values()) == ["700", "900", "1,100", "1,300", "1,500"]


def _shown_apart(labels: dict, edges: list[float]) -> None:
    xs = render._positions(edges)
    shown = [x for x, edge in zip(xs, edges, strict=True) if labels[edge]]
    gaps = [b - a for a, b in zip(shown, shown[1:], strict=False)]
    assert min(gaps) >= render.TILTED_PITCH_PX


def test_narrow_bins_tilt_and_thin_the_edge_labels():
    edges = [700.0, 1000.0, 1010.0, 1020.0, 1030.0, 1040.0, 1300.0, 1600.0, 2000.0]
    labels, tilt = render._edge_labels(edges, "sqft")
    assert tilt > 0
    assert labels[700.0] == "700" and labels[2000.0] == "2,000"
    assert labels[1300.0] == "1,300" and labels[1600.0] == "1,600"
    assert sum(1 for edge in edges[1:6] if labels[edge]) == 1
    _shown_apart(labels, edges)


def test_crowded_ratio_edges_stay_apart_and_keep_both_ends():
    edges = [0.9, 0.975, 0.985, 0.995, 1.0, 1.005, 1.1]
    labels, tilt = render._edge_labels(edges, "ratio")
    assert tilt > 0 and labels[0.9] == "0.90" and labels[1.1] == "1.10"
    _shown_apart(labels, edges)


def test_adjacent_suppressed_bins_merge_into_one_note():
    bars = [
        (700.0, 1000.0, 5, 400.0),
        (1000.0, 1010.0, 0, None),
        (1010.0, 1020.0, 0, None),
        (1020.0, 1030.0, 0, None),
        (1030.0, 1040.0, 1, None),
        (1040.0, 1300.0, 6, 420.0),
        (1300.0, 1600.0, 2, None),
    ]
    assert render._suppressed_runs(bars) == [(1000.0, 1040.0, 1), (1300.0, 1600.0, 2)]


def test_rendered_text_is_never_parsed_as_markup():
    class Params(dict):
        pass

    class Fake:
        rcParams = Params()

        @staticmethod
        def rcdefaults():
            Fake.rcParams.clear()

    render._style(Fake)
    assert Fake.rcParams["text.parse_math"] is False
    assert Fake.rcParams["text.usetex"] is False
