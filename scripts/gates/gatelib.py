"""Shared helpers imported by every gate in scripts/gates/. Standard library only.

Input: the gate's argv (staged paths from pre-commit, or --all-tracked in CI).
Output: file lists, text reads, and fail() which prints to stderr and exits 1.
Exit 1 from any gate blocks the commit (pre-commit) or fails the job (CI).
"""

import pathlib
import subprocess
import sys

# Extensions and exact file names that text-scanning gates read; others are skipped.
TEXT_EXT = {
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
    ".sql",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".csv",
    ".example",
}
TEXT_NAMES = {"Makefile", "Dockerfile", ".gitignore", ".env.example", "justfile"}


def target_files(argv):
    """Return the paths a gate should check.

    Input: argv. With --all-tracked, every path from `git ls-files` (CI mode);
    otherwise the non-flag arguments, which pre-commit fills with staged paths.
    """
    if "--all-tracked" in argv:
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        ).stdout
        return [p for p in out.splitlines() if p]
    return [a for a in argv[1:] if not a.startswith("--")]


def is_text(path):
    """Return True when the path's suffix or name marks it as a scannable text file."""
    p = pathlib.Path(path)
    return p.suffix.lower() in TEXT_EXT or p.name in TEXT_NAMES


def read(path):
    """Return the file's text as UTF-8; undecodable bytes become U+FFFD, never raise."""
    return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")


def fail(msg):
    """Print msg to stderr and exit 1, which blocks the commit or fails CI."""
    print(msg, file=sys.stderr)
    sys.exit(1)
