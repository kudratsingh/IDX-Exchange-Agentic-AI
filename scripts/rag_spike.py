"""WO-012 early-start spike: extraction, chunking, exact names, BM25, and index size.

Read-only, no database, no provider, nothing written. Prints counts, scores, field
names, and section positions only, never PDF text. The PDFs: sources.txt's
data/knowledge/ lines under --docs-root; run with --docs-root <checkout>."""

from __future__ import annotations

import argparse
import logging
import math
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as scripts/market_spike.py does.
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.safety.columns import AGENT_CONTACT, ALLOWLIST, DENYLIST  # noqa: E402
from idx_agent.semantic.embedder import HashingEmbedder, prepare_text  # noqa: E402

SOURCES = ROOT / "scripts" / "gates" / "sources.txt"
SCHEMA_NOTES = ROOT / "docs" / "data" / "schema_notes.md"
CHARS_PER_TOKEN = 4  # an estimate, not a tokenizer count
MAX_CHUNK_CHARS = 4000  # prepare_text's cut in semantic/embedder.py
PART_WORDS = 350  # Primer sections over this split into parts (WO-012)
DIMS = (1536, 512)
FLOAT32_BYTES = 4
HASH_DIMS = (64, 1536)
TOP = 3
PROTECTED = DENYLIST | AGENT_CONTACT
# The profiling run's name patterns for contact columns, plus the deny-list's themes.
PERSONISH = re.compile(r"Agent|Office|Owner|Occupant|Showing|LockBox|Access|^L[AO]\d_")
CONTACTISH = re.compile(r"Name|Email|Phone|Fax|Url|Address")

# Field-reference layout, measured by this spike (structure only): a field entry
# begins with the field name, then its data type (or a lookup name, then "Enum",
# sometimes on the next line), or a link to another resource.
IDENT = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
CAMEL = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+$")
TYPES = frozenset(
    {"String", "Decimal", "Boolean", "DateTime", "DateTimeOffset", "Date", "Timestamp"}
    | {"Int16", "Int32", "Int64", "Integer", "Number", "Double"}
)
LOOKUP_MARK = "Enum"
RESOURCES = frozenset({"Member", "Office", "Media", "Room", "Teams", "OpenHouse"})
# Prose layout: a numbered heading is short, unpunctuated, and one past the last.
NUMBERED = re.compile(r"^(\d+)\.?\s+(\S.*)$")
HEADING_MAX_WORDS = 10
ALL_CAPS = re.compile(r"^[A-Z0-9 &/,:()\-]{4,}$")
NAME_COLON = re.compile(r"^[A-Z][A-Za-z0-9_]+\s*:\s+\S")
WORD = re.compile(r"[A-Za-z0-9]+")
CAMEL_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
RATIO_TERMS = ("ratio", "sale-to-list", "sale to list", "list-to-close")


def names_ratio(heading: str) -> bool:
    """A heading names the ratio: a ratio term, or both "list" and "price"."""
    h = heading.lower()
    words = set(re.findall(r"[a-z]+", h))
    return any(t in h for t in RATIO_TERMS) or {"list", "price"} <= words


BACK_ON_MARKET = "back on market"

# Own-words alias table (the WO-012 draft): a phrase in the question -> a chunk key.
# "@ratio" stands for the Primer sections whose heading names the ratio.
ALIASES = {
    "dom": "trestle#DaysOnMarket",
    "days on market": "trestle#DaysOnMarket",
    "cdom": "trestle#CumulativeDaysOnMarket",
    "sold table": "schema_notes#summary:california_sold",
    "closed sales table": "schema_notes#summary:california_sold",
    "california_sold": "schema_notes#summary:california_sold",
    "active table": "schema_notes#summary:rets_property",
    "listings table": "schema_notes#summary:rets_property",
    "rets_property": "schema_notes#summary:rets_property",
    "list-to-close": "@ratio",
    "list to close": "@ratio",
    "sale-to-list": "@ratio",
    "sale to list": "@ratio",
    "close-to-list": "@ratio",
}
STOPWORDS = frozenset(
    "a an and are as at be by do does for from has have how i in is it its me of on or"
    " the this to was what when which who why with you".split()
)

