"""The merge table (WO-006 req. 1, 2, 3, 5) as a parametrized case list.

Each row: previous filters (or None), the update, the mode, `clear`, and either the
exact filters expected or the Clarification reason. All values are invented.
"""

import pytest

from idx_agent.domain.models import Clarification, PropertySearchFilters
from idx_agent.memory import merge_filters, next_page

# The last accepted search most rows refine: Pasadena, up to $1.5M, 3+ beds, page 2.
PASADENA = {"city": "Pasadena", "max_price": 1_500_000, "min_beds": 3, "page": 2}
ZIP_SEARCH = {"postal_code": "91101", "max_price": 900_000}
FILTER_NAMES = sorted(PropertySearchFilters.model_fields)

# (id, previous, update, mode, clear, expected filters dict or Clarification reason)
TABLE = [
    (
        "update overwrites a field",
        PASADENA,
        {"max_price": 1_200_000},
        "update",
        (),
        {"city": "Pasadena", "max_price": 1_200_000, "min_beds": 3},
    ),
    (
        "update keeps every other field",
        PASADENA,
        {"property_subtype": "Condominium"},
        "update",
        (),
        {
            "city": "Pasadena",
            "max_price": 1_500_000,
            "min_beds": 3,
            "property_subtype": "Condominium",
        },
    ),
    (
        "update with no changes keeps the fields and resets the page",
        PASADENA,
        {},
        "update",
        (),
        {"city": "Pasadena", "max_price": 1_500_000, "min_beds": 3},
    ),
    (
        "update that sets the page keeps it",
        PASADENA,
        {"page": 4},
        "update",
        (),
        {"city": "Pasadena", "max_price": 1_500_000, "min_beds": 3, "page": 4},
    ),
    (
        "update keeps a previous limit",
        {**PASADENA, "limit": 10},
        {"min_beds": 4},
        "update",
        (),
        {"city": "Pasadena", "max_price": 1_500_000, "min_beds": 4, "limit": 10},
    ),
    (
        "update sets pool false, not unset",
        PASADENA,
        {"pool": False},
        "update",
        (),
        {"city": "Pasadena", "max_price": 1_500_000, "min_beds": 3, "pool": False},
    ),
    (
        "None in the update means not given",
        PASADENA,
        {"max_price": None, "min_beds": None, "city": None},
        "update",
        (),
        {"city": "Pasadena", "max_price": 1_500_000, "min_beds": 3},
    ),
    (
        "clear unsets a field",
        PASADENA,
        {},
        "update",
        ("min_beds",),
        {"city": "Pasadena", "max_price": 1_500_000},
    ),
    (
        "clear given as one string",
        PASADENA,
        {},
        "update",
        "max_price",
        {"city": "Pasadena", "min_beds": 3},
    ),
    (
        "clear and set the same field: the update wins",
        PASADENA,
        {"max_price": 1_000_000},
        "update",
        ("max_price",),
        {"city": "Pasadena", "max_price": 1_000_000, "min_beds": 3},
    ),
    (
        "clear the only location asks for one",
        PASADENA,
        {},
        "update",
        ("city",),
        "missing_location",
    ),
    (
        "city replaces ZIP",
        ZIP_SEARCH,
        {"city": "Glendale"},
        "update",
        (),
        {"city": "Glendale", "max_price": 900_000},
    ),
    (
        "ZIP replaces city",
        PASADENA,
        {"postal_code": "91101"},
        "update",
        (),
        {"postal_code": "91101", "max_price": 1_500_000, "min_beds": 3},
    ),
    (
        "update with no previous behaves as replace",
        None,
        {"city": "Arcadia", "min_beds": 2},
        "update",
        (),
        {"city": "Arcadia", "min_beds": 2},
    ),
    (
        "update with no previous and no location asks for one",
        None,
        {"property_subtype": "Condominium"},
        "update",
        (),
        "missing_location",
    ),
    (
        "replace ignores previous",
        PASADENA,
        {"city": "Arcadia"},
        "replace",
        (),
        {"city": "Arcadia"},
    ),
    (
        "replace without a location asks for one",
        PASADENA,
        {"max_price": 800_000},
        "replace",
        (),
        "missing_location",
    ),
    (
        "reset drops previous and uses the update",
        PASADENA,
        {"city": "Arcadia", "max_price": 700_000},
        "reset",
        (),
        {"city": "Arcadia", "max_price": 700_000},
    ),
    (
        "reset with an empty update has nothing to search",
        PASADENA,
        {},
        "reset",
        (),
        "missing_location",
    ),
    (
        "merged conflict: new max below the old min",
        {"city": "Pasadena", "min_price": 800_000},
        {"max_price": 500_000},
        "update",
        (),
        "min_above_max",
    ),
    (
        "merged value out of range",
        PASADENA,
        {"min_beds": 25},
        "update",
        (),
        "above_maximum",
    ),
    (
        "unknown city in the update",
        PASADENA,
        {"city": "Not A Real Place"},
        "update",
        (),
        "unknown_city",
    ),
    (
        "unknown key in the update",
        PASADENA,
        {"garage_spaces": 2},
        "update",
        (),
        "unsupported_filter",
    ),
    (
        "bad clear name",
        PASADENA,
        {},
        "update",
        ("garage_spaces",),
        "unsupported_filter",
    ),
    (
        "bad clear name in replace mode",
        PASADENA,
        {"city": "Arcadia"},
        "replace",
        ("garage_spaces",),
        "unsupported_filter",
    ),
]


