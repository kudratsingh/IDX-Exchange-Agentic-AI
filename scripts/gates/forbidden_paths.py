"""Gate: block paths that must never be tracked (RULES.md, rule 1). Checks names only.

Input: paths from gatelib.target_files. Output: "ok" line, or exit 1 listing each path
and reason. Chain: pre-commit passes staged paths -> check() per path -> exit 1 blocks
the commit; CI runs the same gate with --all-tracked.
"""

import re
import sys

from gatelib import fail, target_files

# .sql is allowed only under these prefixes; any other .sql path is blocked.
ALLOWED_SQL_DIRS = ("scripts/migrations/", "tests/fixtures/")
# (pattern, reason) pairs; the first pattern that matches a path blocks it.
RULES = [
    (
        re.compile(r"^(data|context|coordination)/"),
        "data/, context/ and coordination/ are never tracked",
    ),
    (
        re.compile(r"(^|/)\.env(\..+)?$"),
        ".env files are never tracked (only .env.example)",
    ),
    (
        re.compile(
            r"\.(csv|tsv|parquet|npy|npz|pkl|pickle|faiss|log|sql\.gz|zip|gz|tar|tgz)$",
            re.I,
        ),
        "data, dump, cache and archive files are never tracked",
    ),
    (
        re.compile(r"\.(pdf|docx|pptx|xlsx)$", re.I),
        "PDF and office documents are never tracked; the handbook, Primer and metadata live in context/ or data/",
    ),
    (
        re.compile(r"(^|/)(sessions|whatsapp-auth|\.openclaw|dumps|logs)/"),
        "runtime state, auth files and dumps are never tracked",
    ),
]


def check(path):
    """Return a reason string if the path is forbidden, else None.

    Order: .env.example always passes; .sql is decided by ALLOWED_SQL_DIRS;
    every other path is tested against RULES.
    """
    if path == ".env.example":
        return None
    if path.endswith(".sql"):
        if path.startswith(ALLOWED_SQL_DIRS):
            return None
        return (
            ".sql files are allowed only under scripts/migrations/ and tests/fixtures/"
        )
    for rx, why in RULES:
        if rx.search(path):
            return why
    return None


def main(argv):
    """Check every target path; print ok, or fail with all blocked paths at once."""
    files = target_files(argv)
    bad = [(p, w) for p in files if (w := check(p))]
    if bad:
        fail(
            "BLOCKED by the forbidden-paths gate (RULES.md, rule 1):\n"
            + "\n".join(f"  {p}: {w}" for p, w in bad)
        )
    print(f"forbidden_paths: ok ({len(files)} files)")


if __name__ == "__main__":
    main(sys.argv)
