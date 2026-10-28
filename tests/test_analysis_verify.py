"""WO-017 trusted figure checks against hand-computed synthetic samples."""

import json
import math
import statistics
from datetime import date
from fractions import Fraction

import pytest
from pydantic import ValidationError

from idx_agent.analysis import stats
from idx_agent.analysis.fields import UNITS, field_values
from idx_agent.analysis.protocol import parse_worker_output
from idx_agent.analysis.verify import verify_figure, verify_figures
from idx_agent.domain.analysis import AnalysisRow, AnalysisSample
from idx_agent.domain.analysis_output import Figure, FigureCheck, WorkerOutput
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, StatsWindow

DATES = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SCOPE = MarketStatsRequest(city="Pasadena")
START, END = DATES.window(SCOPE.months)
WINDOW = StatsWindow(start=START, end=END, months=SCOPE.months)

# Close prices in thousands for days on market 1..10 (hand-chosen).
PRICES = [300, 320, 310, 350, 340, 380, 360, 400, 390, 420]


def make(rows) -> AnalysisSample:
    return AnalysisSample(scope=SCOPE, window=WINDOW, as_of=DATES, rows=tuple(rows))


def row(**values) -> AnalysisRow:
    return AnalysisRow(**({"close_price": 500_000, "list_price": 500_000} | values))


def main_sample() -> AnalysisSample:
    rows = []
    for dom, thousands in enumerate(PRICES, start=1):
        close = thousands * 1000
        listed = close + 10_000 * (dom % 3)
        rows.append(
            row(
                close_price=close,
                list_price=listed,
                original_list_price=listed + 20_000 if dom % 2 else None,
                living_area=1000 + 100 * dom,
                days_on_market=dom,
            )
        )
    rows.append(row(close_price=600_000, list_price=600_000))
    return make(rows)


SAMPLE = main_sample()


def fig(kind, x, y=None, value=None, label="f"):
    return Figure(label=label, kind=kind, x=x, y=y, value=value)


def check(kind, x, y=None, value=None, sample=SAMPLE) -> FigureCheck:
    return verify_figure(sample, fig(kind, x, y, value))


# Hand values for the main sample. Deviations of x = 1..10 from 5.5 give
# Sxx = 82.5; price deviations from 357 (thousands) give Syy = 14610 and
# Sxy = 1045, so slope = 1045 / 82.5 thousand per day = 38000 / 3.
HAND = [
    ("count", "days_on_market", None, 10, 10),
    ("count", "close_price", None, 11, 11),
    ("count", "original_list_price", None, 5, 5),
    ("mean", "days_on_market", None, 5.5, 10),
    ("median", "days_on_market", None, 5.5, 10),
    ("min", "days_on_market", None, 1, 10),
    ("max", "days_on_market", None, 10, 10),
    ("stdev", "days_on_market", None, math.sqrt(82.5 / 9), 10),
    ("mean", "close_price", None, 4_170_000 / 11, 11),
    ("median", "close_price", None, 360_000, 11),
    ("max", "close_price", None, 600_000, 11),
    ("min", "close_price", None, 300_000, 11),
    ("pearson", "days_on_market", "close_price", 1045 / math.sqrt(82.5 * 14610), 10),
    ("spearman", "days_on_market", "close_price", 157 / 165, 10),
    ("slope", "days_on_market", "close_price", 38000 / 3, 10),
    ("intercept", "days_on_market", "close_price", 862_000 / 3, 10),
    ("slope", "close_price", "days_on_market", 1045 / 14_610_000, 10),
]


@pytest.mark.parametrize("kind, x, y, expected, n", HAND)
def test_every_kind_matches_a_hand_value(kind, x, y, expected, n):
    result = check(kind, x, y, value=expected)
    assert result.status == "verified"
    assert result.reason is None
    assert result.n == n
    assert result.trusted == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("kind, x, y, expected, n", HAND)
def test_fabricated_value_is_a_mismatch_and_never_adopted(kind, x, y, expected, n):
    fabricated = expected * 1.01 + 1
    result = check(kind, x, y, value=fabricated)
    assert result.status == "mismatch"
    assert result.reason == "value_differs"
    assert result.reported == fabricated
    assert result.trusted == pytest.approx(expected, rel=1e-12)
    assert result.trusted != fabricated