def _previous(raw):
    return None if raw is None else PropertySearchFilters.model_validate(raw)


@pytest.mark.parametrize(
    ("previous", "update", "mode", "clear", "expected"),
    [row[1:] for row in TABLE],
    ids=[row[0] for row in TABLE],
)
def test_merge_table(previous, update, mode, clear, expected):
    result = merge_filters(_previous(previous), update, mode, clear)
    if isinstance(expected, str):
        assert isinstance(result, Clarification)
        assert result.reason == expected
    else:
        assert isinstance(result, PropertySearchFilters)
        assert result == PropertySearchFilters.model_validate(expected)


def test_bad_clear_name_names_the_field_and_lists_the_filters():
    result = merge_filters(_previous(PASADENA), {}, "update", ("garage_spaces",))
    assert isinstance(result, Clarification)
    assert result.field == "garage_spaces"
    assert result.reason == "unsupported_filter"
    assert result.options == FILTER_NAMES


def test_bad_clear_name_that_is_not_snake_case_is_not_echoed():
    result = merge_filters(_previous(PASADENA), {}, "update", ("DROP TABLE x",))
    assert isinstance(result, Clarification)
    assert result.field == "unknown"
    assert result.reason == "unsupported_filter"
    assert "DROP" not in result.question
    assert result.options == FILTER_NAMES


def test_merged_conflict_is_returned_not_raised():
    previous = _previous({"city": "Pasadena", "min_price": 800_000})
    result = merge_filters(previous, {"max_price": 500_000}, "update")
    assert isinstance(result, Clarification)
    assert result.field == "min_price"


def test_merge_keeps_the_stored_city_spelling():
    result = merge_filters(None, {"city": "  pasadena "}, "replace")
    assert isinstance(result, PropertySearchFilters)
    assert result.city == "Pasadena"


def test_merge_does_not_change_the_previous_object():
    previous = _previous(PASADENA)
    before = previous.model_dump()
    merge_filters(previous, {"city": "Arcadia"}, "update", ("min_beds",))
    assert previous.model_dump() == before


def test_unknown_mode_is_a_programmer_error():
    with pytest.raises(ValueError):
        merge_filters(None, {"city": "Pasadena"}, "more")  # type: ignore[arg-type]


@pytest.mark.parametrize("page", [1, 2, 7])
def test_next_page_increments_and_keeps_the_filters(page):
    previous = _previous({**PASADENA, "page": page, "limit": 10})
    result = next_page(previous)
    assert isinstance(result, PropertySearchFilters)
    assert result == previous.model_copy(update={"page": page + 1})


def test_next_page_past_the_last_page_is_a_clarification():
    previous = _previous({**PASADENA, "page": 1000})
    result = next_page(previous)
    assert isinstance(result, Clarification)
    assert result.field == "page"
    assert result.reason == "above_maximum"
