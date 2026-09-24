"""Canonical field map (docs/data/schema_notes.md) as data, plus row -> model helpers.

Flow: db row (dict of source columns) -> to_listing / to_sold_comp -> model.
Only mapped source columns are read, so unknown, deny-listed, and agent-contact
keys in a row are dropped, never copied. No SQL and no database access here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, NamedTuple

from idx_agent.domain.models import MIN_YEAR_BUILT, Listing, SoldComp
from idx_agent.domain.valid_values import parse_flag
from idx_agent.safety.columns import check_column

__all__ = [
    "FIELD_MAP",
    "FieldSpec",
    "listing_columns",
    "sold_columns",
    "to_listing",
    "to_sold_comp",
]

# A raw database row: source column name -> value as the driver returned it.
Row = Mapping[str, Any]

# Text accepted as a whole number ("12", "-3", "4.00"): ASCII digits, no exponent.
_INT_TEXT = re.compile(r"-?[0-9]+(?:\.0+)?")
# Text accepted as a decimal number ("1650.5"): ASCII digits, no exponent.
_NUM_TEXT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
# A postal code: five digits, optionally followed by a four-digit extension.
_ZIP = re.compile(r"([0-9]{5})(?:-?[0-9]{4})?")
# Text dates must start YYYY-MM-DD; timestamps must start YYYY-MM-DD HH:MM:SS.
_DATE_PREFIX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME_PREFIX = re.compile(_DATE_PREFIX.pattern + r"[ T][0-9]{2}:[0-9]{2}:[0-9]{2}")


# --- Scalar coercions: one raw value in, a canonical value (or None) out. ---


def _to_str(value: Any) -> str | None:
    """Return trimmed text; None and empty or blank strings become None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(value: Any, text_pattern: re.Pattern[str]) -> Decimal | None:
    """Return a finite Decimal from int, float, Decimal, or text matching the pattern.

    Booleans, non-finite numbers, and any other text (exponents, non-ASCII
    digits, words) give None.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float | Decimal):
        number = Decimal(str(value))
        return number if number.is_finite() else None
    text = _to_str(value)
    if text is None or not text_pattern.fullmatch(text):
        return None
    return Decimal(text)


def _to_int(value: Any) -> int | None:
    """Strict whole number for keys and counts: 3.0 -> 3; 3.5 or bad text -> None."""
    number = _to_decimal(value, _INT_TEXT)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def _to_rounded_int(value: Any) -> int | None:
    """Measured amount (price, area, fee) rounded half-even: 1650.5 -> 1650.

    Float noise and fractions never fail a row; unparsable input gives None.
    """
    number = _to_decimal(value, _NUM_TEXT)
    if number is None:
        return None
    try:
        return int(number.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    except ArithmeticError:
        return None


def _to_count(value: Any) -> int | None:
    """Strict whole number that must be >= 0 (days on market); else None."""
    number = _to_int(value)
    return number if number is not None and number >= 0 else None


def _to_year(value: Any) -> int | None:
    """Strict whole-number year, None when before MIN_YEAR_BUILT (e.g. a stored 0)."""
    year = _to_int(value)
    return year if year is not None and year >= MIN_YEAR_BUILT else None


def _to_float(value: Any) -> float | None:
    """Return a finite float from a number or decimal text; else None."""
    number = _to_decimal(value, _NUM_TEXT)
    return None if number is None else float(number)


def _to_zip(value: Any) -> str | None:
    """Return the five-digit code from "90210", "90210-1234", or "902101234".

    Anything else becomes None.
    """
    text = _to_str(value)
    match = _ZIP.fullmatch(text) if text else None
    return match.group(1) if match else None


def _to_date(value: Any) -> date | None:
    """Return a date from a date, datetime, or text starting YYYY-MM-DD; else None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _to_str(value)
    if text is None or not _DATE_PREFIX.match(text):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_datetime(value: Any) -> datetime | None:
    """Return a datetime as is, or parse text starting YYYY-MM-DD HH:MM:SS, or None."""
    if isinstance(value, datetime):
        return value
    text = _to_str(value)
    if text is None or not _DATETIME_PREFIX.match(text):
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def _to_flag(value: Any) -> bool | None:
    """Return a yes/no flag via parse_flag: "1" yes, "" no, None unknown."""
    if value is None:
        return None
    return parse_flag(str(value))


# --- Row readers: (row, primary column) in, canonical value out. ---

# Reads one field from a row, given the row and the field's primary source column.
Reader = Callable[[Row, str], Any]

