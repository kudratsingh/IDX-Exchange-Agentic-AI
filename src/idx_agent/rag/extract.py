"""Source files to page texts (WO-012): PDFs through pypdf, text files, summaries.

Each page comes back as its non-blank lines, whitespace collapsed within a line, in
page order (page numbers are list positions + 1). Nothing here prints or logs text;
a missing file raises `SourceMissing`, which names the source id only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from idx_agent.rag.sources import Source

__all__ = [
    "PAGE_BREAK",
    "SourceMissing",
    "clean_lines",
    "empty_pages",
    "load_pages",
    "read_pdf_pages",
    "read_summary_pages",
    "read_text_pages",
]

# A page break in a text source (the fixture corpus): a form feed, or this line.
PAGE_BREAK = re.compile(r"^-{2,}\s*page break\s*-{2,}$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


class SourceMissing(FileNotFoundError):
    """A registered source's file or folder is not there; `source_id` names it."""

    def __init__(self, source_id: str, path: Path) -> None:
        super().__init__(f"source {source_id!r} not found at {path}")
        self.source_id = source_id
        self.path = path


def clean_lines(text: str) -> list[str]:
    """The non-blank lines of `text`, each with its whitespace collapsed."""
    lines = (_WHITESPACE.sub(" ", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


def empty_pages(pages: list[str]) -> list[int]:
    """1-based numbers of the pages that yielded no text."""
    return [number for number, page in enumerate(pages, 1) if not page.strip()]


def read_pdf_pages(path: Path, source_id: str = "pdf") -> list[str]:
    """One cleaned text per PDF page (an empty string for a page with no text)."""
    path = Path(path)
    if not path.is_file():
        raise SourceMissing(source_id, path)
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf is not installed: pip install -e '.[rag]'") from None
    # pypdf warns about odd fonts on stderr; the warnings may quote page text.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(path))
    return ["\n".join(clean_lines(page.extract_text() or "")) for page in reader.pages]


def read_text_pages(path: Path, source_id: str = "text") -> list[str]:
    """A text file split into pages at form feeds and page-break lines."""
    path = Path(path)
    if not path.is_file():
        raise SourceMissing(source_id, path)
    pages: list[str] = []
    for part in path.read_text(encoding="utf-8").split("\f"):
        lines: list[str] = []
        for raw in part.split("\n"):
            if PAGE_BREAK.match(raw.strip()):
                pages.append("\n".join(lines))
                lines = []
            else:
                lines.append(raw.rstrip("\r"))
        pages.append("\n".join(lines))
    return pages


def read_summary_pages(folder: Path, source_id: str = "summaries") -> list[str]:
    """Each `*.txt` in the folder, sorted by name, as one page."""
    folder = Path(folder)
    if not folder.is_dir():
        raise SourceMissing(source_id, folder)
    return [file.read_text(encoding="utf-8") for file in sorted(folder.glob("*.txt"))]


def load_pages(source: Source, path: Path) -> list[str]:
    """The pages of one source: a PDF, a text or markdown file, or a summaries folder.

    Markdown sources keep their blank lines (paragraphs matter to the chunker).
    """
    path = Path(path)
    if source.kind == "summaries":
        return read_summary_pages(path, source.id)
    if path.suffix.lower() == ".pdf":
        return read_pdf_pages(path, source.id)
    return read_text_pages(path, source.id)
