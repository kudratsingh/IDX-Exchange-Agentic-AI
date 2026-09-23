"""Gate: no text from the handbook, the Primer or the Trestle metadata (RULES.md, rule 2).

Every 10-word window of each staged text file is hashed and compared with the
fingerprints of the source documents. Only hashes are tracked; the documents are not.
"""

import hashlib
import pathlib
import re
import sys

from gatelib import fail, is_text, read, target_files

HERE = pathlib.Path(__file__).resolve().parent
FINGERPRINTS = HERE / "fingerprints.txt"
ALLOWED = HERE / "allowed_shingles.txt"
K = 10
WORD = re.compile(r"[a-z0-9_]+")
SKIP = {"scripts/gates/fingerprints.txt", "scripts/gates/allowed_shingles.txt"}


def shingles(text):
    words = WORD.findall(text.lower())
    for i in range(len(words) - K + 1):
        yield i, " ".join(words[i : i + K])


def h(shingle):
    return hashlib.sha256(shingle.encode()).hexdigest()[:12]


def load(path):
    if not path.exists():
        return set()
    return {
        line.split()[0]
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def find_matches(text, fingerprints, allowed=frozenset()):
    """Return [(word_index, window_text)] for windows found in the fingerprints."""
    hits = []
    for i, s in shingles(text):
        digest = h(s)
        if digest in fingerprints and digest not in allowed:
            hits.append((i, s))
    return hits


def main(argv):
    fps = load(FINGERPRINTS)
    if not fps:
        fail(
            "BLOCKED: scripts/gates/fingerprints.txt is missing or empty.\n"
            "Run once, locally:  python scripts/gates/build_fingerprints.py\n"
            "It needs the documents listed in scripts/gates/sources.txt (gitignored paths)."
        )
    allowed = load(ALLOWED)
    files = [
        p for p in target_files(argv) if is_text(p) and p.replace("\\", "/") not in SKIP
    ]
    problems = []
    for p in files:
        hits = find_matches(read(p), fps, allowed)
        if hits:
            problems.append((p, hits))
    if problems:
        lines = [
            "BLOCKED by the confidential-text gate (RULES.md, rule 2). Reword these in your own words:"
        ]
        for p, hits in problems:
            for i, s in hits[:5]:
                lines.append(f'  {p} (word {i}): "{s}"')
            if len(hits) > 5:
                lines.append(f"  {p}: ... and {len(hits) - 5} more windows")
        lines.append(
            "A reviewed false positive can be listed in scripts/gates/allowed_shingles.txt by its hash, with a comment."
        )
        fail("\n".join(lines))
    print(f"confidential_text: ok ({len(files)} text files, {len(fps)} fingerprints)")


if __name__ == "__main__":
    main(sys.argv)
