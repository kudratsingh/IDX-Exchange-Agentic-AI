"""Fail-closed, provider-independent checks for an enrichment wave."""

import json
from decimal import Decimal

TOTAL_ROWS = 54888
CHECKPOINTS = (26000, 46000, TOTAL_ROWS)


def estimated_cost(usage):
    """Sonnet 5.5 batch, USD; 5-minute cache rates, not an invoice."""
    rates = {
        "input_tokens": "1",
        "output_tokens": "5",
        "cache_creation_input_tokens": "1.25",
        "cache_read_input_tokens": "0.05",
    }
    if not isinstance(usage, dict):
        raise ValueError("usage unavailable")
    total = Decimal(0)
    for field, rate in rates.items():
        n = usage.get(field)
        if type(n) is not int or n < 0:
            raise ValueError("usage unavailable")
        total += Decimal(n) * Decimal(rate) / 1000000
    return total


def verify_stored_wave(db, start, end, watermark):
    """Validate private aggregate evidence, including baseline and projection."""
    if start < 1 or end < start or end > TOTAL_ROWS:
        raise ValueError("invalid wave")
    verified = db.execute(
        "SELECT watermark FROM verifications WHERE completed=?", (end,)
    ).fetchone()
    statuses = [
        r[0]
        for r in db.execute(
            "SELECT status FROM batches WHERE start_sequence>=? AND end_sequence<=?",
            (start, end),
        )
    ]
    ranges = db.execute(
        "SELECT start_sequence,end_sequence FROM batches "
        "WHERE start_sequence>=? AND end_sequence<=? ORDER BY start_sequence",
        (start, end),
    ).fetchall()
    cursor = start
    for first, last in ranges:
        if first != cursor or last < first or last - first + 1 > 1000:
            raise ValueError("batch coverage invalid")
        cursor = last + 1
    if cursor != end + 1:
        raise ValueError("batch coverage invalid")
    if db.execute("SELECT COUNT(*) FROM failed_items").fetchone()[0]:
        raise ValueError("provider failures recorded")
    rows = db.execute(
        "SELECT diagnostic_count,usage FROM results WHERE sequence BETWEEN ? AND ?",
        (start, end),
    ).fetchall()
    bad_provenance = db.execute(
        "SELECT COUNT(*) FROM inputs i LEFT JOIN results r ON i.sequence=r.sequence "
        "LEFT JOIN result_origins o ON i.sequence=o.sequence "
        "WHERE i.sequence BETWEEN ? AND ? AND "
        "(r.sequence IS NULL OR r.input_hash != i.input_hash OR "
        "r.listing_key != i.listing_key OR o.extractor IS NULL OR "
        "o.extractor NOT IN ('v1','v2') OR "
        "(i.sequence>8000 AND o.extractor!='v2'))",
        (start, end),
    ).fetchone()[0]
    if bad_provenance:
        raise ValueError("result provenance invalid")
    baseline = db.execute(
        "SELECT usage FROM results WHERE sequence BETWEEN 6001 AND 8000"
    ).fetchall()
    spent = db.execute(
        "SELECT usage FROM results WHERE sequence BETWEEN 8001 AND ?", (end,)
    ).fetchall()
    if len(baseline) != 2000 or len(spent) != max(0, end - 8000):
        raise ValueError("cost evidence incomplete")
    wave_cost = sum((estimated_cost(json.loads(r[1])) for r in rows), Decimal(0))
    reference = (
        max(
            wave_cost / len(rows),
            sum((estimated_cost(json.loads(r[0])) for r in baseline), Decimal(0))
            / 2000,
        )
        if rows
        else Decimal(0)
    )
    cost = sum((estimated_cost(json.loads(r[0])) for r in spent), Decimal(0))
    projected = reference * (TOTAL_ROWS - end)
    check_wave(
        expected=end - start + 1,
        collected=len(rows),
        statuses=statuses,
        source_verified=verified == (watermark,),
        misses=sum(r[0] > 0 for r in rows),
        estimated_spend=cost,
        projected_remaining=projected,
    )
    return {
        "rows": len(rows),
        "misses": sum(r[0] > 0 for r in rows),
        "estimated_spend": str(cost),
        "projected_remaining": str(projected),
        "checkpoint": end in CHECKPOINTS,
    }


def next_wave(completed, *, checkpoint_approved=False):
    """Return the bounded next wave; the operator authorizes each checkpoint."""
    if type(completed) is not int or completed < 8000 or completed > TOTAL_ROWS:
        raise ValueError("invalid completed count")
    if completed == TOTAL_ROWS:
        return 0
    if completed in CHECKPOINTS and not checkpoint_approved:
        raise ValueError("human checkpoint required")
    checkpoint = next(c for c in CHECKPOINTS if c > completed)
    # After the second review the remaining exposure is at most 2,000 rows.
    limit = 2000 if completed >= 46000 else 10000
    return min(limit, checkpoint - completed)


def check_wave(
    *,
    expected,
    collected,
    statuses,
    source_verified,
    misses,
    estimated_spend,
    projected_remaining,
    budget=Decimal("90"),
):
    """Check a completed wave; monetary inputs are estimates, never invoices."""
    if type(expected) is not int or expected < 1 or type(collected) is not int:
        raise ValueError("invalid counts")
    if collected != expected:
        raise ValueError("incomplete results")
    if not statuses or any(status != "complete" for status in statuses):
        raise ValueError("batch incomplete or failed")
    if source_verified is not True:
        raise ValueError("source not verified")
    if type(misses) is not int or not 0 <= misses <= collected:
        raise ValueError("invalid diagnostics")
    if misses * 100 > collected * 2:
        raise ValueError("validation miss rate exceeded")
    for value in (estimated_spend, projected_remaining, budget):
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ValueError("invalid cost projection")
    if estimated_spend + projected_remaining > budget:
        raise ValueError("projected budget exceeded")
