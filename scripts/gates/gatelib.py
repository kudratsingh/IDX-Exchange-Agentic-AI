"""Shared helpers for the commit gates. Standard library only."""

import pathlib
import subprocess
import sys

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
    """Paths passed by pre-commit, or every tracked file with --all-tracked."""
    if "--all-tracked" in argv:
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        ).stdout
        return [p for p in out.splitlines() if p]
    return [a for a in argv[1:] if not a.startswith("--")]


def is_text(path):
    p = pathlib.Path(path)
    return p.suffix.lower() in TEXT_EXT or p.name in TEXT_NAMES


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)
