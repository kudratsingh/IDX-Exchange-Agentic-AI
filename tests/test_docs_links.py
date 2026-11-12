"""Docs layout checks after the AG-A11 moves (2026-11-12). No network, no model.

(a) relative Markdown links, images, reference definitions and HTML hrefs resolve, with
their #anchors; (b) docs/README.md lists every docs/**/*.md; (c) no old path from the
move table returns outside the records that scripts/docs_relink.py names.
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

# Records keep old paths as written (docs/README.md says which and why). The rules
# live in scripts/docs_relink.py so the relink and this check cannot disagree; the two
# files below hold the move map itself.
RECORD_FILES = docs_relink.TEXT_EXEMPT | {
    "scripts/docs_relink.py",
    "tests/test_docs_links.py",
}
RECORD_PREFIXES = docs_relink.TEXT_EXEMPT_PREFIXES

_TITLE = r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?"""
# Inline links and images: [text](target "title"), ![alt](<a target>), and so on.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^)\s]+))" + _TITLE + r"\s*\)")
# Reference definitions, [label]: target (footnotes, [^1]:, are not links).
REF_DEF = re.compile(r"^\s{0,3}\[(?!\^)[^\]]+\]:\s*(?:<([^>]+)>|(\S+))")
HREF = re.compile(r"""<(?:a|img)\s[^>]*?(?:href|src)=["']([^"']+)["']""")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
ANCHOR_TAG = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")
# A moved path, bare or behind ./ or ../ segments. A longer path that ends in one
# (foo/docs/X) is a different path and does not count.
OLD_PATH = re.compile(
    r"(?<![\w/.-])(?:\.\.?/)*(" + "|".join(re.escape(p) for p in MOVED) + r")(?![\w-])"
)


def _targets(line):
    """Every link target on a Markdown line: inline, image, reference or HTML."""
    found = [a or b for a, b in LINK.findall(line)]
    found += [a or b for a, b in REF_DEF.findall(line)]
    return found + HREF.findall(line)


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
    """Each relative link target names an existing path and, if any, a real anchor."""
    bad = []
    for rel in _tracked("*.md"):
        src = ROOT / rel
        for n, line in _prose(src):
            for target in _targets(line):
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
        for t in _targets(line)
    }
    docs = [p for p in _tracked("docs/") if p.endswith(".md") and p != "docs/README.md"]
    missing = [p for p in docs if (ROOT / p).resolve() not in linked]
    assert not missing, "not in docs/README.md: " + ", ".join(missing)


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
            held = docs_relink.record_lines(rel, lines) if held is None else held
            if n not in held:
                found.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not found, "old paths (see docs/README.md):\n" + "\n".join(found)


@pytest.mark.parametrize(
    "line",
    [
        "See docs/CHART_DELIVERY.md.",
        "follow ../docs/BASELINE_ACCEPTANCE.md.",
        "# see ../../docs/CHART_DELIVERY.md",
        "./docs/CHART_DELIVERY.md",
        "(`docs/ENRICHMENT_DESIGN.md` §2)",
    ],
)
def test_c_old_path_forms_are_seen(line):
    """Bare, ./ and ../ forms of an old path all count."""
    assert OLD_PATH.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "docs/whatsapp/CHART_DELIVERY.md",
        "../docs/releases/BASELINE_ACCEPTANCE.md",
        "foo/docs/CHART_DELIVERY.md",
        "docs/CHART_DELIVERY.md-draft",
    ],
)
def test_c_new_and_other_paths_are_not_old(line):
    """New paths, and other paths that merely end in an old one, do not count."""
    assert not OLD_PATH.search(line)


def test_c_quote_and_update_rules_hold_only_in_the_handoff():
    """Verbatim quotes and **Update of** paragraphs are records only in the handoff,
    as docs/README.md says; elsewhere an old path in them is still reported."""
    old = "See docs/CHART_DELIVERY.md."
    quote = ["x", "<!-- BEGIN verbatim -->", old, "<!-- END verbatim -->"]
    update = ["x", "**Update of 2026-11-12.** " + old]
    assert docs_relink.record_lines("docs/STATUS.md", quote) == set()
    assert docs_relink.record_lines("docs/STATUS.md", update) == set()
    handoff = docs_relink.HANDOFF
    assert docs_relink.record_lines(handoff, quote) == {2, 3, 4}
    assert docs_relink.record_lines(handoff, update) == {2}