# Questions, own words. kind: set (Week 8), para (paraphrase), seed (eval seeds), off.
# expect: chunk keys that answer it ("@ratio" and "@bom" are resolved at run time).
QUESTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Q1", "set", "what does DOM mean", ("trestle#DaysOnMarket",)),
    (
        "Q2",
        "set",
        "which columns does the sold table have",
        ("schema_notes#summary:california_sold", "schema_notes#s2"),
    ),
    ("Q3", "set", "what is the list-to-close ratio", ("@ratio",)),
    ("P1", "para", "how long was the house up for sale", ("trestle#DaysOnMarket",)),
    ("P2", "para", "what days on market measures", ("trestle#DaysOnMarket",)),
    (
        "P3",
        "para",
        "what fields are stored for closed sales",
        ("schema_notes#summary:california_sold", "schema_notes#s2"),
    ),
    (
        "P4",
        "para",
        "how does the final sale price compare with the asking price",
        ("@ratio",),
    ),
    ("P5", "para", "did homes sell over asking on average", ("@ratio",)),
    (
        "S1",
        "seed",
        "what does BathroomsTotalInteger count",
        ("trestle#BathroomsTotalInteger",),
    ),
    ("S2", "seed", "what does back on market mean", ("@bom",)),
    ("O1", "off", "will it rain in paris tomorrow", ()),
    ("O2", "off", "recommend a pizza place for dinner", ()),
)


@dataclass
class Chunk:
    source: str  # trestle | primer | schema_notes
    key: str  # field name, s<N>[.p<K>], or summary:<table>
    text: str  # in memory only; never printed or written
    page: int | None = None

    @property
    def cid(self) -> str:
        return f"{self.source}#{self.key}"


