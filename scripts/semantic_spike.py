"""WO-010 spike and judging. --profile (default): read-only remarks profile and cost
arithmetic. --sizes: random unit matrices under data/spike/ (no provider, no database):
disk, ranking, cold start. --judge-sheet (paid, human token): shuffled sheets under
data/semantic/judging/. --score: numbers from the marks, and the judgments file. Never
prints a remark, key, or address; allowlisted columns, bound values, <=50 rows a query.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as scripts/market_spike.py does.
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.db.pool import connect  # noqa: E402
from idx_agent.domain.valid_values import (  # noqa: E402
    ACTIVE_STATUS_COLUMN,
    ACTIVE_STATUS_VALUES,
)
from idx_agent.safety.columns import check_column  # noqa: E402

Stmt = tuple[str, tuple[Any, ...]]

TABLE = "rets_property"
MAX_ROWS = 50
# Remarks shorter than this (after trimming) carry too little text to embed usefully.
MIN_EMBED_CHARS = 20
LONG_CHARS = (1_000, 2_000)
# Estimates, not tokenizer counts: about 4 characters per token for English prose.
CHARS_PER_TOKEN = 4
# The provider's per-input limit for text-embedding-3-small, in tokens (to be checked).
INPUT_TOKEN_LIMIT = 8_191
# Assumed list price per million input tokens; to be checked against the console.
PRICE_PER_MILLION = 0.02
DIMS = (1_536, 512)
FLOAT32_BYTES = 4
# Bytes per row kept beside each vector for in-memory filtering, as packed arrays:
# listing id int64 (8), price int64 (8), city code int32 (4), ZIP int32 (4),
# beds int16 (2), subtype code int8 (1).
SIDE_BYTES = 8 + 8 + 4 + 4 + 2 + 1
QUANTILES = (
    ("min", 0.0),
    ("p10", 0.10),
    ("p25", 0.25),
    ("p50", 0.50),
    ("p75", 0.75),
    ("p90", 0.90),
    ("p95", 0.95),
    ("p99", 0.99),
    ("max", 1.0),
)
# Server-side patterns; each is bound, and only a count ever comes back.
BLANK = "^[[:space:]]*$"
DIGIT_RUN = "[0-9]{10,}"
EMAIL_LIKE = "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}"
PHONE_LIKE = "[(]?[0-9]{3}[)]?[-. ]?[0-9]{3}[-. ][0-9]{4}"
NUMERIC_ID = "^[0-9]+$"
SPACES = "[[:space:]]+"


def _col(name: str) -> str:
    """Return the column name after the rets_property allowlist check."""
    return check_column(TABLE, name)


REMARKS, ID = _col("L_Remarks"), _col("L_ListingID")
CITY, PRICE, BEDS = _col("L_City"), _col("L_SystemPrice"), _col("L_Keyword2")
SUBTYPE, ZIP = _col("L_Type_"), _col("L_Zip")
STATUS = _col(ACTIVE_STATUS_COLUMN or "")
STATUSES = tuple(sorted(ACTIVE_STATUS_VALUES))
ACTIVE = f"{STATUS} IN ({', '.join(['%s'] * len(STATUSES))})"
# A remark with at least one non-space character.
PRESENT = f"({REMARKS} IS NOT NULL AND NOT {REMARKS} REGEXP %s)"
# A remark long enough to embed, measured after trimming.
EMBEDDABLE = f"({PRESENT} AND CHAR_LENGTH(TRIM({REMARKS})) >= %s)"


# ----- statement builders (pure) ----------------------------------------------------
def overview_stmt() -> Stmt:
    """One row: row count, null/blank/short remarks, lengths, and id shape."""
    trimmed = f"CHAR_LENGTH(TRIM({REMARKS}))"
    sql = (
        f"SELECT COUNT(*) AS n_rows, SUM({REMARKS} IS NULL) AS nulls, "
        f"SUM({REMARKS} IS NOT NULL AND {REMARKS} REGEXP %s) AS blanks, "
        f"SUM({PRESENT} AND {trimmed} < %s) AS short, "
        f"SUM({EMBEDDABLE}) AS embeddable, "
        f"SUM(CASE WHEN {EMBEDDABLE} THEN {trimmed} ELSE 0 END) AS embed_chars, "
        f"SUM(CASE WHEN {PRESENT} THEN CHAR_LENGTH({REMARKS}) ELSE 0 END) "
        f"AS present_chars, "
        f"SUM({PRESENT} AND CHAR_LENGTH({REMARKS}) > %s) AS over_a, "
        f"SUM({PRESENT} AND CHAR_LENGTH({REMARKS}) > %s) AS over_b, "
        f"SUM({PRESENT} AND CHAR_LENGTH({REMARKS}) > %s) AS over_limit, "
        f"COUNT(DISTINCT {ID}) AS distinct_ids, SUM({ID} IS NULL) AS null_ids, "
        f"SUM({ID} REGEXP %s) AS numeric_ids "
        f"FROM {TABLE} WHERE {ACTIVE}"
    )
    params = (
        BLANK,
        BLANK,
        MIN_EMBED_CHARS,
        BLANK,
        MIN_EMBED_CHARS,
        BLANK,
        MIN_EMBED_CHARS,
        BLANK,
        BLANK,
        LONG_CHARS[0],
        BLANK,
        LONG_CHARS[1],
        BLANK,
        INPUT_TOKEN_LIMIT * CHARS_PER_TOKEN,
        NUMERIC_ID,
        *STATUSES,
    )
    return sql, params


def quantile_stmt(measure: str, measure_params: tuple[Any, ...]) -> Stmt:
    """One row: n and each quantile (lower nearest rank) of `measure` over present
    remarks, computed on the server with window functions; no row leaves it."""
    picks = ", ".join(
        f"MAX(CASE WHEN rn = FLOOR(%s * (n - 1)) + 1 THEN v END) AS {label}"
        for label, _ in QUANTILES
    )
    sql = (
        f"WITH m AS (SELECT {measure} AS v FROM {TABLE} "
        f"WHERE {ACTIVE} AND {PRESENT}), "
        "o AS (SELECT v, ROW_NUMBER() OVER (ORDER BY v) AS rn, "
        "COUNT(*) OVER () AS n FROM m) "
        f"SELECT MAX(n) AS n, {picks} FROM o"
    )
    params = (*measure_params, *STATUSES, BLANK, *(q for _, q in QUANTILES))
    return sql, params


def chars_quantiles() -> Stmt:
    """Quantiles of remark length in characters."""
    return quantile_stmt(f"CHAR_LENGTH({REMARKS})", ())


def words_quantiles() -> Stmt:
    """Quantiles of an approximate word count: spaces in the collapsed, trimmed
    text plus one."""
    collapsed = f"TRIM(REGEXP_REPLACE({REMARKS}, %s, %s))"
    measure = (
        f"(CHAR_LENGTH({collapsed}) - CHAR_LENGTH(REPLACE({collapsed}, %s, %s)) + 1)"
    )
    return quantile_stmt(measure, (SPACES, " ", SPACES, " ", " ", ""))


def patterns_stmt() -> Stmt:
    """One row: counts of present remarks holding contact-like or link-like text."""
    at, http, www = f"{REMARKS} LIKE %s", f"{REMARKS} LIKE %s", f"{REMARKS} LIKE %s"
    digits = f"{REMARKS} REGEXP %s"
    sql = (
        f"SELECT SUM({at}) AS at_sign, SUM({http}) AS http, SUM({www}) AS www, "
        f"SUM({digits}) AS digit_run, SUM({REMARKS} REGEXP %s) AS email_like, "
        f"SUM({REMARKS} REGEXP %s) AS phone_like, "
        f"SUM({at} OR {http} OR {digits}) AS any_of_three "
        f"FROM {TABLE} WHERE {ACTIVE} AND {PRESENT}"
    )
    params = (
        "%@%",
        "%http%",
        "%www.%",
        DIGIT_RUN,
        EMAIL_LIKE,
        PHONE_LIKE,
        "%@%",
        "%http%",
        DIGIT_RUN,
        *STATUSES,
        BLANK,
    )
    return sql, params


def filter_columns_stmt(scope: str, scope_params: tuple[Any, ...]) -> Stmt:
    """One row: NULL (and blank or zero) counts of the in-memory filter columns."""
    sql = (
        f"SELECT COUNT(*) AS n, "
        f"SUM({CITY} IS NULL) AS city_null, SUM(TRIM({CITY}) = %s) AS city_blank, "
        f"SUM({PRICE} IS NULL) AS price_null, SUM({PRICE} = %s) AS price_zero, "
        f"SUM({BEDS} IS NULL) AS beds_null, SUM({BEDS} = %s) AS beds_zero, "
        f"SUM({SUBTYPE} IS NULL) AS subtype_null, "
        f"SUM(TRIM({SUBTYPE}) = %s) AS subtype_blank, "
        f"SUM({ZIP} IS NULL) AS zip_null, SUM(TRIM({ZIP}) = %s) AS zip_blank, "
        f"COUNT(DISTINCT {CITY}) AS cities, COUNT(DISTINCT {SUBTYPE}) AS subtypes, "
        f"MAX({BEDS}) AS beds_max "
        f"FROM {TABLE} WHERE {ACTIVE}{scope}"
    )
    return sql, ("", 0, 0, "", "", *STATUSES, *scope_params)


def first_ids_stmt() -> Stmt:
    """The first 50 listing ids of present remarks by id, kept in memory for the
    EXPLAIN below; never printed."""
    sql = (
        f"SELECT {ID} AS id FROM {TABLE} WHERE {ACTIVE} AND {PRESENT} "
        f"ORDER BY {ID} LIMIT %s"
    )
    return sql, (*STATUSES, BLANK, MAX_ROWS)


def fetch_by_ids_stmt(ids: list[Any]) -> Stmt:
    """The shape of the candidate fetch: active rule plus L_ListingID IN (...)."""
    marks = ", ".join(["%s"] * len(ids))
    sql = (
        f"SELECT {ID}, {CITY}, {PRICE} FROM {TABLE} "
        f"WHERE {ACTIVE} AND {ID} IN ({marks}) LIMIT %s"
    )
    return sql, (*STATUSES, *ids, MAX_ROWS)


# ----- execution helpers ----------------------------------------------------------
def run(conn: Any, stmt: Stmt) -> list[dict[str, Any]]:
    """Execute one statement; raise if it returns more than MAX_ROWS rows."""
    with conn.cursor() as cursor:
        cursor.execute(stmt[0], stmt[1])
        rows = list(cursor.fetchall())
    if len(rows) > MAX_ROWS:
        raise RuntimeError(f"statement returned {len(rows)} rows (cap {MAX_ROWS})")
    return rows


def timed(conn: Any, stmt: Stmt) -> tuple[dict[str, Any], float]:
    """Run a one-row statement; return the row and its seconds."""
    t0 = time.perf_counter()
    row = run(conn, stmt)[0]
    return row, time.perf_counter() - t0


def num(value: Any) -> int:
    """An aggregate as an int (SUM over no rows is NULL)."""
    return int(value or 0)


def pct(part: float, whole: float) -> str:
    """Share as a percentage with two decimals; '-' when the whole is zero."""
    return f"{100 * part / whole:.2f}%" if whole else "-"


def mb(n_bytes: float) -> str:
    """Bytes as decimal megabytes."""
    return f"{n_bytes / 1e6:,.1f} MB"


def table(header: list[str], rows: list[list[Any]]) -> None:
    """Print a small aligned table."""
    cells = [header, *[[str(c) for c in r] for r in rows]]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    for i, r in enumerate(cells):
        print("  " + " | ".join(c.rjust(w) for c, w in zip(r, widths, strict=True)))
        if i == 0:
            print("  " + "-+-".join("-" * w for w in widths))


# ----- sections -------------------------------------------------------------------
def section_profile(conn: Any) -> dict[str, Any]:
    """(a) null, blank, short, long remarks; id shape."""
    row, secs = timed(conn, overview_stmt())
    n = num(row["n_rows"])
    print(f"\n(a) remarks profile over active rows ({secs:.2f} s)")
    table(
        ["measure", "count", "share of rows"],
        [
            ["active rows", n, pct(n, n)],
            ["remarks NULL", num(row["nulls"]), pct(num(row["nulls"]), n)],
            [
                "remarks empty or whitespace",
                num(row["blanks"]),
                pct(num(row["blanks"]), n),
            ],
            [
                f"present but under {MIN_EMBED_CHARS} chars (trimmed)",
                num(row["short"]),
                pct(num(row["short"]), n),
            ],
            [
                f"embeddable (>= {MIN_EMBED_CHARS} chars)",
                num(row["embeddable"]),
                pct(num(row["embeddable"]), n),
            ],
            [
                f"over {LONG_CHARS[0]:,} chars",
                num(row["over_a"]),
                pct(num(row["over_a"]), n),
            ],
            [
                f"over {LONG_CHARS[1]:,} chars",
                num(row["over_b"]),
                pct(num(row["over_b"]), n),
            ],
            [
                f"over {INPUT_TOKEN_LIMIT * CHARS_PER_TOKEN:,} chars (~input limit)",
                num(row["over_limit"]),
                pct(num(row["over_limit"]), n),
            ],
        ],
    )
    print(
        f"  total characters: present remarks {num(row['present_chars']):,}; "
        f"embeddable (trimmed) {num(row['embed_chars']):,}"
    )
    distinct, numeric = num(row["distinct_ids"]), num(row["numeric_ids"])
    print(
        f"  L_ListingID: distinct {distinct:,} of {n:,} rows "
        f"({n - distinct} duplicate rows); NULL {num(row['null_ids'])}; "
        f"all digits {numeric:,} ({pct(numeric, n)})"
    )
    return row


def section_lengths(conn: Any) -> dict[str, Any]:
    """(a) quantiles of length in characters and in words, computed in SQL."""
    chars, c_secs = timed(conn, chars_quantiles())
    words, w_secs = timed(conn, words_quantiles())
    print(
        f"\n(a) length of present remarks, lower nearest rank "
        f"(chars {c_secs:.2f} s, words {w_secs:.2f} s)"
    )
    labels = [label for label, _ in QUANTILES]
    table(
        ["measure", "n", *labels],
        [
            ["characters", num(chars["n"]), *(num(chars[k]) for k in labels)],
            ["words (approx.)", num(words["n"]), *(num(words[k]) for k in labels)],
            [
                "tokens (chars / 4, est.)",
                num(chars["n"]),
                *(round(num(chars[k]) / CHARS_PER_TOKEN) for k in labels),
            ],
        ],
    )
    return chars


def section_patterns(conn: Any, present: int) -> None:
    """(a) counts of contact-like and link-like text; no value ever returned."""
    row, secs = timed(conn, patterns_stmt())
    print(f"\n(a) contact-like and link-like text in present remarks ({secs:.2f} s)")
    print("  counts only; LIKE follows the column collation (case-insensitive)")
    table(
        ["pattern", "remarks", "share of present"],
        [
            ["contains '@'", num(row["at_sign"]), pct(num(row["at_sign"]), present)],
            ["contains 'http'", num(row["http"]), pct(num(row["http"]), present)],
            ["contains 'www.'", num(row["www"]), pct(num(row["www"]), present)],
            [
                "run of 10+ digits",
                num(row["digit_run"]),
                pct(num(row["digit_run"]), present),
            ],
            [
                "email-like (a name, an at sign, a domain)",
                num(row["email_like"]),
                pct(num(row["email_like"]), present),
            ],
            [
                "phone-like (3-3-4 with separators)",
                num(row["phone_like"]),
                pct(num(row["phone_like"]), present),
            ],
            [
                "any of '@', 'http', 10+ digits",
                num(row["any_of_three"]),
                pct(num(row["any_of_three"]), present),
            ],
        ],
    )


def section_cost(profile: dict[str, Any], chars: dict[str, Any]) -> None:
    """(b) token and dollar estimate for one full embedding run (arithmetic only)."""
    rows, total = num(profile["embeddable"]), num(profile["embed_chars"])
    tokens = total / CHARS_PER_TOKEN
    dollars = tokens / 1e6 * PRICE_PER_MILLION
    print("\n(b) one-time embedding cost, ESTIMATE (no call made)")
    print(
        f"  assumptions: {CHARS_PER_TOKEN} characters per token (not a tokenizer "
        f"count); ${PRICE_PER_MILLION} per million input tokens for "
        "text-embedding-3-small (list price, to be checked; the real figure comes "
        "from the provider console)"
    )
    table(
        ["measure", "value"],
        [
            ["embeddable remarks", f"{rows:,}"],
            ["characters (trimmed)", f"{total:,}"],
            ["estimated tokens, total", f"{tokens:,.0f}"],
            [
                "estimated tokens, mean per listing",
                f"{tokens / rows:,.0f}" if rows else "-",
            ],
            [
                "estimated tokens, median per listing",
                f"{num(chars['p50']) / CHARS_PER_TOKEN:,.0f}",
            ],
            [
                "estimated tokens, p95 per listing",
                f"{num(chars['p95']) / CHARS_PER_TOKEN:,.0f}",
            ],
            ["estimated one-time cost", f"${dollars:,.4f}"],
            ["estimated cost at 10x the assumed price", f"${dollars * 10:,.4f}"],
        ],
    )
    print(
        "  512 dimensions (the `dimensions` request parameter) changes storage and "
        "ranking time, not the input token count or its cost"
    )


def section_sizes(profile: dict[str, Any]) -> None:
    """(c) float32 index size at each dimension, plus the side columns."""
    embeddable, n = num(profile["embeddable"]), num(profile["n_rows"])
    print("\n(c) in-memory index footprint, float32 (arithmetic)")
    print(
        f"  side arrays for filtering: {SIDE_BYTES} bytes/row (id int64, price int64, "
        "city code int32, ZIP int32, beds int16, subtype code int8)"
    )
    rows = []
    for dim in DIMS:
        for label, count in (("embeddable", embeddable), ("all active", n)):
            vec = count * dim * FLOAT32_BYTES
            rows.append(
                [dim, label, f"{count:,}", mb(vec), mb(vec + count * SIDE_BYTES)]
            )
    table(["dims", "rows", "count", "vectors", "vectors + side arrays"], rows)


def section_filters(conn: Any) -> None:
    """(d) null shares of the columns kept beside each vector."""
    all_rows, s1 = timed(conn, filter_columns_stmt("", ()))
    emb_rows, s2 = timed(
        conn, filter_columns_stmt(f" AND {EMBEDDABLE}", (BLANK, MIN_EMBED_CHARS))
    )
    print(f"\n(d) filter columns beside each vector ({s1 + s2:.2f} s)")
    out = []
    for col, keys in (
        (CITY, ("city_null", "city_blank", "blank")),
        (PRICE, ("price_null", "price_zero", "zero")),
        (BEDS, ("beds_null", "beds_zero", "zero")),
        (SUBTYPE, ("subtype_null", "subtype_blank", "blank")),
        (ZIP, ("zip_null", "zip_blank", "blank")),
    ):
        null_k, other_k, other_label = keys
        na, ne = num(all_rows["n"]), num(emb_rows["n"])
        out.append(
            [
                col,
                f"{num(all_rows[null_k])} ({pct(num(all_rows[null_k]), na)})",
                f"{num(all_rows[other_k])} {other_label}",
                f"{num(emb_rows[null_k])} ({pct(num(emb_rows[null_k]), ne)})",
                f"{num(emb_rows[other_k])} {other_label}",
            ]
        )
    table(
        ["column", "NULL, all active", "other, all", "NULL, embeddable", "other, emb."],
        out,
    )
    print(
        f"  distinct cities {num(all_rows['cities'])}, subtypes "
        f"{num(all_rows['subtypes'])}, max beds {num(all_rows['beds_max'])} "
        "(sizes the side-array types)"
    )


def section_explain(conn: Any) -> None:
    """(a) EXPLAIN of a 50-id fetch; ids stay in memory, only the plan is printed."""
    ids = [r["id"] for r in run(conn, first_ids_stmt())]
    stmt = fetch_by_ids_stmt(ids)
    plan = run(conn, ("EXPLAIN FORMAT=TRADITIONAL " + stmt[0], stmt[1]))
    keys = [
        f"{r.get('key') or 'none'} ({r.get('type')}, rows est. {r.get('rows')})"
        for r in plan
        if r.get("table") == TABLE
    ]
    t0 = time.perf_counter()
    got = len(run(conn, stmt))
    secs = time.perf_counter() - t0
    print(f"\n(a) fetch of {len(ids)} ids by {ID} IN (...)")
    print(f"  EXPLAIN: {', '.join(keys) or 'no plan row'}; {got} rows in {secs:.3f} s")


def profile_main() -> int:
    """Connect as the reader and print every section; wall time last."""
    started = time.perf_counter()
    conn = connect()
    try:
        version = run(conn, ("SELECT VERSION() AS v", ()))[0]["v"]
        print(f"MySQL {version}; table {TABLE}; active rule {STATUS} IN {STATUSES}")
        profile = section_profile(conn)
        chars = section_lengths(conn)
        section_patterns(conn, num(chars["n"]))
        section_cost(profile, chars)
        section_sizes(profile)
        section_filters(conn)
        section_explain(conn)
    finally:
        conn.close()
    print(f"\nspike wall time {time.perf_counter() - started:.1f} s")
    return 0


# ----- judging: sheets for the human, then numbers from the marks -------------------
# Everything here is written under data/semantic/judging/ (gitignored) and never
# printed: the sheets hold remarks and keys so the human can judge them.
JUDGING_DIR = ROOT / "data" / "semantic" / "judging"
CASES_FILE = ROOT / "evals" / "cases" / "semantic_retrieval.yaml"
# The file the eval runner's recall_at_k reads (IDX_SEMANTIC_JUDGMENTS names it).
JUDGMENTS_FILE = JUDGING_DIR / "judgments.json"
JUDGMENTS_FORMAT = 1
JUDGE_TOP = 10
SCORE_AT = 5
SHEET_COLUMNS = (
    "row",
    "relevant",
    "listing_key",
    "address",
    "city",
    "postal_code",
    "price",
    "beds",
    "baths",
    "sqft",
    "subtype",
    "year_built",
    "remarks",
)
YES, NO = frozenset({"y", "yes", "1", "true"}), frozenset({"n", "no", "0", "false"})


def judged_queries(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    """The local recall_at_k cases: [{query_id, args}] in file order.

    `args` are the case's tool arguments with k set to 10 (the sheet's depth).
    """
    import yaml

    cases = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    queries = []
    for case in cases:
        if case.get("check") != "recall_at_k" or case.get("suite") != "local":
            continue
        args = {**dict(case.get("input_filters") or {}), "k": JUDGE_TOP}
        queries.append({"query_id": case["expect"]["query_id"], "args": args})
    return queries


def ignored_by_git(path: Path) -> bool:
    """True when `git check-ignore` reports `path` as ignored (requirement 2)."""
    done = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", str(path)],
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


def remarks_stmt(keys: Sequence[int]) -> Stmt:
    """The remarks of at most 50 listing keys, latest row first for a repeated key.

    Keys are bound as text to match the varchar column and its index.
    """
    if not 1 <= len(keys) <= MAX_ROWS:
        raise ValueError(f"1 to {MAX_ROWS} keys")
    modified = _col("ModificationTimestamp")
    marks = ", ".join(["%s"] * len(keys))
    sql = (
        f"SELECT {ID} AS id, {REMARKS} AS remarks FROM {TABLE} "
        f"WHERE {ID} IN ({marks}) ORDER BY {ID} ASC, {modified} DESC LIMIT %s"
    )
    return sql, (*(str(k) for k in keys), MAX_ROWS)


def sheet_rows(
    query_id: str, matches: Sequence[Mapping[str, Any]], remarks: Mapping[int, str]
) -> list[dict[str, Any]]:
    """One sheet row per match, shuffled with a seed from the query id (repeatable).

    `relevant` is left blank for the human: y or n. The rank is not on the sheet.
    """
    rows = []
    for match in matches:
        x = match["listing"]
        rows.append(
            {
                "relevant": "",
                "listing_key": x["listing_key"],
                "address": x.get("address") or "",
                "city": x.get("city") or "",
                "postal_code": x.get("postal_code") or "",
                "price": x["list_price"],
                "beds": x.get("bedrooms"),
                "baths": x.get("bathrooms"),
                "sqft": x.get("living_area"),
                "subtype": x.get("property_subtype") or "",
                "year_built": x.get("year_built"),
                "remarks": " ".join((remarks.get(x["listing_key"]) or "").split()),
            }
        )
    random.Random(query_id).shuffle(rows)
    return [{"row": i, **r} for i, r in enumerate(rows, start=1)]


def _write_new(path: Path, write: Any) -> None:
    """Write through a temporary file, then rename; never replace an existing file."""
    if path.exists():
        raise FileExistsError(path.name)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("x", encoding="utf-8", newline="") as handle:
        write(handle)
    os.replace(tmp, path)


def judge_sheet_main() -> int:
    """Run each judged query through the tool (k=10) and write its sheet and order.

    Paid: one embedding per query, so a human `paid` token must be active. An
    existing sheet is skipped, never overwritten. Prints counts only.
    """
    from idx_agent.mcp_server.server import similar_result
    from idx_agent.safety.consent import paid_consent_active

    if os.environ.get("CI"):
        print("refused: judging sheets are never made under CI")
        return 2
    if not paid_consent_active():
        print("refused: each query is a paid embedding call; a human `paid` token")
        print("must be active (scripts/guards/consent.sh paid)")
        return 2
    JUDGING_DIR.mkdir(parents=True, exist_ok=True)
    if not ignored_by_git(JUDGING_DIR):
        print("refused: data/semantic/judging is not ignored by git")
        return 2
    queries = judged_queries()
    conn = connect()
    try:
        for query in queries:
            qid = query["query_id"]
            sheet, order = JUDGING_DIR / f"{qid}.csv", JUDGING_DIR / f"{qid}.order.json"
            if sheet.exists() or order.exists():
                print(f"{qid}: sheet exists, skipped")
                continue
            result = similar_result(query["args"]).model_dump(mode="json")
            if not result["ok"] or "matches" not in (result["data"] or {}):
                error = (result.get("error") or {}).get("category", "clarification")
                print(f"{qid}: no ranking ({error}); no sheet written")
                continue
            data = result["data"]
            keys = [m["listing"]["listing_key"] for m in data["matches"]]
            remarks = {}
            if keys:
                rows = run(conn, remarks_stmt(keys))
                for r in rows:
                    remarks.setdefault(int(r["id"]), r["remarks"] or "")
            rows = sheet_rows(qid, data["matches"], remarks)

            def write_sheet(handle: Any, rows: list[dict[str, Any]] = rows) -> None:
                writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            record = {
                "query_id": qid,
                "ranked": keys,
                "index_as_of": data["index_as_of"],
                "model": data["model"],
            }
            _write_new(order, lambda h, record=record: json.dump(record, h, indent=1))
            _write_new(sheet, write_sheet)
            print(f"{qid}: sheet written, {len(keys)} rows")
    finally:
        conn.close()
    print(
        f"sheets in {JUDGING_DIR.relative_to(ROOT)}: mark each row y or n, then --score"
    )
    return 0


def read_marks(sheet: Path) -> tuple[set[int], int]:
    """(keys marked relevant, rows left blank or unreadable) from one sheet."""
    relevant: set[int] = set()
    unmarked = 0
    with sheet.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            mark = (row.get("relevant") or "").strip().lower()
            if mark in YES:
                relevant.add(int(row["listing_key"]))
            elif mark not in NO:
                unmarked += 1
    return relevant, unmarked


def query_scores(ranked: Sequence[int], relevant: set[int]) -> dict[str, Any]:
    """recall@5 and precision@5 for one query (WO-010 In scope, Metrics).

    recall@5 = |top5 & relevant| / min(5, |relevant|), None with no relevant row;
    precision@5 = |top5 & relevant| / 5.
    """
    hits = len(set(ranked[:SCORE_AT]) & relevant)
    recall = hits / min(SCORE_AT, len(relevant)) if relevant else None
    return {"hits": hits, "recall": recall, "precision": hits / SCORE_AT}


def score_main() -> int:
    """Print recall@5 and precision@5 per judged query and their means (numbers only),
    then write the judgments file the eval runner reads, if it is not there yet."""
    queries = judged_queries()
    judgments: dict[str, Any] = {}
    recalls, precisions, zero_hit, no_relevant = [], [], 0, []
    print("query | judged | relevant | hits@5 | recall@5 | precision@5")
    for query in queries:
        qid = query["query_id"]
        sheet, order = JUDGING_DIR / f"{qid}.csv", JUDGING_DIR / f"{qid}.order.json"
        if not (sheet.exists() and order.exists()):
            print(f"{qid} | no sheet")
            continue
        ranked = json.loads(order.read_text(encoding="utf-8"))["ranked"]
        relevant, unmarked = read_marks(sheet)
        if unmarked:
            print(f"{qid} | {unmarked} row(s) not marked y or n; not scored")
            continue
        s = query_scores(ranked, relevant)
        judgments[qid] = {"judged": ranked, "relevant": sorted(relevant)}
        precisions.append(s["precision"])
        zero_hit += s["hits"] == 0
        if s["recall"] is None:
            no_relevant.append(qid)
        else:
            recalls.append(s["recall"])
        recall = "-" if s["recall"] is None else f"{s['recall']:.2f}"
        print(
            f"{qid} | {len(ranked)} | {len(relevant)} | {s['hits']} | {recall} | "
            f"{s['precision']:.2f}"
        )

    def mean(xs: list[float]) -> str:
        return f"{sum(xs) / len(xs):.3f}" if xs else "-"

    print(f"mean recall@5 {mean(recalls)} over {len(recalls)} queries")
    print(f"mean precision@5 {mean(precisions)} over {len(precisions)} queries")
    print(f"zero-hit queries (no relevant row in the top 5): {zero_hit}")
    print(
        f"no relevant row, left out of the recall mean: {', '.join(no_relevant) or '-'}"
    )
    body = {"format_version": JUDGMENTS_FORMAT, "queries": judgments}
    if judgments and not JUDGMENTS_FILE.exists():
        _write_new(JUDGMENTS_FILE, lambda h: json.dump(body, h, indent=1))
        print(f"judgments written: {JUDGMENTS_FILE.relative_to(ROOT)}")
    elif JUDGMENTS_FILE.exists():
        print("judgments file exists, left as it is (move it aside to write a new one)")
    return 0


# ----- (c) sizes, ranking speed, cold start (no spend, invented rows) --------------
SIZES_ROWS = 55_212
SIZES_SEED = 20260924
SIZES_TOP = 200
SIZES_TRIES = 3
SIZES_WARM_CALLS = 20
COLD_LIMIT_S = 5.0
SPIKE_DIR = ROOT / "data" / "spike"
# Invented attribute values; no listing data is read in this mode.
FAKE_CITIES = ("Town A", "Town B", "Town C", "Town D", "Town E", "Town F")
FAKE_SUBTYPES = ("Single Family Residence", "Condominium", "Townhouse")
# The child: import, load, one rank; prints its own timings and peak RSS as JSON.
COLD_CHILD = """
import time
t0 = time.perf_counter()
import json, resource, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import numpy as np
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.semantic.index import load_index, rank
t1 = time.perf_counter()
index = load_index(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
t2 = time.perf_counter()
q = np.random.default_rng(1).standard_normal(index.meta.dims).astype(np.float32)
q /= np.linalg.norm(q)
t3 = time.perf_counter()
hits = rank(index, q, PropertySearchFilters(), int(sys.argv[5]))
t4 = time.perf_counter()
print(json.dumps({"import": t1 - t0, "load": t2 - t1, "rank": t4 - t3,
                  "hits": len(hits),
                  "self_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
"""


def rss_mb(maxrss: int) -> float:
    """ru_maxrss as decimal MB: bytes on darwin, kilobytes on Linux."""
    return maxrss / 1e6 if sys.platform == "darwin" else maxrss * 1024 / 1e6


def fake_index_arrays(dims: int, seed: int) -> tuple[Any, Any, Any]:
    """Random unit float32 vectors, ascending invented keys, invented attrs."""
    import numpy as np

    from idx_agent.semantic.index import IndexAttrs

    rng = np.random.default_rng(seed)
    vectors = rng.standard_normal((SIZES_ROWS, dims), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    keys = np.arange(SIZES_ROWS, dtype=np.int64) * 3 + 1_000_000
    attrs = IndexAttrs(
        city=np.array(FAKE_CITIES)[rng.integers(0, len(FAKE_CITIES), SIZES_ROWS)],
        list_price=rng.integers(200_000, 3_000_000, SIZES_ROWS, dtype=np.int64),
        bedrooms=rng.integers(0, 7, SIZES_ROWS, dtype=np.int64),
        property_subtype=np.array(FAKE_SUBTYPES)[
            rng.integers(0, len(FAKE_SUBTYPES), SIZES_ROWS)
        ],
    )
    return vectors, keys, attrs


def cold_start(path: Path, model: str, dims: int) -> dict[str, Any]:
    """One fresh child process: wall time around it, its breakdown, RSS readings."""
    import resource

    argv = [sys.executable, "-c", COLD_CHILD, str(ROOT / "src"), str(path), model]
    t0 = time.perf_counter()
    done = subprocess.run(
        [*argv, str(dims), str(SIZES_TOP)], capture_output=True, text=True, check=False
    )
    wall = time.perf_counter() - t0
    if done.returncode != 0:
        raise RuntimeError(f"cold-start child failed (exit {done.returncode})")
    child = json.loads(done.stdout.strip().splitlines()[-1])
    children_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return {**child, "wall": wall, "children_maxrss": children_rss}


def sizes_main() -> int:
    """(c) Write invented indexes at 512 and 1,536 dims under data/spike/, measure
    disk bytes, cold start (best of 3), warm rank (median of 20), and peak RSS."""
    import shutil
    import statistics
    import tempfile

    import numpy as np

    from idx_agent.domain.models import PropertySearchFilters
    from idx_agent.semantic.embedder import DEFAULT_MODEL
    from idx_agent.semantic.index import load_index, rank, write_index

    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="sizes-", dir=SPIKE_DIR))
    print(f"(c) sizes: {SIZES_ROWS:,} invented rows, seed {SIZES_SEED}, no provider")
    print(f"  temporary directory: {tmp.relative_to(ROOT)}")
    print(f"  git check-ignore says ignored: {ignored_by_git(tmp)}")
    results: dict[int, dict[str, Any]] = {}
    try:
        # 512 first: RUSAGE_CHILDREN is a running maximum over every waited child.
        for dims in sorted(DIMS):
            path = tmp / f"d{dims}"
            vectors, keys, attrs = fake_index_arrays(dims, SIZES_SEED + dims)
            write_index(
                path,
                vectors=vectors,
                keys=keys,
                attrs=attrs,
                model=DEFAULT_MODEL,
                active_as_of=date(2000, 1, 1),
            )
            del vectors, keys, attrs
            disk = {f.name: f.stat().st_size for f in sorted(path.iterdir())}
            runs = [cold_start(path, DEFAULT_MODEL, dims) for _ in range(SIZES_TRIES)]
            best = min(runs, key=lambda r: r["wall"])
            index = load_index(path, DEFAULT_MODEL, dims)
            rng = np.random.default_rng(SIZES_SEED)
            query = rng.standard_normal(dims).astype(np.float32)
            query /= np.linalg.norm(query)
            empty = PropertySearchFilters()
            warm = []
            for _ in range(SIZES_WARM_CALLS):
                t0 = time.perf_counter()
                rank(index, query, empty, SIZES_TOP)
                warm.append(time.perf_counter() - t0)
            del index
            results[dims] = {
                "disk": disk,
                "best": best,
                "walls": [r["wall"] for r in runs],
                "warm_median": statistics.median(warm),
                "warm_min": min(warm),
                "self_rss": max(r["self_maxrss"] for r in runs),
                "children_rss": runs[-1]["children_maxrss"],
            }
    finally:
        try:
            shutil.rmtree(tmp)
            print(f"  removed the temporary directory: {tmp.relative_to(ROOT)}")
        except OSError as exc:
            print(f"  could not remove {tmp.relative_to(ROOT)}: {type(exc).__name__}")
    print_sizes(results)
    return 0


def print_sizes(results: dict[int, dict[str, Any]]) -> None:
    """The measured numbers, one column per dimension, and the 5-second verdict."""
    order = sorted(results, reverse=True)
    names = sorted({n for r in results.values() for n in r["disk"]})

    def row(label: str, pick: Any) -> list[Any]:
        return [label, *(pick(results[d]) for d in order)]

    rows = [row(f"disk bytes, {n}", lambda r, n=n: f"{r['disk'][n]:,}") for n in names]
    rows += [
        row("disk bytes, total", lambda r: f"{sum(r['disk'].values()):,}"),
        row("cold start wall s, best of 3", lambda r: f"{r['best']['wall']:.3f}"),
        row(
            "cold start wall s, 3 runs",
            lambda r: " ".join(f"{w:.3f}" for w in r["walls"]),
        ),
        row("  child import s (best run)", lambda r: f"{r['best']['import']:.3f}"),
        row("  child load_index s", lambda r: f"{r['best']['load']:.3f}"),
        row("  child rank s (top 200)", lambda r: f"{r['best']['rank']:.4f}"),
        row("warm rank ms, median of 20", lambda r: f"{r['warm_median'] * 1e3:.2f}"),
        row("warm rank ms, min of 20", lambda r: f"{r['warm_min'] * 1e3:.2f}"),
        row(
            "child peak RSS MB (RUSAGE_SELF)", lambda r: f"{rss_mb(r['self_rss']):.1f}"
        ),
        row(
            "peak RSS MB (RUSAGE_CHILDREN)",
            lambda r: f"{rss_mb(r['children_rss']):.1f}",
        ),
    ]
    print()
    table(["measure", *(f"{d} dims" for d in order)], rows)
    for dims in order:
        wall = results[dims]["best"]["wall"]
        verdict = "within" if wall <= COLD_LIMIT_S else "OVER"
        print(
            f"  5-second rule at {dims}: {wall:.3f} s, {verdict} {COLD_LIMIT_S:.0f} s"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Pick one mode: --profile (default), --sizes, --judge-sheet, or --score."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--profile", action="store_true", help="read-only profile")
    mode.add_argument(
        "--judge-sheet", action="store_true", help="paid: write judging sheets"
    )
    mode.add_argument("--score", action="store_true", help="numbers from the marks")
    mode.add_argument(
        "--sizes", action="store_true", help="no spend: disk, ranking, cold start"
    )
    args = parser.parse_args(argv)
    if args.sizes:
        return sizes_main()
    if args.judge_sheet:
        return judge_sheet_main()
    if args.score:
        return score_main()
    return profile_main()


if __name__ == "__main__":
    sys.exit(main())