def test_close_price_stdev_includes_the_eleventh_sale():
    values = [p * 1000 for p in PRICES] + [600_000]
    centre = Fraction(4_170_000, 11)
    variance = sum((Fraction(v) - centre) ** 2 for v in values) / 10
    result = check("stdev", "close_price", value=math.sqrt(variance))
    assert result.status == "verified"
    assert result.n == 11


def test_relationships_agree_with_the_standard_library():
    pairs = [
        (x, y)
        for x, y in zip(
            field_values(SAMPLE, "price_per_sqft"),
            field_values(SAMPLE, "sale_to_list"),
            strict=True,
        )
        if x is not None and y is not None
    ]
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    reference = statistics.linear_regression(xs, ys)
    expected = {
        "pearson": statistics.correlation(xs, ys),
        "slope": reference.slope,
        "intercept": reference.intercept,
    }
    for kind, value in expected.items():
        result = check(kind, "price_per_sqft", "sale_to_list", value=value)
        assert result.status == "verified", kind
        assert result.n == 10


def test_tolerance_is_relative_with_an_absolute_floor():
    assert check("mean", "days_on_market", value=5.5 + 5e-6).status == "verified"
    assert check("mean", "days_on_market", value=5.5 + 6e-6).status == "mismatch"
    big = 4_170_000 / 11
    assert check("mean", "close_price", value=big + big * 9e-7).status == "verified"
    assert check("mean", "close_price", value=big + big * 2e-6).status == "mismatch"
    r = 157 / 165
    assert check("spearman", "days_on_market", "close_price", r + 9e-7).status == (
        "verified"
    )
    assert check("spearman", "days_on_market", "close_price", r + 2e-6).status == (
        "mismatch"
    )


def test_absolute_floor_applies_when_the_trusted_value_is_below_one():
    # 9.8e-7 exceeds 1e-6 * r (about 9.5e-7), so only the floor accepts it.
    r = 157 / 165
    assert check("spearman", "days_on_market", "close_price", r + 9.8e-7).status == (
        "verified"
    )


def _pairs(x, y):
    return [
        (a, b)
        for a, b in zip(field_values(SAMPLE, x), field_values(SAMPLE, y), strict=True)
        if a is not None and b is not None
    ]


def test_tiny_slope_is_judged_on_the_data_scale_not_an_absolute_window():
    pairs = _pairs("close_price", "sale_to_list")
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    fit = statistics.linear_regression(xs, ys)
    assert 0 < abs(fit.slope) < 1e-6
    scale = statistics.stdev(ys) / statistics.stdev(xs)
    # Zero and a wrong sign were inside a fixed 1e-6 window; both are refused now.
    for wrong in (0.0, -fit.slope):
        result = check("slope", "close_price", "sale_to_list", wrong)
        assert (result.status, result.reason) == ("mismatch", "value_differs")
    near = fit.slope + 0.5e-6 * scale
    assert check("slope", "close_price", "sale_to_list", near).status == "verified"
    far = fit.slope + 2e-6 * scale
    assert check("slope", "close_price", "sale_to_list", far).status == "mismatch"


def test_intercept_tolerance_uses_the_spread_of_y():
    pairs = _pairs("close_price", "sale_to_list")
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    fit = statistics.linear_regression(xs, ys)
    sd_y = statistics.stdev(ys)
    window = 1e-6 * max(sd_y, abs(fit.intercept))
    good = fit.intercept + 0.5 * window
    bad = fit.intercept + 2 * window
    assert check("intercept", "close_price", "sale_to_list", good).status == (
        "verified"
    )
    assert check("intercept", "close_price", "sale_to_list", bad).status == "mismatch"


def test_count_must_match_exactly():
    assert check("count", "days_on_market", value=10.0).status == "verified"
    for wrong in (10.5, 10.000001, 9.9999999, 11):
        result = check("count", "days_on_market", value=wrong)
        assert (result.status, result.reason) == ("mismatch", "value_differs")
        assert result.trusted == 10


def test_missing_value_for_a_computable_figure_is_a_mismatch():
    result = check("median", "days_on_market", value=None)
    assert (result.status, result.reason) == ("mismatch", "missing_value")
    assert result.trusted == 5.5


def test_other_kind_is_unverified_and_has_no_trusted_value():
    result = verify_figure(SAMPLE, fig("other", "close_price", value=123.0))
    assert result.status == "unverified"
    assert result.reason == "unsupported_kind"
    assert result.trusted is None
    assert result.reported == 123.0
    assert result.n == 0


