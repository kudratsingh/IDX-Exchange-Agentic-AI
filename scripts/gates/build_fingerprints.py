"""Build scripts/gates/fingerprints.txt from the documents in scripts/gates/sources.txt.

Run locally (the documents are gitignored). Writes only 12-hex hashes of 10-word windows,
which cannot be turned back into text. Re-run whenever a source document changes.
"""

import sys

from confidential_text import FINGERPRINTS, HERE, h, shingles

SOURCES = HERE / "sources.txt"


def extract_text(path):
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("pypdf is needed to read the PDFs:  pip install pypdf")
        return "\n".join(
            (page.extract_text() or "") for page in PdfReader(str(path)).pages
        )
    return path.read_text(encoding="utf-8", errors="replace")


def main():
    root = HERE.parent.parent
    paths = [
        root / line.strip()
        for line in SOURCES.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    missing = [p for p in paths if not p.exists()]
    if missing:
        sys.exit(
            "Missing source documents (put them at these gitignored paths):\n"
            + "\n".join(f"  {m.relative_to(root)}" for m in missing)
        )
    hashes = set()
    for p in paths:
        n = 0
        for _, s in shingles(extract_text(p)):
            hashes.add(h(s))
            n += 1
        print(f"{p.name}: {n} windows")
    header = (
        "# 12-hex sha256 prefixes of 10-word windows from the documents in sources.txt.\n"
        "# Hashes only; regenerate with: python scripts/gates/build_fingerprints.py\n"
    )
    FINGERPRINTS.write_text(header + "\n".join(sorted(hashes)) + "\n")
    print(f"wrote {len(hashes)} fingerprints to {FINGERPRINTS.relative_to(root)}")


if __name__ == "__main__":
    main()
