"""Profile the two MLS tables and write docs/data/schema_notes.md (WO-002).

Read-only, parameterized, aggregates only. Rules enforced here, not by convention:
- connects as `idx_reader` only (refuses any other user) and sets the session READ ONLY;
- identifiers come from information_schema and are backtick-quoted; every value is a
  bound parameter; no user text ever reaches a query string;
- never writes rows: counts, null rates, distinct values (capped at 200 per column,
  never for free-text, deny-listed, or agent-contact columns), percentiles, index lists;
- deny-listed and agent-contact columns are reported by name and null rate only.

Usage:  python scripts/profile_data.py --write docs/data/schema_notes.md [--sample 5000]
Reads MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD from the
environment or from a .env file in the repo root (never committed).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
from collections import defaultdict
from typing import Any

import pymysql
import pymysql.cursors

REPO = pathlib.Path(__file__).resolve().parents[1]
TABLES = ("rets_property", "california_sold")
READER_USER = "idx_reader"
DISTINCT_CAP = 200

DATE_COLUMNS = (
    "CloseDate",
    "PurchaseContractDate",
    "ListingContractDate",
    "ModificationTimestamp",
    "L_ContractDate",
    "L_UpdateDate",
    "L_ListingDate",
)
STATUS_COLUMNS = ("L_Status", "StandardStatus", "MlsStatus", "L_StatusCatID")
CATEGORY_COLUMNS = ("L_Class", "L_Type_", "PropertyType", "PropertySubType")
UNIT_COLUMNS = ("AssociationFeeFrequency", "LivingAreaUnits", "LotSizeUnits")
DISPLAY_COLUMNS = ("InternetEntireListingDisplayYN", "InternetAddressDisplayYN")
CITY_COLUMNS = ("L_City", "City")

DENY_PATTERNS = (
    r"^AccessCode",
    r"^LockBox",
    r"^PrivateRemarks",
    r"^PrivateOfficeRemarks",
    r"^ShowingInstructions",
    r"^Owner",
    r"^Occupant",
    r"Gate.?Code",
    r"Alarm",
)
AGENT_CONTACT_PATTERNS = (
    r"Agent.*(Email|Phone|Name|Fax|Cell|Direct)",
    r"^LA[0-9]_",
    r"^LO[0-9]_",
    r"Office.*(Email|Phone|Name|Fax)",
    r"Member.*(Email|Phone|Name)",
    r"^ListAgent",
    r"^BuyerAgent",
    r"^CoListAgent",
    r"^CoBuyerAgent",
)
FREE_TEXT_PATTERNS = (
    r"Remarks",
    r"Description",
    r"Directions",
    r"Instructions",
    r"Comment",
    r"Photos?$",
    r"URL",
    r"Address",
    r"Street",
    r"Name$",
    r"Email",
    r"Phone",
    r"Virtual",
)
TEXT_TYPES = ("text", "mediumtext", "longtext", "blob", "json")


# ----- environment and connection -------------------------------------------------
def load_env() -> dict[str, str]:
    """Environment first, then .env in the repo root for anything missing."""
    values = {k: v for k, v in os.environ.items() if k.startswith("MYSQL_")}
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("MYSQL_") and key not in values:
                values[key] = value.strip().strip("\"'")
    return values


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    user = env.get("MYSQL_USER", "")
    if user != READER_USER:
        sys.exit(
            f"profile_data: refusing to run as {user!r}; only {READER_USER!r} is allowed"
        )
    conn = pymysql.connect(
        host=env.get("MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("MYSQL_PORT", "3306")),
        user=user,
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", "idx_exchange"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor,
        read_timeout=600,
        autocommit=True,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("SELECT CURRENT_USER()")
        current = str(cur.fetchone()[0])
    if not current.startswith(READER_USER + "@"):
        sys.exit(f"profile_data: connected as {current}, not {READER_USER}; stopping")
    return conn


# ----- small query helpers ----------------------------------------------------------
class Profiler:
    def __init__(
        self, conn: pymysql.connections.Connection, database: str, sample: int
    ):
        self.conn = conn
        self.database = database
        self.sample = sample
        self.columns: dict[str, list[dict[str, Any]]] = {}
        self.notes: list[str] = []

    def q(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def one(self, sql: str, params: tuple = ()) -> Any:
        rows = self.q(sql, params)
        return rows[0][0] if rows else None

    @staticmethod
    def ident(name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise ValueError(f"unsafe identifier {name!r}")
        return f"`{name}`"

    def has(self, table: str, column: str) -> bool:
        return any(c["name"] == column for c in self.columns.get(table, []))

    def col_type(self, table: str, column: str) -> str:
        for c in self.columns.get(table, []):
            if c["name"] == column:
                return c["type"]
        return ""

    def load_columns(self) -> None:
        for table in TABLES:
            rows = self.q(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (self.database, table),
            )
            self.columns[table] = [
                {"name": r[0], "type": r[1], "full_type": r[2], "nullable": r[3]}
                for r in rows
            ]

    # classification -------------------------------------------------------------
    @staticmethod
    def matches(name: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(p, name, re.I) for p in patterns)

    def is_deny(self, name: str) -> bool:
        return self.matches(name, DENY_PATTERNS)

    def is_agent_contact(self, name: str) -> bool:
        return self.matches(name, AGENT_CONTACT_PATTERNS)

    def is_free_text(self, table: str, name: str) -> bool:
        return self.col_type(table, name) in TEXT_TYPES or self.matches(
            name, FREE_TEXT_PATTERNS
        )

    def listable(self, table: str, name: str) -> bool:
        return not (
            self.is_deny(name)
            or self.is_agent_contact(name)
            or self.is_free_text(table, name)
        )


# ----- sections -----------------------------------------------------------------------
def section_counts(p: Profiler) -> list[str]:
    out = ["## 1. Row counts", "", "| table | rows |", "|---|---|"]
    for t in TABLES:
        out.append(f"| {t} | {p.one(f'SELECT COUNT(*) FROM {p.ident(t)}'):,} |")
    return out + [""]


def section_columns(p: Profiler) -> list[str]:
    out = ["## 2. Columns: type, null rate, empty rate, flags", ""]
    for t in TABLES:
        n = p.one(f"SELECT COUNT(*) FROM {p.ident(t)}") or 1
        out += [
            f"### {t} ({len(p.columns[t])} columns)",
            "",
            "| column | type | null % | empty % | flags |",
            "|---|---|---|---|---|",
        ]
        for c in p.columns[t]:
            name = c["name"]
            null = (
                p.one(
                    f"SELECT COUNT(*) FROM {p.ident(t)} WHERE {p.ident(name)} IS NULL"
                )
                or 0
            )
            if c["type"] in ("char", "varchar", "text", "mediumtext", "longtext"):
                empty = (
                    p.one(
                        f"SELECT COUNT(*) FROM {p.ident(t)} WHERE {p.ident(name)} = ''"
                    )
                    or 0
                )
            else:
                empty = 0
            flags = []
            if p.is_deny(name):
                flags.append("DENY-LIST candidate")
            if p.is_agent_contact(name):
                flags.append("agent contact")
            if p.is_free_text(t, name):
                flags.append("free text")
            out.append(
                f"| {name} | {c['full_type']} | {100 * null / n:.1f} | {100 * empty / n:.1f} | {', '.join(flags)} |"
            )
        out.append("")
    return out


def section_dates(p: Profiler) -> list[str]:
    out = [
        "## 3. Dates and the as-of dates",
        "",
        "| table | column | min | max | not YYYY-MM-DD % | null/empty % |",
        "|---|---|---|---|---|---|",
    ]
    as_of: dict[str, str] = {}
    for t in TABLES:
        for col in DATE_COLUMNS:
            if not p.has(t, col):
                continue
            ic = p.ident(col)
            n = p.one(f"SELECT COUNT(*) FROM {p.ident(t)}") or 1
            row = p.q(
                f"SELECT MIN(LEFT({ic},10)), MAX(LEFT({ic},10)), "
                f"SUM(CASE WHEN {ic} IS NULL OR {ic} = '' THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {ic} IS NOT NULL AND {ic} <> '' AND LEFT({ic},10) NOT REGEXP %s THEN 1 ELSE 0 END) "
                f"FROM {p.ident(t)}",
                (r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",),
            )[0]
            out.append(
                f"| {t} | {col} | {row[0]} | {row[1]} | {100 * (row[3] or 0) / n:.2f} | {100 * (row[2] or 0) / n:.2f} |"
            )
            if t == "california_sold" and col == "CloseDate":
                as_of["sold"] = str(row[1])
            if (
                t == "rets_property"
                and col in ("ModificationTimestamp", "L_UpdateDate")
                and "active" not in as_of
            ):
                as_of["active"] = str(row[1])
    out += [
        "",
        "**As-of dates (derived):**",
        "",
        f"- sold: `{as_of.get('sold', 'not found')}` (MAX CloseDate in california_sold)",
        f"- active: `{as_of.get('active', 'not found')}` (MAX of the modification timestamp in rets_property)",
        "",
    ]
    return out


def distribution(p: Profiler, t: str, col: str, cap: int = DISTINCT_CAP) -> list[str]:
    ic = p.ident(col)
    n_distinct = p.one(f"SELECT COUNT(DISTINCT {ic}) FROM {p.ident(t)}") or 0
    lines = [f"**{t}.{col}**: {n_distinct} distinct values"]
    if n_distinct > cap:
        lines.append(f"(more than {cap}; not listed)")
        return lines
    rows = p.q(
        f"SELECT {ic}, COUNT(*) FROM {p.ident(t)} GROUP BY {ic} ORDER BY COUNT(*) DESC LIMIT %s",
        (cap,),
    )
    lines += ["", "| value | count |", "|---|---|"]
    for v, c in rows:
        shown = "(null)" if v is None else ("(empty)" if v == "" else str(v)[:60])
        lines.append(f"| {shown} | {c:,} |")
    return lines


def section_status(p: Profiler) -> list[str]:
    out = ["## 4. Status columns", ""]
    for t in TABLES:
        present = [c for c in STATUS_COLUMNS if p.has(t, c)]
        for c in present:
            out += distribution(p, t, c) + [""]
        if len(present) >= 2:
            a, b = present[0], present[1]
            rows = p.q(
                f"SELECT {p.ident(a)}, {p.ident(b)}, COUNT(*) FROM {p.ident(t)} GROUP BY {p.ident(a)}, {p.ident(b)} ORDER BY COUNT(*) DESC LIMIT %s",
                (DISTINCT_CAP,),
            )
            out += [
                f"**Cross-tab {t}: {a} x {b}**",
                "",
                f"| {a} | {b} | count |",
                "|---|---|---|",
            ]
            out += [f"| {r[0]} | {r[1]} | {r[2]:,} |" for r in rows] + [""]
    return out


def section_categories(p: Profiler) -> list[str]:
    out = ["## 5. Categories and flags", ""]
    for t in TABLES:
        for c in CATEGORY_COLUMNS:
            if p.has(t, c):
                out += distribution(p, t, c) + [""]
        flags = [
            c["name"]
            for c in p.columns[t]
            if re.search(r"(YN|Flag)$", c["name"]) and p.listable(t, c["name"])
        ]
        for c in flags[:60]:
            out += distribution(p, t, c, cap=12) + [""]
    return out


def section_cities(p: Profiler) -> list[str]:
    out = ["## 6. City spellings", ""]
    for t in TABLES:
        for c in CITY_COLUMNS:
            if not p.has(t, c):
                continue
            rows = p.q(
                f"SELECT {p.ident(c)}, COUNT(*) FROM {p.ident(t)} GROUP BY {p.ident(c)} ORDER BY COUNT(*) DESC"
            )
            groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for v, cnt in rows:
                key = re.sub(r"\s+", " ", str(v or "").strip()).lower()
                groups[key].append((str(v), cnt))
            variants = {k: v for k, v in groups.items() if len(v) > 1}
            out += [
                f"**{t}.{c}**: {len(rows)} raw spellings, {len(groups)} normalized cities, {len(variants)} with casing/spacing variants",
                "",
            ]
            if variants:
                out += ["| normalized | variants (count) |", "|---|---|"]
                for k, vs in sorted(variants.items())[:DISTINCT_CAP]:
                    out.append(
                        f"| {k} | "
                        + "; ".join(f"{s} ({n:,})" for s, n in vs[:6])
                        + " |"
                    )
            out.append("")
    return out


def section_dom(p: Profiler) -> list[str]:
    out = ["## 7. Days on market: stored vs derived (sample)", ""]
    for t in TABLES:
        dom = next((c for c in ("DaysOnMarket", "L_DOM", "DOM") if p.has(t, c)), None)
        pcd = next(
            (c for c in ("PurchaseContractDate", "L_ContractDate") if p.has(t, c)), None
        )
        lcd = next(
            (c for c in ("ListingContractDate", "L_ListingDate") if p.has(t, c)), None
        )
        if not (dom and pcd and lcd):
            out.append(
                f"- {t}: needs {dom or 'a DOM column'}, {pcd or 'a contract date'}, {lcd or 'a listing date'}; not all present"
            )
            continue
        rows = p.q(
            f"SELECT COUNT(*), AVG(ABS(d)), SUM(CASE WHEN ABS(d) <= 1 THEN 1 ELSE 0 END) FROM ("
            f"SELECT CAST({p.ident(dom)} AS SIGNED) - DATEDIFF(STR_TO_DATE(LEFT({p.ident(pcd)},10), '%%Y-%%m-%%d'), STR_TO_DATE(LEFT({p.ident(lcd)},10), '%%Y-%%m-%%d')) AS d "
            f"FROM {p.ident(t)} WHERE {p.ident(dom)} IS NOT NULL AND {p.ident(pcd)} <> '' AND {p.ident(lcd)} <> '' LIMIT %s) s",
            (p.sample,),
        )[0]
        n, avg, within = rows
        out.append(
            f"- {t}: {n:,} sampled rows; mean |stored - derived| = {float(avg or 0):.1f} days; {100 * (within or 0) / (n or 1):.1f}% within 1 day"
        )
    return out + [""]


def section_duplicates(p: Profiler) -> list[str]:
    out = ["## 8. Duplicates", ""]
    for t, key in (("rets_property", "L_ListingID"), ("california_sold", "ListingKey")):
        if p.has(t, key):
            dup = (
                p.one(
                    f"SELECT COUNT(*) FROM (SELECT {p.ident(key)} FROM {p.ident(t)} GROUP BY {p.ident(key)} HAVING COUNT(*) > 1) d"
                )
                or 0
            )
            out.append(f"- {t}.{key}: {dup:,} keys appear more than once")
    addr = next(
        (
            c
            for c in ("UnparsedAddress", "StreetAddress", "Address")
            if p.has("california_sold", c)
        ),
        None,
    )
    if addr and p.has("california_sold", "CloseDate"):
        dup = (
            p.one(
                f"SELECT COUNT(*) FROM (SELECT {p.ident(addr)}, `CloseDate` FROM `california_sold` GROUP BY {p.ident(addr)}, `CloseDate` HAVING COUNT(*) > 1) d"
            )
            or 0
        )
        out.append(
            f"- california_sold: {dup:,} (address, close date) pairs appear more than once (values not listed)"
        )
    return out + [""]


def percentiles(p: Profiler, t: str, col: str) -> dict[str, float] | None:
    ic = p.ident(col)
    n = (
        p.one(f"SELECT COUNT(*) FROM {p.ident(t)} WHERE {ic} IS NOT NULL AND {ic} > 0")
        or 0
    )
    if n == 0:
        return None
    out: dict[str, float] = {"n": n}
    for label, q in (
        ("p1", 0.01),
        ("p5", 0.05),
        ("p50", 0.5),
        ("p95", 0.95),
        ("p99", 0.99),
    ):
        k = min(n - 1, int(n * q))
        out[label] = float(
            p.one(
                f"SELECT {ic} FROM {p.ident(t)} WHERE {ic} IS NOT NULL AND {ic} > 0 ORDER BY {ic} LIMIT 1 OFFSET %s",
                (k,),
            )
            or 0
        )
    return out


def section_outliers(p: Profiler) -> list[str]:
    out = [
        "## 9. Outliers and proposed floors",
        "",
        "| table | column | n>0 | p1 | p5 | p50 | p95 | p99 | proposed floor |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    targets = (
        (
            "california_sold",
            (
                "ClosePrice",
                "ListPrice",
                "LivingArea",
                "LotSizeSquareFeet",
                "LotSizeArea",
            ),
        ),
        (
            "rets_property",
            (
                "L_SystemPrice",
                "L_AskingPrice",
                "LM_Int2_3",
                "L_LotSize",
                "LotSizeSquareFeet",
            ),
        ),
    )
    for t, cols in targets:
        for c in cols:
            if not p.has(t, c):
                continue
            pc = percentiles(p, t, c)
            if not pc:
                continue
            floor = pc["p1"] if "Price" in c else max(1.0, pc["p1"])
            out.append(
                f"| {t} | {c} | {int(pc['n']):,} | {pc['p1']:,.0f} | {pc['p5']:,.0f} | {pc['p50']:,.0f} | {pc['p95']:,.0f} | {pc['p99']:,.0f} | >= {floor:,.0f} (review) |"
            )
    return out + [""]


def section_units_and_display(p: Profiler) -> list[str]:
    out = ["## 10-11. Unit, frequency, and display columns", ""]
    for t in TABLES:
        for c in UNIT_COLUMNS + DISPLAY_COLUMNS:
            if p.has(t, c):
                out += distribution(p, t, c, cap=30) + [""]
            else:
                out.append(f"- {t}.{c}: not present")
    return out + [""]


def section_photos_and_coords(p: Profiler) -> list[str]:
    out = ["## 12. Photos and coordinates", ""]
    t = "rets_property"
    if p.has(t, "L_Photos"):
        rows = p.q(
            f"SELECT `L_Photos` FROM {p.ident(t)} WHERE `L_Photos` IS NOT NULL AND `L_Photos` <> '' LIMIT %s",
            (min(p.sample, 2000),),
        )
        parsed = 0
        for (v,) in rows:
            try:
                parsed += isinstance(json.loads(v), list)
            except (TypeError, ValueError):
                pass
        out.append(
            f"- L_Photos: {parsed}/{len(rows)} sampled non-empty values parse as a JSON array"
        )
    for t in TABLES:
        lat = next(
            (c for c in ("Latitude", "L_Latitude", "LMD_MP_Latitude") if p.has(t, c)),
            None,
        )
        lon = next(
            (
                c
                for c in ("Longitude", "L_Longitude", "LMD_MP_Longitude")
                if p.has(t, c)
            ),
            None,
        )
        if lat and lon:
            bad = (
                p.one(
                    f"SELECT COUNT(*) FROM {p.ident(t)} WHERE {p.ident(lat)} IS NULL OR {p.ident(lon)} IS NULL OR {p.ident(lat)} = 0 OR {p.ident(lon)} = 0"
                )
                or 0
            )
            n = p.one(f"SELECT COUNT(*) FROM {p.ident(t)}") or 1
            out.append(
                f"- {t}: {lat}/{lon} null or zero in {bad:,} rows ({100 * bad / n:.1f}%)"
            )
        else:
            out.append(f"- {t}: no latitude/longitude columns found by name")
    return out + [""]


def section_indexes(p: Profiler) -> list[str]:
    out = ["## 13. Existing indexes", ""]
    for t in TABLES:
        rows = p.q(
            "SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX), NON_UNIQUE, INDEX_TYPE "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "GROUP BY INDEX_NAME, NON_UNIQUE, INDEX_TYPE ORDER BY INDEX_NAME",
            (p.database, t),
        )
        out += [
            f"**{t}**",
            "",
            "| index | columns | unique | type |",
            "|---|---|---|---|",
        ]
        out += [
            f"| {r[0]} | {r[1]} | {'no' if r[2] else 'yes'} | {r[3]} |" for r in rows
        ] + [""]
    return out


def section_lists(p: Profiler) -> list[str]:
    out = ["## Deny-list and agent-contact columns found (names only)", ""]
    for t in TABLES:
        deny = [c["name"] for c in p.columns[t] if p.is_deny(c["name"])]
        contact = [c["name"] for c in p.columns[t] if p.is_agent_contact(c["name"])]
        out += [
            f"- {t} deny-list: {', '.join(deny) or 'none by name pattern'}",
            f"- {t} agent contact: {', '.join(contact) or 'none by name pattern'}",
        ]
    return out + [""]


CANONICAL_MAP = [
    ("ListingKey", "L_ListingID (cast)", "ListingKey", "join key"),
    ("ListingId", "L_DisplayId", "ListingId", "verify names"),
    ("City", "L_City", "City", "normalize casing"),
    ("PostalCode", "L_Zip", "PostalCode", "5 digits"),
    ("ListPrice", "L_SystemPrice", "ListPrice", ""),
    ("ClosePrice", "", "ClosePrice", "sold only"),
    ("CloseDate", "", "CloseDate", "text; migration adds a DATE column"),
    ("BedroomsTotal", "L_Keyword2", "BedroomsTotal", "doubles in sold; cast"),
    (
        "Bathrooms",
        "LM_Dec_3",
        "BathroomsTotalInteger",
        "different definitions; never compared",
    ),
    ("LivingArea", "LM_Int2_3", "LivingArea", ""),
    (
        "PropertySubType",
        "L_Type_",
        "PropertySubType",
        "value sets differ; map in valid_values",
    ),
    ("Status", "L_Status / StandardStatus", "", "decision below"),
    ("DaysOnMarket", "L_DOM?", "DaysOnMarket", "section 7"),
    ("Remarks", "L_Remarks", "PublicRemarks?", "untrusted text; never logged"),
    ("Photos", "L_Photos (JSON)", "", "section 12"),
    ("Latitude/Longitude", "?", "?", "section 12"),
]


def render(p: Profiler, sections: list[list[str]], env: dict[str, str]) -> str:
    head = [
        "# Schema notes (generated by scripts/profile_data.py)",
        "",
        f"Generated {dt.datetime.now(dt.UTC).isoformat(timespec='minutes')} against database "
        f"`{env.get('MYSQL_DATABASE', 'idx_exchange')}` as `{READER_USER}`. Aggregates only; no rows.",
        "Sections marked (decision) are filled in by hand after reading the numbers.",
        "",
        "## Canonical map (RESO name | rets_property | california_sold | note)",
        "",
        "| RESO | rets_property | california_sold | note |",
        "|---|---|---|---|",
    ]
    head += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in CANONICAL_MAP]
    head += [
        "",
        "## Decisions (filled by hand after the run)",
        "",
        '- Which status column defines "active": (decision)',
        "- Exclusion rules (price floors, missing sqft, test rows): (decision)",
        "- Deny-list (confirmed present): (decision; see the names section below)",
        "- Allowlist per table: `src/idx_agent/safety/columns.py`",
        "- Index plan: `scripts/migrations/001_dates_and_indexes.sql`",
        "",
    ]
    body: list[str] = []
    for s in sections:
        body += s
    if p.notes:
        body += ["## Profiler notes", ""] + [f"- {n}" for n in p.notes] + [""]
    return "\n".join(head + body) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--write", type=pathlib.Path, default=REPO / "docs" / "data" / "schema_notes.md"
    )
    ap.add_argument(
        "--sample", type=int, default=5000, help="rows sampled for DOM and photo checks"
    )
    args = ap.parse_args(argv[1:])
    env = load_env()
    conn = connect(env)
    p = Profiler(conn, env.get("MYSQL_DATABASE", "idx_exchange"), args.sample)
    p.load_columns()
    for t in TABLES:
        if not p.columns.get(t):
            sys.exit(f"profile_data: table {t} not found in {p.database}")
    sections = []
    for fn in (
        section_counts,
        section_columns,
        section_dates,
        section_status,
        section_categories,
        section_cities,
        section_dom,
        section_duplicates,
        section_outliers,
        section_units_and_display,
        section_photos_and_coords,
        section_indexes,
        section_lists,
    ):
        try:
            sections.append(fn(p))
        except pymysql.MySQLError as exc:  # keep going; record the failure class only
            p.notes.append(
                f"{fn.__name__} failed: {type(exc).__name__} {getattr(exc, 'args', [''])[0]}"
            )
            sections.append(
                [f"## {fn.__name__}", "", "(failed; see profiler notes)", ""]
            )
    text = render(p, sections, env)
    args.write.parent.mkdir(parents=True, exist_ok=True)
    args.write.write_text(text, encoding="utf-8")
    print(f"wrote {args.write} ({text.count(chr(10))} lines)")
    for line in text.splitlines():
        if (
            line.startswith("## 1.")
            or line.startswith("- sold:")
            or line.startswith("- active:")
        ):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
