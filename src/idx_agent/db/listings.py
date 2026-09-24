"""Active-listing search: SQL builders plus executors (WO-004, WO-006, WO-010).

`build_search_sql`, `build_count_sql`, and `build_candidate_sql` are pure and share one
WHERE builder (allowlisted columns, bound values). `search_active_listings`,
`count_active_listings`, and `fetch_candidates` (ranked keys re-checked) run them."""

from __future__ import annotations

import operator
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from idx_agent.domain.fieldmap import listing_columns, to_listing
from idx_agent.domain.models import Listing, PropertySearchFilters
from idx_agent.domain.valid_values import ACTIVE_STATUS_COLUMN, ACTIVE_STATUS_VALUES
from idx_agent.safety.columns import check_column

__all__ = [
    "MAX_ROWS",
    "SearchOutcome",
    "SearchQuery",
    "build_candidate_sql",
    "build_count_sql",
    "build_search_sql",
    "count_active_listings",
    "fetch_candidates",
    "search_active_listings",
]

MAX_ROWS = 50
_TABLE = "rets_property"
# The one stored value meaning yes in the pool and view flag columns.
_FLAG_YES = "1"
# The only fee frequency compared against a monthly HOA limit.
_MONTHLY = "Monthly"
# Sort keys: price, then listing ids, so equal prices still page in a fixed order.
_ORDER_BY = ("L_SystemPrice", "L_ListingID", "L_DisplayId")
# Simple one-value filters: (filter field, column, comparison), in clause order.
_SIMPLE_FILTERS = (
    ("city", "L_City", "="),
    ("min_price", "L_SystemPrice", ">="),
    ("max_price", "L_SystemPrice", "<="),
    ("min_beds", "L_Keyword2", ">="),
    ("min_baths", "LM_Dec_3", ">="),
    ("min_sqft", "LM_Int2_3", ">="),
    ("property_subtype", "L_Type_", "="),
)
_FIVE_DIGITS = re.compile(r"[0-9]{5}")
# Candidate fetch (WO-010): the key column, and the one listing column it never reads.
_KEY = "L_ListingID"
_REMARKS = "L_Remarks"
# A repeated key keeps its latest row, as the semantic index does.
_CANDIDATE_ORDER = ((_KEY, "ASC"), ("ModificationTimestamp", "DESC"))


@dataclass(frozen=True)
class SearchQuery:
    """A built query: SQL text with %s placeholders, bound params, clamp warnings."""

    sql: str
    params: tuple[Any, ...]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchOutcome:
    """Executed search: mapped listings, warnings, and the count of skipped rows."""

    listings: list[Listing]
    warnings: list[str] = field(default_factory=list)
    skipped_rows: int = 0


def _col(name: str) -> str:
    """Return the column name after the rets_property allowlist check (ValueError)."""
    return check_column(_TABLE, name)


def _flag_clause(column: str, wanted: bool) -> tuple[str, tuple[Any, ...]]:
    """Clause for a yes/no flag: True matches "1"; False matches anything else.

    False includes empty and NULL: both mean the feature was not marked as present.
    """
    if wanted:
        return f"{_col(column)} = %s", (_FLAG_YES,)
    return f"COALESCE({_col(column)}, '') <> %s", (_FLAG_YES,)


def _filter_clauses(
    filters: PropertySearchFilters,
) -> list[tuple[str, tuple[Any, ...]]]:
    """Return one (clause, params) pair per filter that is set, in a fixed order."""
    clauses: list[tuple[str, tuple[Any, ...]]] = []
    for name, column, op in _SIMPLE_FILTERS:
        value = getattr(filters, name)
        if value is not None:
            clauses.append((f"{_col(column)} {op} %s", (value,)))
    if filters.postal_code is not None:
        # A prefix match also finds ZIP+4 values ("91101-1234") and stays indexable.
        if not _FIVE_DIGITS.fullmatch(filters.postal_code):
            raise ValueError("postal_code must be five digits")
        clauses.append((f"{_col('L_Zip')} LIKE %s", (f"{filters.postal_code}%",)))
    if filters.pool is not None:
        clauses.append(_flag_clause("PoolPrivateYN", filters.pool))
    if filters.view is not None:
        clauses.append(_flag_clause("ViewYN", filters.view))
    if filters.max_hoa_monthly is not None:
        # No fee (NULL or 0) passes; a fee passes only when it is monthly and at most
        # the limit. Other frequencies are not converted, so they do not match.
        fee, freq = _col("AssociationFee"), _col("AssociationFeeFrequency")
        clauses.append(
            (
                f"(COALESCE({fee}, 0) = 0 OR ({freq} = %s AND {fee} <= %s))",
                (_MONTHLY, filters.max_hoa_monthly),
            )
        )
    return clauses


