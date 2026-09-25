"""The decided chunking (WO-012), pure: page texts per source in, chunks and counts out.

Trestle: one chunk per field. Primer: one per numbered section (parts past 350 words).
Schema notes: one per `##` section plus one summary per table. Glossary: one per term.
Summaries: one per file. Protected names are dropped here and counted; nothing logged.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields

from idx_agent.rag.extract import clean_lines
from idx_agent.rag.sources import SOURCES
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

__all__ = [
    "CONTACT_WORDS",
    "MAX_CHUNK_CHARS",
    "MIGRATION_MARK",
    "PART_WORDS",
    "PERSON_WORDS",
    "PROTECTED",
    "SUMMARY_LISTS_ALL",
    "TYPES",
    "Chunk",
    "DropCounts",
    "build_chunks",
    "contact_like",
    "is_field_start",
    "names_protected",
    "page_lines",
]

PART_WORDS = 350  # a Primer section over this splits into parts by line
# prepare()'s cut in semantic/embedder.py: a longer chunk splits at paragraphs.
MAX_CHUNK_CHARS = 4000
PROTECTED = DENYLIST | AGENT_CONTACT
_PROTECTED_LOWER = frozenset(name.lower() for name in PROTECTED)
_DENY_LOWER = frozenset(name.lower() for name in DENYLIST)
# A field name holding one of each group looks like a person's or office's contact
# detail; such Trestle entries are dropped too (an agent decision for the human).
PERSON_WORDS = ("Agent", "Office", "Owner", "Occupant", "Showing", "LockBox", "Access")
CONTACT_WORDS = ("Name", "Email", "Phone", "Fax", "URL", "Url")
# Decision 8: the sold table's summary lists every column; the active table's keeps
# the WO body's rule (contact names withheld, their count given).
SUMMARY_LISTS_ALL = frozenset({"california_sold"})
MIGRATION_MARK = " (ours, added by the migration)"
_MIGRATION_COLUMN = re.compile(r"^[a-z][a-z_]*_d$")

# Field-reference layout (the spike's measurements): a field entry begins with its
# name, then a data type, or a lookup name then "Enum" (which may wrap to the next
# line), or a link to another resource.
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
_WORD = re.compile(r"[A-Za-z0-9_]+")
_SECTION_NUMBER = re.compile(r"^(\d+(?:-\d+)?)\.\s")
_TABLE_HEADING = re.compile(r"^###\s+([A-Za-z_][A-Za-z0-9_]*)")
_TABLE_ROW = re.compile(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|")
_SUMMARY_HEADER = re.compile(r"^Market summary:\s*(\S.*)$")
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage. `text` is data, never instructions, never logged."""

    doc: str
    key: str
    page: int | None
    text: str = field(repr=False)
    confidential: bool
    label: str

    @property
    def chunk_id(self) -> str:
        """`doc#key`, the name the log line, the evals, and the tool use."""
        return f"{self.doc}#{self.key}"


def _counter() -> dict[str, int]:
    return {}


@dataclass
class DropCounts:
    """What the chunker removed or split, per source id (counts only).

    `field_chunks_dropped` = deny-listed + agent-contact field entries.
    """

    field_chunks_dropped: dict[str, int] = field(default_factory=_counter)
    deny_listed_dropped: dict[str, int] = field(default_factory=_counter)
    agent_contact_dropped: dict[str, int] = field(default_factory=_counter)
    contact_like_dropped: dict[str, int] = field(default_factory=_counter)
    lines_removed: dict[str, int] = field(default_factory=_counter)
    empty_dropped: dict[str, int] = field(default_factory=_counter)
    header_lines_removed: dict[str, int] = field(default_factory=_counter)
    split_chunks: dict[str, int] = field(default_factory=_counter)

    def add(self, name: str, source: str, n: int = 1) -> None:
        """Add `n` to one count for one source."""
        counts = getattr(self, name)
        counts[source] = counts.get(source, 0) + n

    def total(self, name: str) -> int:
        """One count summed over the sources."""
        return sum(getattr(self, name).values())

    def as_dict(self) -> dict[str, dict[str, int]]:
        """Every count, for the index meta."""
        return {f.name: dict(getattr(self, f.name)) for f in fields(self)}


# ----- shared helpers -----------------------------------------------------------------
def names_protected(line: str) -> bool:
    """True when a line names a deny-listed or agent-contact field (any case)."""
    return any(word.lower() in _PROTECTED_LOWER for word in _WORD.findall(line))