# Each coordinate column and the column holding the other half of its pair.
_COORD_PARTNER = {
    "LMD_MP_Latitude": "LMD_MP_Longitude",
    "LMD_MP_Longitude": "LMD_MP_Latitude",
    "Latitude": "Longitude",
    "Longitude": "Latitude",
}


def _col(fn: Callable[[Any], Any]) -> Reader:
    """Wrap a scalar coercion so it reads the primary column from the row."""

    def read(row: Row, column: str) -> Any:
        """Apply the wrapped coercion to row[column] (missing -> None)."""
        return fn(row.get(column))

    return read


def _coord(row: Row, column: str) -> float | None:
    """Return this coordinate, or None when it or its partner is missing or zero."""
    value = _to_float(row.get(column))
    partner = _to_float(row.get(_COORD_PARTNER[column]))
    if not value or not partner:
        return None
    return value


def _hoa_monthly(row: Row, column: str) -> int | None:
    """Return AssociationFee (rounded) only when its frequency is Monthly, else None.

    The sold table has no frequency column, so a sold row always gives None.
    """
    frequency = _to_str(row.get("AssociationFeeFrequency"))
    if frequency is None or frequency.lower() != "monthly":
        return None
    return _to_rounded_int(row.get(column))


def _photo_count(row: Row, column: str) -> int:
    """Return PhotoCount; if None, the length of the L_Photos JSON array; else 0."""
    count = _to_count(row.get(column))
    if count is not None:
        return count
    raw = _to_str(row.get("L_Photos"))
    try:
        photos = json.loads(raw) if raw else None
    except ValueError:
        photos = None
    return len(photos) if isinstance(photos, list) else 0


def _close_date(row: Row, column: str) -> date | None:
    """Return close_date_d when present, else the CloseDate text parsed as a date."""
    return _to_date(row.get(column)) or _to_date(row.get("CloseDate"))


class FieldSpec(NamedTuple):
    """One canonical field: source column per table, reader, note, models using it.

    `rets` / `sold` is None only when that table has no such column. `models`
    names the models filled from this row; `*_extra` are companion columns read.
    """

    canonical: str
    rets: str | None
    sold: str | None
    coerce: Reader
    note: str
    models: tuple[str, ...] = ()
    rets_extra: tuple[str, ...] = ()
    sold_extra: tuple[str, ...] = ()


# Which models a row fills: both, Listing only, SoldComp only, or none yet.
_BOTH = ("Listing", "SoldComp")
_LISTING = ("Listing",)
_SOLD = ("SoldComp",)