def test_pairs_drop_missing_values_and_need_ten():
    result = check("pearson", "original_list_price", "close_price", value=0.5)
    assert (result.status, result.reason, result.n) == (
        "unavailable",
        "too_few_pairs",
        5,
    )
    assert result.trusted is None
    assert result.reported == 0.5


def test_constant_inputs_make_relationships_unavailable():
    flat = make(
        row(close_price=300_000 + 1000 * i, days_on_market=7) for i in range(12)
    )
    for kind in ("pearson", "spearman", "slope", "intercept"):
        for x, y in (
            ("days_on_market", "close_price"),
            ("close_price", "days_on_market"),
        ):
            result = check(kind, x, y, value=0.0, sample=flat)
            assert (result.status, result.reason, result.n) == (
                "unavailable",
                "constant_input",
                12,
            )
    assert check("stdev", "days_on_market", value=0.0, sample=flat).status == (
        "verified"
    )


def test_small_and_empty_inputs_are_unavailable():
    small = make([row(days_on_market=3)])
    result = check("stdev", "days_on_market", value=0.0, sample=small)
    assert (result.status, result.reason, result.n) == (
        "unavailable",
        "too_few_values",
        1,
    )
    assert check("median", "days_on_market", value=3, sample=small).status == (
        "verified"
    )
    for kind in ("count", "mean", "median", "min", "max", "stdev"):
        result = check(kind, "living_area", value=0.0, sample=small)
        assert (result.status, result.reason, result.n) == (
            "unavailable",
            "no_values",
            0,
        )
    empty = make([])
    assert check("count", "close_price", value=0, sample=empty).reason == "no_values"
    result = check("pearson", "close_price", "list_price", value=1.0, sample=empty)
    assert (result.reason, result.n) == ("too_few_pairs", 0)


def test_fewer_than_ten_rows_never_verify_relationships():
    nine = make(
        row(close_price=300_000 + 1000 * i * i, days_on_market=i) for i in range(9)
    )
    for kind in ("pearson", "spearman", "slope", "intercept"):
        result = check(kind, "days_on_market", "close_price", value=1.0, sample=nine)
        assert (result.status, result.reason, result.n) == (
            "unavailable",
            "too_few_pairs",
            9,
        )


# Three sales chosen so each derived value is a round number.
DERIVED = make(
    [
        row(
            close_price=300_000,
            list_price=250_000,
            original_list_price=200_000,
            living_area=1000,
        ),
        row(close_price=400_000, list_price=500_000, living_area=2000),
        row(close_price=600_000, list_price=600_000, original_list_price=750_000),
    ]
)


@pytest.mark.parametrize(
    "kind, x, expected, n",
    [
        ("mean", "price_per_sqft", 250, 2),
        ("max", "price_per_sqft", 300, 2),
        ("mean", "sale_to_list", 1.0, 3),
        ("max", "sale_to_list", 1.2, 3),
        ("min", "sale_to_list", 0.8, 3),
        ("count", "list_change_pct", 2, 2),
        ("median", "list_change_pct", 2.5, 2),
        ("min", "list_change_pct", -20, 2),
        ("max", "list_change_pct", 25, 2),
        ("stdev", "list_change_pct", math.sqrt(2 * 22.5**2), 2),
    ],
)
def test_derived_fields_are_computed_by_host_code(kind, x, expected, n):
    result = check(kind, x, value=expected, sample=DERIVED)
    assert (result.status, result.n) == ("verified", n)
    assert result.trusted == pytest.approx(expected, rel=1e-12)


def test_field_values_keep_row_order_and_nulls():
    assert field_values(DERIVED, "price_per_sqft") == [300.0, 200.0, None]
    assert field_values(DERIVED, "list_change_pct") == [25.0, None, -20.0]
    assert field_values(DERIVED, "original_list_price") == [200_000.0, None, 750_000.0]
    assert set(UNITS) == set(Figure.model_fields["x"].annotation.__args__[0].__args__)
    with pytest.raises(ValueError):
        field_values(DERIVED, "ListingKey")


