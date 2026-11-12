"""Docs layout checks after the AG-A11 moves (2026-11-12). No network, no model.

(a) relative Markdown links and #anchors resolve; (b) docs/README.md lists every
docs/**/*.md; (c) no old path from the move table returns outside the records.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docs_relink  # noqa: E402

PRIVATE = {"data", "context", "coordination", "worktrees", "node_modules"}

# The 2026-11-12 move table (docs/README.md "Moved on 2026-11-12"), old -> new.
MOVED = {
    "docs/ACCEPTANCE_MATRIX.md": "docs/releases/ACCEPTANCE_MATRIX.md",
    "docs/ACTIVATION_HANDOFF.md": "docs/releases/ACTIVATION_HANDOFF.md",
    "docs/ADDITIONAL_CAPABILITIES.md": "docs/releases/ADDITIONAL_CAPABILITIES.md",
    "docs/BASELINE_ACCEPTANCE.md": "docs/releases/BASELINE_ACCEPTANCE.md",
    "docs/PROVIDER_HANDOFF.md": "docs/releases/PROVIDER_HANDOFF.md",
    "docs/RELEASE_WO017_ANALYSIS.md": "docs/releases/RELEASE_WO017_ANALYSIS.md",
    "docs/RELEASE_WO021_SEARCH.md": "docs/releases/RELEASE_WO021_SEARCH.md",
    "docs/CHART_DELIVERY.md": "docs/whatsapp/CHART_DELIVERY.md",
    "docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md": (
        "docs/whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md"
    ),
    "docs/WHATSAPP_TRANSPORT_RECOMMENDATION.md": (
        "docs/whatsapp/WHATSAPP_TRANSPORT_RECOMMENDATION.md"
    ),
    "docs/ENRICHMENT_DESIGN.md": "docs/enrichment/ENRICHMENT_DESIGN.md",
    "docs/ENRICHMENT_CARRIED_EVIDENCE.md": (
        "docs/enrichment/ENRICHMENT_CARRIED_EVIDENCE.md"
    ),
    "docs/ENRICHMENT_DEV_RESULTS.md": "docs/enrichment/ENRICHMENT_DEV_RESULTS.md",
    "docs/ENRICHMENT_DEV3_RESULTS.md": "docs/enrichment/ENRICHMENT_DEV3_RESULTS.md",
    "docs/ENRICHMENT_HELDOUT_RESULTS.md": (
        "docs/enrichment/ENRICHMENT_HELDOUT_RESULTS.md"
    ),
    "docs/ENRICHMENT_OMISSION_PILOT.md": (
        "docs/enrichment/ENRICHMENT_OMISSION_PILOT.md"
    ),
    "docs/ENRICHMENT_OMISSION_PILOT_V2.md": (
        "docs/enrichment/ENRICHMENT_OMISSION_PILOT_V2.md"
    ),
    "docs/ENRICHMENT_OVERLAP_DEV.md": "docs/enrichment/ENRICHMENT_OVERLAP_DEV.md",
    "docs/ENRICHMENT_REFRESH_PREFLIGHT.md": (
        "docs/enrichment/ENRICHMENT_REFRESH_PREFLIGHT.md"
    ),
    "docs/ENRICHMENT_SYNTHETIC_EXPERIMENT.md": (
        "docs/enrichment/ENRICHMENT_SYNTHETIC_EXPERIMENT.md"
    ),
    "docs/ENRICHMENT_V2_DEV_RESULTS.md": (
        "docs/enrichment/ENRICHMENT_V2_DEV_RESULTS.md"
    ),
    "docs/ENRICHMENT_V21_DEV_RESULTS.md": (
        "docs/enrichment/ENRICHMENT_V21_DEV_RESULTS.md"
    ),
}

# Records that keep old paths as written (docs/README.md says which and why).
RECORD_FILES = {
    "docs/EVIDENCE_LOG.md",
    "docs/STATUS_HISTORY.md",
    "docs/README.md",
    "docs/releases/ACCEPTANCE_MATRIX.md",
    "config/chart-prune.launchd.plist.proposal",
    "scripts/docs_relink.py",
    "tests/test_docs_links.py",
}
RECORD_PREFIXES = ("work_orders/", "docs/adrs/", "docs/enrichment/", "docs/ENRICHMENT_")
# Dated record sections inside ACTIVATION_HANDOFF.md, by heading prefix.
RECORD_HEADINGS = ("## 10.", "## 11.", "## Decided", "## Appendix")

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
ANCHOR_TAG = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")
SHA = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")
PR_CITE = re.compile(r"#\d+['’]s\b|\b(?:at|on|from|in|up to) #\d+\b")
OLD_PATH = re.compile(
    r"(?<![\w/.-])(" + "|".join(re.escape(p) for p in MOVED) + r")(?![\w-])"
)


def _tracked(pattern=None):
    """Tracked repo-relative paths outside the private folders."""
    args = ["git", "ls-files"] + ([pattern] if pattern else [])
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split() if p.split("/")[0] not in PRIVATE]


def _slug(text):
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").strip().lower()
    return "".join(
        "-" if ch == " " else ch for ch in text if ch.isalnum() or ch in "-_ "
    )


def _prose(path):
    """Yield (line number, line) outside fenced code blocks."""
    fence = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            yield n, line


_ANCHORS = {}


def _anchors(path):
    """Every heading slug (with -1, -2 for repeats) and <a id> in a Markdown file."""
    cache = _ANCHORS
    if path not in cache:
        ids, seen = set(), {}
        for _, line in _prose(path):
            ids.update(ANCHOR_TAG.findall(line))
            m = HEADING.match(line)
            if m:
                s = _slug(m[2])
                ids.add(s if s not in seen else f"{s}-{seen[s]}")
                seen[s] = seen.get(s, 0) + 1
        cache[path] = ids
    return cache[path]


def test_a_every_relative_link_and_anchor_resolves():
    """Each relative Markdown link names an existing path and, if any, a real anchor."""
    bad = []
    for rel in _tracked("*.md"):
        src = ROOT / rel
        for n, line in _prose(src):
            for target in LINK.findall(line):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    continue
                path, _, frag = target.partition("#")
                dest = (src.parent / path).resolve() if path else src
                if not dest.exists():
                    bad.append(f"{rel}:{n} -> {target} (no such path)")
                elif frag and dest.suffix == ".md" and frag not in _anchors(dest):
                    bad.append(f"{rel}:{n} -> {target} (no such anchor)")
    assert not bad, "\n".join(bad)


def test_b_the_docs_index_lists_every_markdown_doc():
    """docs/README.md links every docs/**/*.md (JSON freezes are listed by hand)."""
    index = ROOT / "docs" / "README.md"
    linked = {
        (index.parent / t.partition("#")[0]).resolve()
        for _, line in _prose(index)
        for t in LINK.findall(line)
    }
    docs = [p for p in _tracked("docs/") if p.endswith(".md") and p != "docs/README.md"]
    missing = [p for p in docs if (ROOT / p).resolve() not in linked]
    assert not missing, "not in docs/README.md: " + ", ".join(missing)


def _record_lines(rel, lines):
    """Line numbers in `rel` that are records: verbatim quotes and dated sections."""
    held, verbatim, section, dated = set(), False, False, False
    for n, line in enumerate(lines, 1):
        if "<!-- BEGIN verbatim" in line:
            verbatim = True
        if line.startswith("## "):
            section = rel.endswith("ACTIVATION_HANDOFF.md") and line.startswith(
                RECORD_HEADINGS
            )
        if not line.strip():
            dated = False
        elif line.lstrip().startswith("**Update of "):
            dated = True
        if verbatim or section or dated:
            held.add(n)
        if "<!-- END verbatim" in line:
            verbatim = False
    return held


def test_c_no_old_moved_path_outside_the_records():
    """No tracked text names a pre-move docs/ path, except records and pinned lines."""
    assert MOVED == docs_relink.MOVES
    assert all((ROOT / new).exists() for new in MOVED.values())
    assert not any((ROOT / old).exists() for old in MOVED)
    found = []
    for rel in _tracked():
        if rel in RECORD_FILES or rel.startswith(RECORD_PREFIXES):
            continue
        try:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        held = None
        for n, line in enumerate(lines, 1):
            if not OLD_PATH.search(line):
                continue
            prev = lines[n - 2] if n > 1 else ""
            if SHA.search(line) or SHA.search(prev) or PR_CITE.search(line):
                continue
            held = _record_lines(rel, lines) if held is None else held
            if n not in held:
                found.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not found, "old paths (see docs/README.md):\n" + "\n".join(found)


@pytest.mark.parametrize("old", sorted(MOVED))
def test_c_the_index_maps_each_old_path(old):
    """The README's old->new table carries each moved path."""
    readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert f"| `{old}` | `{MOVED[old]}` |" in readme
