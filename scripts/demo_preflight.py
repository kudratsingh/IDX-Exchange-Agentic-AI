"""WO-014 demo preflight: the runbook's checks, run before a live WhatsApp demo.

Read-only: no model call, no model SDK, no write; settings are checked for presence
only. One line per check; exit 0 when all pass, 1 on a failure, 2 on a usage error.
Run: python scripts/demo_preflight.py [--minutes N] [--json] [--openclaw]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as the other scripts do.
sys.path.insert(0, str(ROOT / "src"))

EXPECTED_TOOLS = frozenset(
    {
        "health",
        "search_listings",
        "get_market_stats",
        "find_similar_listings",
        "recommend",
        "rag_answer",
    }
)
# Presence only: a value is never printed.
SETTINGS = (
    "IDX_SENDER_KEY",
    "IDX_SEMANTIC_INDEX_DIR",
    "IDX_RAG_INDEX_DIR",
    "IDX_OTLP_ENDPOINT",
)
DEFAULT_MINUTES = 60
MAX_MINUTES = 240  # the longest window a consent token can have
# A token minted for N minutes has a little under N left by the time it is checked.
GRACE_MINUTES = 1
# Read-only OpenClaw commands; only the human runs them, with --openclaw.
OPENCLAW_COMMANDS = (
    ("openclaw", "gateway", "status"),
    ("openclaw", "mcp", "doctor", "idx", "--probe"),
)


@dataclass(frozen=True)
class Check:
    """One check's outcome: its name, whether it passed, and a short reason."""

    name: str
    ok: bool
    reason: str


def tilde(text: str) -> str:
    """`text` with the home folder written as `~` (the OpenClaw output only)."""
    home = str(Path.home())
    return text.replace(home, "~") if home and home != "/" else text


class _Unconfigured(Exception):
    """The database has no host setting; the check prints fixed text only."""


def _failure(exc: BaseException) -> str:
    """An exception as its class name only (a message may carry a host or path)."""
    return type(exc).__name__


# ----- seams (tests replace these) --------------------------------------------------
def _tool_names() -> list[str]:
    """The tool server's registered tool names, in process (no subprocess)."""
    from idx_agent.mcp_server import server

    return sorted(tool.name for tool in asyncio.run(server.server.list_tools()))


def _read_asof() -> Any:
    """Both as-of dates as the reader user, through the existing db layer."""
    from idx_agent.db import asof, pool

    if not pool.database_configured():
        raise _Unconfigured
    conn = pool.connect()
    try:
        return asof.read_asof_dates(conn)
    finally:
        conn.close()


def _index_dir(setting: str) -> Path | None:
    """An index-folder setting as the tool server resolves it; None when unset."""
    from idx_agent.mcp_server.server import configured_dir

    return configured_dir(setting)


def _load_remarks(path: Path) -> Any:
    """The WO-010 remarks index through its own loader; nothing is embedded."""
    from idx_agent.semantic.embedder import embed_settings
    from idx_agent.semantic.index import load_index

    model, dims = embed_settings()
    return load_index(path, model, dims)


def _load_docs(path: Path) -> Any:
    """The WO-012 document index through its own loader; nothing is embedded."""
    from idx_agent.rag.store import load_doc_index

    return load_doc_index(path)


def _setting(name: str) -> str | None:
    """A setting as the code reads it: the environment, then the repo `.env`."""
    from idx_agent.db.pool import env_setting

    return env_setting(name)


def _token_reader() -> Any:
    """The consent-token reader, loaded by path as safety/consent.py loads it."""
    from idx_agent.safety import consent

    return consent.reader()


