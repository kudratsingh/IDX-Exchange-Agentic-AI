"""Claude Code PreToolUse guard for this repo (docs/AGENT_RULES.md).

Reads one tool call as JSON on stdin (``tool_name``, ``tool_input``) and exits 2 to
block it when it would delete or discard data, spend money on a model or API, or edit
the gates that enforce the rules, unless a human has granted a consent token of the
matching kind (``scripts/guards/consent.sh``). A few actions are refused outright and
no token unlocks them: creating a consent token, skipping the commit hooks, and adding
the PR label that approves deletions in CI.

Wired in ``.claude/settings.json`` for Bash, Write, Edit and NotebookEdit. Fails closed:
any error inside the guard blocks the call. Standard library only.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import sys
from typing import NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import consent_token as ct  # noqa: E402


class Finding(NamedTuple):
    kind: str  # delete | paid | gates | consent (consent is never unlocked)
    reason: str


# Paths whose deletion or overwrite is a data loss, relative to the project root.
DATA_ROOTS = ("data/", "context/", "coordination/")
EVIDENCE = (
    "docs/EVIDENCE_LOG.md",
    "evals/cases/",
    "evals/runs/",
    "evals/reports/",
    "experiments/",
)
# The enforcement itself: editing needs a `gates` token.
GATE_RE = re.compile(
    r"(^|/)(scripts/gates/|scripts/guards/|\.github/workflows/"
    r"|\.pre-commit-config\.yaml$|\.gitignore$)"
)
SETTINGS_RE = re.compile(r"(^|/)\.claude/settings(\.local)?\.json$")
# The same paths, unanchored, for free text such as a whole shell command.
GATE_ANY_RE = re.compile(
    r"scripts/(gates|guards)/|\.github/workflows/|\.pre-commit-config\.yaml"
    r"|\.gitignore\b|\.claude/settings(\.local)?\.json"
)
# The consent mechanism: the agent never touches it.
CONSENT_RE = re.compile(r"\.local/consent\b|consent\.sh\b|consent_token\.py\b")
# The agent's own memory and Claude Code config live under a .claude/ directory.
CLAUDE_HOME_RE = re.compile(r"(^|/)\.claude/")

# rm targets that are always fine: scratch space and rebuildable caches.
SCRATCH_RE = re.compile(r"^(/private)?/tmp(/|$)|^\$\{?TMPDIR|(^|/)scratchpad(/|$)")
CACHE_RE = re.compile(
    r"(^|/)(\.venv|venv|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache"
    r"|build|dist|node_modules|htmlcov)(/|$)|\.egg-info/?$|\.pyc$"
)

SQL_RE = re.compile(
    r"\b(drop\s+(table|database|schema|index|view)\b|truncate(\s+table)?\s+\w"
    r"|delete\s+from\s+\w|alter\s+table\b[^;]*\bdrop\b)",
    re.I,
)
PAID_HOST_RE = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com"
    r"|openrouter\.ai|api\.mistral\.ai|api\.cohere\.(ai|com)|api\.groq\.com"
    r"|api\.together\.xyz|api\.voyageai\.com",
    re.I,
)
PAID_SDK_RE = re.compile(
    r"\b(from|import)\s+(openai|anthropic|google\.generativeai|cohere|mistralai"
    r"|voyageai)\b|\b(Async)?(OpenAI|Anthropic)\("
    r"|\b(chat\.completions|messages|embeddings|responses)\.create\("
)
PAID_SUITE_RE = re.compile(
    r"--suite[= ]+local\b|\bpytest\b[^|;&]*\s-m\s+['\"]?(paid|live)\b"
    r"|\bmake\s+\S*(live|paid)\b"
)
OPENCLAW_FREE = {
    "--help",
    "-h",
    "help",
    "--version",
    "-V",
    "version",
    "config",
    "doctor",
    "install",
    "skills",
    "skill",
    "list",
    "status",
    "info",
    "init",
    "setup",
    "logs",
    "log",
    "update",
    "upgrade",
}
NEVER_RES = (
    (
        re.compile(r"\bgit\s+commit\b[^|;&]*(--no-verify|\s-n\b)"),
        "git commit that skips the hooks",
    ),
    (re.compile(r"\bSKIP=\S*\s+git\s+commit\b"), "SKIP= around git commit"),
    (
        re.compile(r"(add-label|labels?\b)[^|;&]*deletion-approved"),
        "adding the deletion-approved label (a human does that)",
    ),
    (re.compile(r"\bpre-commit\s+uninstall\b"), "uninstalling the commit hooks"),
    (re.compile(r"\bgit\s+config\b[^|;&]*core\.hooksPath"), "moving the hooks path"),
)
WRAPPERS = {
    "sudo",
    "env",
    "time",
    "nohup",
    "exec",
    "command",
    "builtin",
    "caffeinate",
    "nice",
    "ionice",
    "timeout",
}
WRAPPER_FLAGS_WITH_VALUE = {"-t", "-n", "-w", "-u"}
WRITER_BASES = {
    "cp",
    "mv",
    "tee",
    "touch",
    "chmod",
    "install",
    "ln",
    "patch",
    "rm",
    "truncate",
    "shred",
    "rsync",
}
SCRIPT_BASES = {"python", "python3", "perl", "ruby", "node", "bash", "sh", "zsh"}
DB_CLIENTS = {"mysql", "mysqlsh", "mariadb", "psql", "sqlite3", "duckdb"}
READ_ONLY_BASES = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "rg",
    "wc",
    "diff",
    "ls",
    "stat",
    "file",
    "awk",
    "git",
    "find",
    "tree",
    "du",
    "shasum",
    "sha256sum",
    "md5",
    "jq",
    "bat",
    "echo",
    "printf",
}
WRITE_HINT_RE = re.compile(r"write_text|write_bytes|\.write\(|open\([^)]*['\"][wa]")
GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
SEGMENT_RE = re.compile(r"\s*(?:\|\||&&|;|\||\n)\s*")
REDIRECT_RE = re.compile(r"(?<![<>])(>>|>)\s*(\S+)")
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)


def _norm(path: str) -> str:
    return os.path.normpath(path.strip("\"'"))


def _matches_root(path: str, roots: tuple[str, ...]) -> bool:
    """True when `path` (relative or absolute) is one of `roots` or lies under it."""
    p = _norm(path)
    for root in roots:
        r = root.rstrip("/")
        if p == r or p.startswith(r + "/") or ("/" + r + "/") in ("/" + p + "/"):
            return True
    return False


def _argv(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _strip_prefix(argv: list[str]) -> tuple[list[str], bool]:
    """Drop leading env assignments and wrappers; say whether an API key was passed."""
    key_passed = False
    while argv:
        head = argv[0]
        if ASSIGNMENT_RE.fullmatch(head):
            if head.split("=", 1)[0].endswith("_API_KEY") and len(argv) > 1:
                key_passed = True
            argv = argv[1:]
            continue
        if head not in WRAPPERS:
            break
        argv = argv[1:]
        if head == "timeout" and argv and not argv[0].startswith("-"):
            argv = argv[1:]
        while argv and argv[0].startswith("-"):
            flag = argv[0]
            argv = argv[1:]
            if flag in WRAPPER_FLAGS_WITH_VALUE and argv:
                argv = argv[1:]
    return argv, key_passed


def _git_subcommand(argv: list[str]) -> tuple[str, list[str]]:
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in GIT_GLOBAL_WITH_ARG:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        return arg, argv[i + 1 :]
    return "", []


def _mentions_gate(text: str) -> bool:
    return bool(GATE_ANY_RE.search(text))


def _classify_git(rest_all: list[str]) -> list[Finding]:
    sub, rest = _git_subcommand(rest_all)
    out: list[Finding] = []
    if sub == "clean" and not any(a in ("-n", "--dry-run") for a in rest):
        out.append(Finding("delete", "git clean removes untracked files"))
    elif sub == "reset" and any(a in ("--hard", "--merge") for a in rest):
        out.append(Finding("delete", "git reset --hard discards work"))
    elif sub == "checkout" and ("--" in rest or (rest and rest[-1] == ".")):
        out.append(Finding("delete", "git checkout of paths discards changes"))
    elif sub == "restore":
        staged_only = any(a in ("--staged", "-S") for a in rest) and not any(
            a in ("--worktree", "-W") for a in rest
        )
        if not staged_only:
            out.append(Finding("delete", "git restore discards working changes"))
    elif sub == "stash":
        out.append(Finding("delete", "git stash is banned in shared checkouts"))
    elif sub == "push" and any(
        a in ("-f", "--force") or a.startswith("--force") for a in rest
    ):
        out.append(Finding("delete", "force push rewrites a shared branch"))
    elif sub == "branch" and "-D" in rest:
        out.append(Finding("delete", "git branch -D drops unmerged work"))
    elif (
        sub == "worktree"
        and rest[:1] == ["remove"]
        and ("--force" in rest or "-f" in rest)
    ):
        out.append(Finding("delete", "forced worktree removal drops changes"))
    elif sub == "rm":
        out.append(Finding("delete", "git rm stages a deletion"))
    elif sub in ("filter-branch", "filter-repo", "replace"):
        out.append(Finding("delete", f"git {sub} rewrites history"))
    elif sub == "reflog" and "expire" in rest:
        out.append(Finding("delete", "reflog expire drops recovery points"))
    elif sub == "gc" and any(a.startswith("--prune") for a in rest):
        out.append(Finding("delete", "git gc --prune drops recovery points"))
    elif sub == "update-ref" and "-d" in rest:
        out.append(Finding("delete", "deleting a ref"))
    elif sub == "tag" and any(a in ("-d", "--delete") for a in rest):
        out.append(Finding("delete", "deleting a tag"))
    return out


def _classify_segment(segment: str, command: str) -> list[Finding]:
    argv, key_passed = _strip_prefix(_argv(segment))
    if not argv:
        return []
    base = os.path.basename(argv[0])
    rest = argv[1:]
    out: list[Finding] = []

    if key_passed:
        out.append(Finding("paid", "an API key is passed to a command"))
    if base == "export" and any(re.match(r"[A-Z0-9_]*_API_KEY=", a) for a in rest):
        out.append(Finding("paid", "exports an API key for later calls"))

    if CONSENT_RE.search(segment) and base not in READ_ONLY_BASES:
        out.append(Finding("consent", "touches the consent mechanism"))

    for op, target in REDIRECT_RE.findall(segment):
        t = target.strip("\"'")
        if CONSENT_RE.search(t):
            out.append(Finding("consent", f"writes {t}"))
        elif _mentions_gate(t):
            out.append(Finding("gates", f"writes {t}"))
        elif op == ">" and (_matches_root(t, EVIDENCE) or _matches_root(t, DATA_ROOTS)):
            out.append(Finding("delete", f"truncates {t}"))

    writer = base in WRITER_BASES or (
        base == "sed" and any(a.startswith("-i") for a in rest)
    )
    if writer and any(_mentions_gate(a) for a in rest):
        out.append(Finding("gates", f"{base} edits the enforcement"))
    if (
        base in SCRIPT_BASES
        and _mentions_gate(command)
        and WRITE_HINT_RE.search(command)
    ):
        out.append(Finding("gates", "a script writes to the enforcement"))

    if base == "rm":
        targets = [a for a in rest if not a.startswith("-")]
        bad = [
            t
            for t in targets
            if not (SCRATCH_RE.search(_norm(t)) or CACHE_RE.search(_norm(t)))
        ]
        if not targets:
            out.append(Finding("delete", "rm with no literal target"))
        elif bad:
            out.append(Finding("delete", "rm of " + ", ".join(bad[:3])))
    elif base == "find" and ("-delete" in rest or "rm" in rest):
        root = rest[0] if rest and not rest[0].startswith("-") else "."
        if not (SCRATCH_RE.search(_norm(root)) or CACHE_RE.search(_norm(root))):
            out.append(Finding("delete", f"find deletes under {root}"))
    elif base == "xargs" and "rm" in rest:
        out.append(Finding("delete", "xargs rm"))
    elif base in ("shred", "truncate"):
        out.append(Finding("delete", f"{base} destroys file contents"))
    elif base == "mv":
        sources = [a for a in rest if not a.startswith("-")][:-1]
        if any(
            _matches_root(s, DATA_ROOTS)
            or _matches_root(s, EVIDENCE)
            or CLAUDE_HOME_RE.search(_norm(s))
            for s in sources
        ):
            out.append(Finding("delete", "moves data or evidence out of place"))
    elif base == "git":
        out.extend(_classify_git(argv))
    elif base == "docker":
        joined = " ".join(rest)
        if (
            "compose" in rest
            and "down" in rest
            and ("-v" in rest or "--volumes" in rest)
        ) or re.search(
            r"\bvolume\s+(rm|prune)\b|\bsystem\s+prune\b|\brm\b.*\s-v\b", joined
        ):
            out.append(Finding("delete", "docker command deletes volumes"))
    elif base in DB_CLIENTS:
        if SQL_RE.search(segment) or "<" in segment or " source " in segment:
            out.append(Finding("delete", f"{base} runs destructive or unread SQL"))
    elif base in SCRIPT_BASES or base == "make":
        if SQL_RE.search(segment):
            out.append(Finding("delete", "destructive SQL in a script"))
    elif base == "openclaw":
        if not rest or rest[0] not in OPENCLAW_FREE:
            out.append(Finding("paid", "openclaw run may call a paid model"))
    return out


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[Finding] = set()
    out: list[Finding] = []
    for f in findings:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def classify_bash(command: str) -> list[Finding]:
    findings: list[Finding] = []
    for regex, why in NEVER_RES:
        if regex.search(command):
            findings.append(Finding("consent", why))
    if PAID_HOST_RE.search(command):
        findings.append(Finding("paid", "reaches a paid API host"))
    if PAID_SDK_RE.search(command):
        findings.append(Finding("paid", "uses a model SDK"))
    if PAID_SUITE_RE.search(command):
        findings.append(Finding("paid", "runs a paid suite"))
    for segment in SEGMENT_RE.split(command):
        segment = segment.strip()
        if segment:
            findings.extend(_classify_segment(segment, command))
    return _dedupe(findings)


def classify_file(tool_name: str, path: str) -> list[Finding]:
    if not path:
        return []
    root = ct.project_root()
    p = pathlib.Path(path)
    try:
        rel = str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(p)
    out: list[Finding] = []
    if CONSENT_RE.search(rel) or CONSENT_RE.search(path):
        out.append(Finding("consent", f"writes the consent mechanism: {rel}"))
    if SETTINGS_RE.search(rel) or SETTINGS_RE.search(path):
        out.append(Finding("gates", f"edits Claude Code settings: {rel}"))
    if GATE_RE.search(rel):
        out.append(Finding("gates", f"edits the enforcement: {rel}"))
    overwrite = tool_name == "Write" and p.exists()
    if overwrite and (_matches_root(rel, EVIDENCE) or _matches_root(rel, DATA_ROOTS)):
        out.append(Finding("delete", f"overwrites evidence or data: {rel}"))
    return _dedupe(out)


def decide(findings: list[Finding], subject: str) -> tuple[int, str]:
    """Exit code and message for a set of findings; consumes no token."""
    if not findings:
        return 0, ""
    kinds = sorted({f.kind for f in findings if f.kind != "consent"})
    lines = ["BLOCKED by scripts/guards/guard.py (docs/AGENT_RULES.md):"]
    lines += [f"  - {f.kind}: {f.reason}" for f in findings]
    lines.append(f"  call: {subject[:160]!r}")
    if any(f.kind == "consent" for f in findings):
        lines.append(
            "No consent token unlocks this. The agent never does it; "
            "a human may, by hand."
        )
        ct.log("refuse", "consent", subject[:120])
        return 2, "\n".join(lines)
    missing = [k for k in kinds if not ct.is_valid(k)]
    if not missing:
        for kind in kinds:
            ct.log("use", kind, subject[:120])
        return 0, "guard: allowed by human consent token(s): " + ", ".join(kinds)
    for kind in missing:
        ct.log("block", kind, subject[:120])
    lines.append(
        "This needs human consent. The human (not the agent) grants a 15-minute window:"
    )
    lines += [f"  ! scripts/guards/consent.sh {kind}" for kind in missing]
    lines.append(
        "typed in the Claude Code prompt with the leading '!', or run in another "
        "terminal. Then retry the exact same call."
    )
    return 2, "\n".join(lines)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool = str(payload.get("tool_name", ""))
        tool_input = payload.get("tool_input") or {}
        if tool == "Bash":
            subject = str(tool_input.get("command", ""))
            findings = classify_bash(subject)
        elif tool in ("Write", "Edit", "NotebookEdit"):
            subject = str(
                tool_input.get("file_path") or tool_input.get("notebook_path") or ""
            )
            findings = classify_file(tool, subject)
        else:
            return 0
        code, message = decide(findings, subject)
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        print(f"BLOCKED: the guard failed closed: {exc!r}", file=sys.stderr)
        return 2
    if message:
        print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
