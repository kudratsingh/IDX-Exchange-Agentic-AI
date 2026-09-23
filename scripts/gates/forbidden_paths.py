"""Gate: files that must never be tracked (RULES.md, rule 1)."""

import re
import sys

from gatelib import fail, target_files

ALLOWED_SQL_DIRS = ("scripts/migrations/", "tests/fixtures/")
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
    """Return a reason string if the path is forbidden, else None."""
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
