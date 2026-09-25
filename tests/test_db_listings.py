"""Unit tests for db/listings.py; no database.

The SQL builder is checked as (sql, params): allowlisted columns only, every value
bound, one clause per filter, clamp and pagination. The executor runs on a fake
connection with invented rows.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from idx_agent.db import listings
from idx_agent.db.listings import (
    MAX_ROWS,
    build_candidate_sql,
    build_count_sql,
    build_remarks_length_sql,
    build_search_sql,
    count_active_listings,
    fetch_candidates,
    fetch_remarks_length,
    search_active_listings,
)
from idx_agent.domain.fieldmap import listing_columns
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.safety.columns import AGENT_CONTACT, ALLOWLIST, DENYLIST

# SQL words and names the builder may emit besides rets_property columns.
_SQL_WORDS = {
    "SELECT",
    "FROM",
    "WHERE",
    "AND",
    "OR",
    "IN",
    "LIKE",
    "COALESCE",
    "ORDER",
    "BY",
    "ASC",
    "LIMIT",
    "OFFSET",
    "rets_property",
    "s",  # from the %s placeholders
}

# Every filter set to a distinctive, invented value.
ALL_FILTERS = {
    "city": "Pasadena",
    "postal_code": "91106",
    "min_price": 123457,
    "max_price": 987653,
    "min_beds": 7,
    "min_baths": 4.5,
    "min_sqft": 1789,
    "property_subtype": "Townhouse",
    "pool": True,
    "view": False,
    "max_hoa_monthly": 412,
}


def _where_clauses(sql: str) -> list[str]:
    """Split the WHERE line on top-level AND (ANDs inside parentheses stay put)."""
    where = re.search(r"^WHERE (.*)$", sql, re.MULTILINE).group(1)
    clauses, depth, start = [], 0, 0
    for i, char in enumerate(where):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and where.startswith(" AND ", i):
            clauses.append(where[start:i])
            start = i + len(" AND ")
    clauses.append(where[start:])
    return clauses


def _pasadena(**extra: Any) -> PropertySearchFilters:
    """The WO-004 example: 3+ beds in Pasadena at or under 1.5M, plus extras."""
    return PropertySearchFilters(
        city="Pasadena", min_beds=3, max_price=1_500_000, **extra
    )


# --- build_search_sql: columns and allowlist ---


def test_select_list_is_exactly_listing_columns():
    sql = build_search_sql(_pasadena()).sql
    selected = re.search(r"^SELECT (.*)$", sql, re.MULTILINE).group(1).split(", ")
    assert tuple(selected) == listing_columns()
    assert "*" not in sql


def test_every_identifier_in_the_sql_is_allowlisted():
    sql = build_search_sql(PropertySearchFilters(**ALL_FILTERS)).sql
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)) - _SQL_WORDS
    assert names <= ALLOWLIST["rets_property"]
    assert not names & (DENYLIST | AGENT_CONTACT)


@pytest.mark.parametrize(
    "bad", ["NotAColumn", "ListAgentEmail", "PrivateRemarks", "L_Remarks; DROP"]
)
def test_a_column_outside_the_allowlist_raises(monkeypatch, bad):
    monkeypatch.setattr(listings, "listing_columns", lambda: ("L_ListingID", bad))
    with pytest.raises(ValueError):
        build_search_sql(_pasadena())


# --- build_search_sql: parameters ---


def test_status_is_a_bound_parameter():
    query = build_search_sql(_pasadena())
    assert _where_clauses(query.sql)[0] == "StandardStatus = %s"
    assert query.params[0] == "Active"
    assert "Active" not in query.sql


def test_pasadena_example_params():
    query = build_search_sql(_pasadena())
    assert query.params == ("Active", "Pasadena", 1_500_000, 3, 5, 0)
    assert query.warnings == []


@pytest.mark.parametrize(
    ("name", "value", "expected_params"),
    [
        ("city", "Pasadena", ("Pasadena",)),
        ("postal_code", "91106", ("91106%",)),
        ("min_price", 400_000, (400_000,)),
        ("max_price", 900_000, (900_000,)),
        ("min_beds", 3, (3,)),
        ("min_baths", 2.5, (2.5,)),
        ("min_sqft", 1500, (1500,)),
        ("property_subtype", "Condominium", ("Condominium",)),
        ("pool", True, ("1",)),
        ("pool", False, ("1",)),
        ("view", True, ("1",)),
        ("view", False, ("1",)),
        # The HOA clause binds the Monthly frequency too, so it adds two params.
        ("max_hoa_monthly", 300, ("Monthly", 300)),
    ],
)
def test_each_filter_adds_one_clause_and_its_params(name, value, expected_params):
    base = build_search_sql(PropertySearchFilters())
    query = build_search_sql(PropertySearchFilters(**{name: value}))
    assert len(_where_clauses(base.sql)) == 1
    assert len(_where_clauses(query.sql)) == 2
    assert query.params == ("Active", *expected_params, 5, 0)
    assert query.sql.count("%s") == len(query.params)


def test_flag_false_matches_anything_but_yes():
    clause = _where_clauses(build_search_sql(PropertySearchFilters(pool=False)).sql)[1]
    assert clause == "COALESCE(PoolPrivateYN, '') <> %s"


def test_hoa_limit_applies_to_monthly_fees_only():
    sql = build_search_sql(PropertySearchFilters(max_hoa_monthly=300)).sql
    clause = _where_clauses(sql)[1]
    assert "AssociationFeeFrequency = %s AND AssociationFee <= %s" in clause


def test_no_filter_value_appears_in_the_sql_text():
    query = build_search_sql(PropertySearchFilters(**ALL_FILTERS))
    for name, value in ALL_FILTERS.items():
        if isinstance(value, bool):
            continue
        pattern = rf"(?<![\w.]){re.escape(str(value))}(?![\w.])"
        assert not re.search(pattern, query.sql), name
    assert len(_where_clauses(query.sql)) == 1 + len(ALL_FILTERS)
    assert query.sql.count("%s") == len(query.params)


def test_injection_text_stays_in_params():
    hostile = "Pasadena' OR '1'='1"
    subtype = "x'; DROP TABLE rets_property; --"
    filters = PropertySearchFilters.model_construct(
        city=hostile, property_subtype=subtype, page=1, limit=5
    )
    query = build_search_sql(filters)
    assert "DROP" not in query.sql and "'1'" not in query.sql
    assert hostile in query.params and subtype in query.params


def test_malformed_postal_code_raises_before_any_sql():
    filters = PropertySearchFilters.model_construct(postal_code="9%", page=1, limit=5)
    with pytest.raises(ValueError):
        build_search_sql(filters)


# --- build_search_sql: limit, pagination, order ---


def test_limit_above_cap_is_clamped_with_a_warning():
    filters = PropertySearchFilters.model_construct(city="Pasadena", page=1, limit=500)
    query = build_search_sql(filters)
    assert query.params[-2:] == (MAX_ROWS, 0)
    assert len(query.warnings) == 1 and str(MAX_ROWS) in query.warnings[0]


def test_limit_at_cap_has_no_warning():
    query = build_search_sql(PropertySearchFilters(city="Pasadena", limit=MAX_ROWS))
    assert query.params[-2:] == (MAX_ROWS, 0)
    assert query.warnings == []


@pytest.mark.parametrize(
    ("page", "limit", "offset"), [(1, 5, 0), (2, 5, 5), (3, 10, 20)]
)
def test_offset_is_page_minus_one_times_limit(page, limit, offset):
    query = build_search_sql(_pasadena(page=page, limit=limit))
    assert query.params[-2:] == (limit, offset)
    assert all(type(p) is int for p in query.params[-2:])
    assert query.sql.endswith("LIMIT %s OFFSET %s")


def test_order_is_deterministic_price_then_ids():
    sql = build_search_sql(_pasadena()).sql
    assert "ORDER BY L_SystemPrice ASC, L_ListingID ASC, L_DisplayId ASC" in sql


def test_city_only_filters_use_the_stored_spelling():
    query = build_search_sql(PropertySearchFilters(city="  pasadena "))
    assert _where_clauses(query.sql) == ["StandardStatus = %s", "L_City = %s"]
    assert query.params == ("Active", "Pasadena", 5, 0)


# --- search_active_listings on a fake connection ---


class FakeCursor:
    """Records the executed query and returns the connection's rows."""

    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.conn.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.conn.rows)


