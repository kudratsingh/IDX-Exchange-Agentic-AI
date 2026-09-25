"""WO-013 spike part A: where the fixed prompt prefix comes from, in counts only.

Read-only; no model, no database, no network. Prints names and numbers, never content:
each configured skill's frontmatter description and body (bytes, words, estimated
tokens), every tool schema as the MCP server registers it, the server `instructions`
string, and the size of each regular file in the one workspace folder the human names.
Token figures are estimates at four characters per token; only the known total (the
37,000-token prefix read from the `openclaw.model.call` spans) is a measured count.

The workspace is listed with `os.scandir` and `os.lstat` only: no file in it is opened.
Secrets (`.env`, keys), credential and auth folders, session stores, logs, hidden
entries, and anything whose real path is outside the named folder (a symlink, say) are
skipped by name, and the skip is printed with its reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as the other spike scripts do, and the
# eval runner (its skill list and skill reader) from this checkout's root.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config" / "openclaw.idx.json5"
SKILLS_DIR = ROOT / "skills"
DEFAULT_WORKSPACE = Path("~/.openclaw/workspace-idx")
# Measured from the `openclaw.model.call` spans of one session (docs/DECISIONS.md,
# "Gateway chat model"); everything else here is an estimate.
KNOWN_TOTAL_TOKENS = 37_000
# Estimates, not tokenizer counts: about 4 characters per token for English prose.
CHARS_PER_TOKEN = 4
# A typical session loads this many skill bodies (decision rule, WO-013).
TYPICAL_SKILLS_PER_SESSION = 4
MAX_DEPTH = 4

# Never listed inside: secrets, credentials, auth, sessions, logs, state.
SKIP_DIR_NAMES = frozenset(
    {
        "credentials",
        "credential",
        "auth",
        "auth-profiles",
        "secrets",
        "sessions",
        "session",
        "logs",
        "log",
        "state",
        "tmp",
        "cache",
    }
)
SKIP_NAME_PARTS = (
    "credential",
    "creds",
    "auth",
    "secret",
    "session",
    "token",
    "password",
    "key",
)
SKIP_SUFFIXES = (".log", ".jsonl", ".key", ".pem", ".p12", ".sqlite", ".db", ".env")


def estimate_tokens(size: int) -> int:
    """Estimated tokens for `size` bytes of text (4 chars per token, rounded up)."""
    return -(-size // CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Count:
    """Bytes, words, and estimated tokens of one piece of text."""

    label: str
    size: int
    words: int

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.size)


def count(label: str, text: str) -> Count:
    """Count one text; the text itself is never kept or printed."""
    return Count(label, len(text.encode("utf-8")), len(text.split()))


def _runner() -> Any:
    """evals/run.py: the skill list and skill reader the routing eval uses."""
    from evals import run

    return run


def configured_skills(config: Path = CONFIG) -> list[str]:
    """The `idx` agent's skill list, in config order."""
    return _runner().configured_skills(config)


@dataclass(frozen=True)
class SkillCounts:
    name: str
    description: Count
    list_entry: Count
    body: Count


def skill_counts(
    names: Sequence[str], skills_dir: Path = SKILLS_DIR
) -> list[SkillCounts]:
    """Per skill: its description, list entry, and body (evals.run.skill_parts). The
    list entry is the gateway's assumed listing: name, description, and the SKILL.md
    path (an estimate of OpenClaw's format; the path is counted, never printed)."""
    out = []
    for name in names:
        path = skills_dir / name / "SKILL.md"
        description, body = _runner().skill_parts(name, skills_dir)
        entry = f"{name}\n{description}\n{path}"
        out.append(
            SkillCounts(
                name,
                count("description", description),
                count("list entry", entry),
                count("body", body),
            )
        )
    return out


