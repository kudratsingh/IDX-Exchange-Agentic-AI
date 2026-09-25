"""Tests for scripts/demo_preflight.py (WO-014): each check passes on a good stubbed
setup and fails on its broken twin; exit codes; no secret printed, no model SDK, no
socket, no file written. The indexes are the real fixture ones; the paid token is a
real v2 token in conftest's temp consent dir; the database is a stub."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import time
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from tests import rag_fixture, semantic_fixture
from tests.paid_token import grant_paid

import idx_agent
from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_preflight.py"
SERVER = " ".join(consent.SERVER_ARGV)
ACTIVE = date(2026, 9, 18)  # the fixture index's active as-of date
SENTINEL = "sentinel-secret-7f3a91"


def _load() -> ModuleType:
    """Load the script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("demo_preflight", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


pf = _load()
REAL_READ_ASOF = pf._read_asof


@pytest.fixture(scope="module")
def indexes(tmp_path_factory) -> dict[str, Path]:
    """The two fixture indexes, built once in a temp folder."""
    # The folder name carries the sentinel: the index settings' values hold it.
    base = tmp_path_factory.mktemp(f"preflight_{SENTINEL}")
    return {
        "remarks": semantic_fixture.build_fixture_index(base),
        "docs": rag_fixture.build_fixture_index(base),
    }


@pytest.fixture
def good(monkeypatch, tmp_path, indexes) -> Path:
    """A setup where every check passes; returns the log folder."""
    env = {
        **semantic_fixture.fixture_env(indexes["remarks"]),
        **rag_fixture.fixture_env(indexes["docs"]),
        "IDX_SENDER_KEY": SENTINEL,
        "IDX_OTLP_ENDPOINT": "http://127.0.0.1:4318",
        "IDX_LOG_FILE": str(tmp_path / f"logs-{SENTINEL}" / "idx.log"),
        "OPENAI_API_KEY": SENTINEL,
        "MYSQL_PASSWORD": SENTINEL,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    (tmp_path / f"logs-{SENTINEL}").mkdir()
    dates = SimpleNamespace(active=ACTIVE, sold=date(2026, 9, 17))
    monkeypatch.setattr(pf, "_read_asof", lambda: dates)
    grant_paid(SERVER, max_calls=20, minutes=90)
    return tmp_path / f"logs-{SENTINEL}"


def by_name(minutes: int = 60) -> dict[str, object]:
    """Run every check; the checks by name."""
    checks, _ = pf.run_checks(minutes)
    return {c.name: c for c in checks}


def test_every_check_passes_on_a_good_setup_in_order(good) -> None:
    checks, outputs = pf.run_checks(60)
    assert [c.name for c in checks] == [
        "package",
        "tools",
        "database",
        "remarks_index",
        "docs_index",
        "settings",
        "paid_token",
        "log_file",
    ]
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert outputs == []
    assert "matches the database" in by_name()["remarks_index"].reason


def test_exit_0_when_every_check_passes(good, capsys) -> None:
    assert pf.main(["--minutes", "60"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 9 and lines[-1] == "preflight: 8 of 8 checks ok"
    assert all(line.split()[1] == "ok" for line in lines[:8])


def test_tools_fail_when_one_is_missing_from_the_registry(good, monkeypatch) -> None:
    names = sorted(pf.EXPECTED_TOOLS - {"recommend"}) + ["extra_tool"]
    monkeypatch.setattr(pf, "_tool_names", lambda: names)
    check = by_name()["tools"]
    assert not check.ok
    assert "missing recommend" in check.reason and "unexpected extra_tool" in (
        check.reason
    )


def test_database_error_fails_with_the_class_name_only(good, monkeypatch) -> None:
    def broken():
        raise ConnectionError(f"host db.internal refused {SENTINEL}")

    monkeypatch.setattr(pf, "_read_asof", broken)
    checks = by_name()
    assert not checks["database"].ok
    assert checks["database"].reason == "no answer (ConnectionError)"
    # The indexes still load; with no database date they are not compared.
    assert checks["remarks_index"].ok and "no database date" in (
        checks["remarks_index"].reason
    )


@pytest.mark.parametrize("error", [LookupError, KeyError, IndexError])
def test_a_lookup_error_prints_its_class_name_only(good, monkeypatch, error) -> None:
    def broken():
        raise error(f"MYSQL_PASSWORD={SENTINEL}")

    monkeypatch.setattr(pf, "_read_asof", broken)
    check, _ = pf.check_database()
    assert check.reason == f"no answer ({error.__name__})"


def test_database_unconfigured_fails(good, monkeypatch) -> None:
    monkeypatch.setattr(pf, "_read_asof", REAL_READ_ASOF)
    monkeypatch.setenv("MYSQL_HOST", "")
    check, dates = pf.check_database()
    assert not check.ok and dates is None
    assert check.reason == "MYSQL_HOST is not set"


def test_remarks_index_missing_folder_fails(good, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", str(tmp_path / "no-such-index"))
    check = by_name()["remarks_index"]
    assert not check.ok and check.reason == "does not load (missing)"


def test_remarks_index_unset_fails(good, monkeypatch) -> None:
    monkeypatch.setenv("IDX_SEMANTIC_INDEX_DIR", "")
    check = by_name()["remarks_index"]
    assert not check.ok and "IDX_SEMANTIC_INDEX_DIR is not set" in check.reason


def test_remarks_index_failing_a_load_check_fails(good, monkeypatch) -> None:
    # Another dimension than the index was built with: the loader's dims check.
    monkeypatch.setenv("IDX_EMBED_DIMS", "32")
    check = by_name()["remarks_index"]
    assert not check.ok and check.reason == "does not load (dims)"


def test_remarks_index_for_another_as_of_date_fails(good, monkeypatch) -> None:
    later = SimpleNamespace(active=date(2026, 9, 25), sold=date(2026, 9, 24))
    monkeypatch.setattr(pf, "_read_asof", lambda: later)
    check = by_name()["remarks_index"]
    assert not check.ok
    assert "2026-09-18" in check.reason and "2026-09-25" in check.reason


def test_docs_index_missing_folder_fails(good, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDX_RAG_INDEX_DIR", str(tmp_path / "no-such-index"))
    check = by_name()["docs_index"]
    assert not check.ok and check.reason == "does not load (missing)"


def test_docs_index_failing_a_load_check_fails(good, monkeypatch) -> None:
    monkeypatch.setenv("IDX_RAG_FLOOR_BM25", "not-a-number")
    check = by_name()["docs_index"]
    assert not check.ok and check.reason == "does not load (floor_setting)"


@pytest.mark.parametrize("name", pf.SETTINGS)
def test_an_unset_setting_fails_by_name(good, monkeypatch, name) -> None:
    monkeypatch.setenv(name, "")
    check = by_name()["settings"]
    assert not check.ok and check.reason == f"not set: {name}"


def test_no_token_fails(good, paid_consent_dir) -> None:
    consent.reader().revoke("paid")
    check = by_name()["paid_token"]
    assert not check.ok and check.reason == "no paid token"


def test_a_token_for_another_command_fails(good) -> None:
    grant_paid("python -m evals.run --suite local --allow-paid", max_calls=5)
    check = by_name()["paid_token"]
    assert not check.ok and check.reason == "the paid token is for another command"


def test_a_token_with_too_few_minutes_fails(good) -> None:
    grant_paid(SERVER, max_calls=20, minutes=30)
    check = by_name(60)["paid_token"]
    assert not check.ok and "60 needed (1 min grace)" in check.reason
    assert by_name(20)["paid_token"].ok


def test_a_token_minted_for_exactly_the_minutes_passes_by_the_grace(good) -> None:
    # Minted 30 seconds ago for 60 minutes: 59.5 left, inside the one-minute grace.
    grant_paid(SERVER, max_calls=20, minutes=60, now=time.time() - 30)
    check = by_name(60)["paid_token"]
    assert check.ok and "59.5 min left, 60 needed (1 min grace)" in check.reason


def test_a_token_two_minutes_short_fails(good) -> None:
    grant_paid(SERVER, max_calls=20, minutes=58)
    check = by_name(60)["paid_token"]
    assert not check.ok and "60 needed (1 min grace)" in check.reason


def test_an_expired_token_fails(good) -> None:
    grant_paid(SERVER, max_calls=5, minutes=15, now=0.0)
    check = by_name()["paid_token"]
    assert not check.ok and check.reason == "the paid token is expired"


@pytest.mark.parametrize("step", ["admit_paid", "consume_paid"])
def test_an_admitted_or_consumed_token_fails(good, step) -> None:
    getattr(consent.reader(), step)(list(consent.SERVER_ARGV))
    check = by_name()["paid_token"]
    assert not check.ok and check.reason.startswith("the paid token is already")


def test_the_token_check_never_changes_the_token(good, paid_consent_dir) -> None:
    before = (paid_consent_dir / "paid").read_bytes()
    listing = sorted(p.name for p in paid_consent_dir.iterdir())
    assert by_name()["paid_token"].ok
    assert (paid_consent_dir / "paid").read_bytes() == before
    assert sorted(p.name for p in paid_consent_dir.iterdir()) == listing


def test_an_unset_log_file_fails(good, monkeypatch) -> None:
    monkeypatch.setenv("IDX_LOG_FILE", "")
    check = by_name()["log_file"]
    assert not check.ok and check.reason == "IDX_LOG_FILE is not set"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_unwritable_log_folder_fails(good) -> None:
    good.chmod(0o500)
    try:
        check = by_name()["log_file"]
    finally:
        good.chmod(0o700)
    assert not check.ok and check.reason == "folder not writable"


def test_a_missing_log_folder_under_a_writable_one_passes(good, monkeypatch) -> None:
    monkeypatch.setenv("IDX_LOG_FILE", str(good / "new" / "idx.log"))
    check = by_name()["log_file"]
    assert check.ok and check.reason == "folder writable"
    assert not (good / "new").exists()


def test_exit_1_on_any_failure(good, monkeypatch, capsys) -> None:
    monkeypatch.setenv("IDX_SENDER_KEY", "")
    assert pf.main([]) == 1
    out = capsys.readouterr().out
    assert "settings      fail  not set: IDX_SENDER_KEY" in out
    assert out.splitlines()[-1] == "preflight: 7 of 8 checks ok"


@pytest.mark.parametrize(
    "argv", [["--minutes", "0"], ["--minutes", "abc"], ["--minutes", "999"], ["-x"]]
)
def test_exit_2_on_a_usage_error(argv, capsys) -> None:
    assert pf.main(argv) == 2
    assert "usage" in capsys.readouterr().err


def test_json_shape(good, capsys) -> None:
    assert pf.main(["--json", "--minutes", "30"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert set(body) == {"ok", "minutes", "checks"}
    assert body["ok"] is True and body["minutes"] == 30
    assert [c["name"] for c in body["checks"]][0] == "package"
    assert all(set(c) == {"name", "ok", "reason"} for c in body["checks"])
    reasons = {c["name"]: c["reason"] for c in body["checks"]}
    assert reasons["package"] == f"idx_agent {idx_agent.__version__}"
    assert reasons["log_file"] == "folder writable"
    assert reasons["remarks_index"].startswith("loads (as-of 2026-09-18 matches")
    assert reasons["docs_index"].startswith("loads (built ")
    assert SENTINEL not in json.dumps(body)


def test_openclaw_flag_prints_both_commands_output(good, monkeypatch, capsys) -> None:
    seen = []

    def fake_run(command):
        seen.append(" ".join(command))
        return 0, f"output of {command[1]} in {Path.home() / 'x'}"

    monkeypatch.setattr(pf, "_run", fake_run)
    assert pf.main(["--openclaw"]) == 0
    out = capsys.readouterr().out
    assert seen == ["openclaw gateway status", "openclaw mcp doctor idx --probe"]
    assert "openclaw      ok" in out and "output of mcp in ~/x" in out
    assert str(Path.home()) not in out


def test_openclaw_failure_is_a_failed_check(good, monkeypatch) -> None:
    monkeypatch.setattr(pf, "_run", lambda command: (1, "not running"))
    checks, outputs = pf.run_checks(60, openclaw=True)
    assert checks[-1].name == "openclaw" and not checks[-1].ok
    assert [o["exit"] for o in outputs] == [1, 1]


def test_home_paths_print_with_a_tilde() -> None:
    assert pf.tilde(f"{Path.home()}/data/x") == "~/data/x"


def test_no_secret_no_model_sdk_no_socket_no_write(
    good, indexes, monkeypatch, capsys
) -> None:
    for name in [m for m in sys.modules if m == "openai" or m.startswith("openai.")]:
        monkeypatch.delitem(sys.modules, name)

    def no_socket(*args, **kwargs):
        raise AssertionError("the preflight opened a socket")

    monkeypatch.setattr(socket.socket, "connect", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    for name in ("IDX_SEMANTIC_INDEX_DIR", "IDX_RAG_INDEX_DIR", "IDX_LOG_FILE"):
        assert SENTINEL in os.environ[name]
    folders = (good.parent, indexes["remarks"].parent)
    before = sorted(str(p) for base in folders for p in base.rglob("*"))
    assert pf.main([]) == 0
    assert pf.main(["--json"]) == 0
    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err
    assert str(Path.home()) not in out.out and "~" not in out.out
    assert "openai" not in sys.modules
    assert not any(m.startswith("openai.") for m in sys.modules)
    assert sorted(str(p) for base in folders for p in base.rglob("*")) == before
