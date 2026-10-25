"""WO-017 adversarial source batches; synthetic records, no DB or execution."""

from datetime import date

import pytest
from pydantic import ValidationError

from idx_agent.domain.analysis import AnalysisRow, make_analysis_sample
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow

DATES = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SCOPE = MarketStatsRequest(city="Pasadena", property_subtype="Condominium")
WINDOW = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)


def sale(**changes):
    return SoldComp.model_validate(
        dict(
            listing_key=123,
            address="123 Synthetic Avenue",
            city="Pasadena",
            postal_code="91101",
            close_date=date(2026, 9, 1),
            close_price=800_000,
            list_price=820_000,
            original_list_price=850_000,
            living_area=1_200,
            days_on_market=25,
            property_subtype="Condominium",
        )
        | changes
    )


def sample(rows, **changes):
    return make_analysis_sample(
        rows,
        changes.get("scope", SCOPE),
        changes.get("window", WINDOW),
        changes.get("as_of", DATES),
    )


def test_worker_projection_has_no_identifier_text_or_location():
    value = sample([sale()])
    assert value.worker_rows() == [
        dict(
            close_price=800_000,
            list_price=820_000,
            original_list_price=850_000,
            living_area=1_200,
            days_on_market=25,
        )
    ]
    assert all(
        number is None or type(number) is int
        for row in value.worker_rows()
        for number in row.values()
    )
    copy = value.worker_rows()
    copy[0]["close_price"] = 1
    assert value.rows[0].close_price == 800_000
    with pytest.raises(ValidationError):
        value.rows[0].close_price = 1


def test_oversize_source_is_refused_instead_of_truncated():
    with pytest.raises(ValueError, match="50-row ceiling"):
        sample([sale(listing_key=i) for i in range(51)])
    assert len(sample([sale(listing_key=i) for i in range(50)]).rows) == 50


def test_duplicate_sale_cannot_inflate_sample():
    with pytest.raises(ValueError, match="duplicate"):
        sample([sale(), sale(close_price=900_000)])


@pytest.mark.parametrize(
    "changes",
    [
        {"city": "Glendale"},
        {"property_subtype": "SingleFamilyResidence"},
        {"close_date": date(2026, 9, 18)},
        {"close_date": date(2026, 3, 17)},
        {"close_price": 24_999},
        {"list_price": 24_999},
        {"list_price": None},
    ],
)
def test_mismatched_or_unclean_batch_fails_closed(changes):
    with pytest.raises(ValueError):
        sample([sale(**changes)])


def test_source_errors_do_not_echo_private_fields():
    with pytest.raises(ValueError) as caught:
        sample([sale(city="Glendale", address="Private test value")])
    assert "Glendale" not in str(caught.value)
    assert "Private test value" not in str(caught.value)


def test_zip_scope_and_default_type_are_enforced():
    scope = MarketStatsRequest(postal_code="91101")
    value = sale(property_subtype="SingleFamilyResidence")
    assert len(sample([value], scope=scope).rows) == 1
    with pytest.raises(ValueError):
        sample([value.model_copy(update={"postal_code": "91201"})], scope=scope)


def test_unknowns_are_not_silently_turned_into_zero():
    value = sample(
        [sale(original_list_price=0, living_area=199, days_on_market=None)]
    ).rows[0]
    assert value.original_list_price is None
    assert value.living_area is None
    assert value.days_on_market is None
    assert sample([sale(days_on_market=0)]).rows[0].days_on_market == 0


@pytest.mark.parametrize(
    "window",
    [
        StatsWindow(start=date(2026, 3, 17), end=WINDOW.end, months=6),
        StatsWindow(start=WINDOW.start, end=date(2026, 9, 18), months=6),
        StatsWindow(start=WINDOW.start, end=WINDOW.end, months=5),
    ],
)
def test_window_provenance_cannot_be_forged(window):
    with pytest.raises(ValueError):
        sample([], window=window)


def test_snapshot_order_cannot_be_reversed():
    with pytest.raises(ValueError):
        sample([], as_of=AsOfDates(sold=DATES.sold, active=date(2026, 9, 16)))


def test_short_sample_is_explicit_and_even_large_sample_is_not_population():
    assert "Fewer than 10" in " ".join(sample([]).caveats())
    value = sample([sale(listing_key=i) for i in range(10)])
    assert "Fewer than 10" not in " ".join(value.caveats())
    assert "not a representative" in " ".join(value.caveats())
    assert "causation" in " ".join(value.caveats())


@pytest.mark.parametrize(
    "changes",
    [
        {"address": "untrusted"},
        {"listing_key": 99},
        {"close_price": True},
        {"close_price": float("inf")},
        {"living_area": float("nan")},
        {"days_on_market": -1},
    ],
)
def test_worker_row_rejects_extra_fields_and_invalid_numeric_values(changes):
    with pytest.raises(ValidationError):
        AnalysisRow.model_validate(
            dict(close_price=800_000, list_price=820_000) | changes
        )