def test_ties_use_average_ranks():
    # x ranks: 1.5, 1.5, 3.5, ...; y ranks 2,1,3,4,6,5,7,8,10,9 give
    # Sxy = 80, Sxx = 80, Syy = 82.5, so rho = sqrt(80 / 82.5).
    y_ranks = [2, 1, 3, 4, 6, 5, 7, 8, 10, 9]
    tied = make(
        row(close_price=300_000 + 10_000 * rank, days_on_market=i // 2 + 1)
        for i, rank in enumerate(y_ranks)
    )
    result = check(
        "spearman", "days_on_market", "close_price", math.sqrt(32 / 33), sample=tied
    )
    assert result.status == "verified"
    assert stats.ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert stats.ranks([5, 5, 5]) == [2.0, 2.0, 2.0]
    assert stats.ranks([3, 1, 2]) == [3.0, 1.0, 2.0]
    assert stats.ranks([]) == []


def test_stats_functions_refuse_unsupported_input():
    for function, values, reason in [
        (stats.mean, [], "no_values"),
        (stats.median, [], "no_values"),
        (stats.minimum, [], "no_values"),
        (stats.maximum, [], "no_values"),
        (stats.stdev, [], "no_values"),
        (stats.stdev, [4.0], "too_few_values"),
    ]:
        with pytest.raises(stats.StatUnavailable) as caught:
            function(values)
        assert caught.value.reason == reason
    with pytest.raises(stats.StatUnavailable) as caught:
        stats.pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
    assert caught.value.reason == "constant_input"
    with pytest.raises(stats.StatUnavailable):
        stats.slope([1.0], [2.0])
    with pytest.raises(ValueError):
        stats.pearson([1.0, 2.0], [1.0, 2.0, 3.0])


def test_stats_match_hand_values_and_the_standard_library():
    assert stats.median([3.0, 1.0, 2.0]) == 2.0
    assert stats.median([4.0, 1.0, 3.0, 2.0]) == 2.5
    assert stats.stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(
        math.sqrt(32 / 7)
    )
    xs = [1.0, 2.0, 4.0, 8.0, 16.0, 3.0, 5.0]
    ys = [2.0, 1.5, 7.0, 6.0, 30.0, 4.0, -1.0]
    reference = statistics.linear_regression(xs, ys)
    assert stats.pearson(xs, ys) == pytest.approx(statistics.correlation(xs, ys))
    assert stats.slope(xs, ys) == pytest.approx(reference.slope)
    assert stats.intercept(xs, ys) == pytest.approx(reference.intercept)
    assert stats.stdev(xs) == pytest.approx(statistics.stdev(xs))
    assert stats.pearson(xs, [2 * x + 1 for x in xs]) == pytest.approx(1.0)
    assert stats.spearman(xs, [x**3 for x in xs]) == pytest.approx(1.0)


def test_verify_figures_keeps_order_end_to_end():
    raw = json.dumps(
        {
            "version": 1,
            "figures": [
                {
                    "label": "dom_median",
                    "kind": "median",
                    "x": "days_on_market",
                    "y": None,
                    "value": 5.5,
                },
                {
                    "label": "made_up",
                    "kind": "pearson",
                    "x": "days_on_market",
                    "y": "close_price",
                    "value": -0.9,
                },
                {"label": "extra", "kind": "other", "x": None, "y": None, "value": 1},
            ],
            "chart": None,
        }
    ).encode()
    checks = verify_figures(SAMPLE, parse_worker_output(raw))
    assert [c.label for c in checks] == ["dom_median", "made_up", "extra"]
    assert [c.status for c in checks] == ["verified", "mismatch", "unverified"]
    assert checks[1].trusted == pytest.approx(1045 / math.sqrt(82.5 * 14610))
    empty = WorkerOutput(version=1, figures=(), chart=None)
    assert verify_figures(SAMPLE, empty) == ()


def test_check_model_refuses_inconsistent_states():
    base = dict(label="a", kind="mean", x="close_price", y=None, reported=1.0, n=1)
    for changes in [
        {"status": "verified", "trusted": None, "reason": None},
        {"status": "verified", "trusted": 1.0, "reason": "value_differs"},
        {"status": "mismatch", "trusted": 2.0, "reason": None},
        {"status": "unavailable", "trusted": 1.0, "reason": "no_values"},
        {"status": "unverified", "trusted": 1.0, "reason": "unsupported_kind"},
        {"status": "verified", "trusted": math.nan, "reason": None},
        {"status": "verified", "trusted": 1.0, "reason": None, "n": -1},
        {"status": "verified", "trusted": 1.0, "reason": "free text"},
    ]:
        with pytest.raises(ValidationError):
            FigureCheck(**(base | changes))
    ok = FigureCheck(**base, status="verified", trusted=1.0, reason=None)
    with pytest.raises(ValidationError):
        ok.trusted = 2.0