# The canonical map. Names match Listing / SoldComp fields where a model reads them.
FIELD_MAP: tuple[FieldSpec, ...] = (
    FieldSpec("listing_key", "L_ListingID", "ListingKey", _col(_to_int),
              "join key; active side is text cast to int", models=_BOTH),
    FieldSpec("listing_id", "L_DisplayId", None, _col(_to_str),
              "public id; active table only", models=_LISTING),
    FieldSpec("address", "L_Address", "UnparsedAddress", _col(_to_str),
              "free text; no display-flag columns exist in either table",
              models=_BOTH),
    FieldSpec("city", "L_City", "City", _col(_to_str),
              "kept as stored; value-set checks happen on user filters", models=_BOTH),
    FieldSpec("postal_code", "L_Zip", "PostalCode", _col(_to_zip),
              "five digits, optional +4 dropped; anything else -> None", models=_BOTH),
    FieldSpec("list_price", "L_SystemPrice", "ListPrice", _col(_to_rounded_int),
              "int in active, double in sold; rounded half-even", models=_BOTH),
    FieldSpec("original_list_price", None, "OriginalListPrice",
              _col(_to_rounded_int), "sold only; rounded half-even", models=_SOLD),
    FieldSpec("close_price", None, "ClosePrice", _col(_to_rounded_int),
              "sold only; double, rounded half-even", models=_SOLD),
    FieldSpec("close_date", None, "close_date_d", _close_date,
              "generated DATE column; falls back to CloseDate text",
              models=_SOLD, sold_extra=("CloseDate",)),
    FieldSpec("listing_contract_date", "ListingContractDate", "ListingContractDate",
              _col(_to_date), "date in active, text in sold; no model reads it yet"),
    FieldSpec("purchase_contract_date", None, "PurchaseContractDate", _col(_to_date),
              "sold only, text; no model reads it yet"),
    FieldSpec("modification_timestamp", "ModificationTimestamp", None,
              _col(_to_datetime), "active as-of source; no model reads it yet"),
    FieldSpec("bedrooms", "L_Keyword2", "BedroomsTotal", _col(_to_int),
              "double in sold; whole numbers only", models=_BOTH),
    FieldSpec("bathrooms", "LM_Dec_3", "BathroomsTotalInteger", _col(_to_float),
              "different definitions per table; never compared; SoldComp omits it",
              models=_LISTING),
    FieldSpec("living_area", "LM_Int2_3", "LivingArea", _col(_to_rounded_int),
              "square feet; rounded half-even", models=_BOTH),
    FieldSpec("lot_size_sqft", "LotSizeSquareFeet", "LotSizeSquareFeet",
              _col(_to_rounded_int), "square feet; no model reads it yet"),
    FieldSpec("property_subtype", "L_Type_", "PropertySubType", _col(_to_str),
              "same RESO vocabulary in both tables", models=_BOTH),
    FieldSpec("status", "StandardStatus", None, _col(_to_str),
              "active only; sold rows are closed by definition", models=_LISTING),
    FieldSpec("year_built", "YearBuilt", "YearBuilt", _col(_to_year),
              "double in sold; before 1800 (e.g. 0) -> None", models=_BOTH),
    FieldSpec("hoa_fee_monthly", "AssociationFee", "AssociationFee", _hoa_monthly,
              "Monthly frequency only; other frequencies not converted yet",
              models=_LISTING, rets_extra=("AssociationFeeFrequency",)),
    FieldSpec("days_on_market", "DaysOnMarket", "DaysOnMarket", _col(_to_count),
              "as stored at the data pull; negative -> None", models=_BOTH),
    FieldSpec("photo_count", "PhotoCount", None, _photo_count,
              "falls back to the L_Photos JSON array length", models=_LISTING,
              rets_extra=("L_Photos",)),
    FieldSpec("latitude", "LMD_MP_Latitude", "Latitude", _coord,
              "pair is None if either half is missing or 0", models=_LISTING,
              rets_extra=("LMD_MP_Longitude",), sold_extra=("Longitude",)),
    FieldSpec("longitude", "LMD_MP_Longitude", "Longitude", _coord,
              "pair is None if either half is missing or 0", models=_LISTING,
              rets_extra=("LMD_MP_Latitude",), sold_extra=("Latitude",)),
    FieldSpec("pool", "PoolPrivateYN", "PoolPrivateYN", _col(_to_flag),
              "'1' yes, '' not marked, null unknown", models=_LISTING),
    FieldSpec("view", "ViewYN", "ViewYN", _col(_to_flag),
              "'1' yes, '' not marked, null unknown", models=_LISTING),
    FieldSpec("fireplace", "FireplaceYN", "FireplaceYN", _col(_to_flag),
              "'1' yes, '' not marked, null unknown", models=_LISTING),
    FieldSpec("remarks", "L_Remarks", None, _col(_to_str),
              "untrusted text; never logged", models=_LISTING),
)  # fmt: skip


def _specs(model: str) -> tuple[FieldSpec, ...]:
    """Return the FIELD_MAP rows that fill the named model."""
    return tuple(spec for spec in FIELD_MAP if model in spec.models)


def _columns(table: str, side: str, model: str) -> tuple[str, ...]:
    """Return the unique source columns one model reads, each through check_column.

    `side` is "rets" or "sold"; order follows FIELD_MAP. Raises ValueError if a
    name is not allowlisted for the table.
    """
    names: list[str] = []
    for spec in _specs(model):
        for name in (getattr(spec, side), *getattr(spec, f"{side}_extra")):
            if name not in names:
                names.append(check_column(table, name))
    return tuple(names)


def listing_columns() -> tuple[str, ...]:
    """Return exactly the rets_property columns to_listing reads, all allowlisted."""
    return _columns("rets_property", "rets", "Listing")


def sold_columns() -> tuple[str, ...]:
    """Return exactly the california_sold columns to_sold_comp reads (allowlisted)."""
    return _columns("california_sold", "sold", "SoldComp")


def to_listing(row: Row) -> Listing:
    """Build a Listing from a rets_property row; unmapped keys are ignored.

    Raises pydantic ValidationError when a required value (key, id, price) is
    missing or invalid after coercion.
    """
    return Listing(**{s.canonical: s.coerce(row, s.rets) for s in _specs("Listing")})


def to_sold_comp(row: Row) -> SoldComp:
    """Build a SoldComp from a california_sold row; unmapped keys are ignored.

    Raises pydantic ValidationError when a required value (key, close date,
    close price) is missing or invalid after coercion.
    """
    values = {s.canonical: s.coerce(row, s.sold) for s in _specs("SoldComp")}
    return SoldComp(**values)