def _where(filters: PropertySearchFilters) -> tuple[str, list[Any]]:
    """Return the WHERE text (active status, then each set filter) and its params.

    Shared by the search and the count, so both always match the same rows.
    Raises ValueError if a column is not allowlisted or no status rule exists.
    """
    if ACTIVE_STATUS_COLUMN is None or not ACTIVE_STATUS_VALUES:
        raise ValueError("no active status rule in valid_values")
    # Status values are bound like any other value: "= %s" for one, "IN (...)" for more.
    statuses = sorted(ACTIVE_STATUS_VALUES)
    marks = ", ".join(["%s"] * len(statuses))
    status_test = "= %s" if len(statuses) == 1 else f"IN ({marks})"
    where = [f"{_col(ACTIVE_STATUS_COLUMN)} {status_test}"]
    params: list[Any] = list(statuses)
    for clause, values in _filter_clauses(filters):
        where.append(clause)
        params.extend(values)
    return " AND ".join(where), params


def build_count_sql(filters: PropertySearchFilters) -> SearchQuery:
    """Build the parameterized COUNT for the filters without touching a database.

    Same WHERE and params as `build_search_sql`, minus LIMIT and OFFSET. COUNT(*)
    returns a number and selects no column, so no row data can come back.
    """
    where, params = _where(filters)
    sql = f"SELECT COUNT(*) AS total_matches\nFROM {_TABLE}\nWHERE {where}"
    return SearchQuery(sql=sql, params=tuple(params))


def build_search_sql(filters: PropertySearchFilters) -> SearchQuery:
    """Build the parameterized SELECT for the filters without touching a database.

    Raises ValueError if a column is not allowlisted. A limit above MAX_ROWS is
    clamped and a warning added; OFFSET is (page - 1) * limit.
    """
    columns = [_col(name) for name in listing_columns()]
    where, params = _where(filters)

    warnings: list[str] = []
    limit = max(1, int(filters.limit))
    if limit > MAX_ROWS:
        warnings.append(
            f"limit {limit} is above the {MAX_ROWS}-row cap; "
            f"returning at most {MAX_ROWS} rows"
        )
        limit = MAX_ROWS
    offset = (max(1, int(filters.page)) - 1) * limit
    params.extend([limit, offset])

    order = ", ".join(f"{_col(name)} ASC" for name in _ORDER_BY)
    sql = (
        f"SELECT {', '.join(columns)}\n"
        f"FROM {_TABLE}\n"
        f"WHERE {where}\n"
        f"ORDER BY {order}\n"
        "LIMIT %s OFFSET %s"
    )
    return SearchQuery(sql=sql, params=tuple(params), warnings=warnings)


def search_active_listings(filters: PropertySearchFilters, conn: Any) -> SearchOutcome:
    """Run `build_search_sql` on `conn` (dict-row cursors) and map rows to Listings.

    A row that fails Listing validation is skipped and counted, with one warning
    for all of them. Rows are never logged.
    """
    query = build_search_sql(filters)
    with conn.cursor() as cursor:
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    listings: list[Listing] = []
    skipped = 0
    for row in rows:
        try:
            listings.append(to_listing(row))
        except ValidationError:
            skipped += 1
    warnings = list(query.warnings)
    if skipped:
        warnings.append(
            f"{skipped} row(s) skipped because a required value was missing or invalid"
        )
    return SearchOutcome(listings=listings, warnings=warnings, skipped_rows=skipped)


