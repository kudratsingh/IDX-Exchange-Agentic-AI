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

HANDOFF = "docs/releases/ACTIVATION_HANDOFF.md"

# Path text is kept as written in these whole files: the logs, the move table, work
# orders, ADRs, the pinned top-level enrichment files and the moved enrichment results
# docs (ENRICHMENT_DESIGN.md is a current design doc, so it is not one of them).
TEXT_EXEMPT_PREFIXES = ("work_orders/", "docs/adrs/", "docs/ENRICHMENT_")
TEXT_EXEMPT = {
    "docs/EVIDENCE_LOG.md",
    "docs/STATUS_HISTORY.md",
    "docs/README.md",
    # Owner-approved template (D6); not edited without the owner's OK. Its comment keeps
    # the old docs/CHART_DELIVERY.md path; docs/README.md's move table maps it.
    "config/chart-prune.launchd.plist.proposal",
} | {
    f"docs/enrichment/{n}" for n in FOLDERS["enrichment"] if n != "ENRICHMENT_DESIGN.md"
}
# Dated record sections inside an otherwise current doc (heading prefixes).
RECORD_HEADINGS = {HANDOFF: ("## 10.", "## 11.", "## Decided", "## Appendix")}
# A record body inside a current doc: from the line starting with the first prefix
# (held) to the line starting with the second (not held, nor anything after it).
RECORD_RANGES = {
    "docs/releases/ACCEPTANCE_MATRIX.md": (
        "Recorded 2026-11-02 by WO-022",
        "## Readiness update",
    ),
}
# Files whose `<!-- BEGIN verbatim` quotes and `**Update of` paragraphs are records.
QUOTE_FILES = {HANDOFF}
# Single lines that cite a doc as it was at a commit or PR, each named by a substring
# that occurs on exactly one line of its file. Nothing else is pinned.
PINNED = {
    HANDOFF: (
        "The order is #148's (`docs/CHART_DELIVERY.md` §7, steps 1-3)",
        "#148's (`docs/CHART_DELIVERY.md` §7 at `ef3bb25`",
        "in them is `docs/CHART_DELIVERY.md`'s)",
        "acceptance check in docs/CHART_DELIVERY.md passes.",
        "Quoted verbatim from `docs/CHART_DELIVERY.md` §7 at #148 `ef3bb25`",
        'are `docs/CHART_DELIVERY.md`\'s; "this PR"',
        "as #148's `docs/CHART_DELIVERY.md` §7 (quoted in §9)",
    ),
}

LINK = re.compile(r"(?<!!)(\[[^\]]*\]\()([^)\s]+)(\))")
OLD_TEXT = re.compile(
    r"(?<![\w/.-])((?:\.\.?/)*)(docs/(?:"
    + "|".join(re.escape(p[len("docs/") :]) for p in MOVES)
    + r"))(?![\w.-]*[\w])"
)


def record_lines(src, lines):
    """Return the 1-based line numbers of `lines` (the file `src`) that are records.

    Raises ValueError when a `<!-- BEGIN verbatim` has no END, or a record range in
    RECORD_RANGES is missing its start or end line.
    """
    headings = RECORD_HEADINGS.get(src, ())
    quotes = src in QUOTE_FILES
    pins = PINNED.get(src, ())
    start, end = RECORD_RANGES.get(src, (None, None))
    held, verbatim, section, dated, in_range = set(), 0, False, False, False
    seen_start = seen_end = False
    for n, line in enumerate(lines, 1):
        if "<!-- BEGIN verbatim" in line:
            if verbatim:
                raise ValueError(f"{src}:{n}: BEGIN verbatim inside another")
            verbatim = n
        if line.startswith("## "):
            section = bool(headings) and line.startswith(headings)
        if not line.strip():
            dated = False
        elif line.lstrip().startswith("**Update of "):
            dated = True
        if start and line.startswith(start):
            in_range, seen_start = True, True
        if end and in_range and line.startswith(end):
            in_range, seen_end = False, True
        if (
            (quotes and (verbatim or dated))
            or section
            or in_range
            or any(p in line for p in pins)
        ):
            held.add(n)
        if "<!-- END verbatim" in line:
            if not verbatim:
                raise ValueError(f"{src}:{n}: END verbatim with no BEGIN")
            verbatim = 0
    if verbatim:
        raise ValueError(f"{src}:{verbatim}: BEGIN verbatim with no END")
    if start and not (seen_start and seen_end):
        raise ValueError(f"{src}: record range {start!r} to {end!r} not found")
    return held


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
    """Return `text` with links fixed and, where allowed, old path text updated.

    Path text is never changed inside fenced blocks, records or pinned lines.
    """
    text_ok = src.endswith(".md") and not (
        src in TEXT_EXEMPT or src.startswith(TEXT_EXEMPT_PREFIXES)
    )
    held = record_lines(src, text.splitlines()) if text_ok else set()
    out, fence, verbatim = [], False, False
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        if "<!-- BEGIN verbatim" in line:
            verbatim = True
        if not fence and not verbatim:
            line = LINK.sub(lambda m: m[1] + fix_link(src, m[2]) + m[3], line)
        if text_ok and not fence and n not in held:
            line = OLD_TEXT.sub(lambda m: m[1] + MOVES[m[2]], line)
        if "<!-- END verbatim" in line:
            verbatim = False
        out.append(line)
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
