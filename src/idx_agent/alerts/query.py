"""Bound, allowlisted MLS reader for listings first listed since a saved snapshot."""

from datetime import date, datetime

from idx_agent.db.listings import SearchQuery, _where
from idx_agent.domain.fieldmap import listing_columns, to_listing
from idx_agent.safety.columns import check_column


def build_new_sql(search, active_as_of, *, count=False, scope=None, changed=False):
    """New-listing SQL for one saved search, optionally limited to a feature scope.

    Features need the scope bound by `FeatureAccess.bind` (WO-025), else ValueError.
    `changed=True` (count only) counts in-window IDs left out as changed since then.
    """
    table = "rets_property"
    listed = check_column(table, "ListingContractDate")
    key = check_column(table, "L_ListingID")
    if search.filters.features and scope is None:
        # Never drop features silently: an unscoped feature search is refused.
        raise ValueError(
            "saved-search alerts need a feature scope for listing features"
        )
    if scope is not None and not search.filters.features:
        raise ValueError("a feature scope needs a saved search with features")
    if changed and not (count and scope is not None):
        raise ValueError("the changed count needs count=True and a feature scope")
    where, params = _where(search.filters, scope, changed)
    where += f" AND {listed} > %s AND {listed} <= %s"
    params.extend([search.checked_as_of, active_as_of])
    if search.alerted_keys:
        marks = ", ".join(["%s"] * len(search.alerted_keys))
        where += f" AND {key} NOT IN ({marks})"
        params.extend(str(k) for k in search.alerted_keys)
    if count:
        # Count distinct keys because the source has a few repeated listing keys.
        return SearchQuery(
            sql=f"SELECT COUNT(DISTINCT {key}) AS n FROM {table} WHERE {where}",
            params=tuple(params),
        )
    columns = [check_column(table, c) for c in listing_columns() if c != "L_Remarks"]
    # Rank duplicates before limiting, so ten rows represent ten distinct listings.
    modified = check_column(table, "ModificationTimestamp")
    price = check_column(table, "L_SystemPrice")
    picked = ", ".join(columns)
    sql = (
        f"WITH ranked AS (SELECT {picked}, ROW_NUMBER() OVER (PARTITION BY {key} "
        f"ORDER BY {modified} DESC, {price} ASC) AS pick FROM {table} WHERE {where}) "
        f"SELECT {picked} FROM ranked WHERE pick = %s ORDER BY {price}, {key} LIMIT %s"
    )
    return SearchQuery(sql=sql, params=(*params, 1, 10))


def _count(cursor, query):
    cursor.execute(query.sql, query.params)
    rows = cursor.fetchall()
    if len(rows) > 1:
        raise ValueError("invalid aggregate size")
    return int(rows[0]["n"] or 0) if rows else 0


def fetch_new(search, active_as_of, conn, scope=None):
    count_query = build_new_sql(search, active_as_of, count=True, scope=scope)
    query = build_new_sql(search, active_as_of, scope=scope)
    with conn.cursor() as cursor:
        count = _count(cursor, count_query)
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if len(rows) > 10:
        raise ValueError("alert query exceeded row cap")
    return count, [to_listing(row) for row in rows]


def fetch_new_features(search, horizon, scope, conn):
    """(matches, up to ten listings, in-window listing IDs left out as changed)."""
    count, listings = fetch_new(search, horizon, conn, scope)
    changed_query = build_new_sql(
        search, horizon, count=True, scope=scope, changed=True
    )
    with conn.cursor() as cursor:
        left_out = _count(cursor, changed_query)
    return count, listings, left_out


def build_unchecked_sql(search, horizon, watermark):
    """Earliest listing date in the window that the snapshot could not check (WO-025).

    The job keeps the saved search's cursor before this date, so a rebuilt store
    checks those listings later instead of the cursor skipping past them.
    """
    # Counted: first listed in (checked_as_of, horizon], matching the plain filters,
    # not already alerted, with a row changed after `watermark` (no usable features in
    # that snapshot, matched there or not). A listing with no recorded change time can
    # never be checked by any snapshot, so it holds nothing.
    if not search.filters.features:
        raise ValueError("the unchecked-listing date is for saved feature searches")
    if not isinstance(watermark, str) or not watermark:
        raise ValueError("the unchecked-listing date needs the snapshot watermark")
    table = "rets_property"
    listed = check_column(table, "ListingContractDate")
    key = check_column(table, "L_ListingID")
    modified = check_column(table, "ModificationTimestamp")
    where, params = _where(search.filters)  # never the features: those are unknown
    where += f" AND {listed} > %s AND {listed} <= %s"
    params.extend([search.checked_as_of, horizon])
    if search.alerted_keys:
        marks = ", ".join(["%s"] * len(search.alerted_keys))
        where += f" AND {key} NOT IN ({marks})"
        params.extend(str(k) for k in search.alerted_keys)
    rows = f"FROM {table} AS newer WHERE newer.{key} = {table}.{key}"
    where += (
        f" AND EXISTS (SELECT 1 {rows} AND newer.{modified} > %s)"
        f" AND NOT EXISTS (SELECT 1 {rows} AND newer.{modified} IS NULL)"
    )
    params.append(watermark)
    return SearchQuery(
        sql=f"SELECT MIN({listed}) AS first_listed FROM {table} WHERE {where}",
        params=tuple(params),
    )


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError("invalid listing date")


def fetch_unchecked_from(search, horizon, watermark, conn):
    """The earliest unchecked listing date in the window (`build_unchecked_sql`)."""
    query = build_unchecked_sql(search, horizon, watermark)
    with conn.cursor() as cursor:
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if len(rows) > 1:
        raise ValueError("invalid aggregate size")
    return _as_date(rows[0]["first_listed"]) if rows else None