def _run(command: Sequence[str]) -> tuple[int, str]:
    """Run one read-only command; (exit code, combined output). Human use only."""
    try:
        done = subprocess.run(
            list(command), capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, _failure(exc)
    return done.returncode, (done.stdout + done.stderr).rstrip()


# ----- checks, in order ---------------------------------------------------------------
def check_package() -> Check:
    """The idx_agent package imports; its version (no path)."""
    try:
        import idx_agent
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return Check("package", False, f"idx_agent does not import ({_failure(exc)})")
    return Check("package", True, f"idx_agent {idx_agent.__version__}")


def check_tools() -> Check:
    """The tool server registers exactly the six tools."""
    try:
        names = set(_tool_names())
    except Exception as exc:  # noqa: BLE001
        return Check("tools", False, f"tool registry unreadable ({_failure(exc)})")
    missing, extra = sorted(EXPECTED_TOOLS - names), sorted(names - EXPECTED_TOOLS)
    if missing or extra:
        parts = [f"missing {', '.join(missing)}"] if missing else []
        parts += [f"unexpected {', '.join(extra)}"] if extra else []
        return Check("tools", False, "; ".join(parts))
    return Check("tools", True, f"exactly the {len(EXPECTED_TOOLS)} tools")


def check_database() -> tuple[Check, Any]:
    """The reader user answers with both as-of dates; (check, dates or None)."""
    try:
        dates = _read_asof()
    except _Unconfigured:
        return Check("database", False, "MYSQL_HOST is not set"), None
    except Exception as exc:  # noqa: BLE001
        return Check("database", False, f"no answer ({_failure(exc)})"), None
    reason = f"as-of active {dates.active}, sold {dates.sold}"
    return Check("database", True, reason), dates


def check_remarks_index(dates: Any) -> Check:
    """The remarks index loads and was built for the database's active as-of date."""
    name = "remarks_index"
    try:
        path = _index_dir("IDX_SEMANTIC_INDEX_DIR")
        if path is None:
            return Check(name, False, "IDX_SEMANTIC_INDEX_DIR is not set")
        index = _load_remarks(path)
    except ImportError:
        return Check(name, False, "the semantic extra is not installed")
    except Exception as exc:  # noqa: BLE001
        cause = getattr(exc, "cause", None) or _failure(exc)
        return Check(name, False, f"does not load ({cause})")
    built, rows = index.meta.active_as_of, index.meta.rows
    if dates is None:
        return Check(
            name, True, f"loads (as-of {built}, {rows} rows); no database date"
        )
    if built != dates.active:
        reason = f"as-of {built} but the database's active as-of is {dates.active}"
        return Check(name, False, reason)
    return Check(name, True, f"loads (as-of {built} matches the database, {rows} rows)")


def check_docs_index(dates: Any) -> Check:
    """The document index loads; its meta holds a build date, not a data as-of."""
    name = "docs_index"
    try:
        path = _index_dir("IDX_RAG_INDEX_DIR")
        if path is None:
            return Check(name, False, "IDX_RAG_INDEX_DIR is not set")
        index = _load_docs(path)
    except ImportError:
        return Check(name, False, "the rag extra is not installed")
    except Exception as exc:  # noqa: BLE001
        cause = getattr(exc, "cause", None) or _failure(exc)
        return Check(name, False, f"does not load ({cause})")
    meta = index.meta
    reason = (
        f"loads (built {meta.built_at}, {meta.rows} chunks, {meta.route}); "
        "no data as-of in its meta to compare"
    )
    return Check(name, True, reason)


def check_settings() -> Check:
    """The sender key, index folders, and tracing endpoint are set (presence only)."""
    try:
        unset = [n for n in SETTINGS if not (_setting(n) or "").strip()]
    except Exception as exc:  # noqa: BLE001
        return Check("settings", False, f"settings unreadable ({_failure(exc)})")
    if unset:
        return Check("settings", False, f"not set: {', '.join(unset)}")
    return Check("settings", True, f"all {len(SETTINGS)} set (values not shown)")


def check_paid_token(minutes: int) -> Check:
    """An unspent v2 `paid` token for the tool server, at least `minutes` less the
    one-minute grace left."""
    name = "paid_token"
    try:
        module = _token_reader()
        info = module.paid_token_status()
        from idx_agent.safety.consent import SERVER_ARGV

        matches = bool(info.get("command")) and module.command_matches(
            str(info["command"]), list(SERVER_ARGV)
        )
    except Exception as exc:  # noqa: BLE001
        return Check(name, False, f"token reader unusable ({_failure(exc)})")
    state = info.get("state")
    if state == "missing":
        return Check(name, False, "no paid token")
    if state in ("expired", "malformed"):
        return Check(name, False, f"the paid token is {state}")
    if not matches:
        return Check(name, False, "the paid token is for another command")
    if state in ("admitted", "consumed"):
        return Check(name, False, f"the paid token is already {state}")
    left = float(info.get("remaining_minutes") or 0.0)
    window = f"{left:.1f} min left, {minutes} needed ({GRACE_MINUTES} min grace)"
    if state != "valid" or left < minutes - GRACE_MINUTES:
        return Check(name, False, window)
    return Check(name, True, f"unspent, for the tool server, {window}")


def _writable_folder(path: Path) -> Path | None:
    """The folder that would receive the log file (the nearest existing one), if
    writable; checked with os.access, nothing created."""
    folder = path.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    ok = folder.is_dir() and os.access(folder, os.W_OK | os.X_OK)
    if path.exists():
        ok = ok and os.access(path, os.W_OK)
    return folder if ok else None


def check_log_file() -> Check:
    """IDX_LOG_FILE is set and its folder is writable; nothing is written."""
    try:
        target = (_setting("IDX_LOG_FILE") or "").strip()
    except Exception as exc:  # noqa: BLE001
        return Check("log_file", False, f"setting unreadable ({_failure(exc)})")
    if not target:
        return Check("log_file", False, "IDX_LOG_FILE is not set")
    path = Path(target)  # relative resolves against the working directory, as logging
    path = path if path.is_absolute() else Path.cwd() / path
    if _writable_folder(path) is None:
        return Check("log_file", False, "folder not writable")
    return Check("log_file", True, "folder writable")


def check_openclaw() -> tuple[Check, list[dict[str, Any]]]:
    """Run the two read-only OpenClaw commands (human only); (check, outputs)."""
    outputs = []
    for command in OPENCLAW_COMMANDS:
        code, text = _run(command)
        outputs.append({"command": " ".join(command), "exit": code, "output": text})
    failed = [o["command"] for o in outputs if o["exit"] != 0]
    if failed:
        return Check("openclaw", False, f"non-zero exit: {'; '.join(failed)}"), outputs
    return Check("openclaw", True, "both commands exited 0 (output below)"), outputs


def run_checks(
    minutes: int, openclaw: bool = False
) -> tuple[list[Check], list[dict[str, Any]]]:
    """Every check in the WO's order; (checks, OpenClaw outputs or [])."""
    checks = [check_package(), check_tools()]
    database, dates = check_database()
    checks += [database, check_remarks_index(dates), check_docs_index(dates)]
    checks += [check_settings(), check_paid_token(minutes), check_log_file()]
    outputs: list[dict[str, Any]] = []
    if openclaw:
        check, outputs = check_openclaw()
        checks.append(check)
    return checks, outputs


def _minutes(value: str) -> int:
    """--minutes: a whole number from 1 to MAX_MINUTES."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if not 1 <= number <= MAX_MINUTES:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_MINUTES}")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the flags, run the checks, print them; return the exit code."""
    parser = argparse.ArgumentParser(description="WO-014 demo preflight (read-only).")
    parser.add_argument(
        "--minutes",
        type=_minutes,
        default=DEFAULT_MINUTES,
        help="minutes the paid token must still have (default 60; 1 min grace)",
    )
    parser.add_argument("--json", action="store_true", help="one JSON object")
    parser.add_argument(
        "--openclaw", action="store_true", help="human only: two read-only commands"
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 2
    checks, outputs = run_checks(args.minutes, args.openclaw)
    all_ok = all(c.ok for c in checks)
    if args.json:
        body: dict[str, Any] = {
            "ok": all_ok,
            "minutes": args.minutes,
            "checks": [asdict(c) for c in checks],
        }
        if args.openclaw:
            body["openclaw_output"] = [
                {**o, "output": tilde(o["output"])} for o in outputs
            ]
        print(json.dumps(body, indent=2))
    else:
        for c in checks:
            print(f"{c.name:<13} {'ok' if c.ok else 'fail':<4}  {c.reason}")
        for out in outputs:
            print(tilde(f"\n$ {out['command']}  (exit {out['exit']})\n{out['output']}"))
        failed = sum(not c.ok for c in checks)
        print(f"preflight: {len(checks) - failed} of {len(checks)} checks ok")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True  # writes nothing, not even a bytecode cache
    sys.exit(main())