def test_c_a_verbatim_quote_with_no_end_fails():
    """A BEGIN verbatim with no END is an error in any file, not a held rest of file."""
    for rel in ("docs/STATUS.md", docs_relink.HANDOFF):
        with pytest.raises(ValueError, match="no END"):
            docs_relink.record_lines(rel, ["<!-- BEGIN verbatim -->", "x", "later"])


def test_c_every_markdown_file_closes_its_verbatim_quotes():
    """Each <!-- BEGIN verbatim has its END, so a lost marker cannot hold a file."""
    bad = []
    for rel in _tracked("*.md"):
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        try:
            docs_relink.record_lines(rel, lines)
        except ValueError as exc:
            bad.append(str(exc))
    assert not bad, "\n".join(bad)


def test_c_the_matrix_holds_only_its_original_body():
    """ACCEPTANCE_MATRIX's current pointer and dated updates are checked, its 2026-11-02
    body is a record."""
    rel = "docs/releases/ACCEPTANCE_MATRIX.md"
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    held = docs_relink.record_lines(rel, lines)
    numbered = list(enumerate(lines, 1))
    start = next(n for n, x in numbered if x.startswith("Recorded 2026-11-02"))
    end = next(n for n, x in numbered if x.startswith("## Readiness update"))
    assert held == set(range(start, end))
    assert rel not in RECORD_FILES


def test_c_each_pinned_line_is_one_line_with_an_old_path():
    """Every pin still names exactly one line, and that line has an old path, so the
    list cannot go stale or grow into a blanket exemption."""
    for rel, pins in docs_relink.PINNED.items():
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        for pin in pins:
            hits = [x for x in lines if pin in x]
            assert len(hits) == 1, f"{rel}: {pin!r} on {len(hits)} lines"
            assert OLD_PATH.search(hits[0]), f"{rel}: {pin!r} has no old path"


def test_c_the_relink_has_nothing_left_to_change():
    """`scripts/docs_relink.py --dry-run` would change no file (README's check)."""
    changed = [
        src
        for src in docs_relink.tracked_md()
        if docs_relink.rewrite(src, (ROOT / src).read_text(encoding="utf-8"))
        != (ROOT / src).read_text(encoding="utf-8")
    ]
    assert not changed, ", ".join(changed)


def test_c_the_relink_leaves_fenced_path_text_alone():
    """Path text in a fenced block is output or code as recorded, never rewritten."""
    text = "```\nSee docs/CHART_DELIVERY.md.\n```\nSee docs/CHART_DELIVERY.md.\n"
    out = docs_relink.rewrite("docs/STATUS.md", text)
    assert out.splitlines() == [
        "```",
        "See docs/CHART_DELIVERY.md.",
        "```",
        "See docs/whatsapp/CHART_DELIVERY.md.",
    ]


@pytest.mark.parametrize(
    "line, target",
    [
        ("[c](X.md 't')", "X.md"),
        ("[c](X.md (t))", "X.md"),
        ('[c](X.md "t")', "X.md"),
        ("[c](<X Y.md>)", "X Y.md"),
        ("![c](X.png)", "X.png"),
        ("[c]: X.md", "X.md"),
        ('<a href="X.md">c</a>', "X.md"),
    ],
)
def test_a_link_forms_are_all_read(line, target):
    """Single-quoted and parenthesised titles, angle targets, images, reference
    definitions and HTML hrefs are all checked, not only plain inline links."""
    assert _targets(line) == [target]


def test_a_footnotes_are_not_links():
    """A footnote definition is text, not a link target."""
    assert _targets("[^1]: Some note.") == []


@pytest.mark.parametrize("old", sorted(MOVED))
def test_c_the_index_maps_each_old_path(old):
    """The README's old->new table carries each moved path."""
    readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert f"| `{old}` | `{MOVED[old]}` |" in readme