def contact_like(name: str) -> bool:
    """A field name that looks like a person's or office's contact detail."""
    return any(p in name for p in PERSON_WORDS) and any(
        c in name for c in CONTACT_WORDS
    )


def _drop_lines(lines: Sequence[str], source: str, drops: DropCounts) -> list[str]:
    """The lines that name no protected field; the rest are counted."""
    kept = [line for line in lines if not names_protected(line)]
    if len(kept) != len(lines):
        drops.add("lines_removed", source, len(lines) - len(kept))
    return kept


def _collapse(lines: Sequence[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _join_markdown(lines: Sequence[str]) -> str:
    """Lines joined with newlines; runs of blank lines become one; ends trimmed."""
    out: list[str] = []
    for line in lines:
        line = line.rstrip()
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    return "\n".join(out).strip()


def page_lines(pages: Sequence[str]) -> tuple[list[tuple[int, str]], int]:
    """(page number, line) for every non-blank line, minus running headers and
    footers: a line (digits masked) on at least half the pages (and at least 3).
    Returns the lines and how many were removed."""
    per_page = [
        {re.sub(r"\d+", "#", line) for line in clean_lines(page)} for page in pages
    ]
    seen = Counter(line for page in per_page for line in page)
    running = {line for line, n in seen.items() if n >= max(3, len(pages) / 2)}
    out: list[tuple[int, str]] = []
    removed = 0
    for number, page in enumerate(pages, start=1):
        for line in clean_lines(page):
            if re.sub(r"\d+", "#", line) in running:
                removed += 1
                continue
            out.append((number, line))
    return out, removed


def _split_long(text: str, joiner: str) -> list[str]:
    """Parts of at most MAX_CHUNK_CHARS: whole paragraphs (blank-line separated)
    where they fit, else whole lines, else hard cuts."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        if len(paragraph) <= MAX_CHUNK_CHARS:
            units.append(paragraph)
            continue
        for line in paragraph.splitlines():
            while len(line) > MAX_CHUNK_CHARS:
                units.append(line[:MAX_CHUNK_CHARS])
                line = line[MAX_CHUNK_CHARS:]
            units.append(line)
    parts: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}{joiner}{unit}" if current else unit
        if current and len(candidate) > MAX_CHUNK_CHARS:
            parts.append(current)
            current = unit
        else:
            current = candidate
    if current:
        parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def _finish(
    doc: str,
    key: str,
    page: int | None,
    text: str,
    label: str,
    drops: DropCounts,
    joiner: str = "\n\n",
) -> list[Chunk]:
    """One chunk, or `<key>.<n>` parts when over MAX_CHUNK_CHARS; none when empty."""
    confidential = SOURCES[doc].confidential
    text = text.strip()
    if not text:
        drops.add("empty_dropped", doc)
        return []
    parts = _split_long(text, joiner)
    if len(parts) == 1:
        return [Chunk(doc, key, page, parts[0], confidential, label)]
    drops.add("split_chunks", doc)
    return [
        Chunk(doc, f"{key}.{n}", page, part, confidential, f"{label}, part {n}")
        for n, part in enumerate(parts, 1)
    ]


# ----- Trestle: one chunk per field entry ---------------------------------------------
def is_field_start(tokens: Sequence[str], next_tokens: Sequence[str]) -> bool:
    """A field entry begins: name + type; name + lookup + Enum (Enum possibly on the
    next line); name + resource (a link); a name + one capitalized word whose next
    line is a type; or a lone name whose next line begins with a type."""
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
        if IDENT.match(t[1]) and nxt0 in TYPES:
            return True
    return len(t) == 1 and nxt0 in TYPES


def _chunk_fields(doc: str, pages: Sequence[str], drops: DropCounts) -> list[Chunk]:
    """Field entries in page order; lines before the first form an intro chunk."""
    lines, removed = page_lines(pages)
    if removed:
        drops.add("header_lines_removed", doc, removed)
    entries: list[tuple[str, int, list[str]]] = []
    intro: list[str] = []
    for i, (page, line) in enumerate(lines):
        tokens = line.split()
        nxt = lines[i + 1][1].split() if i + 1 < len(lines) else []
        if is_field_start(tokens, nxt):
            entries.append((tokens[0].rstrip(","), page, [line]))
        elif entries:
            entries[-1][2].append(line)
        else:
            intro.append(line)
    label = SOURCES[doc].label
    chunks: list[Chunk] = []
    if intro:
        text = _collapse(_drop_lines(intro, doc, drops))
        chunks += _finish(doc, "intro", 1, text, f"{label}, introduction", drops, " ")
    seen: Counter[str] = Counter()
    for name, page, body in entries:
        if name.lower() in _PROTECTED_LOWER:
            drops.add("field_chunks_dropped", doc)
            deny = name.lower() in _DENY_LOWER
            kind = "deny_listed_dropped" if deny else "agent_contact_dropped"
            drops.add(kind, doc)
            continue
        if contact_like(name):
            drops.add("contact_like_dropped", doc)
            continue
        seen[name] += 1
        key = name if seen[name] == 1 else f"{name}.{seen[name]}"
        text = _collapse(_drop_lines(body, doc, drops))
        chunks += _finish(
            doc, key, page, text, f"Trestle field {key}, p. {page}", drops
        )
    return chunks


# ----- Primer: one chunk per numbered section -----------------------------------------
def _sections(
    lines: Sequence[tuple[int, str]],
) -> list[tuple[int, list[str], int]]:
    """(number, heading and body lines, page) per section; 0 is any preamble."""
    sections: list[tuple[int, list[str], int]] = [(0, [], 1)]
    for page, line in lines:
        m = NUMBERED.match(line)
        if m:
            n, rest = int(m.group(1)), m.group(2)
            if (
                n == sections[-1][0] + 1
                and len(rest.split()) <= HEADING_MAX_WORDS
                and line[-1] not in ".,;:"
            ):
                sections.append((n, [line], page))
                continue
        sections[-1][1].append(line)
    if not sections[0][1]:
        sections.pop(0)
    return sections


def _word_parts(lines: Sequence[str]) -> list[list[str]]:
    """Lines grouped into parts of at most PART_WORDS words (a longer line alone)."""
    parts: list[list[str]] = []
    buf: list[str] = []
    words = 0
    for line in lines:
        n = len(line.split())
        if buf and words + n > PART_WORDS:
            parts.append(buf)
            buf, words = [], 0
        buf.append(line)
        words += n
    if buf:
        parts.append(buf)
    return parts


def _chunk_sections(doc: str, pages: Sequence[str], drops: DropCounts) -> list[Chunk]:
    """One chunk per section, keyed `s<n>`; `s<n>.<k>` parts past PART_WORDS."""
    lines, removed = page_lines(pages)
    if removed:
        drops.add("header_lines_removed", doc, removed)
    label = SOURCES[doc].label
    chunks: list[Chunk] = []
    for number, body, page in _sections(lines):
        kept = _drop_lines(body, doc, drops)
        name = f"{label} introduction" if number == 0 else f"{label} section {number}"
        key = f"s{number}"
        if len(_collapse(kept).split()) <= PART_WORDS:
            chunks += _finish(doc, key, page, _collapse(kept), name, drops, " ")
            continue
        drops.add("split_chunks", doc)
        for k, part in enumerate(_word_parts(kept), 1):
            chunks += _finish(
                doc,
                f"{key}.{k}",
                page,
                _collapse(part),
                f"{name}, part {k}",
                drops,
                " ",
            )
    return chunks


# ----- Markdown: schema notes and the glossary ----------------------------------------
def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """(heading, lines incl. the heading line) per `## ` block; "" for the preamble."""
    blocks: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        if line.startswith("## "):
            blocks.append((line[3:].strip(), [line]))
        else:
            blocks[-1][1].append(line)
    return blocks


def _slug(heading: str, max_words: int = 5) -> str:
    """Lowercase words of a heading (before any "("), joined by "_"."""
    words = _SLUG.sub(" ", heading.split("(")[0].lower()).split()
    return "_".join(words[:max_words]) or "section"


def _table_columns(lines: Sequence[str]) -> dict[str, list[tuple[str, str]]]:
    """table -> [(column, type)] from `### <table>` markdown tables, in order."""
    tables: dict[str, list[tuple[str, str]]] = {}
    table = ""
    for line in lines:
        heading = _TABLE_HEADING.match(line)
        if heading:
            table = heading.group(1)
            tables[table] = []
            continue
        row = _TABLE_ROW.match(line)
        if table and row and row.group(1) != "column":
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            tables[table].append((row.group(1), cells[1] if len(cells) > 1 else ""))
    return tables


def _table_summary(table: str, columns: Sequence[tuple[str, str]]) -> str:
    """The summary text: every column name (sold table) or the non-contact ones plus
    a count line (other tables), one per line; migration date columns marked."""

    def line(name: str, kind: str) -> str:
        ours = _MIGRATION_COLUMN.match(name) and kind == "date"
        return name + (MIGRATION_MARK if ours else "")

    total = len(columns)
    if table in SUMMARY_LISTS_ALL:
        head = (
            f"The {table} table has {total} columns. "
            "In the order the schema notes list them:"
        )
        return "\n".join([head, *(line(n, k) for n, k in columns)])
    shown = [(n, k) for n, k in columns if n not in PROTECTED]
    hidden = total - len(shown)
    head = (
        f"The {table} table has {total} columns. In the order the schema notes "
        f"list them, the {len(shown)} that may be shown:"
    )
    tail = (
        f"{hidden} more columns hold agent or office contact details "
        "and are never shown."
    )
    return "\n".join([head, *(line(n, k) for n, k in shown), tail])


def _chunk_schema_notes(
    doc: str, pages: Sequence[str], drops: DropCounts
) -> list[Chunk]:
    """One chunk per `##` section (`sec<N>` when numbered), then one per table."""
    label = SOURCES[doc].label
    chunks: list[Chunk] = []
    tables: dict[str, list[tuple[str, str]]] = {}
    for heading, lines in _blocks("\n".join(pages)):
        tables.update(_table_columns(lines))
        number = _SECTION_NUMBER.match(heading)
        if not heading:
            key, name = "intro", f"{label}: introduction"
        elif number:
            key, name = f"sec{number.group(1)}", f"{label} section {number.group(1)}"
        else:
            key, name = _slug(heading), f"{label}: {heading.split('(')[0].strip()}"
        text = _join_markdown(_drop_lines(lines, doc, drops))
        chunks += _finish(doc, key, None, text, name, drops)
    for table, columns in tables.items():
        text = _table_summary(table, columns)
        chunks += _finish(doc, table, None, text, f"{label}: {table}", drops, "\n")
    return chunks


def _chunk_glossary(doc: str, pages: Sequence[str], drops: DropCounts) -> list[Chunk]:
    """One chunk per `##` term, keyed by the term's slug; the preamble is skipped."""
    label = SOURCES[doc].label
    chunks: list[Chunk] = []
    for heading, lines in _blocks("\n".join(pages)):
        if not heading:
            continue
        text = _join_markdown(_drop_lines(lines, doc, drops))
        term = heading.split("(")[0].strip()
        chunks += _finish(doc, _slug(heading), None, text, f"{label}: {term}", drops)
    return chunks


# ----- Market summaries: one chunk per file -------------------------------------------
def _chunk_summaries(doc: str, pages: Sequence[str], drops: DropCounts) -> list[Chunk]:
    """One chunk per summary; the city comes from its "Market summary:" line (the
    first or second, after the "Saved on" line); the saved-on line stays in the text."""
    label = SOURCES[doc].label
    chunks: list[Chunk] = []
    for n, page in enumerate(pages, 1):
        lines = page.strip().splitlines()
        heads = (_SUMMARY_HEADER.match(line.strip()) for line in lines[:2])
        header = next((m for m in heads if m), None)
        city = header.group(1).strip() if header else str(n)
        text = _join_markdown(_drop_lines(lines, doc, drops))
        key = f"summary:{city.replace(' ', '_')}"
        chunks += _finish(doc, key, None, text, f"{label}: {city}", drops)
    return chunks


_CHUNKERS = {
    "fields": _chunk_fields,
    "sections": _chunk_sections,
    "schema_notes": _chunk_schema_notes,
    "glossary": _chunk_glossary,
    "summaries": _chunk_summaries,
}


def build_chunks(
    pages_by_source: Mapping[str, Sequence[str]],
) -> tuple[list[Chunk], DropCounts]:
    """Chunks for every given source, in registry order, and the drop counts.

    Raises ValueError for an unknown source id or a repeated chunk id.
    """
    unknown = sorted(set(pages_by_source) - set(SOURCES))
    if unknown:
        raise ValueError(f"unknown source ids: {unknown}")
    drops = DropCounts()
    chunks: list[Chunk] = []
    for source_id, source in SOURCES.items():
        if source_id in pages_by_source:
            pages = list(pages_by_source[source_id])
            chunks += _CHUNKERS[source.kind](source_id, pages, drops)
    ids = Counter(chunk.chunk_id for chunk in chunks)
    repeated = [cid for cid, n in ids.items() if n > 1]
    if repeated:
        raise ValueError(f"repeated chunk ids: {len(repeated)}")
    return chunks, drops