# ----- helpers -----------------------------------------------------------------------
def pct(values: Sequence[float], q: float) -> float:
    """Lower nearest-rank quantile; 0 for an empty list."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[math.floor(q * (len(ordered) - 1))]


def table(title: str, header: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    """Print a fixed-width table of numbers and identifiers."""
    cells = [[str(c) for c in header]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    print(f"\n## {title}")
    for i, r in enumerate(cells):
        print("  ".join(c.rjust(w) for c, w in zip(r, widths, strict=True)))
        if i == 0:
            print("  ".join("-" * w for w in widths))


def pdf_paths(docs_root: Path) -> dict[str, Path]:
    """trestle/primer -> path, from the data/knowledge/ lines of sources.txt."""
    found: dict[str, Path] = {}
    for line in SOURCES.read_text().splitlines():
        line = line.strip()
        if not line.startswith("data/knowledge/"):
            continue
        doc = "trestle" if "Trestle" in line else "primer" if "Primer" in line else ""
        if doc:
            found[doc] = docs_root / line
    missing = [str(p) for p in found.values() if not p.exists()]
    if len(found) != 2 or missing:
        sys.exit(f"missing PDFs (expected two under data/knowledge/): {missing}")
    return found


def read_pages(path: Path) -> tuple[list[str], list[int]]:
    """Page texts (never printed) and, per page, how many images it holds."""
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(path))
    texts, images = [], []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
        try:
            images.append(len(page.images))
        except Exception:  # an unreadable image list counts as none
            images.append(0)
    return texts, images


def page_lines(pages: Sequence[str]) -> tuple[list[tuple[int, str]], int]:
    """(page number, line) for every non-blank line, minus running headers/footers:
    a line (digits masked) on at least half the pages. Returns the removed count."""
    per_page = [
        {re.sub(r"\d+", "#", ln.strip()) for ln in p.splitlines() if ln.strip()}
        for p in pages
    ]
    seen = Counter(s for page in per_page for s in page)
    running = {s for s, n in seen.items() if n >= max(3, len(pages) / 2)}
    out, removed = [], 0
    for number, text in enumerate(pages, start=1):
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            if re.sub(r"\d+", "#", ln) in running:
                removed += 1
                continue
            out.append((number, ln))
    return out, removed


def is_field_start(tokens: list[str], next_tokens: list[str]) -> bool:
    """A field entry begins: name + type; name + lookup + Enum (Enum possibly on the
    next line); name + resource (a link); or a lone name whose next line begins with
    a type (a wrapped entry)."""
    if not tokens or not IDENT.match(tokens[0]):
        return False
    t = [x.rstrip(",") for x in tokens]
    nxt0 = next_tokens[0].rstrip(",") if next_tokens else ""
    if len(t) > 1 and t[1] in TYPES:
        return True
    if len(t) > 2 and t[2] == LOOKUP_MARK:
        return True
    if len(t) == 2 and CAMEL.match(t[0]):
        if t[1] in RESOURCES or (CAMEL.match(t[1]) and nxt0 == LOOKUP_MARK):
            return True
    return len(t) == 1 and nxt0 in TYPES


def collapse(lines: Sequence[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


# ----- chunking ----------------------------------------------------------------------
def chunk_trestle(lines: list[tuple[int, str]]) -> tuple[list[Chunk], dict[str, int]]:
    """One chunk per field entry; lines before the first entry form a preamble chunk."""
    chunks: list[Chunk] = []
    stats = Counter()
    current: Chunk | None = None
    buf: list[str] = []
    pre: list[str] = []
    for i, (page, ln) in enumerate(lines):
        tokens = ln.split()
        nxt = lines[i + 1][1].split() if i + 1 < len(lines) else []
        if is_field_start(tokens, nxt):
            if current is not None:
                current.text = collapse(buf)
                chunks.append(current)
            current, buf = Chunk("trestle", tokens[0], "", page), [ln]
            stats["field_starts"] += 1
            continue
        if CAMEL.match(tokens[0]):
            # A camel-case name leading a line the rule did not take as an entry.
            stats["camel_lines_not_placed"] += 1
            if len(tokens) > 1 and tokens[1][:1].isupper():
                stats["suspect_unplaced"] += 1
        (buf if current is not None else pre).append(ln)
    if current is not None:
        current.text = collapse(buf)
        chunks.append(current)
    names = Counter(c.key for c in chunks)
    stats["duplicate_names"] = sum(1 for n in names.values() if n > 1)
    stats["preamble_lines"] = len(pre)
    if pre:
        chunks.insert(0, Chunk("trestle", "preamble", collapse(pre), 1))
    return chunks, dict(stats)


def split_parts(key: str, lines: list[str], page: int) -> list[Chunk]:
    """A section as one chunk, or parts of at most PART_WORDS words by line."""
    if len(collapse(lines).split()) <= PART_WORDS:
        return [Chunk("primer", key, collapse(lines), page)]
    parts, buf, words = [], [], 0
    for ln in lines:
        n = len(ln.split())
        if buf and words + n > PART_WORDS:
            parts.append(buf)
            buf, words = [], 0
        buf.append(ln)
        words += n
    parts.append(buf)
    return [
        Chunk("primer", f"{key}.p{k}", collapse(p), page)
        for k, p in enumerate(parts, 1)
    ]


def primer_sections(
    lines: list[tuple[int, str]],
) -> tuple[list[tuple[int, str, list[str], int]], int]:
    """(number, heading, body lines, page) per section; 0 is the preamble. Also the
    count of numbered lines that were not headings (list items inside a section)."""
    sections = [(0, "", [], 1)]
    not_heading = 0
    for page, ln in lines:
        m = NUMBERED.match(ln)
        if m:
            n, rest = int(m.group(1)), m.group(2)
            is_heading = (
                n == sections[-1][0] + 1
                and len(rest.split()) <= HEADING_MAX_WORDS
                and ln[-1] not in ".,;:"
            )
            if is_heading:
                sections.append((n, rest, [], page))
                continue
            not_heading += 1
        sections[-1][2].append(ln)
    if not sections[0][2]:
        sections.pop(0)
    return sections, not_heading


def chunk_primer(sections) -> list[Chunk]:
    chunks: list[Chunk] = []
    for n, heading, body, page in sections:
        chunks += split_parts(f"s{n}", [heading, *body] if heading else body, page)
    return chunks


def chunk_schema_notes(text: str) -> tuple[list[Chunk], dict[str, int]]:
    """One chunk per '## ' section (s<N> for numbered, s<pos>x otherwise) and one
    summary per table: section 2's column names minus every protected name."""
    chunks: list[Chunk] = []
    blocks: list[tuple[str, list[str]]] = [("", [])]
    for ln in text.splitlines():
        if ln.startswith("## "):
            blocks.append((ln[3:].strip(), [ln]))
        else:
            blocks[-1][1].append(ln)
    names_by_table: dict[str, list[str]] = {}
    for pos, (heading, body) in enumerate(blocks):
        m = re.match(r"^(\d+)", heading)
        key = f"s{m.group(1)}" if m else f"x{pos}"
        chunks.append(Chunk("schema_notes", key, collapse(body)))
        if key == "s2":
            table_name = ""
            for ln in body:
                sub = re.match(r"^### (\w+)", ln)
                if sub:
                    table_name = sub.group(1)
                    names_by_table[table_name] = []
                cell = re.match(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|", ln)
                if table_name and cell and cell.group(1) != "column":
                    names_by_table[table_name].append(cell.group(1))
    stats: dict[str, int] = {}
    for tbl, names in names_by_table.items():
        keep = [n for n in names if n not in PROTECTED]
        dropped = len(names) - len(keep)
        line = f"{dropped} more columns hold agent or office contact details"
        chunks.append(
            Chunk(
                "schema_notes",
                f"summary:{tbl}",
                f"{tbl} table columns: {', '.join(keep)}. {line} and are never shown.",
            )
        )
        stats[f"{tbl}_columns"] = len(names)
        stats[f"{tbl}_kept"] = len(keep)
    return chunks, stats


# ----- ranking -----------------------------------------------------------------------
def tokens(text: str) -> list[str]:
    """Lowercased words; a camel-case name also yields its parts (DaysOnMarket ->
    daysonmarket, days, on, market). Stopwords dropped."""
    out: list[str] = []
    for w in WORD.findall(text):
        out.append(w.lower())
        parts = CAMEL_PART.findall(w)
        if len(parts) > 1:
            out += [p.lower() for p in parts]
    return [t for t in out if t not in STOPWORDS]


class BM25:
    """Okapi BM25 over token lists; idf = ln((N - df + 0.5) / (df + 0.5) + 1)."""

    def __init__(self, docs: Sequence[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, dl in zip(self.tf, self.len, strict=True):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * dl / self.avg)
            for t in query:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out


def ranked(scores: Sequence[float]) -> list[int]:
    """Indices by score, high first; ties by position (source order)."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def best_rank(order: list[int], chunks: list[Chunk], expect: set[str]) -> int | str:
    """1-based rank of the first chunk whose id (or section, ignoring the part) is
    expected; '-' when none is."""
    for r, i in enumerate(order, 1):
        cid = chunks[i].cid
        if cid in expect or cid.split(".p")[0] in expect:
            return r
    return "-"


def exact_hits(question: str, chunks: list[Chunk], ratio_ids: set[str]) -> list[str]:
    """Chunk ids the question names: a field name (any case) or an alias."""
    ids = {c.cid for c in chunks}
    by_lower = {c.key.lower(): c.cid for c in chunks if c.source == "trestle"}
    q = question.lower()
    hits: list[str] = []
    for w in re.findall(r"[a-z0-9_]+", q):
        if w in by_lower and by_lower[w] not in hits:
            hits.append(by_lower[w])
    for phrase, target in ALIASES.items():
        if re.search(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", q):
            for t in sorted(ratio_ids) if target == "@ratio" else [target]:
                if (t in ids or t.split(".p")[0] in ratio_ids) and t not in hits:
                    hits.append(t)
    return hits


# ----- main --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--docs-root",
        type=Path,
        default=ROOT,
        help="checkout whose data/knowledge/ holds the PDFs (default: this one)",
    )
    args = ap.parse_args()
    paths = pdf_paths(args.docs_root.resolve())

    # (a) extraction
    raw: dict[str, list[str]] = {}
    rows = []
    shape_rows = []
    for doc in ("trestle", "primer"):
        pages, images = read_pages(paths[doc])
        raw[doc] = pages
        per = [len(p) for p in pages]
        with_text = sum(1 for p in pages if p.strip())
        img_only = sum(
            1 for p, n in zip(pages, images, strict=True) if not p.strip() and n
        )
        total = sum(per)
        rows.append(
            [doc, len(pages), with_text, f"{with_text / len(pages):.0%}", img_only]
            + [min(per), pct(per, 0.5), max(per), total, total // CHARS_PER_TOKEN]
        )
        lines, _ = page_lines(pages)
        toks = [ln.split() for _, ln in lines]
        field = sum(
            1
            for i, t in enumerate(toks)
            if is_field_start(t, toks[i + 1] if i + 1 < len(toks) else [])
        )
        colon = sum(1 for _, ln in lines if NAME_COLON.match(ln))
        caps = sum(
            1 for _, ln in lines if ALL_CAPS.match(ln) and re.search("[A-Z]{3}", ln)
        )
        numbered = sum(1 for _, ln in lines if NUMBERED.match(ln))
        verdict = (
            "field table"
            if field / max(len(lines), 1) > 0.2
            else "prose sections"
            if numbered >= 3 or caps >= 3
            else "unclear"
        )
        shape_rows.append(
            [doc, len(lines), field, colon, caps, numbered, f"{field / len(lines):.0%}"]
            + [verdict]
        )
    table(
        "(a) Extraction (tokens = chars / 4, an estimate)",
        ["doc", "pages", "text_pg", "share", "img_no_text"]
        + ["ch_min", "ch_p50", "ch_max", "chars", "tok_est"],
        rows,
    )
    table(
        "(a) Layout: line shapes after running headers/footers are removed",
        ["doc", "lines", "field_rows", "name_colon", "all_caps", "numbered"]
        + ["field_share", "looks_like"],
        shape_rows,
    )

    # (b) chunks
    t_lines, t_removed = page_lines(raw["trestle"])
    p_lines, p_removed = page_lines(raw["primer"])
    t_chunks, t_stats = chunk_trestle(t_lines)
    sections, p_not_heading = primer_sections(p_lines)
    p_chunks = chunk_primer(sections)
    s_chunks, s_stats = chunk_schema_notes(SCHEMA_NOTES.read_text())
    chunks = t_chunks + p_chunks + s_chunks
    fields = [c for c in t_chunks if c.key != "preamble"]
    sec_words = [len(collapse([h, *b]).split()) for _, h, b, _ in sections]

    size_rows = []
    for name, group in (
        ("trestle", t_chunks),
        ("primer", p_chunks),
        ("schema_notes", s_chunks),
        ("all", chunks),
    ):
        ch = [len(c.text) for c in group]
        wd = [len(c.text.split()) for c in group]
        size_rows.append(
            [name, len(group)]
            + [pct(ch, q) for q in (0.1, 0.5, 0.9)]
            + [max(ch), pct(ch, 0.5) // CHARS_PER_TOKEN, max(ch) // CHARS_PER_TOKEN]
            + [pct(wd, 0.5), pct(wd, 0.9), max(wd), sum(wd)]
            + [sum(1 for n in ch if n > MAX_CHUNK_CHARS)]
        )
    table(
        "(b) Chunks by the decided rule (chars; tok = chars / 4)",
        ["source", "chunks", "ch_p10", "ch_p50", "ch_p90", "ch_max", "tok_p50"]
        + ["tok_max", "w_p50", "w_p90", "w_max", "words", "over_4000ch"],
        size_rows,
    )
    allow = ALLOWLIST["rets_property"] | ALLOWLIST["california_sold"]
    field_names = {c.key for c in fields}
    long_secs = [
        s[0] for s, w in zip(sections, sec_words, strict=True) if w > PART_WORDS
    ]
    n_notes = sum(1 for c in s_chunks if not c.key.startswith("summary"))
    ts, ss = t_stats, s_stats
    sold_cols = f"{ss['california_sold_columns']} / {ss['california_sold_kept']}"
    act_cols = f"{ss['rets_property_columns']} / {ss['rets_property_kept']}"
    table(
        "(b) Rule details",
        ["measure", "value"],
        [
            ["trestle running header/footer lines removed", t_removed],
            ["trestle field entries", len(fields)],
            ["trestle preamble lines (before the first entry)", ts["preamble_lines"]],
            ["trestle duplicate field names", ts["duplicate_names"]],
            ["camel-case lines not placed", ts.get("camel_lines_not_placed", 0)],
            [
                "  of which name + capitalized word (suspect)",
                ts.get("suspect_unplaced", 0),
            ],
            ["allowlisted RESO names with a field chunk", len(field_names & allow)],
            ["allowlisted names without one", len(allow - field_names)],
            ["primer running header/footer lines removed", p_removed],
            ["primer sections incl. preamble", len(sections)],
            ["primer numbered lines kept inside a section", p_not_heading],
            [
                "primer section words p50 / max",
                f"{pct(sec_words, 0.5)} / {max(sec_words)}",
            ],
            ["primer sections over 350 words", len(long_secs)],
            ["  their positions", ",".join(map(str, long_secs)) or "-"],
            ["schema_notes sections", n_notes],
            ["sold columns / kept in summary", sold_cols],
            ["active columns / kept in summary", act_cols],
        ],
    )
    missing_allow = sorted(allow - field_names)
    print("  allowlisted names without a field chunk (column names):")
    print("   ", ", ".join(missing_allow) if missing_allow else "none")

    # (b, c) protected names
    def mentions(c: Chunk) -> set[str]:
        words = set(re.findall(r"[A-Za-z0-9_]+", c.text))
        return words & PROTECTED

    prot_rows = []
    for name, group in (
        ("trestle", t_chunks),
        ("primer", p_chunks),
        ("schema_notes", s_chunks),
    ):
        own_deny = sum(1 for c in group if c.key in DENYLIST)
        own_agent = sum(1 for c in group if c.key in AGENT_CONTACT)
        other = [c for c in group if c.key not in PROTECTED and mentions(c)]
        prot_rows.append(
            [name, own_deny, own_agent, len(other)]
            + [sum(len(mentions(c)) for c in other)]
        )
    table(
        "(b/c) Deny-listed and agent-contact names (names only; before the build drop)",
        ["source", "deny_field_chunks", "agent_field_chunks", "other_chunks_naming"]
        + ["names_summed_over_them"],
        prot_rows,
    )
    kept = [c for c in chunks if c.key not in PROTECTED]
    print(
        f"  chunks after dropping protected field chunks: {len(kept)} of {len(chunks)}"
    )
    naming = [c.cid for c in chunks if c.key not in PROTECTED and mentions(c)]
    print(f"  other chunks naming a protected name: {', '.join(naming) or 'none'}")
    # Field entries outside both sets whose names look like people or access fields.
    look = [k for k in field_names - PROTECTED if PERSONISH.search(k)]
    contact = [k for k in look if CONTACTISH.search(k)]
    print(f"  field chunks outside both sets, agent/office-like names: {len(look)}")
    print(f"    of which also name/email/phone/fax/url-like: {len(contact)}")
    over = [c.cid for c in chunks if len(c.text) > MAX_CHUNK_CHARS]
    print(f"  chunks over {MAX_CHUNK_CHARS} chars: {', '.join(over) or 'none'}")

    # (c) exact-name hits and ratio candidates
    ratio_secs = [n for n, h, _, _ in sections if h and names_ratio(h)]
    mention_secs = [
        n
        for n, h, b, _ in sections
        if any(t in collapse([h, *b]).lower() for t in RATIO_TERMS[:2])
    ]
    ratio_ids = {f"primer#s{n}" for n in ratio_secs}
    bom = [
        c.key
        for c in fields
        if BACK_ON_MARKET in c.text.lower() or c.key.startswith("BackOnMarket")
    ]
    resolve = {"@ratio": ratio_ids, "@bom": {f"trestle#{k}" for k in bom}}
    ids = {c.cid for c in chunks}
    dom = "trestle#DaysOnMarket"
    table(
        "(c) Exact-name hits",
        ["check", "value"],
        [
            ["DaysOnMarket field chunk", dom in ids],
            ["alias DOM -> that chunk", dom in exact_hits("DOM", chunks, ratio_ids)],
            [
                "CumulativeDaysOnMarket field chunk",
                "trestle#CumulativeDaysOnMarket" in ids,
            ],
            [
                "california_sold summary chunk",
                "schema_notes#summary:california_sold" in ids,
            ],
            ["schema notes section 2 chunk", "schema_notes#s2" in ids],
            ["primer headings naming ratio, sale-to-list, list+price", len(ratio_secs)],
            ["  their positions", ",".join(map(str, ratio_secs)) or "-"],
            ["primer sections mentioning ratio or sale-to-list", len(mention_secs)],
            ["  their positions", ",".join(map(str, mention_secs)) or "-"],
            ["field chunks naming or mentioning back on market", len(bom)],
            ["  their field names", ",".join(bom) or "-"],
        ],
    )
    rows = []
    for qid, kind, text, _ in QUESTIONS:
        if kind != "set":
            continue
        hits = exact_hits(text, chunks, ratio_ids)
        rows.append([qid, "yes" if hits else "no", ",".join(hits) or "-"])
    table("(c) Set questions: exact-name hit", ["q", "exact", "chunks"], rows)

    # (d) BM25, (e) hashing cosine
    # Ranked over the chunks the build would keep (protected field chunks dropped).
    bm = BM25([tokens(c.text) for c in kept])
    texts = [c.text for c in kept]
    hashers = {d: HashingEmbedder(d) for d in HASH_DIMS}
    matrices = {d: h.embed(texts) for d, h in hashers.items()}
    bm_rows, hs_rows, top1 = [], [], {}
    for qid, kind, text, expect in QUESTIONS:
        exp = set().union(*(resolve.get(e, {e}) for e in expect)) if expect else set()
        exact = bool(exact_hits(text, kept, ratio_ids))
        s = bm.scores(tokens(text))
        order = ranked(s)
        top1[qid] = (kind, exact, s[order[0]])
        tops = [f"{kept[i].cid}={s[i]:.2f}" for i in order[:TOP]]
        rank = best_rank(order, kept, exp) if exp else "n/a"
        bm_rows.append([qid, kind, "yes" if exact else "no", rank] + tops)
        usable = prepare_text(text) is not None
        hrow = [qid, kind, "yes" if usable else "no"]
        for d in HASH_DIMS:
            cos = matrices[d] @ hashers[d].vector(text)
            ho = ranked(list(cos))
            hrow += [best_rank(ho, kept, exp) if exp else "n/a", f"{cos[ho[0]]:.3f}"]
        hs_rows.append(hrow)
    print("\n  Questions (own words):")
    for qid, kind, text, _ in QUESTIONS:
        print(f"    {qid} [{kind}] {text}")
    table(
        f"(d) BM25 (k1 1.5, b 0.75) over {len(kept)} kept chunks: expected rank, top 3",
        ["q", "kind", "exact", "rank", "top1", "top2", "top3"],
        bm_rows,
    )

    def low(pick) -> float:
        vals = [v for k, e, v in top1.values() if pick(k, e)]
        return min(vals) if vals else float("nan")

    off = max(v for k, _, v in top1.values() if k == "off")
    groups = (
        ("set + seed", lambda k, e: k in {"set", "seed"}),
        ("set + seed + paraphrase", lambda k, e: k != "off"),
        ("set + seed, no exact hit", lambda k, e: k in {"set", "seed"} and not e),
        ("all on-topic, no exact hit", lambda k, e: k != "off" and not e),
    )
    rows = []
    for name, pick in groups:
        lo = low(pick)
        gap = lo - off
        floor = f"{(lo + off) / 2:.2f}" if gap > 0 else "none"
        rows.append([name, f"{lo:.2f}", f"{off:.2f}", f"{gap:.2f}", floor])
    table(
        "(d) Off-topic gap (BM25 top-1; the floor applies only without an exact hit)",
        ["on-topic group", "lowest_on", "highest_off", "gap", "midpoint_floor"],
        rows,
    )
    table(
        "(e) HashingEmbedder cosine: rank of expected, top-1 cosine "
        "(embeddable = prepare_text keeps the question)",
        ["q", "kind", "embeddable"]
        + [f"{h}{d}" for d in HASH_DIMS for h in ("rank@", "top1@")],
        hs_rows,
    )

    # (f) size
    n = len(kept)
    text_bytes = sum(len(c.text.encode()) for c in kept)
    rows = [
        [d, n, n * d * FLOAT32_BYTES, text_bytes, n * d * FLOAT32_BYTES + text_bytes]
        for d in DIMS
    ]
    table(
        "(f) Hybrid index on disk (float32 vectors + chunk text; BM25 built at load)",
        ["dims", "chunks", "vector_bytes", "text_bytes", "total_bytes"],
        rows,
    )
    return 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    sys.exit(main())
