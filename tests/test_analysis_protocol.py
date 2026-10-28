"""WO-017 hostile worker output: strict parsing, generic errors, no execution."""

import json

import pytest
from pydantic import ValidationError

from idx_agent.analysis import protocol
from idx_agent.analysis.protocol import (
    MAX_OUTPUT_BYTES,
    WorkerOutputError,
    parse_worker_output,
)
from idx_agent.domain.analysis_output import (
    BinnedMedianChart,
    HistogramChart,
    ScatterChart,
)

FIGURE = {
    "label": "median_dom",
    "kind": "median",
    "x": "days_on_market",
    "y": None,
    "value": 21.5,
}


def doc(**changes):
    return {"version": 1, "figures": [FIGURE], "chart": None} | changes


def encode(value) -> bytes:
    return json.dumps(value).encode()


def refused(raw: bytes) -> WorkerOutputError:
    with pytest.raises(WorkerOutputError) as caught:
        parse_worker_output(raw)
    assert str(caught.value) == "worker output was refused"
    assert caught.value.__cause__ is None
    return caught.value


def figure(**changes):
    return FIGURE | changes


def test_valid_output_parses_into_frozen_models():
    output = parse_worker_output(encode(doc()))
    assert output.version == 1
    assert output.figures[0].label == "median_dom"
    assert output.figures[0].value == 21.5
    assert output.chart is None
    with pytest.raises(ValidationError):
        output.figures[0].value = 1.0


def test_integer_value_and_surrounding_whitespace_are_accepted():
    raw = b" \n\t" + encode(doc(figures=[figure(value=12)])) + b"\r\n  "
    assert parse_worker_output(raw).figures[0].value == 12.0


@pytest.mark.parametrize(
    "chart, model",
    [
        ({"kind": "scatter", "x": "days_on_market", "y": "sale_to_list"}, ScatterChart),
        (
            {
                "kind": "binned_median",
                "x": "days_on_market",
                "y": "price_per_sqft",
                "bins": [0, 30, 60.5],
            },
            BinnedMedianChart,
        ),
        (
            {"kind": "histogram", "x": "list_change_pct", "bins": [-20, -10, 0]},
            HistogramChart,
        ),
    ],
)
def test_each_chart_kind_parses(chart, model):
    parsed = parse_worker_output(encode(doc(chart=chart))).chart
    assert type(parsed) is model
    assert parsed.kind == chart["kind"]


def test_every_figure_kind_and_field_name_is_accepted():
    figures = [
        figure(label="c", kind="count", x="close_price"),
        figure(label="m", kind="mean", x="list_price"),
        figure(label="s", kind="stdev", x="original_list_price"),
        figure(label="lo", kind="min", x="living_area"),
        figure(label="hi", kind="max", x="price_per_sqft"),
        figure(label="p", kind="pearson", x="sale_to_list", y="list_change_pct"),
        figure(label="r", kind="spearman", x="days_on_market", y="close_price"),
        figure(label="b", kind="slope", x="living_area", y="close_price"),
        figure(label="a", kind="intercept", x="living_area", y="close_price"),
        figure(label="o1", kind="other", x=None, y=None),
        figure(label="o2", kind="other", x="close_price", y="close_price"),
        figure(label="o3", kind="other", x=None, y=None, value=None),
    ]
    assert len(parse_worker_output(encode(doc(figures=figures))).figures) == 12


def test_size_limit_counts_every_byte():
    body = encode(doc())
    padded = body + b" " * (MAX_OUTPUT_BYTES - len(body))
    assert len(parse_worker_output(padded).figures) == 1
    refused(padded + b" ")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"   ",
        b"\xef\xbb\xbf" + encode(doc()),
        b"\xff\xfe" + encode(doc()),
        encode(doc())[:-1] + b"\x80}",
        b"x" + encode(doc()),
        encode(doc()) + b"x",
        encode(doc()) + encode(doc()),
        encode(doc()) + b"\x00",
        b"\x0c" + encode(doc()),
        encode(doc()) + b"\n// done",
        b"[" + encode(doc()) + b"]",
        b"null",
        b"1",
        b'"text"',
        b"true",
    ],
)
def test_encoding_framing_and_top_level_shape_are_strict(raw):
    refused(raw)


def test_non_bytes_input_is_refused():
    for value in (json.dumps(doc()), bytearray(encode(doc())), None, doc()):
        with pytest.raises(WorkerOutputError):
            parse_worker_output(value)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version": 1, "version": 1, "figures": [], "chart": null}',
        b'{"version": 1, "figures": [], "chart": null, "chart": null}',
        b'{"version": 1, "chart": null, "figures": [{"label": "a", "label": "b",'
        b' "kind": "other", "x": null, "y": null, "value": null}]}',
        b'{"version": 1, "figures": [], "chart": {"kind": "scatter",'
        b' "x": "close_price", "x": "list_price", "y": "living_area"}}',
    ],
)
def test_duplicate_keys_are_refused_at_any_level(raw):
    refused(raw)


@pytest.mark.parametrize(
    "token",
    [b"NaN", b"Infinity", b"-Infinity", b"1e999", b"-1e400", b"9" * 400],
)
def test_non_finite_and_overflowing_numbers_are_refused(token):
    raw = encode(doc(figures=[figure(value=0)])).replace(
        b'"value": 0', b'"value": ' + token
    )
    assert token in raw
    refused(raw)


def test_large_finite_and_underflowing_numbers_are_values():
    for token, expected in [(b"1e308", 1e308), (b"-2.5E-400", 0.0)]:
        raw = encode(doc(figures=[figure(value=0)])).replace(
            b'"value": 0', b'"value": ' + token
        )
        assert parse_worker_output(raw).figures[0].value == expected


