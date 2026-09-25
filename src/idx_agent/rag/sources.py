"""The document registry for the RAG index (WO-012): ids, paths, flags, labels.

The two PDFs and the market summaries live under the gitignored data/knowledge/
folder (a build may point `docs_root` elsewhere); schema notes and the glossary are
tracked, own-words files. `confidential` is True for the two PDFs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from idx_agent.semantic.index import REPO_ROOT

__all__ = [
    "DEFAULT_DOCS_ROOT",
    "REPO_ROOT",
    "SOURCES",
    "SOURCE_IDS",
    "Source",
    "SourceKind",
]

DEFAULT_DOCS_ROOT = REPO_ROOT / "data" / "knowledge"

SourceKind = Literal["fields", "sections", "schema_notes", "glossary", "summaries"]


@dataclass(frozen=True)
class Source:
    """One registered document: where it lives, how it is chunked, how it is shown.

    `relpath` is from the repo root when `tracked`, else from the docs root.
    """

    id: str
    relpath: str
    kind: SourceKind
    confidential: bool
    tracked: bool
    label: str

    @property
    def path(self) -> Path:
        """The default location: the repo root (tracked) or data/knowledge/."""
        return self.resolve()

    def resolve(self, docs_root: Path | None = None) -> Path:
        """Under the repo root (tracked), else `docs_root` (default data/knowledge)."""
        if self.tracked:
            return REPO_ROOT / self.relpath
        return Path(docs_root or DEFAULT_DOCS_ROOT) / self.relpath


# Registry order is chunk order in the index, and so the tie order in ranking.
SOURCES: dict[str, Source] = {
    source.id: source
    for source in (
        Source(
            "trestle",
            "Trestle_Property_MetaData.pdf",
            "fields",
            confidential=True,
            tracked=False,
            label="Trestle field reference",
        ),
        Source(
            "primer",
            "Real_Estate_Data_Analys_Primer.pdf",
            "sections",
            confidential=True,
            tracked=False,
            label="Primer",
        ),
        Source(
            "schema_notes",
            "docs/data/schema_notes.md",
            "schema_notes",
            confidential=False,
            tracked=True,
            label="Schema notes",
        ),
        Source(
            "glossary",
            "docs/data/glossary.md",
            "glossary",
            confidential=False,
            tracked=True,
            label="Glossary",
        ),
        Source(
            "summaries",
            "summaries",
            "summaries",
            confidential=False,
            tracked=False,
            label="Market summary",
        ),
    )
}
SOURCE_IDS: tuple[str, ...] = tuple(SOURCES)
