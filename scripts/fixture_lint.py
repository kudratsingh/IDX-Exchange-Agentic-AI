"""Fixture lint: fail when a test fixture holds anything that could be real (WO-005).

Whole text: no email, no phone-like digits; only CREATE TABLE, SET, and one-row INSERT
statements. DDL: no quoted DEFAULT on a protected column. INSERT: keys present and
invented (9 then 5-6 digits); protected columns NULL. Usage: fixture_lint.py FILE ...
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The column sets live in the package; read them from this checkout's src.
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST  # noqa: E402

PROTECTED = AGENT_CONTACT | DENYLIST
KEY_COLUMNS = frozenset({"L_ListingID", "L_DisplayId", "ListingKey"})
# Key columns each known table must carry in every INSERT, even if its DDL is elsewhere.
TABLE_KEYS = {
    "rets_property": frozenset({"L_ListingID", "L_DisplayId"}),
    "california_sold": frozenset({"ListingKey"}),
}
INVENTED_KEY = re.compile(r"9[0-9]{5,6}")
# The domain needs a dot and a letter-only last part; a bare "name@host" is not flagged.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
# 3-3-4 numbers with separators (optional +1 and parentheses), 3-4 local numbers,
# and bare runs of 10 or 11 digits that are not the fraction of a decimal.
PHONES = (
    re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]\d{4}(?!\d)"),
    re.compile(r"(?<![\d-])\d{3}-\d{4}(?![\d-])"),
    re.compile(r"(?<![\d.])\d{10,11}(?!\d)"),
)
INSERT = re.compile(r"INSERT INTO `?(\w+)`?\s*\(([^)]*)\)\s*VALUES\s*\((.*)\);\s*$")
CREATE = re.compile(r"CREATE TABLE `?(\w+)`?\s*\($")
CREATE_END = re.compile(r"\)[^;]*;\s*$")
SET = re.compile(r"SET\s[^;]*;\s*$", re.IGNORECASE)
DDL_COLUMN = re.compile(r"`?(\w+)`?\s")
QUOTED_DEFAULT = re.compile(r"\bDEFAULT\s+['\"]", re.IGNORECASE)
# An unquoted value must be NULL or a plain number; anything else is an expression.
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_values(text: str) -> list[str | None]:
    """Split a VALUES body into Python values: strings unescaped, NULL as None.

    Numbers stay as their text. Raises ValueError on an unterminated string or on an
    unquoted token that is not NULL or a number (a second row, a call, a subquery).
    """
    values: list[str | None] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char in " ,":
            i += 1
        elif char == "'":
            out, i = [], i + 1
            while True:
                if i >= len(text):
                    raise ValueError("unterminated string")
                if text[i] == "\\":
                    out.append(text[i + 1 : i + 2])
                    i += 2
                elif text.startswith("''", i):
                    out.append("'")
                    i += 2
                elif text[i] == "'":
                    i += 1
                    break
                else:
                    out.append(text[i])
                    i += 1
            values.append("".join(out))
        else:
            end = text.find(",", i)
            end = len(text) if end < 0 else end
            token = text[i:end].strip()
            if token.upper() != "NULL" and not NUMBER.fullmatch(token):
                raise ValueError("a value is not a string, a number, or NULL")
            values.append(None if token.upper() == "NULL" else token)
            i = end
    return values


def check_row(line: str, table_columns: dict[str, set[str]]) -> list[str]:
    """Return the problems in one INSERT line (empty when it is clean).

    `table_columns` maps each table created earlier in the file to its column names.
    """
    match = INSERT.match(line.strip())
    if not match:
        return ["INSERT statement the lint cannot parse (keep one row per line)"]
    table = match.group(1)
    columns = [name.strip(" `") for name in match.group(2).split(",")]
    try:
        values = parse_values(match.group(3))
    except ValueError as exc:
        return [f"INSERT values: {exc} (only single-row INSERTs are allowed)"]
    if len(values) != len(columns):
        return ["INSERT has a different number of columns and values"]
    problems = []
    if table not in table_columns:
        problems.append(f"INSERT into {table}, a table this file does not create")
    required = TABLE_KEYS.get(table, frozenset()) | (
        KEY_COLUMNS & table_columns.get(table, set())
    )
    problems += [
        f"INSERT into {table} leaves out key column {key}"
        for key in sorted(required - set(columns))
    ]
    for column, value in zip(columns, values, strict=True):
        if column in AGENT_CONTACT and value is not None:
            problems.append(f"agent-contact column {column} is not NULL")
        elif column in DENYLIST and value is not None:
            problems.append(f"deny-listed column {column} is not NULL")
        elif column in KEY_COLUMNS and not INVENTED_KEY.fullmatch(value or ""):
            problems.append(f"{column} is not an invented key (9 then 5-6 digits)")
    return problems


def check_ddl_line(line: str, columns: set[str]) -> list[str]:
    """Record one CREATE TABLE body line's column; return its problems."""
    match = DDL_COLUMN.match(line.strip())
    if not match or match.group(1).upper() in ("PRIMARY", "KEY", "UNIQUE", "FULLTEXT"):
        return []
    column = match.group(1)
    columns.add(column)
    if column in PROTECTED and QUOTED_DEFAULT.search(line):
        return [f"protected column {column} has a quoted DEFAULT value"]
    return []


def lint_text(text: str) -> tuple[list[str], int]:
    """Return (problems as "line N: message", number of INSERT rows checked).

    Offending values are never echoed, so a real one does not spread into logs.
    """
    problems: list[str] = []
    rows = 0
    table_columns: dict[str, set[str]] = {}
    creating: set[str] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        found = []
        if EMAIL.search(line):
            found.append("email address")
        if any(pattern.search(line) for pattern in PHONES):
            found.append("phone-number-like digit run")
        stripped = line.strip()
        upper = stripped.upper()
        if creating is not None:
            if CREATE_END.match(stripped):
                creating = None
            elif ";" in stripped:
                found.append("statement inside CREATE TABLE the lint does not allow")
            else:
                found += check_ddl_line(stripped, creating)
        elif not stripped or stripped.startswith("-- ") or stripped == "--":
            pass
        elif CREATE.match(stripped):
            creating = table_columns.setdefault(CREATE.match(stripped).group(1), set())
        elif upper.startswith("INSERT"):
            rows += 1
            found += check_row(stripped, table_columns)
        elif not SET.match(stripped):
            found.append("statement other than CREATE TABLE, SET, or one-row INSERT")
        problems += [f"line {number}: {message}" for message in found]
    if creating is not None:
        problems.append("end of file: CREATE TABLE is not closed")
    return problems, rows


def main(argv: list[str]) -> int:
    """Lint each file named in argv; print ok or every problem; return the exit code."""
    if not argv:
        print("usage: python scripts/fixture_lint.py FILE [FILE ...]")
        return 2
    failed = False
    for name in argv:
        problems, rows = lint_text(Path(name).read_text(encoding="utf-8"))
        if problems:
            failed = True
            print(f"fixture_lint: FAILED {name} ({len(problems)} problem(s))")
            print("\n".join(f"  {name}: {problem}" for problem in problems))
        else:
            print(f"fixture_lint: ok {name} ({rows} rows checked)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