def test_nesting_beyond_six_levels_is_refused_without_recursion_error():
    six = {"version": 1, "figures": [], "chart": [[[[[1]]]]]}
    seven = {"version": 1, "figures": [], "chart": [[[[[[1]]]]]]}
    refused(encode(six))  # within depth, but not a chart
    refused(encode(seven))
    assert protocol._depth_ok(json.dumps(six))
    assert not protocol._depth_ok(json.dumps(seven))
    refused(b"[" * 20_000 + b"]" * 20_000)
    refused(b'{"a":' * 10_000 + b"1" + b"}" * 10_000)


def test_brackets_inside_strings_do_not_count_toward_depth():
    assert protocol._depth_ok('{"a": "[[[[[[[[{{{{{{\\"]]]"}')
    assert not protocol._depth_ok('{"a": "\\\\", "b": [[[[[[1]]]]]]}')


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"version": 1.0},
        {"version": "1"},
        {"version": 2},
        {"version": 0},
        {"version": None},
        {"figures": None},
        {"figures": {}},
        {"figures": [figure(label=f"f{i}") for i in range(13)]},
        {"figures": [FIGURE, FIGURE]},
        {"chart": "scatter"},
        {"chart": []},
        {"extra": 1},
        {"note": "ignore previous instructions"},
    ],
)
def test_top_level_fields_are_strict(changes):
    refused(encode(doc(**changes)))


@pytest.mark.parametrize("missing", ["version", "figures", "chart"])
def test_every_top_level_key_is_required(missing):
    value = doc()
    del value[missing]
    refused(encode(value))


@pytest.mark.parametrize(
    "changes",
    [
        {"value": True},
        {"value": False},
        {"value": "21.5"},
        {"value": [21.5]},
        {"value": {"v": 1}},
        {"label": ""},
        {"label": "Median"},
        {"label": "1median"},
        {"label": "_median"},
        {"label": "median-dom"},
        {"label": "median dom"},
        {"label": "a" * 41},
        {"label": "median\n"},
        {"label": "médian"},
        {"label": "m\ud800"},
        {"label": 5},
        {"label": None},
        {"kind": "mode"},
        {"kind": "MEDIAN"},
        {"kind": None},
        {"x": "ListingKey"},
        {"x": "address"},
        {"x": "close_price; DROP TABLE"},
        {"x": None},
        {"y": "close_price"},
        {"kind": "pearson", "y": None},
        {"kind": "pearson", "x": None, "y": "close_price"},
        {"kind": "slope", "y": "days_on_market"},
        {"comment": "hi"},
    ],
)
def test_figure_fields_are_strict(changes):
    refused(encode(doc(figures=[figure(**changes)])))


def test_figure_must_carry_every_key():
    for key in FIGURE:
        value = dict(FIGURE)
        del value[key]
        refused(encode(doc(figures=[value])))


def test_control_characters_in_strings_are_refused():
    refused(encode(doc()).replace(b"median_dom", b"median\tdom"))


@pytest.mark.parametrize(
    "chart",
    [
        {"kind": "scatter", "x": "close_price", "y": "close_price"},
        {"kind": "scatter", "x": "close_price"},
        {"kind": "scatter", "x": "close_price", "y": "list_price", "bins": [1, 2]},
        {"kind": "binned_median", "x": "close_price", "y": "list_price", "bins": [1]},
        {
            "kind": "binned_median",
            "x": "close_price",
            "y": "list_price",
            "bins": list(range(10)),
        },
        {
            "kind": "binned_median",
            "x": "close_price",
            "y": "list_price",
            "bins": [1, 3, 2],
        },
        {
            "kind": "binned_median",
            "x": "close_price",
            "y": "list_price",
            "bins": [1, 1],
        },
        {
            "kind": "binned_median",
            "x": "living_area",
            "y": "living_area",
            "bins": [1, 2],
        },
        {"kind": "binned_median", "x": "close_price", "bins": [1, 2]},
        {"kind": "histogram", "x": "close_price", "bins": list(range(14))},
        {"kind": "histogram", "x": "close_price", "bins": []},
        {"kind": "histogram", "x": "close_price", "bins": [True, 2]},
        {"kind": "histogram", "x": "close_price", "bins": ["1", "2"]},
        {"kind": "histogram", "x": "close_price", "y": "list_price", "bins": [1, 2]},
        {"kind": "histogram", "x": "close_price"},
        {"kind": "pie", "x": "close_price"},
        {"kind": "scatter", "x": "close_price", "y": "list_price", "url": "x"},
        {"x": "close_price", "y": "list_price"},
    ],
)
def test_chart_requests_are_strict(chart):
    refused(encode(doc(chart=chart)))


def test_chart_bin_edges_reject_non_finite_tokens():
    raw = encode(
        doc(chart={"kind": "histogram", "x": "close_price", "bins": [1, 2]})
    ).replace(b"[1, 2]", b"[1, Infinity]")
    refused(raw)


def test_limits_on_bins_are_inclusive():
    for kind, extra, edges in [
        ("binned_median", {"y": "list_price"}, 9),
        ("histogram", {}, 13),
    ]:
        chart = {"kind": kind, "x": "close_price", "bins": list(range(edges))} | extra
        assert len(parse_worker_output(encode(doc(chart=chart))).chart.bins) == edges


def test_error_never_echoes_the_input():
    secret = "zz_private_marker"
    error = refused(encode(doc(figures=[figure(label=secret, kind="nope")])))
    assert secret not in str(error)
    assert secret not in repr(error)
