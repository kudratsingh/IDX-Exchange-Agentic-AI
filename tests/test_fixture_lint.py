"""Tests for scripts/fixture_lint.py and the committed synthetic fixture (WO-005).

The shipped fixture must pass; a temp copy with one bad value must fail with exit 1.
Bad values are assembled at run time so this file itself never holds one.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic.sql"
LINT = ROOT / "scripts" / "fixture_lint.py"
GENERATOR = ROOT / "tests" / "fixtures" / "make_synthetic.py"
FIRST_KEY = "'9100001'"


def _lint(path: Path) -> subprocess.CompletedProcess[str]:
    """Run the lint on one file as CI does and capture its output."""
    return subprocess.run(
        [sys.executable, str(LINT), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def _variant(tmp_path: Path, old: str, new: str) -> Path:
    """Write a copy of the fixture with the first `old` replaced by `new`."""
    text = FIXTURE.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "variant.sql"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_the_shipped_fixture_passes():
    result = _lint(FIXTURE)
    assert result.returncode == 0, result.stdout
    assert "ok" in result.stdout


def test_the_committed_fixture_matches_the_generator():
    spec = importlib.util.spec_from_file_location("make_synthetic", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.render() == FIXTURE.read_text(encoding="utf-8")


def test_an_inserted_email_address_fails(tmp_path):
    email = "someone" + chr(64) + "mailhost.org"
    result = _lint(_variant(tmp_path, "Invented Way'", f"Invented Way {email}'"))
    assert result.returncode == 1
    assert "email address" in result.stdout
    assert email not in result.stdout


def test_an_inserted_phone_number_fails(tmp_path):
    phone = "-".join(("310", "123", "4567"))
    result = _lint(_variant(tmp_path, "Invented Way'", f"Invented Way {phone}'"))
    assert result.returncode == 1
    assert "phone-number-like" in result.stdout


@pytest.mark.parametrize("key", ["912345678", "8100001", "91001"])
def test_a_key_outside_the_invented_range_fails(tmp_path, key):
    result = _lint(_variant(tmp_path, FIRST_KEY, f"'{key}'"))
    assert result.returncode == 1
    assert "not an invented key" in result.stdout


def test_an_agent_contact_value_fails(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8")
    row = (
        "INSERT INTO `rets_property` (`L_ListingID`, `L_DisplayId`, "
        "`ListAgentFullName`) VALUES ('9100999', '9500999', 'Invented Person');\n"
    )
    path = tmp_path / "variant.sql"
    path.write_text(text + row, encoding="utf-8")
    result = _lint(path)
    assert result.returncode == 1
    assert "agent-contact column ListAgentFullName" in result.stdout


def _appended(tmp_path: Path, statement: str) -> Path:
    """Write a copy of the fixture with one extra line at the end."""
    path = tmp_path / "variant.sql"
    text = FIXTURE.read_text(encoding="utf-8")
    path.write_text(text + statement + "\n", encoding="utf-8")
    return path


def _statement(*words: str) -> str:
    """Join words into one statement at run time, so no bad SQL sits in this file."""
    return " ".join(words) + ";"


TABLE = "`rets_property`"
KEYS_AND_CITY = "(`L_ListingID`, `L_DisplayId`, `L_City`)"
ROW = "('9100998', '9500998', 'Pasadena')"


@pytest.mark.parametrize(
    "statement",
    [
        _statement("REPLACE", "INTO", TABLE, KEYS_AND_CITY, "VALUES", ROW),
        _statement("UPDATE", TABLE, "SET", "`L_City`", "=", "'Pasadena'"),
        _statement("LOAD", "DATA", "INFILE", "'rows.csv'", "INTO", "TABLE", TABLE),
        _statement("DELETE", "FROM", TABLE),
    ],
    ids=["replace", "update", "load-data", "delete"],
)
def test_a_statement_other_than_create_set_insert_fails(tmp_path, statement):
    result = _lint(_appended(tmp_path, statement))
    assert result.returncode == 1
    assert "statement other than CREATE TABLE, SET, or one-row INSERT" in result.stdout


def test_a_multi_row_insert_fails(tmp_path):
    second = "('9100997', '9500997', 'Pasadena')"
    statement = _statement(
        "INSERT", "INTO", TABLE, KEYS_AND_CITY, "VALUES", ROW + ",", second
    )
    result = _lint(_appended(tmp_path, statement))
    assert result.returncode == 1
    assert "only single-row INSERTs are allowed" in result.stdout


def test_a_multi_line_insert_fails(tmp_path):
    head = _statement("INSERT", "INTO", TABLE, KEYS_AND_CITY, "VALUES", ROW)[:-1]
    result = _lint(_appended(tmp_path, head + ",\n('9100997', '9500997', 'Pasadena');"))
    assert result.returncode == 1


def test_a_quoted_default_on_an_agent_contact_column_fails(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "`ListAgentFullName` varchar(" in ln)
    bad = line.replace(" NULL,", " " + "DEFAULT" + " 'x',")
    path = tmp_path / "variant.sql"
    path.write_text(text.replace(line, bad, 1), encoding="utf-8")
    result = _lint(path)
    assert result.returncode == 1
    assert "protected column ListAgentFullName has a quoted DEFAULT" in result.stdout


def test_a_quoted_default_on_a_deny_listed_column_fails(tmp_path):
    # The fixture has no deny-listed column, so one is added to the active table's DDL.
    head = "CREATE TABLE `rets_property` (\n"
    extra = "  `AccessCode` varchar(64) " + "DEFAULT" + " 'x',\n"
    result = _lint(_variant(tmp_path, head, head + extra))
    assert result.returncode == 1
    assert "protected column AccessCode has a quoted DEFAULT" in result.stdout


@pytest.mark.parametrize(
    ("table", "columns", "values", "missing"),
    [
        ("`rets_property`", "(`L_ListingID`, `L_City`)", "('9100996', 'Pasadena')",
         "L_DisplayId"),
        ("`california_sold`", "(`City`, `PostalCode`)", "('Pasadena', '91101')",
         "ListingKey"),
    ],
)  # fmt: skip
def test_an_insert_without_its_key_columns_fails(
    tmp_path, table, columns, values, missing
):
    statement = _statement("INSERT", "INTO", table, columns, "VALUES", values)
    result = _lint(_appended(tmp_path, statement))
    assert result.returncode == 1
    assert f"leaves out key column {missing}" in result.stdout


def test_an_insert_into_a_table_the_file_does_not_create_fails(tmp_path):
    statement = _statement(
        "INSERT", "INTO", "`other_table`", "(`City`)", "VALUES", "('Pasadena')"
    )
    result = _lint(_appended(tmp_path, statement))
    assert result.returncode == 1
    assert "a table this file does not create" in result.stdout


def _lint_module():
    """Import scripts/fixture_lint.py as a module for direct pattern checks."""
    spec = importlib.util.spec_from_file_location("fixture_lint", LINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_email_pattern_needs_a_dot_in_the_domain():
    email = _lint_module().EMAIL
    at = chr(64)
    assert email.search("someone" + at + "mailhost.org")
    assert email.search("some.one" + at + "mail.host.co")
    assert not email.search("someone" + at + "mailhost")
    assert not email.search("pkg" + at + "1.2")
