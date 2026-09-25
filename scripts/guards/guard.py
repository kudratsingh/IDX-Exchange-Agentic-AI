"""Claude Code PreToolUse guard for this repo (docs/AGENT_RULES.md).

A tripwire, not a security boundary. It reads one tool call as JSON on stdin
(``tool_name``, ``tool_input``), classifies it from the command text or the file path,
and exits 2 to block it when it looks like it would delete or discard data (``delete``),
spend money on a model or API (``paid``), or edit the enforcement (``gates``), unless a
human has granted a consent token of that kind (``scripts/guards/consent.sh``). A paid
call passes only when the paid token names its exact command line and is unspent. A few
things are refused with no token at all: touching the consent mechanism, skipping the
commit hooks, and labelling a pull request.

It catches the common spellings of an accident. A determined agent can phrase around a
text classifier, which is why the real boundaries are the branch ruleset on ``main``,
provider API keys kept out of the agent's environment, and the commit gate plus CI
(docs/AGENT_RULES.md). Wired in ``.claude/settings.json`` for Bash, Write, Edit,
MultiEdit and NotebookEdit. Fails closed: any error inside the guard, or a command
longer than ``MAX_COMMAND_CHARS``, blocks the call. Standard library only.
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

MAX_COMMAND_CHARS = 20_000
MAX_DEPTH = 3


class Finding(NamedTuple):
    kind: str  # delete | paid | gates | consent (consent is never unlocked)
    reason: str
    # paid only: the argv of the one plain command that carries the finding, which a
    # paid token must name exactly. None (heredoc, inline code, nested shell, inline
    # key, .env) means no paid token unlocks it.
    argv: tuple[str, ...] | None = None


# ----- paths ---------------------------------------------------------------------
DATA_ROOTS = ("data/", "context/", "coordination/")
EVIDENCE = (
    "docs/EVIDENCE_LOG.md",
    "evals/cases/",
    "evals/runs/",
    "evals/reports/",
    "experiments/",
)
PROTECTED_WRITE = DATA_ROOTS + EVIDENCE
PROTECTED_TEXT_RE = re.compile(
    r"(^|[\s'\"=(])(data|context|coordination|evals/(cases|runs|reports)|experiments)/"
    r"|docs/EVIDENCE_LOG\.md"
)
# The enforcement itself. Anchored form for clean paths (the file tools).
GATE_RE = re.compile(
    r"(^|/)(scripts/gates/|scripts/guards/|\.github/workflows/|\.git/hooks/"
    r"|\.pre-commit-config\.yaml$|\.gitignore$|\.git/config$"
    r"|tests/test_(guards|protected_deletions|gates)\.py$)"
)
SETTINGS_RE = re.compile(r"(^|/)\.claude/settings(\.local)?\.json$")
# Unanchored form for free text such as a shell command; also catches globs.
GATE_ANY_RE = re.compile(
    r"scripts/(gates|guards|g[^/\s]*[*?][^/\s]*)/|\.github/workflows/|\.git/hooks/"
    r"|\.git/config\b|\.pre-commit-config\.yaml|\.gitignore\b"
    r"|\.claude/settings(\.local)?\.json|tests/test_(guards|protected_deletions|gates)\.py"
    r"|\.claude['\"]\s*,\s*['\"]settings|scripts['\"]\s*,\s*['\"](gates|guards)"
)
GATE_DIR_RE = re.compile(
    r"(^|/)(scripts/gates|scripts/guards|\.github|\.git|\.claude)(/|$)"
)
CONSENT_DIR_RE = re.compile(r"(^|/)\.local(/|$)")
# The consent mechanism inside a shell command: the agent never touches it.
CONSENT_TEXT_RE = re.compile(
    r"(^|[\s'\"=(])\.local\b|\bconsent_token\b(?!\.py)|[/'\"]consent[/'\"]|\bconsent/"
    r"|\b(IDX_CONSENT_DIR|CLAUDE_PROJECT_DIR|IDX_PROJECT_ROOT)\s*="
)
CONSENT_PATH_RE = re.compile(r"(^|/)\.local/consent(/|$)")
CONSENT_SCRIPTS = ("consent.sh", "consent_token.py")
CLAUDE_HOME_RE = re.compile(r"(^|/)\.claude/")

# rm targets that are always fine: scratch space and rebuildable caches.
SCRATCH_RE = re.compile(r"^(/private)?/tmp(/|$)|^\$\{?TMPDIR|(^|/)scratchpad(/|$)")
CACHE_RE = re.compile(
    r"(^|/)(\.venv|venv|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache"
    r"|build|dist|node_modules|htmlcov|\.coverage)(/|$)|\.egg-info/?$|\.pyc$"
)
CACHE_GLOB_RE = re.compile(
    r"^(\*\.pyc|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\*\.egg-info"
    r"|\.coverage|htmlcov)$"
)

# ----- text patterns --------------------------------------------------------------
SQL_RE = re.compile(
    r"\b(drop\s+(table|database|schema|index|view)\b|truncate(\s+table)?\s*\\?[\w`]"
    r"|delete\s+from\s*\\?[\w`]|alter\s+table\b[^;]{0,200}\bdrop\b"
    r"|update\s+[\w`.]+\s+set\b|rename\s+table\b)",
    re.I,
)
SQL_EXEC_HINT_RE = re.compile(
    r"execute|cursor|query|\bsql\b|mysql|psql|engine|connect|\s-e\s|--execute", re.I
)
PAID_HOST_RE = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com"
    r"|openrouter\.ai|api\.mistral\.ai|api\.cohere\.(ai|com)|api\.groq\.com"
    r"|api\.together\.xyz|api\.voyageai\.com|api\.deepseek\.com|api\.x\.ai",
    re.I,
)
PAID_SDK_RE = re.compile(
    r"\b(from|import)\s+(openai|anthropic|google\.generativeai|cohere|mistralai"
    r"|voyageai|litellm)\b|__import__\(['\"](openai|anthropic)"
    r"|\b(Async)?(OpenAI|Anthropic)\("
    r"|\b(chat\.completions|messages|embeddings|responses)\.create\("
    r"|\s-m\s*(openai|anthropic)\b"
)
PAID_SUITE_RE = re.compile(
    r"--suite[= ]+['\"]?local\b|\bpytest\b[^\n]{0,300}?\s-m\s*['\"]?(paid|live)\b"
    r"|\bmake\s+\S*(live|paid)\b|--allow-paid\b|--judge-sheet\b"
)
# Command and process substitution: the command that runs is not the visible argv.
SUBST_RE = re.compile(r"\$\(|`|<\(|>\(")
DANGER_CODE_RE = re.compile(
    r"\b(rmtree|os\.remove|os\.unlink|os\.rmdir|os\.removedirs|\bunlink\b|rmSync"
    r"|rmdirSync|unlinkSync|rm_rf|rm_r\b|FileUtils\.rm|send2trash|os\.system"
    r"|shell=True|\.truncate\(|shutil\.move)"
)
WRITE_HINT_RE = re.compile(
    r"write_text|write_bytes|\.write\(|open\([^)]{0,200}['\"][wa]"
)
ENV_FILE_RE = re.compile(r"(^|/)\.env(\.[A-Za-z0-9_-]+)?$")
SEGMENT_RE = re.compile(
    r"\s*(?:\|\||&&|;;|;|(?<!>)\||&|\n|\$\(|(?<!\\)`|\(|\)|\{|\}"
    r"|\bthen\b|\bdo\b|\belse\b|\belif\b|\bfi\b|\bdone\b)\s*"
)
COARSE_RE = re.compile(r"\s*(?:\|\||&&|;;|;|(?<!>)\||&|\n)\s*")
REDIRECT_RE = re.compile(r"(?<![<>])(>>|>\||>)\s*(\S+)")
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)
LABEL_RE = re.compile(r"addLabelsToLabelable|/labels\b", re.I)
GIT_CONFIG_ENV_RE = re.compile(r"\bGIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)\s*=")
CONSENT_ENV_RE = re.compile(
    r"\b(IDX_CONSENT_DIR|CLAUDE_PROJECT_DIR|IDX_PROJECT_ROOT)\s*="
)
SKIP_RE = re.compile(r"\bSKIP=\S*\s+git\b[^\n]{0,300}\bcommit\b|\bexport\s+SKIP=")
HOOKSPATH_RE = re.compile(r"core\.hookspath", re.I)

# ----- command vocab ---------------------------------------------------------------
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
    # Registry, inspection, and channel-management subcommands: no model turn.
    "mcp",
    "channels",
    "gateway",
    "sessions",
    "pairing",
    "agents",
    "models",
    "plugins",
    "secrets",
    "audit",
    "health",
    "validate",
    "restart",
    "stop",
    "tail",
    "export-trajectory",
}
OPENCLAW_RUN = {
    "run",
    "start",
    "chat",
    "send",
    "serve",
    "agent",
    "message",
    "invoke",
    "exec",
    "ask",
    "reply",
    "talk",
    "tui",
    "daemon",
}
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
    "watch",
    "parallel",
    "npx",
    "bunx",
    "pnpm",
    "yarn",
    "uv",
    "uvx",
    "poetry",
    "pipx",
}
WRAPPER_FLAGS_WITH_VALUE = {"-t", "-n", "-w", "-u", "-s", "-k", "--signal", "-j"}
WRAPPER_SUBWORDS = {"exec", "dlx", "run"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "php"}
CODE_RUNNERS = SHELLS | INTERPRETERS | {"make"}
WRITER_BASES = {
    "cp",
    "mv",
    "tee",
    "touch",
    "chmod",
    "chown",
    "install",
    "ln",
    "patch",
    "rm",
    "unlink",
    "truncate",
    "shred",
    "rsync",
    "dd",
    "trash",
}
DB_CLIENTS = {
    "mysql",
    "mysqlsh",
    "mariadb",
    "psql",
    "sqlite3",
    "duckdb",
    "mycli",
    "pgcli",
}
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
    "yq",
    "bat",
    "echo",
    "printf",
    "mkdir",
    "pwd",
    "which",
    "type",
    "test",
    "true",
    "false",
    "cd",
    "pushd",
    "popd",
}
GIT_GLOBAL_WITH_ARG = {"-C", "--git-dir", "--work-tree", "--namespace"}
# Output redirections dropped from a paid command's argv (`> /tmp/run.log 2>&1`,
# `> "/tmp/run log.txt"`); a quoted `">x"` argument is left alone. A trailing bare `2>`
# is what is left of `2>&1` after the splitter cuts at `&`.
OUT_REDIRECT_RE = re.compile(
    r"(?<![\w'\"])(?:\d*|&)(?:>>|>\||>&|>)\s*"
    r"(?:&?\d+\b|-(?=\s|$)|\"[^\"]*\"|'[^']*'|[^\s'\"<>|&;(]+|$)"
)
# Input redirection, heredocs, and substitutions: the argv would not be the program.
PAID_ARGV_UNSAFE_RE = re.compile(r"<|\$\(|`|>\(")
INLINE_CODE_RE = re.compile(r"-[A-Za-z]*[ceE]")
# Env words that change which code runs: a paid argv with one of them never matches.
CODE_ENV_RE = re.compile(r"(PATH|PYTHON\w*|DYLD_\w*|LD_\w*)=.*", re.S)
# The modules that may hold provider calls (content scan of Write/Edit); tests too.
PAID_MODULES = (
    "src/idx_agent/semantic/embedder.py",
    "src/idx_agent/semantic/build_index.py",
    "src/idx_agent/rag/build.py",
    "src/idx_agent/rag/vectors.py",
    "evals/run.py",
    "scripts/semantic_spike.py",
)
# The tool_input keys that hold the text a file tool writes.
CONTENT_KEYS = ("content", "new_string", "new_source")


# ----- helpers ----------------------------------------------------------------------
def _norm(path: str) -> str:
    return os.path.normpath(path.strip("\"'"))


def _under(path: str, roots: tuple[str, ...]) -> bool:
    """True when `path` (relative or absolute) is one of `roots` or lies under it."""
    p = _norm(path)
    for root in roots:
        r = root.rstrip("/")
        if p == r or p.startswith(r + "/") or ("/" + r + "/") in ("/" + p + "/"):
            return True
    return False


def _evidence_root(path: str) -> str | None:
    for root in EVIDENCE:
        if _under(path, (root,)):
            return root
    return None


def _scratch(path: str) -> bool:
    p = _norm(path)
    return bool(SCRATCH_RE.search(p) or CACHE_RE.search(p))


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
        base = os.path.basename(head)
        if base not in WRAPPERS:
            break
        argv = argv[1:]
        # `command -v x` / `command -V x` only look a program up; nothing runs.
        if base == "command" and argv and argv[0] in ("-v", "-V"):
            return [], key_passed
        while argv and argv[0].startswith("-"):
            flag = argv[0]
            argv = argv[1:]
            if flag in WRAPPER_FLAGS_WITH_VALUE and argv:
                argv = argv[1:]
        if base == "timeout" and argv and re.fullmatch(r"\d+(\.\d+)?[smhd]?", argv[0]):
            argv = argv[1:]
        if base in ("pnpm", "yarn", "uv", "poetry", "pipx") and argv:
            if argv[0] in WRAPPER_SUBWORDS:
                argv = argv[1:]
    return argv, key_passed


def _short(rest: list[str], letter: str) -> bool:
    """A bundled short flag such as -nm or -df that contains `letter`."""
    return any(re.fullmatch(rf"-[a-zA-Z]*{letter}[a-zA-Z]*", a) for a in rest)


def _no_verify(arg: str) -> bool:
    return arg.startswith("--no-v") and "--no-verify".startswith(arg)


def _git_parts(argv: list[str]) -> tuple[str, list[str], list[str]]:
    """Subcommand, its args, and the values of any global -c / --config-env."""
    i = 1
    config_values: list[str] = []
    while i < len(argv):
        arg = argv[i]
        if arg in ("-c", "--config-env") and i + 1 < len(argv):
            config_values.append(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--config-env="):
            config_values.append(arg.split("=", 1)[1])
            i += 1
            continue
        if arg in GIT_GLOBAL_WITH_ARG:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        return arg, argv[i + 1 :], config_values
    return "", [], config_values


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[Finding] = set()
    out: list[Finding] = []
    for f in findings:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _paid_argv(text: str) -> tuple[str, ...] | None:
    """The argv a paid token must name for this plain command, or None (blocked).

    Drops output redirects and leading wrappers or `NAME=value` words. None for input
    redirects, heredocs, substitutions, inline code (`python -c`, `-`, `node -e`), or
    a dropped PATH, PYTHON*, DYLD_* or LD_* word (it changes which code runs)."""
    if SUBST_RE.search(text):
        return None
    stripped = OUT_REDIRECT_RE.sub(" ", text)
    if PAID_ARGV_UNSAFE_RE.search(stripped):
        return None
    typed = _argv(stripped)
    words, _ = _strip_prefix(typed)
    if not words:
        return None
    if any(CODE_ENV_RE.fullmatch(w) for w in typed[: len(typed) - len(words)]):
        return None
    base = os.path.basename(words[0])
    if base in CODE_RUNNERS or re.fullmatch(r"python[\d.]*", base):
        if len(words) == 1:
            return None  # the program reads its code from stdin
        for word in words[1:]:
            if word == "-m" or not word.startswith("-"):
                break
            if word == "-" or INLINE_CODE_RE.fullmatch(word):
                return None
    return tuple(words)


def _without_paid_argv(findings: list[Finding]) -> list[Finding]:
    return [f._replace(argv=None) if f.kind == "paid" else f for f in findings]


# ----- git and gh ---------------------------------------------------------------
def _classify_git(argv: list[str], depth: int) -> list[Finding]:
    sub, rest, config_values = _git_parts(argv)
    out: list[Finding] = []
    for value in config_values:
        if HOOKSPATH_RE.search(value):
            out.append(Finding("consent", "git -c core.hooksPath skips the hooks"))
        if value.startswith("alias.") and "=!" in value:
            out.extend(classify_bash(value.split("=!", 1)[1], depth + 1))
    positional = [a for a in rest if not a.startswith("-")]

    if sub in ("commit", "merge", "am") and (
        _short(rest, "n") or any(_no_verify(a) for a in rest)
    ):
        out.append(Finding("consent", f"git {sub} that skips the hooks"))
    if sub == "push" and any(_no_verify(a) for a in rest):
        out.append(Finding("consent", "git push that skips the hooks"))
    if sub == "config":
        if any(HOOKSPATH_RE.search(a) for a in rest):
            out.append(Finding("consent", "moving the hooks path"))
        for i, a in enumerate(rest):
            if (
                a.startswith("alias.")
                and i + 1 < len(rest)
                and rest[i + 1].startswith("!")
            ):
                out.extend(classify_bash(rest[i + 1][1:], depth + 1))
    if sub == "rebase":
        for i, a in enumerate(rest):
            if a in ("--exec", "-x") and i + 1 < len(rest):
                out.extend(classify_bash(rest[i + 1], depth + 1))
            elif a.startswith("--exec="):
                out.extend(classify_bash(a.split("=", 1)[1], depth + 1))

    if sub == "clean":
        dry = (_short(rest, "n") or "--dry-run" in rest) and "--no-dry-run" not in rest
        if not dry:
            out.append(Finding("delete", "git clean removes untracked files"))
    elif sub == "reset" and any(a in ("--hard", "--merge", "--keep") for a in rest):
        out.append(Finding("delete", "git reset that discards work"))
    elif sub == "checkout":
        creates = any(a in ("-b", "-B", "--orphan") for a in rest)
        if _short(rest, "f") or "--force" in rest:
            out.append(Finding("delete", "forced checkout discards changes"))
        elif "--" in rest and rest.index("--") < len(rest) - 1:
            out.append(Finding("delete", "git checkout of paths discards changes"))
        elif (positional and positional[-1] == ".") or (
            len(positional) >= 2 and not creates
        ):
            out.append(Finding("delete", "git checkout of paths discards changes"))
    elif sub == "switch" and (
        _short(rest, "f") or any(a in ("--discard-changes", "--force") for a in rest)
    ):
        out.append(Finding("delete", "git switch that discards changes"))
    elif sub == "restore":
        staged_only = any(a in ("--staged", "-S") for a in rest) and not any(
            a in ("--worktree", "-W") for a in rest
        )
        if not staged_only:
            out.append(Finding("delete", "git restore discards working changes"))
    elif sub == "stash" and not (rest and rest[0] in ("list", "show")):
        out.append(Finding("delete", "git stash is banned in shared checkouts"))
    elif sub == "push":
        if (
            _short(rest, "f")
            or any(a == "--mirror" or a.startswith("--force") for a in rest)
            or any(a.startswith(("+", ":")) for a in positional)
        ):
            out.append(Finding("delete", "push that forces or deletes a remote ref"))
        elif any(a in ("-d", "--delete") for a in rest) and any(
            p in ("main", "master") for p in positional
        ):
            out.append(Finding("delete", "deleting the main branch"))
    elif sub == "branch":
        force = _short(rest, "D") or _short(rest, "f") or "--force" in rest
        deleting = _short(rest, "d") or _short(rest, "D") or "--delete" in rest
        if force and deleting:
            out.append(Finding("delete", "force-deleting a branch drops unmerged work"))
    elif (
        sub == "worktree"
        and rest[:1] == ["remove"]
        and (_short(rest, "f") or "--force" in rest)
    ):
        out.append(Finding("delete", "forced worktree removal drops changes"))
    elif sub == "rm":
        out.append(Finding("delete", "git rm stages a deletion"))
    elif sub == "mv" and positional:
        if any(GATE_ANY_RE.search(a) for a in positional):
            out.append(Finding("gates", "git mv of the enforcement"))
        elif any(_under(s, PROTECTED_WRITE) for s in positional[:-1]) and not all(
            _evidence_root(s) == _evidence_root(positional[-1]) for s in positional[:-1]
        ):
            out.append(Finding("delete", "git mv moves data or evidence out of place"))
    elif sub in ("filter-branch", "filter-repo", "replace"):
        out.append(Finding("delete", f"git {sub} rewrites history"))
    elif sub == "reflog" and rest[:1] and rest[0] in ("expire", "delete"):
        out.append(Finding("delete", "dropping reflog recovery points"))
    elif sub == "gc" and any(a.startswith("--prune") for a in rest):
        out.append(Finding("delete", "git gc --prune drops recovery points"))
    elif sub == "update-ref" and positional:
        out.append(Finding("delete", "rewriting a ref by hand"))
    elif sub == "read-tree" and "--reset" in rest:
        out.append(Finding("delete", "git read-tree --reset discards work"))
    elif sub == "tag" and (_short(rest, "d") or "--delete" in rest):
        out.append(Finding("delete", "deleting a tag"))
    return out


def _classify_gh(rest: list[str]) -> list[Finding]:
    out: list[Finding] = []
    if rest[:1] == ["repo"] and "delete" in rest:
        out.append(Finding("consent", "deleting the repository"))
    elif rest[:1] == ["release"] and "delete" in rest:
        out.append(Finding("delete", "deleting a release"))
    elif rest[:1] == ["label"]:
        out.append(Finding("consent", "editing labels (a human does that)"))
    elif rest[:2] in (["pr", "create"], ["pr", "edit"], ["pr", "merge"]) and any(
        a in ("--add-label", "--label", "-l")
        or a.startswith(("--add-label=", "--label="))
        for a in rest
    ):
        out.append(Finding("consent", "labelling a pull request (a human does that)"))
    elif rest[:1] == ["api"]:
        if any("label" in a.lower() for a in rest):
            out.append(
                Finding("consent", "labelling through the API (a human does that)")
            )
        if any(a in ("-X", "--method") for a in rest) and "DELETE" in rest:
            out.append(Finding("delete", "DELETE request through the API"))
    return out


# ----- one shell segment ------------------------------------------------------------
def _classify_segment(
    segment: str, depth: int, ctx: str
) -> tuple[list[Finding], str, list[str]]:
    argv, key_passed = _strip_prefix(_argv(segment))
    base = os.path.basename(argv[0]) if argv else ""
    rest = argv[1:]
    out: list[Finding] = []

    if key_passed:
        out.append(Finding("paid", "an API key is passed to a command"))
    if base == "export" and any(re.match(r"[A-Z0-9_]*_API_KEY=", a) for a in rest):
        out.append(Finding("paid", "exports an API key for later calls"))
    if base in ("source", ".") and rest and ENV_FILE_RE.search(_norm(rest[0])):
        if not rest[0].endswith(".example"):
            out.append(Finding("paid", "loads a .env with credentials"))

    # The consent mechanism: never.
    if CONSENT_TEXT_RE.search(segment) and base not in READ_ONLY_BASES:
        out.append(Finding("consent", "touches the consent mechanism"))
    if base in CONSENT_SCRIPTS or (
        base in CODE_RUNNERS
        and any(os.path.basename(a.strip("\"'")) in CONSENT_SCRIPTS for a in rest)
    ):
        out.append(Finding("consent", "runs the consent script"))
    if ctx == "consent" and base and base not in READ_ONLY_BASES:
        out.append(Finding("consent", "writes inside .local after cd"))

    for op, target in REDIRECT_RE.findall(segment):
        t = target.strip("\"'")
        if t.startswith("&") or t.startswith("/dev/"):
            continue
        if CONSENT_TEXT_RE.search(t) or ctx == "consent":
            out.append(Finding("consent", f"writes {t}"))
        elif GATE_ANY_RE.search(t) or ctx == "gates":
            out.append(Finding("gates", f"writes {t}"))
        elif op in (">", ">|") and _under(t, PROTECTED_WRITE):
            out.append(Finding("delete", f"truncates {t}"))

    in_place = base in ("sed", "perl") and _short(rest, "i")
    writer = base in WRITER_BASES or in_place
    if writer and (any(GATE_ANY_RE.search(a) for a in rest) or ctx == "gates"):
        out.append(Finding("gates", f"{base} edits the enforcement"))
    if in_place and any(
        _under(a, PROTECTED_WRITE) for a in rest if not a.startswith("-")
    ):
        out.append(Finding("delete", "in-place edit of evidence or data"))
    if base == "patch":
        out.append(Finding("gates", "patch applies changes to unknown files"))

    if base == "rm":
        targets = [a for a in rest if not a.startswith("-")]
        bad = [t for t in targets if not _scratch(t)]
        if not targets:
            out.append(Finding("delete", "rm with no literal target"))
        elif bad:
            out.append(Finding("delete", "rm of " + ", ".join(bad[:3])))
    elif base in ("unlink", "trash"):
        out.append(Finding("delete", f"{base} removes a file"))
    elif base == "find" and ("-delete" in rest or "rm" in rest):
        root = rest[0] if rest and not rest[0].startswith("-") else "."
        names = [
            rest[i + 1].strip("\"'")
            for i, a in enumerate(rest)
            if a in ("-name", "-iname") and i + 1 < len(rest)
        ]
        cache_only = bool(names) and all(CACHE_GLOB_RE.match(n) for n in names)
        if not (_scratch(root) or cache_only):
            out.append(Finding("delete", f"find deletes under {root}"))
    elif base == "xargs" and "rm" in rest:
        out.append(Finding("delete", "xargs rm"))
    elif base in ("shred", "truncate"):
        out.append(Finding("delete", f"{base} destroys file contents"))
    elif base == "dd":
        outs = [a[3:] for a in rest if a.startswith("of=")]
        if any(not _scratch(t) for t in outs):
            out.append(Finding("delete", "dd overwrites a file"))
    elif base == "cp":
        args = [a for a in rest if not a.startswith("-")]
        dest = args[-1] if len(args) >= 2 else ""
        if "/dev/null" in args or (dest and _under(dest, PROTECTED_WRITE)):
            out.append(Finding("delete", "cp overwrites evidence or data"))
    elif base == "tee" and "-a" not in rest:
        if any(_under(a, PROTECTED_WRITE) for a in rest if not a.startswith("-")):
            out.append(Finding("delete", "tee truncates evidence or data"))
    elif base == "mv":
        args = [a for a in rest if not a.startswith("-")]
        dest = ""
        if "-t" in rest and rest.index("-t") + 1 < len(rest):
            dest = rest[rest.index("-t") + 1]
            sources = [a for a in args if a != dest]
        else:
            dest = args[-1] if len(args) >= 2 else ""
            sources = args[:-1]
        same_root = bool(dest) and all(
            _evidence_root(s) is not None and _evidence_root(s) == _evidence_root(dest)
            for s in sources
        )
        moves_protected = any(
            _under(s, PROTECTED_WRITE) or CLAUDE_HOME_RE.search(_norm(s))
            for s in sources
        )
        if not same_root and (
            moves_protected or (dest and _under(dest, PROTECTED_WRITE))
        ):
            out.append(Finding("delete", "moves data or evidence out of place"))
    elif base == "rsync":
        args = [a for a in rest if not a.startswith("-")]
        if any(a.startswith("--delete") for a in rest) or (
            args and _under(args[-1], PROTECTED_WRITE)
        ):
            out.append(Finding("delete", "rsync deletes or overwrites data"))
    elif base == "git":
        out.extend(_classify_git(argv, depth))
    elif base == "gh":
        out.extend(_classify_gh(rest))
    elif base in ("docker", "docker-compose"):
        joined = " ".join(rest)
        if re.search(
            r"\bdown\b.*(\s-v\b|--volumes)|\bvolume\s+(rm|prune)\b|\bsystem\s+prune\b"
            r"|\brm\b.*\s-v\b",
            joined,
        ):
            out.append(Finding("delete", "docker command deletes volumes"))
        if SQL_RE.search(segment):
            out.append(Finding("delete", "destructive SQL through docker"))
    elif base in DB_CLIENTS:
        if (
            SQL_RE.search(segment)
            or "<" in segment
            or re.search(r"\bsource\b", segment)
        ):
            out.append(Finding("delete", f"{base} runs destructive or unread SQL"))
    elif base in SHELLS and "-c" in rest and rest.index("-c") + 1 < len(rest):
        out.extend(classify_bash(rest[rest.index("-c") + 1], depth + 1))
    elif base == "eval":
        out.extend(classify_bash(" ".join(rest), depth + 1))
    elif base in ("openai", "anthropic", "claude"):
        out.append(
            Finding("paid", f"{base} CLI calls a paid model", _paid_argv(segment))
        )
    elif base == "openclaw":
        words = set(rest)
        if not rest or not (words & OPENCLAW_FREE) or (words & OPENCLAW_RUN):
            out.append(
                Finding(
                    "paid",
                    "openclaw command may call a paid model",
                    _paid_argv(segment),
                )
            )
    elif base == "pre-commit" and "uninstall" in rest:
        out.append(Finding("consent", "uninstalling the commit hooks"))
    return out, base, argv


# ----- whole commands and file paths ----------------------------------------------
def classify_bash(command: str, depth: int = 0) -> list[Finding]:
    if depth > MAX_DEPTH:
        return [Finding("delete", "nested shell too deep to inspect")]
    findings: list[Finding] = []
    if GIT_CONFIG_ENV_RE.search(command):
        findings.append(Finding("consent", "GIT_CONFIG_* env can skip the hooks"))
    if SKIP_RE.search(command):
        findings.append(Finding("consent", "SKIP= around git commit"))
    if LABEL_RE.search(command):
        findings.append(
            Finding("consent", "labelling a pull request (a human does that)")
        )
    if CONSENT_ENV_RE.search(command):
        findings.append(Finding("consent", "points the guard at another consent dir"))

    ctx = ""
    bases: set[str] = set()
    active: list[str] = []
    # A paid token names one plain command run directly: a nested shell or a heredoc
    # anywhere in the call means no paid finding carries an argv.
    plain = depth == 0 and "<<" not in command
    for segment in SEGMENT_RE.split(command):
        segment = segment.strip()
        if not segment:
            continue
        seg_findings, base, argv = _classify_segment(segment, depth, ctx)
        findings.extend(seg_findings)
        bases.add(base)
        if base in ("cd", "pushd"):
            target = _norm(argv[1]) if len(argv) > 1 else "~"
            if CONSENT_DIR_RE.search(target) and not target.startswith(("/", "~")):
                ctx = "consent"
            elif GATE_DIR_RE.search(target):
                ctx = "gates"
            else:
                ctx = ""
    substituted: list[str] = []
    for piece in COARSE_RE.split(command):
        piece = piece.strip()
        if not piece:
            continue
        piece_argv, _ = _strip_prefix(_argv(piece))
        piece_base = os.path.basename(piece_argv[0]) if piece_argv else ""
        if piece_base and piece_base not in READ_ONLY_BASES:
            active.append(piece)
        elif SUBST_RE.search(piece):
            substituted.append(piece)  # `echo $(python -m evals.run ...)` still runs
    active_text = "\n".join(active)

    # Pieces hold no newline, so matching each piece equals matching active_text;
    # each matching piece is its own finding with its own argv (None: blocked).
    for pattern, reason in (
        (PAID_HOST_RE, "reaches a paid API host"),
        (PAID_SDK_RE, "uses a model SDK"),
        (PAID_SUITE_RE, "runs a paid suite or a paid builder"),
    ):
        for piece in active + substituted:
            if pattern.search(piece):
                findings.append(Finding("paid", reason, _paid_argv(piece)))
    if not plain:
        findings = _without_paid_argv(findings)
    if bases & CODE_RUNNERS:
        if DANGER_CODE_RE.search(active_text):
            findings.append(
                Finding("delete", "code that deletes files or runs a shell")
            )
        if SQL_RE.search(active_text) and SQL_EXEC_HINT_RE.search(active_text):
            findings.append(Finding("delete", "destructive SQL in a script"))
        if WRITE_HINT_RE.search(active_text):
            if GATE_ANY_RE.search(active_text):
                findings.append(Finding("gates", "a script writes to the enforcement"))
            if PROTECTED_TEXT_RE.search(active_text):
                findings.append(
                    Finding("delete", "a script writes to evidence or data")
                )
    return _dedupe(findings)


def _rel_path(path: str) -> tuple[pathlib.Path, pathlib.Path, str]:
    """(as given, resolved, relative to the project root when inside it)."""
    root = ct.project_root()
    p = pathlib.Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()
    try:
        rel = str(resolved.relative_to(root.resolve()))
    except ValueError:
        rel = str(resolved)
    return p, resolved, rel


def _worktree_rel(path: str) -> str:
    """`path` relative to the checkout or worktree that holds it (git-free)."""
    p = pathlib.Path(os.path.expanduser(path)).resolve()
    for parent in p.parents:
        if (parent / ".git").exists():
            return str(p.relative_to(parent))
    return _rel_path(path)[2]


def classify_content(path: str, content: str) -> list[Finding]:
    """A paid finding (no token unlocks it) for text written by Write or Edit that
    calls a model SDK or a paid host, outside the known paid modules and tests/."""
    if not content or not (PAID_SDK_RE.search(content) or PAID_HOST_RE.search(content)):
        return []
    rel = _worktree_rel(path) if path else ""
    if rel in PAID_MODULES or rel.startswith("tests/"):
        return []
    return [Finding("paid", f"writes a provider call outside the paid modules: {rel}")]


def classify_file(tool_name: str, path: str) -> list[Finding]:
    if not path:
        return []
    p, resolved, rel = _rel_path(path)
    out: list[Finding] = []
    if CONSENT_PATH_RE.search(rel) or CONSENT_PATH_RE.search(str(p)):
        out.append(Finding("consent", f"writes the consent mechanism: {rel}"))
    if SETTINGS_RE.search(rel) or SETTINGS_RE.search(str(p)):
        out.append(Finding("gates", f"edits Claude Code settings: {rel}"))
    if GATE_RE.search(rel) or GATE_RE.search(str(p)):
        out.append(Finding("gates", f"edits the enforcement: {rel}"))
    if tool_name == "Write" and resolved.exists() and _under(rel, PROTECTED_WRITE):
        out.append(Finding("delete", f"overwrites evidence or data: {rel}"))
    return _dedupe(out)


def decide(findings: list[Finding], subject: str) -> tuple[int, str]:
    """Exit code and message for a set of findings.

    A paid finding passes only when `consent_token.admit_paid` admits its argv, which
    marks the token admitted: the same command cannot pass the hook twice.
    """
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
        ct.log("refuse", "consent", subject)
        return 2, "\n".join(lines)
    # A paid finding passes only when the paid token names its exact argv and is
    # unexpired, un-admitted and unspent; admitting it marks the token, and the run
    # itself spends it. Nothing is admitted while anything else in the call blocks.
    paid = [f for f in findings if f.kind == "paid"]
    windows = [k for k in kinds if k != "paid" and not ct.is_valid(k)]
    paid_blocked = [f for f in paid if f.argv is None]
    reasons: dict[tuple[str, ...], str] = {}
    if len({f.argv for f in paid if f.argv is not None}) > 1:
        # One token names one command: admit none rather than waste it on the first.
        reasons = {f.argv: "one token covers one command" for f in paid if f.argv}
        paid_blocked = paid
    elif paid and not windows and not paid_blocked:
        for f in paid:
            if f.argv is None or f.argv in reasons:
                continue
            try:
                ct.admit_paid(list(f.argv))
                reasons[f.argv] = ""
            except ct.NoPaidToken as exc:
                reasons[f.argv] = exc.reason
                paid_blocked.append(f)
    elif paid:  # something else blocks: say which paid parts need a token, admit none
        paid_blocked = [f for f in paid if f.argv is None or ct.paid_reason(f.argv)]
    if not windows and not paid_blocked:
        for kind in kinds:
            ct.log("use", kind, subject)
        return 0, "guard: allowed by human consent token(s): " + ", ".join(kinds)
    for kind in windows + (["paid"] if paid_blocked else []):
        ct.log("block", kind, subject)
    if windows:
        lines.append(
            "This needs human consent. The human (not the agent) grants a "
            "15-minute window:"
        )
        lines += [f"  ! scripts/guards/consent.sh {kind}" for kind in windows]
    if paid_blocked:
        lines += _paid_hint(paid_blocked, reasons)
    lines.append(
        "typed in the Claude Code prompt with the leading '!', or run in another "
        "terminal. Then retry the exact same call."
    )
    return 2, "\n".join(lines)


def mint_line(argv: list[str] | tuple[str, ...], max_calls: str = "<N>") -> str:
    """The consent.sh line a human runs for one run of `argv` (same form as
    idx_agent.safety.consent.mint_command: double quotes unless they are unsafe)."""
    words = " ".join(ct.normalize_command(list(argv)))
    unsafe = any(ch in words for ch in ('"', "$", "`", "\\"))
    quoted = shlex.quote(words) if unsafe else f'"{words}"'
    return (
        f"! scripts/guards/consent.sh paid 30 --command {quoted} "
        f"--max-calls {max_calls}"
    )


def _paid_hint(
    blocked: list[Finding], reasons: dict[tuple[str, ...], str] | None = None
) -> list[str]:
    """Block-message lines for paid findings: the mint command, or why none fits."""
    reasons = reasons or {}
    lines = [
        "A paid token covers one run of one exact command line with a call ceiling; "
        "the hook admits that command once, the run spends it, and a second run "
        "needs a new token."
    ]
    argvs: list[tuple[str, ...]] = []
    for f in blocked:
        if f.argv is not None and f.argv not in argvs:
            argvs.append(f.argv)
    if any(f.argv is None for f in blocked):
        lines.append(
            "No paid token unlocks this spelling (heredoc, substitution, inline code, "
            "nested shell, PATH/PYTHON*/LD_* env words, inline API key, .env, or a "
            "provider call written outside the paid modules). Run the paid program "
            "as one plain command."
        )
    if argvs:
        lines.append(
            "The human (not the agent) mints one for this command, with N = the "
            "run's call ceiling:"
        )
    for argv in argvs:
        reason = reasons.get(argv) or ct.paid_reason(list(argv)) or "unused"
        lines.append(f"  (current paid token: {reason})")
        lines.append(f"  {mint_line(argv)}")
    return lines


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool = str(payload.get("tool_name", ""))
        tool_input = payload.get("tool_input") or {}
        if tool == "Bash":
            subject = str(tool_input.get("command", ""))
            if len(subject) > MAX_COMMAND_CHARS:
                print(
                    f"BLOCKED: command longer than {MAX_COMMAND_CHARS} characters; "
                    "split it or put it in a script file.",
                    file=sys.stderr,
                )
                return 2
            findings = classify_bash(subject)
        elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            subject = str(
                tool_input.get("file_path") or tool_input.get("notebook_path") or ""
            )
            findings = classify_file(tool, subject)
            edits = tool_input.get("edits") or []
            content = "\n".join(
                [str(tool_input.get(key) or "") for key in CONTENT_KEYS]
                + [str(e.get("new_string") or "") for e in edits if isinstance(e, dict)]
            )
            findings = _dedupe(findings + classify_content(subject, content))
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