class FakeConnection:
    """Stands in for a pymysql connection that returns fixed dict rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


# Invented remarks text; the test checks it is never printed or put in a warning.
REMARK = "invented remark text for a unit test"


def _row(key: str, price: Any) -> dict[str, Any]:
    """An invented rets_property row in source column names."""
    return {
        "L_ListingID": key,
        "L_DisplayId": f"TST{key}",
        "L_Address": "100 Example Way",
        "L_City": "Pasadena",
        "L_Zip": "91106-0000",
        "L_SystemPrice": price,
        "L_Keyword2": 3,
        "LM_Dec_3": 2.0,
        "LM_Int2_3": 1600,
        "L_Type_": "SingleFamilyResidence",
        "StandardStatus": "Active",
        "PoolPrivateYN": "",
        "ViewYN": "1",
        "L_Remarks": REMARK,
    }


def test_search_maps_rows_and_skips_invalid_ones(capsys):
    rows = [_row("1001", 900_000), _row("1002", None), _row("1003", 1_200_000)]
    conn = FakeConnection(rows)
    filters = _pasadena()
    outcome = search_active_listings(filters, conn)
    assert [item.listing_key for item in outcome.listings] == [1001, 1003]
    assert outcome.listings[0].postal_code == "91106"
    assert outcome.skipped_rows == 1
    assert len(outcome.warnings) == 1
    query = build_search_sql(filters)
    assert conn.executed == [(query.sql, query.params)]
    # The db layer writes nothing (the project logger writes to stderr), and the
    # skip warning names a count, never the skipped row's text.
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert REMARK not in outcome.warnings[0]


def test_search_carries_the_clamp_warning():
    filters = PropertySearchFilters.model_construct(city="Pasadena", page=1, limit=500)
    outcome = search_active_listings(filters, FakeConnection([_row("1001", 900_000)]))
    assert outcome.skipped_rows == 0
    assert len(outcome.listings) == 1
    assert len(outcome.warnings) == 1


# --- count (WO-006) ---


def test_count_has_the_search_where_and_params_minus_limit_and_offset():
    """Same WHERE text and params as the search, without LIMIT/OFFSET or ORDER BY."""
    filters = PropertySearchFilters(**ALL_FILTERS, page=3, limit=7)
    search = build_search_sql(filters)
    count = build_count_sql(filters)
    assert _where_clauses(count.sql) == _where_clauses(search.sql)
    assert count.params == search.params[:-2]
    assert search.params[-2:] == (7, 14)
    assert "LIMIT" not in count.sql and "ORDER BY" not in count.sql
    assert count.sql.startswith("SELECT COUNT(*) AS total_matches\nFROM rets_property")


def test_count_names_only_allowlisted_columns_and_binds_every_value():
    count = build_count_sql(PropertySearchFilters(**ALL_FILTERS))
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", count.sql))
    names -= _SQL_WORDS | {"COUNT", "AS", "total_matches"}
    assert names <= ALLOWLIST["rets_property"]
    for value in ALL_FILTERS.values():
        if isinstance(value, str):
            assert value not in count.sql


def test_count_reads_a_dict_row_or_a_tuple_row_and_runs_one_query():
    filters = _pasadena()
    conn = FakeConnection([{"total_matches": 57}])
    assert count_active_listings(filters, conn) == 57
    query = build_count_sql(filters)
    assert conn.executed == [(query.sql, query.params)]
    assert count_active_listings(filters, FakeConnection([(8,)])) == 8
    assert count_active_listings(filters, FakeConnection([])) == 0


# --- WO-010: search and count unchanged by the shared candidate builder ---

# Recorded from build_search_sql and build_count_sql before WO-010 touched the
# module (every filter set, page 3, limit 7): the shared WHERE must not move a byte.
_WHERE_BEFORE = (
    "WHERE StandardStatus = %s AND L_City = %s AND L_SystemPrice >= %s "
    "AND L_SystemPrice <= %s AND L_Keyword2 >= %s AND LM_Dec_3 >= %s "
    "AND LM_Int2_3 >= %s AND L_Type_ = %s AND L_Zip LIKE %s AND PoolPrivateYN = %s "
    "AND COALESCE(ViewYN, '') <> %s AND (COALESCE(AssociationFee, 0) = 0 "
    "OR (AssociationFeeFrequency = %s AND AssociationFee <= %s))"
)
_SEARCH_SQL_BEFORE = (
    "SELECT L_ListingID, L_DisplayId, L_Address, L_City, L_Zip, L_SystemPrice, "
    "L_Keyword2, LM_Dec_3, LM_Int2_3, L_Type_, StandardStatus, YearBuilt, "
    "AssociationFee, AssociationFeeFrequency, DaysOnMarket, PhotoCount, L_Photos, "
    "LMD_MP_Latitude, LMD_MP_Longitude, PoolPrivateYN, ViewYN, FireplaceYN, "
    "L_Remarks\nFROM rets_property\n"
    f"{_WHERE_BEFORE}\n"
    "ORDER BY L_SystemPrice ASC, L_ListingID ASC, L_DisplayId ASC\n"
    "LIMIT %s OFFSET %s"
)
_COUNT_SQL_BEFORE = (
    f"SELECT COUNT(*) AS total_matches\nFROM rets_property\n{_WHERE_BEFORE}"
)
_PARAMS_BEFORE = (
    "Active",
    "Pasadena",
    123457,
    987653,
    7,
    4.5,
    1789,
    "Townhouse",
    "91106%",
    "1",
    "1",
    "Monthly",
    412,
)


def test_search_and_count_sql_are_byte_identical_to_before_wo010():
    filters = PropertySearchFilters(**ALL_FILTERS, page=3, limit=7)
    search = build_search_sql(filters)
    count = build_count_sql(filters)
    assert search.sql == _SEARCH_SQL_BEFORE
    assert search.params == (*_PARAMS_BEFORE, 7, 14)
    assert search.warnings == []
    assert count.sql == _COUNT_SQL_BEFORE
    assert count.params == _PARAMS_BEFORE


# --- WO-010: build_candidate_sql ---

KEYS = [9100007, 9100003, 9100001]


def test_candidate_sql_shares_the_search_where_then_adds_the_keys():
    filters = _pasadena()
    candidate = build_candidate_sql(filters, KEYS)
    search = build_search_sql(filters)
    clauses = _where_clauses(candidate.sql)
    assert clauses[:-1] == _where_clauses(search.sql)
    assert clauses[-1] == "L_ListingID IN (%s, %s, %s)"
    assert candidate.params == (
        *search.params[:-2],
        "9100007",
        "9100003",
        "9100001",
        MAX_ROWS,
    )
    assert candidate.sql.count("%s") == len(candidate.params)
    assert candidate.sql.endswith("\nLIMIT %s") and candidate.params[-1] == 50
    assert "OFFSET" not in candidate.sql
    assert "ORDER BY L_ListingID ASC, ModificationTimestamp DESC" in candidate.sql


def test_candidate_sql_selects_listing_columns_without_remarks():
    sql = build_candidate_sql(PropertySearchFilters(), KEYS).sql
    selected = re.search(r"^SELECT (.*)$", sql, re.MULTILINE).group(1).split(", ")
    assert tuple(selected) == tuple(c for c in listing_columns() if c != "L_Remarks")
    assert "L_Remarks" not in sql and "*" not in sql


def test_candidate_sql_names_only_allowlisted_columns_and_no_agent_column():
    sql = build_candidate_sql(PropertySearchFilters(**ALL_FILTERS), KEYS).sql
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)) - _SQL_WORDS - {"DESC"}
    assert names <= ALLOWLIST["rets_property"]
    assert not names & (DENYLIST | AGENT_CONTACT)
    for column in AGENT_CONTACT | DENYLIST:
        assert column not in sql


def test_candidate_sql_binds_keys_and_filter_values():
    hostile = "Pasadena' OR '1'='1"
    subtype = "x'; DROP TABLE rets_property; --"
    filters = PropertySearchFilters.model_construct(
        city=hostile, property_subtype=subtype, page=1, limit=5
    )
    query = build_candidate_sql(filters, KEYS)
    assert "DROP" not in query.sql and "'1'" not in query.sql
    assert hostile in query.params and subtype in query.params
    for key in KEYS:
        assert str(key) not in query.sql


@pytest.mark.parametrize(
    "keys",
    [
        [],
        list(range(1, 52)),
        ["9100001 OR 1=1"],
        ["9100001"],
        [1.5],
        [True],
        [-1],
        [9100001, 9100001],
        [None],
    ],
    ids=["none", "51", "injection", "text", "float", "bool", "negative", "dup", "null"],
)
def test_candidate_sql_refuses_bad_key_lists(keys):
    with pytest.raises(ValueError):
        build_candidate_sql(PropertySearchFilters(), keys)


def test_candidate_sql_accepts_fifty_keys_and_numpy_style_integers():
    class Int64Like:
        """Stands in for a NumPy int64: an integer through __index__ only."""

        def __init__(self, value: int) -> None:
            self.value = value

        def __index__(self) -> int:
            return self.value

    query = build_candidate_sql(
        PropertySearchFilters(), [Int64Like(k) for k in range(1, 51)]
    )
    assert query.params[1:-1] == tuple(str(k) for k in range(1, 51))


def test_candidate_sql_raises_on_a_column_outside_the_allowlist(monkeypatch):
    monkeypatch.setattr(listings, "listing_columns", lambda: ("L_ListingID", "Nope"))
    with pytest.raises(ValueError):
        build_candidate_sql(PropertySearchFilters(), KEYS)
    monkeypatch.setattr(
        listings, "listing_columns", lambda: ("L_ListingID", "ListAgentEmail")
    )
    with pytest.raises(ValueError):
        build_candidate_sql(PropertySearchFilters(), KEYS)


# --- WO-010: fetch_candidates on a fake connection ---


def test_fetch_candidates_keeps_key_order_whatever_sql_returns(capsys):
    rows = [_row("9100001", 800_000), _row("9100003", 700_000), _row("9100007", 1)]
    conn = FakeConnection(rows)
    outcome = fetch_candidates(_pasadena(), KEYS, conn)
    assert [x.listing_key for x in outcome.listings] == KEYS
    query = build_candidate_sql(_pasadena(), KEYS)
    assert conn.executed == [(query.sql, query.params)]
    assert outcome.warnings == [] and outcome.skipped_rows == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_fetch_candidates_leaves_out_keys_sql_did_not_return():
    rows = [_row("9100003", 700_000)]
    outcome = fetch_candidates(_pasadena(), KEYS, FakeConnection(rows))
    assert [x.listing_key for x in outcome.listings] == [9100003]


def test_fetch_candidates_skips_invalid_rows_and_keeps_the_first_of_a_repeat():
    first = _row("9100001", 800_000)
    later = dict(_row("9100001", 900_000), L_DisplayId="TSTOLDER")
    rows = [_row("9100003", None), first, later]
    outcome = fetch_candidates(_pasadena(), KEYS, FakeConnection(rows))
    assert [x.listing_id for x in outcome.listings] == ["TST9100001"]
    assert outcome.skipped_rows == 1 and len(outcome.warnings) == 1
    assert REMARK not in outcome.warnings[0]


def test_fetch_candidates_raises_over_fifty_rows():
    rows = [_row(str(9100001), 800_000)] * (MAX_ROWS + 1)
    with pytest.raises(ValueError):
        fetch_candidates(_pasadena(), [9100001], FakeConnection(rows))


def test_fetch_candidates_raises_on_a_key_not_asked_for():
    rows = [_row("4242", 800_000)]
    with pytest.raises(ValueError):
        fetch_candidates(_pasadena(), KEYS, FakeConnection(rows))


# --- WO-011: the remark-length statement (a length, never the text) ---

REMARKS_LENGTH_SQL = (
    "SELECT CHAR_LENGTH(L_Remarks) AS n\n"
    "FROM rets_property\n"
    "WHERE StandardStatus = %s AND L_ListingID = %s\n"
    "ORDER BY ModificationTimestamp DESC, L_DisplayId ASC\n"
    "LIMIT 1"
)


def test_remarks_length_sql_is_pinned_and_binds_the_key_as_text():
    sql, params = build_remarks_length_sql(9100001)
    assert sql == REMARKS_LENGTH_SQL
    assert params == ("Active", "9100001")
    assert sql.count("%s") == len(params) and "9100001" not in sql


def test_remarks_length_sql_selects_the_remarks_length_alone():
    sql, _ = build_remarks_length_sql(9100001)
    selected = re.search(r"^SELECT (.*)$", sql, re.MULTILINE).group(1)
    assert selected == "CHAR_LENGTH(L_Remarks) AS n"
    assert "*" not in sql and sql.endswith("\nLIMIT 1")
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))
    names -= _SQL_WORDS | {"DESC", "CHAR_LENGTH", "AS", "n"}
    assert names <= ALLOWLIST["rets_property"]
    assert not names & (DENYLIST | AGENT_CONTACT)
    for column in AGENT_CONTACT | DENYLIST:
        assert column not in sql


@pytest.mark.parametrize("key", [-1, True, "9100001", 1.5, "1 OR 1=1"])
def test_remarks_length_sql_refuses_a_key_that_is_not_a_whole_number(key):
    with pytest.raises(ValueError):
        build_remarks_length_sql(key)


def test_remarks_length_sql_raises_on_a_column_outside_the_allowlist(monkeypatch):
    monkeypatch.setattr(listings, "_REMARKS", "PrivateRemarks")
    with pytest.raises(ValueError):
        build_remarks_length_sql(9100001)


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([{"n": 212}], 212),
        ([(7,)], 7),
        ([{"n": 0}], 0),
        ([{"n": None}], None),
        ([], None),
    ],
    ids=["dict", "tuple", "empty", "null", "no-row"],
)
def test_fetch_remarks_length_runs_one_statement(rows, expected):
    conn = FakeConnection(rows)
    assert fetch_remarks_length(9100001, conn) == expected
    assert conn.executed == [build_remarks_length_sql(9100001)]


def test_fetch_remarks_length_raises_on_more_than_one_row():
    with pytest.raises(ValueError):
        fetch_remarks_length(9100001, FakeConnection([{"n": 1}, {"n": 2}]))
