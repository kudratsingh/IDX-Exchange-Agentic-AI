"""Relink Markdown after the AG-A11 docs/ moves (2026-11-12). Moves nothing itself.

Rewrites relative links to moved files and `docs/OLD` path text in current docs only.
Idempotent: a correct link or new path is left alone. `--dry-run` prints a diff.
"""

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# New folder -> the docs moved into it. Folders change; basenames do not.
FOLDERS = {
    "releases": (
        "ACCEPTANCE_MATRIX.md",
        "ACTIVATION_HANDOFF.md",
        "ADDITIONAL_CAPABILITIES.md",
        "BASELINE_ACCEPTANCE.md",
        "PROVIDER_HANDOFF.md",
        "RELEASE_WO017_ANALYSIS.md",
        "RELEASE_WO021_SEARCH.md",
    ),
    "whatsapp": (
        "CHART_DELIVERY.md",
        "WHATSAPP_CLOUD_API_ELIGIBILITY.md",
        "WHATSAPP_TRANSPORT_RECOMMENDATION.md",
    ),
    "enrichment": (
        "ENRICHMENT_DESIGN.md",
        "ENRICHMENT_CARRIED_EVIDENCE.md",
        "ENRICHMENT_DEV_RESULTS.md",
        "ENRICHMENT_DEV3_RESULTS.md",
        "ENRICHMENT_HELDOUT_RESULTS.md",
        "ENRICHMENT_OMISSION_PILOT.md",
        "ENRICHMENT_OMISSION_PILOT_V2.md",
        "ENRICHMENT_OVERLAP_DEV.md",
        "ENRICHMENT_REFRESH_PREFLIGHT.md",
        "ENRICHMENT_SYNTHETIC_EXPERIMENT.md",
        "ENRICHMENT_V2_DEV_RESULTS.md",
        "ENRICHMENT_V21_DEV_RESULTS.md",
    ),
}
# Old path -> new path, both from the repository root.
MOVES = {f"docs/{n}": f"docs/{d}/{n}" for d, names in FOLDERS.items() for n in names}
OLD_OF = {new: old for old, new in MOVES.items()}

# Private folders are never read. Link targets are fixed everywhere else.
SKIP_TOP = {"data", "context", "coordination", "worktrees", "node_modules"}

# Never written: the append-only log and the pinned top-level enrichment files.
NEVER_WRITE = re.compile(r"^docs/(EVIDENCE_LOG\.md|ENRICHMENT_[^/]+)$")

# Path text is kept in these (records, frozen or sealed files, and the move table).
TEXT_EXEMPT_PREFIXES = (
    "work_orders/",
    "docs/adrs/",
    "docs/enrichment/",
    "docs/ENRICHMENT_",
)
TEXT_EXEMPT = {
    "docs/EVIDENCE_LOG.md",
    "docs/STATUS_HISTORY.md",
    "docs/README.md",
    "docs/releases/ACCEPTANCE_MATRIX.md",
}
# Dated record sections inside an otherwise current doc (heading prefixes).
RECORD_HEADINGS = {
    "docs/releases/ACTIVATION_HANDOFF.md": (
        "## 10.",
        "## 11.",
        "## Decided",
        "## Appendix",
    ),
}

LINK = re.compile(r"(?<!!)(\[[^\]]*\]\()([^)\s]+)(\))")
SHA = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")
PR_CITE = re.compile(r"#\d+['’]s\b|\b(?:at|on|from|in|up to) #\d+\b")
OLD_TEXT = re.compile(
    r"(?<![\w/.-])((?:\.\./)*)(docs/(?:"
    + "|".join(re.escape(p[len("docs/") :]) for p in MOVES)
    + r"))(?![\w.-]*[\w])"
)


def tracked_md():
    """Return tracked .md paths (repo-relative), skipping the private folders."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    keep = [p for p in out if p.split("/")[0] not in SKIP_TOP]
    return [p for p in keep if not NEVER_WRITE.match(p)]


def fix_link(src, target):
    """Return the corrected link target for `src`, or `target` when it is fine."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
        return target
    path, hash_, frag = target.partition("#")
    here = os.path.dirname(src)
    if os.path.exists(ROOT / os.path.normpath(os.path.join(here, path))):
        return target
    old_here = os.path.dirname(OLD_OF.get(src, src))
    resolved = os.path.normpath(os.path.join(old_here, path))
    resolved = MOVES.get(resolved, resolved)
    if not (ROOT / resolved).exists():
        return target
    new = os.path.relpath(resolved, here or ".")
    return new + (hash_ + frag if hash_ else "")


def rewrite(src, text):
    """Return `text` with links fixed and, where allowed, old path text updated."""
    text_ok = src.endswith(".md") and not (
        src in TEXT_EXEMPT or src.startswith(TEXT_EXEMPT_PREFIXES)
    )
    records = RECORD_HEADINGS.get(src, ())
    out, fence, verbatim, in_record, prev, para_dated = (
        [],
        False,
        False,
        False,
        "",
        False,
    )
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            fence = not fence
        if "<!-- BEGIN verbatim" in line:
            verbatim = True
        if line.startswith("## "):
            in_record = line.startswith(records) if records else False
        if not line.strip():
            para_dated = False
        elif stripped.startswith("**Update of "):
            para_dated = True
        if not fence and not verbatim:
            line = LINK.sub(lambda m: m[1] + fix_link(src, m[2]) + m[3], line)
        held = verbatim or in_record or para_dated
        pinned = SHA.search(line) or SHA.search(prev) or PR_CITE.search(line)
        if text_ok and not held and not pinned:
            line = OLD_TEXT.sub(lambda m: m[1] + MOVES[m[2]], line)
        if "<!-- END verbatim" in line:
            verbatim = False
        out.append(line)
        prev = line
    return "".join(out)


def main(argv):
    """Rewrite tracked Markdown in place, or print the diff with --dry-run."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print the diff only")
    args = ap.parse_args(argv)
    changed = 0
    for src in tracked_md():
        before = (ROOT / src).read_text(encoding="utf-8")
        after = rewrite(src, before)
        if after == before:
            continue
        changed += 1
        if args.dry_run:
            sys.stdout.writelines(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    f"a/{src}",
                    f"b/{src}",
                )
            )
        else:
            (ROOT / src).write_text(after, encoding="utf-8")
    verb = "would change" if args.dry_run else "changed"
    print(f"docs_relink: {verb} {changed} file(s)")


if __name__ == "__main__":
    main(sys.argv[1:])
