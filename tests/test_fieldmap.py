"""Field map (WO-003): synthetic rows map to models with the right coercions.

Every row here is invented: placeholder address, a known city, zip 90210, made-up
keys and prices. Contact keys carry placeholder values and must be dropped.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from idx_agent.domain import fieldmap
from idx_agent.domain.models import Listing, SoldComp
from idx_agent.safety import columns

# Invented stand-in for a contact value; only the key names matter.
CONTACT_VALUE = "placeholder-contact"


def rets_row(**overrides):
    """Return an invented rets_property row as a driver would return it."""
    row = {
        "L_ListingID": "700001",
        "L_DisplayId": "EX700001",
        "L_Address": "123 Example St",
        "L_City": "Los Angeles",
        "L_Zip": "90210-0001",
        "L_SystemPrice": 1_250_000,
        "L_Keyword2": 3.0,
        "LM_Dec_3": Decimal("2.5"),
        "LM_Int2_3": 1800.0,
        "L_Type_": "SingleFamilyResidence",
        "StandardStatus": "Active",
        "YearBuilt": 1995,
        "AssociationFee": 250,
        "AssociationFeeFrequency": "Monthly",
        "DaysOnMarket": 12,
        "PhotoCount": None,
        "L_Photos": '["p1.jpg", "p2.jpg", "p3.jpg"]',
        "LMD_MP_Latitude": Decimal("34.050000000000000"),
        "LMD_MP_Longitude": Decimal("-118.400000000000000"),
        "PoolPrivateYN": "1",
        "ViewYN": "",
        "FireplaceYN": None,
        "L_Remarks": "Sunny rooms.",
        # Not read by to_listing: must be ignored, never copied or raised on.
        "ListingContractDate": "2024-03-05",
        "SomeFutureColumn": "x",
        "ListAgentFullName": CONTACT_VALUE,
        "ListAgentEmail": CONTACT_VALUE,
        "PrivateRemarks": CONTACT_VALUE,
    }
    row.update(overrides)
    return row


def sold_row(**overrides):
    """Return an invented california_sold row as a driver would return it."""
    row = {
        "ListingKey": 700002,
        "UnparsedAddress": "123 Example St",
        "City": "Los Angeles",
        "PostalCode": "90210",
        "close_date_d": None,
        "CloseDate": "2024-03-05",
        "ClosePrice": 1_300_000.4,
        "ListPrice": 1_250_000.0,
        "OriginalListPrice": 1_299_000.0,
        "DaysOnMarket": 20,
        "BedroomsTotal": 3.0,
        "LivingArea": 1650.5,
        "PropertySubType": "Condominium",
        "YearBuilt": 1988.0,
        # Not read by to_sold_comp: must be ignored.
        "BathroomsTotalInteger": 2.0,
        "Latitude": 34.0,
        "ListAgentFirstName": CONTACT_VALUE,
        "BuyerOfficeName": CONTACT_VALUE,
        "SomeFutureColumn": "x",
    }
    row.update(overrides)
    return row


class RecordingRow(Mapping):
    """A read-only row that records every key looked up (including missing ones)."""

    def __init__(self, data):
        """Wrap a dict; `read` collects the keys accessed."""
        self.data = data
        self.read = set()

    def __getitem__(self, key):
        """Record the key, then look it up (KeyError when absent)."""
        self.read.add(key)
        return self.data[key]

    def __iter__(self):
        """Iterate over the wrapped keys."""
        return iter(self.data)

    def __len__(self):
        """Return the number of wrapped keys."""
        return len(self.data)


def spec(name):
    """Return the FIELD_MAP row with the given canonical name."""
    return next(s for s in fieldmap.FIELD_MAP if s.canonical == name)


# --- Whole rows ---


def test_rets_row_maps_to_listing_with_coercions():
    """Text key -> int, 3.0 -> 3, Decimal -> float, zip+4 -> five digits, flags."""
    listing = fieldmap.to_listing(rets_row())
    assert isinstance(listing, Listing)
    assert listing.listing_key == 700001 and listing.listing_id == "EX700001"
    assert listing.bedrooms == 3 and type(listing.bedrooms) is int
    assert listing.living_area == 1800 and type(listing.living_area) is int
    assert listing.bathrooms == 2.5 and listing.postal_code == "90210"
    assert listing.hoa_fee_monthly == 250 and listing.photo_count == 3
    assert (listing.pool, listing.view, listing.fireplace) == (True, False, None)
    assert listing.latitude == 34.05 and listing.longitude == -118.4
    assert listing.status == "Active" and listing.remarks == "Sunny rooms."


def test_rets_row_unknown_and_contact_keys_dropped():
    """Unknown, agent-contact, and deny-listed keys never reach the Listing."""
    listing = fieldmap.to_listing(rets_row())
    assert listing.address == "123 Example St" and listing.remarks == "Sunny rooms."
    assert CONTACT_VALUE not in listing.model_dump_json()


def test_sold_row_maps_to_sold_comp_with_coercions():
    """Text date -> date, whole doubles -> ints, measured doubles rounded half-even."""
    comp = fieldmap.to_sold_comp(sold_row())
    assert isinstance(comp, SoldComp)
    assert comp.close_date == date(2024, 3, 5)
    assert comp.close_price == 1_300_000 and type(comp.close_price) is int
    assert comp.living_area == 1650  # 1650.5 rounds half-even to the even 1650
    assert comp.bedrooms == 3 and comp.year_built == 1988
    assert comp.original_list_price == 1_299_000 and comp.list_price == 1_250_000


def test_sold_row_unknown_and_contact_keys_dropped():
    """Contact and unmapped keys in a sold row are dropped, not raised on."""
    comp = fieldmap.to_sold_comp(sold_row())
    assert comp.listing_key == 700002 and comp.address == "123 Example St"
    assert CONTACT_VALUE not in comp.model_dump_json()


# --- Numbers ---


@pytest.mark.parametrize(
    "raw,expected",
    [(1650.5, 1650), (1651.5, 1652), (1800.0000001, 1800), ("1799.6", 1800),
     (Decimal("250.5"), 250), (float("nan"), None), ("1e3", None), ("n/a", None)],
)  # fmt: skip
def test_measured_amounts_round_half_even(raw, expected):
    """Area and price round half-even; float noise never fails a row."""
    assert fieldmap.to_sold_comp(sold_row(LivingArea=raw)).living_area == expected


@pytest.mark.parametrize(
    "raw,expected",
    [(3.0, 3), ("3", 3), ("4.00", 4), (3.5, None), ("1e1", None),
     ("٣", None), (True, None), ("", None)],
)  # fmt: skip
def test_strict_whole_numbers(raw, expected):
    """Bedrooms accept whole values only; exponents and non-ASCII digits -> None."""
    assert fieldmap.to_sold_comp(sold_row(BedroomsTotal=raw)).bedrooms == expected


def test_year_and_days_on_market_out_of_range_become_none():
    """A stored year of 0 and a negative days on market become None, not errors."""
    listing = fieldmap.to_listing(rets_row(YearBuilt=0, DaysOnMarket=-2))
    assert listing.year_built is None and listing.days_on_market is None


@pytest.mark.parametrize("raw", [float("inf"), float("nan"), "abc"])
def test_non_finite_float_becomes_none(raw):
    """Bathrooms that are not a finite number become None."""
    assert fieldmap.to_listing(rets_row(LM_Dec_3=raw)).bathrooms is None


# --- Postal codes, dates, coordinates ---


@pytest.mark.parametrize(
    "raw,expected",
    [("90210", "90210"), ("90210-1234", "90210"), ("902101234", "90210"),
     (90210, "90210"), ("9021", None), ("90210-12", None), ("abcde", None),
     ("", None)],
)  # fmt: skip
def test_postal_code_forms(raw, expected):
    """Five digits with an optional +4 keep the five digits; anything else -> None."""
    assert fieldmap.to_listing(rets_row(L_Zip=raw)).postal_code == expected


def test_close_date_prefers_generated_column():
    """close_date_d wins over the CloseDate text when both are present."""
    comp = fieldmap.to_sold_comp(
        sold_row(close_date_d=date(2026, 6, 1), CloseDate="2024-03-05")
    )
    assert comp.close_date == date(2026, 6, 1)


def test_close_date_text_with_time_and_datetime():
    """Only the first 10 characters of text are read; a datetime gives its date."""
    assert fieldmap.to_sold_comp(
        sold_row(CloseDate="2024-03-05T10:30:00")
    ).close_date == date(2024, 3, 5)
    assert fieldmap.to_sold_comp(
        sold_row(close_date_d=datetime(2024, 3, 6, 9, 0))
    ).close_date == date(2024, 3, 6)


@pytest.mark.parametrize("raw", ["soon", "03/05/2024", "2024-3-5", "2024-02-30"])
def test_unparsable_close_date_fails_the_row(raw):
    """A text date not starting YYYY-MM-DD (or invalid) -> None; close_date required."""
    with pytest.raises(ValidationError):
        fieldmap.to_sold_comp(sold_row(CloseDate=raw))


def test_unmodelled_rows_still_coerce():
    """Rows no model reads yet (contract dates, timestamp, lot size) still coerce."""
    stamp = spec("modification_timestamp")
    row = {"ModificationTimestamp": "2026-09-18 07:15:00"}
    assert stamp.coerce(row, stamp.rets) == datetime(2026, 9, 18, 7, 15)
    signed = spec("purchase_contract_date")
    assert signed.coerce({"PurchaseContractDate": "2026-02-01"}, signed.sold) == date(
        2026, 2, 1
    )
    lot = spec("lot_size_sqft")
    assert lot.coerce({"LotSizeSquareFeet": 7404.5}, lot.sold) == 7404


@pytest.mark.parametrize(
    "lat,lon", [(Decimal("0"), Decimal("-118.4")), (Decimal("34.05"), None)]
)
def test_coordinates_null_together(lat, lon):
    """If either coordinate is missing or zero, both become None."""
    listing = fieldmap.to_listing(rets_row(LMD_MP_Latitude=lat, LMD_MP_Longitude=lon))
    assert listing.latitude is None and listing.longitude is None


# --- Fee and photos ---


@pytest.mark.parametrize("frequency", ["Annually", "Quarterly", None])
def test_hoa_fee_only_when_monthly(frequency):
    """AssociationFee is kept only for a Monthly frequency; others give None."""
    listing = fieldmap.to_listing(rets_row(AssociationFeeFrequency=frequency))
    assert listing.hoa_fee_monthly is None


@pytest.mark.parametrize(
    "count,photos,expected",
    [(7, '["a.jpg"]', 7), (None, "not json", 0), (None, None, 0), (None, "", 0)],
)
def test_photo_count_and_fallback(count, photos, expected):
    """PhotoCount wins; else the L_Photos array length; else 0."""
    listing = fieldmap.to_listing(rets_row(PhotoCount=count, L_Photos=photos))
    assert listing.photo_count == expected


def test_missing_required_value_raises():
    """A row without a price cannot become a Listing."""
    with pytest.raises(ValidationError):
        fieldmap.to_listing(rets_row(L_SystemPrice=None))


# --- The map itself ---


def test_helpers_read_exactly_the_declared_columns():
    """to_listing / to_sold_comp look up exactly listing_columns() / sold_columns()."""
    row = RecordingRow(rets_row())
    fieldmap.to_listing(row)
    assert row.read == set(fieldmap.listing_columns())
    row = RecordingRow(sold_row())
    fieldmap.to_sold_comp(row)
    assert row.read == set(fieldmap.sold_columns())


def test_every_map_column_is_allowlisted():
    """Every column in FIELD_MAP, used by a model or not, passes check_column."""
    for s in fieldmap.FIELD_MAP:
        for name in filter(None, (s.rets, *s.rets_extra)):
            assert columns.check_column("rets_property", name) == name
        for name in filter(None, (s.sold, *s.sold_extra)):
            assert columns.check_column("california_sold", name) == name
    assert "AssociationFeeFrequency" in fieldmap.listing_columns()
    assert "CloseDate" in fieldmap.sold_columns()


def test_map_rows_match_model_fields():
    """Model-marked rows cover every model field once, with a column on that side."""
    names = [s.canonical for s in fieldmap.FIELD_MAP]
    assert len(names) == len(set(names))
    for model, side in ((Listing, "rets"), (SoldComp, "sold")):
        rows = [s for s in fieldmap.FIELD_MAP if model.__name__ in s.models]
        assert {s.canonical for s in rows} == set(model.model_fields)
        assert all(getattr(s, side) for s in rows)
    assert all(set(s.models) <= {"Listing", "SoldComp"} for s in fieldmap.FIELD_MAP)