def tool_counts() -> tuple[list[tuple[str, Count, Count]], Count]:
    """Per registered tool, as compact JSON: the function form sent to a model (name
    with the gateway's `idx__` prefix, description, input schema) and the full MCP
    record (adding the output schema); plus the server `instructions` count."""
    from idx_agent.mcp_server import server as mcp_server

    tools = asyncio.run(mcp_server.server.list_tools())
    rows = []
    for tool in tools:
        function = {
            "type": "function",
            "function": {
                "name": f"idx__{tool.name}",
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        }
        record = tool.model_dump(by_alias=True, exclude_none=True)
        rows.append(
            (
                tool.name,
                count("function form", json.dumps(function, separators=(",", ":"))),
                count("MCP record", json.dumps(record, separators=(",", ":"))),
            )
        )
    instructions = count("instructions", mcp_server.server.instructions or "")
    return rows, instructions


def skip_reason(name: str, is_dir: bool) -> str | None:
    """Why an entry is never listed, or None when it may be sized."""
    lower = name.lower()
    if lower.startswith("."):
        return "hidden or secret"
    if is_dir and lower in SKIP_DIR_NAMES:
        return "credentials, auth, sessions, logs, or state"
    if any(part in lower for part in SKIP_NAME_PARTS):
        return "credentials, auth, keys, sessions, or secrets"
    if not is_dir and lower.endswith(SKIP_SUFFIXES):
        return "log, session, key, or database file"
    return None


def _inside(path: Path, folder: Path) -> bool:
    """True when `path`'s real location is `folder` or below it."""
    try:
        Path(os.path.realpath(path)).relative_to(folder)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class WorkspaceEntry:
    """One listed or skipped workspace entry: a relative name and its size or reason."""

    name: str
    size: int | None
    reason: str | None


def refuse_folder(folder: Path) -> str | None:
    """Why a named folder is refused as a whole, or None when it may be listed."""
    home = Path.home().resolve()
    real = Path(os.path.realpath(folder))
    if folder.is_symlink():
        return "the named folder is a symlink"
    if real == home or real in home.parents or real == home / ".openclaw":
        return (
            "the named folder is too broad (the home folder, a folder above it, or"
            " ~/.openclaw itself)"
        )
    if skip_reason(real.name, is_dir=True):
        return "the named folder is itself a secret, session, or log folder"
    return None


def audit_workspace(folder: Path) -> list[WorkspaceEntry]:
    """Name and size of each regular file under `folder`, by lstat only; nothing is
    opened. Skipped entries carry their reason; a symlink or an entry whose real path
    leaves `folder` is refused; folders deeper than MAX_DEPTH are not entered."""
    root = Path(os.path.realpath(folder))
    entries: list[WorkspaceEntry] = []

    def walk(current: Path, prefix: str, depth: int) -> None:
        with os.scandir(current) as it:
            items = sorted(it, key=lambda e: e.name)
        for item in items:
            rel = f"{prefix}{item.name}"
            info = os.lstat(item.path)
            is_link = stat.S_ISLNK(info.st_mode)
            is_dir = stat.S_ISDIR(info.st_mode)
            if is_link or not _inside(Path(item.path), root):
                entries.append(WorkspaceEntry(rel, None, "outside the named folder"))
                continue
            reason = skip_reason(item.name, is_dir)
            if reason:
                entries.append(
                    WorkspaceEntry(rel + ("/" if is_dir else ""), None, reason)
                )
                continue
            if is_dir:
                if depth >= MAX_DEPTH:
                    entries.append(WorkspaceEntry(rel + "/", None, "too deep"))
                else:
                    walk(Path(item.path), rel + "/", depth + 1)
                continue
            if stat.S_ISREG(info.st_mode):
                entries.append(WorkspaceEntry(rel, info.st_size, None))
            else:
                entries.append(WorkspaceEntry(rel, None, "not a regular file"))

    walk(root, "", 1)
    return entries


def _row(label: str, c: Count) -> str:
    return f"  {label:<34} {c.size:>8,} B {c.words:>7,} w {c.tokens:>7,} tok~"


def verdict(
    ours: int, bodies_typical: int, workspace: int, total: int = KNOWN_TOTAL_TOKENS
) -> list[str]:
    """The WO-013 decision rule applied to the estimated split of `total`."""
    rest = total - ours
    openclaw_own = rest - workspace
    third = total / 3
    lines = [
        f"known total (measured, spans)       {total:>8,} tok",
        f"our part (list + tools + instr.)    {ours:>8,} tok~  {ours / total:.1%}",
        f"rest, by subtraction                {rest:>8,} tok~  {rest / total:.1%}",
        f"  of which workspace files          {workspace:>8,} tok~",
        f"  of which OpenClaw's own prompt    {openclaw_own:>8,} tok~  "
        f"{openclaw_own / total:.1%}",
        f"bodies, typical {TYPICAL_SKILLS_PER_SESSION}-skill session     "
        f"{bodies_typical:>8,} tok~  {bodies_typical / total:.1%} of the prefix",
        "",
        "decision rule:",
    ]
    lines.append(
        "  our part > 1/3 of the prefix: "
        + ("yes, trimming descriptions is worth a change" if ours > third else "no")
    )
    lines.append(
        "  bodies per session > 1/3 of the prefix: "
        + (
            "yes, shortening bodies is worth a change"
            if bodies_typical > third
            else "no"
        )
    )
    lines.append(
        "  OpenClaw's own part > 2/3: "
        + (
            "yes, trimming ours cannot move the cost much; the levers are OpenClaw's"
            if openclaw_own > 2 * third
            else "no"
        )
    )
    lines.append(
        "  bodies inside the fixed prefix: not measurable from counts; ADR-0003 says a "
        "body is read on pick; the WhatsApp run's first-turn span settles it"
    )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workspace",
        default=str(DEFAULT_WORKSPACE),
        help="the one workspace folder to size (default: the idx agent's)",
    )
    parser.add_argument("--known-total", type=int, default=KNOWN_TOTAL_TOKENS)
    args = parser.parse_args(argv)

    names = configured_skills()
    skills = skill_counts(names)
    tools, instructions = tool_counts()

    print("Prefix audit (counts only; tok~ = estimate at 4 chars/token)")
    print("\nSkills (config order):")
    for s in skills:
        print(_row(f"{s.name} description", s.description))
        print(_row(f"{s.name} list entry", s.list_entry))
        print(_row(f"{s.name} body", s.body))
    list_total = sum(s.list_entry.tokens for s in skills)
    body_sizes = sorted((s.body.tokens for s in skills), reverse=True)
    bodies_typical = sum(body_sizes[:TYPICAL_SKILLS_PER_SESSION])
    print(f"  skill list entries, all             {list_total:>8,} tok~")
    print(f"  bodies, all                         {sum(body_sizes):>8,} tok~")
    print(
        f"  bodies, {TYPICAL_SKILLS_PER_SESSION} largest                  "
        f"{bodies_typical:>8,} tok~"
    )

    print("\nTools (as registered; function form = what a model is sent):")
    for name, function, record in tools:
        print(_row(f"{name} function form", function))
        print(_row(f"{name} MCP record", record))
    tools_total = sum(function.tokens for _, function, _ in tools)
    print(f"  function forms, all                 {tools_total:>8,} tok~")
    print("\nServer instructions:")
    print(_row("instructions", instructions))

    folder = Path(os.path.expanduser(args.workspace))
    workspace_tokens = 0
    print(f"\nWorkspace folder {args.workspace}:")
    if not folder.is_dir():
        print("  does not exist; skipped")
    elif reason := refuse_folder(folder):
        print(f"  refused: {reason}")
    else:
        entries = audit_workspace(folder)
        for entry in entries:
            if entry.size is None:
                print(f"  {entry.name:<40} skipped: {entry.reason}")
            else:
                tokens = estimate_tokens(entry.size)
                workspace_tokens += tokens
                print(f"  {entry.name:<40} {entry.size:>8,} B {tokens:>7,} tok~")
        if not entries:
            print("  empty")
        print(f"  regular files, all                  {workspace_tokens:>8,} tok~")

    ours = list_total + tools_total + instructions.tokens
    print("\nSplit of the fixed prefix:")
    for line in verdict(ours, bodies_typical, workspace_tokens, args.known_total):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
