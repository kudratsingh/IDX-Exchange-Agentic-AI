"""Bound, allowlisted MLS reader for listings first listed since a saved snapshot."""

from idx_agent.db.listings import SearchQuery, _where
from idx_agent.domain.fieldmap import listing_columns, to_listing
from idx_agent.safety.columns import check_column


def build_new_sql(search, active_as_of, *, count=False):
    table = "rets_property"
    listed = check_column(table, "ListingContractDate")
    key = check_column(table, "L_ListingID")
    where, params = _where(search.filters)
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


def fetch_new(search, active_as_of, conn):
    count_query = build_new_sql(search, active_as_of, count=True)
    query = build_new_sql(search, active_as_of)
    with conn.cursor() as cursor:
        cursor.execute(count_query.sql, count_query.params)
        count_rows = cursor.fetchall()
        if len(count_rows) > 1:
            raise ValueError("invalid aggregate size")
        count = int(count_rows[0]["n"] or 0) if count_rows else 0
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if len(rows) > 10:
        raise ValueError("alert query exceeded row cap")
    return count, [to_listing(row) for row in rows]
