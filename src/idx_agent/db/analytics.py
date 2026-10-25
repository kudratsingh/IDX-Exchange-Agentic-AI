"""Additional bounded aggregates over the exact cleaned WO-008 sale sample."""

from idx_agent.db.listings import _where
from idx_agent.db.market import (
    _columns,
    _geography,
    _run,
    _sample,
)
from idx_agent.domain.market import AREA_FLOOR, DEFAULT_SUBTYPE
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.safety.columns import check_column


def build_analytics_sql(request, window, dates):
    if window.end > dates.sold or window.start > window.end:
        raise ValueError("window exceeds the sales snapshot")
    c = _columns()
    subtype = request.property_subtype or DEFAULT_SUBTYPE
    cte, params = _sample("d", c, _geography(request, c), window, dates, subtype)
    totals = (
        f"WITH {cte} SELECT COUNT(*) AS n, AVG(close_price) AS mean_price, "
        "SUM(dom >= %s) AS dom_n, AVG(CASE WHEN dom >= %s THEN dom END) AS mean_dom, "
        "SUM(area >= %s) AS ppsf_n, "
        "AVG(CASE WHEN area >= %s THEN close_price / area END) AS mean_ppsf FROM d",
        (*params, 0, 0, AREA_FLOOR, AREA_FLOOR),
    )
    monthly = (
        f"WITH {cte}, b AS (SELECT ym, COUNT(*) AS n, AVG(close_price) AS mean_price, "
        "SUM(dom >= %s) AS dom_n, AVG(CASE WHEN dom >= %s THEN dom END) AS mean_dom "
        "FROM d GROUP BY ym), p AS (SELECT ym, close_price / area AS ppsf, "
        "ROW_NUMBER() OVER (PARTITION BY ym ORDER BY close_price / area) AS rn, "
        "COUNT(*) OVER (PARTITION BY ym) AS n FROM d WHERE area >= %s), "
        "q AS (SELECT ym, MAX(n) AS ppsf_n, "
        "AVG(CASE WHEN rn = FLOOR((n + %s) / %s) OR rn = FLOOR(n / %s) + %s "
        "THEN ppsf END) AS median_ppsf FROM p GROUP BY ym) "
        "SELECT b.ym, b.n, b.mean_price, b.dom_n, b.mean_dom, q.ppsf_n, q.median_ppsf "
        "FROM b LEFT JOIN q ON b.ym = q.ym ORDER BY b.ym LIMIT %s",
        (*params, 0, 0, AREA_FLOOR, 1, 2, 2, 1, 25),
    )
    filters = PropertySearchFilters(
        city=request.city,
        postal_code=request.postal_code,
        property_subtype=subtype,
    )
    where, bound = _where(filters)
    key = check_column("rets_property", "L_ListingID")
    inventory = (
        f"SELECT COUNT(DISTINCT {key}) AS n FROM rets_property WHERE {where}",
        tuple(bound),
    )
    return totals, monthly, inventory


def fetch_analytics(request, window, dates, conn):
    totals, monthly, inventory = build_analytics_sql(request, window, dates)
    one = _run(conn, "analytics_totals", totals)
    rows = _run(conn, "analytics_months", monthly)
    active = _run(conn, "analytics_inventory", inventory)
    if len(one) != 1 or len(active) != 1:
        raise ValueError("missing analytics aggregate")
    return one[0], rows, int(active[0]["n"])