def count_active_listings(filters: PropertySearchFilters, conn: Any) -> int:
    """Run `build_count_sql` on `conn` and return the number of matching listings.

    Accepts dict rows (the pool's cursor) or tuple rows; no row at all counts as 0.
    """
    query = build_count_sql(filters)
    with conn.cursor() as cursor:
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if not rows:
        return 0
    row = rows[0]
    value = row["total_matches"] if isinstance(row, Mapping) else row[0]
    return int(value or 0)


def _candidate_keys(keys: Sequence[Any]) -> list[int]:
    """Return 1-50 distinct, non-negative whole-number keys, or raise ValueError.

    Accepts ints and NumPy integers; refuses bools, strings, and floats.
    """
    checked: list[int] = []
    for key in keys:
        if isinstance(key, bool):
            raise ValueError("listing keys must be whole numbers")
        try:
            value = operator.index(key)
        except TypeError:
            raise ValueError("listing keys must be whole numbers") from None
        if value < 0:
            raise ValueError("listing keys must not be negative")
        checked.append(value)
    if not 1 <= len(checked) <= MAX_ROWS:
        raise ValueError(f"a candidate fetch takes 1 to {MAX_ROWS} keys")
    if len(set(checked)) != len(checked):
        raise ValueError("candidate keys must be distinct")
    return checked


def build_candidate_sql(
    filters: PropertySearchFilters, keys: Sequence[int]
) -> SearchQuery:
    """Build the parameterized SELECT that re-checks ranked keys against the filters.

    Same WHERE as search (active status plus each set filter), then `L_ListingID IN`
    the keys, bound as text to match the varchar column and its index; LIMIT 50.
    The listing columns minus L_Remarks: remarks never leave the database here.
    Known edge, kept for the 50-row cap: a key stored on two rows (a few exist) uses
    two of the 50, so in a full batch the last key in key order can be cut and counts
    as dropped. Within a key the newest row comes first, so no key keeps a stale row.
    """
    return _candidate_query(filters, _candidate_keys(keys))


def _candidate_query(filters: PropertySearchFilters, wanted: list[int]) -> SearchQuery:
    """`build_candidate_sql` for keys `_candidate_keys` has already checked."""
    columns = [_col(name) for name in listing_columns() if name != _REMARKS]
    where, params = _where(filters)
    marks = ", ".join(["%s"] * len(wanted))
    params.extend(str(key) for key in wanted)
    params.append(MAX_ROWS)
    order = ", ".join(f"{_col(name)} {way}" for name, way in _CANDIDATE_ORDER)
    sql = (
        f"SELECT {', '.join(columns)}\n"
        f"FROM {_TABLE}\n"
        f"WHERE {where} AND {_col(_KEY)} IN ({marks})\n"
        f"ORDER BY {order}\n"
        "LIMIT %s"
    )
    return SearchQuery(sql=sql, params=tuple(params))


def fetch_candidates(
    filters: PropertySearchFilters, keys: Sequence[int], conn: Any
) -> SearchOutcome:
    """Run `build_candidate_sql` and return the surviving listings in `keys` order.

    A key SQL did not return (filter, status, or a bad row) is simply absent. Raises
    ValueError when the statement returns over 50 rows or a key not asked for.
    """
    wanted = _candidate_keys(keys)
    query = _candidate_query(filters, wanted)
    with conn.cursor() as cursor:
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError(f"candidate statement returned more than {MAX_ROWS} rows")
    asked = set(wanted)
    found: dict[int, Listing] = {}
    skipped = 0
    for row in rows:
        try:
            listing = to_listing(row)
        except ValidationError:
            skipped += 1
            continue
        if listing.listing_key not in asked:
            raise ValueError(
                "candidate statement returned a key that was not asked for"
            )
        # Rows come latest first within a key, so the first one seen is kept.
        found.setdefault(listing.listing_key, listing)
    warnings: list[str] = []
    if skipped:
        warnings.append(
            f"{skipped} row(s) skipped because a required value was missing or invalid"
        )
    listings = [found[key] for key in wanted if key in found]
    return SearchOutcome(listings=listings, warnings=warnings, skipped_rows=skipped)
