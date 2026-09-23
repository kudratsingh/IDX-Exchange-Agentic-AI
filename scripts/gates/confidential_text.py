"""Gate: no text from the handbook, the Primer or the Trestle metadata (RULES.md, rule 2).

Hashes every 10-word window of each text file; a hash found in fingerprints.txt blocks
unless it is in allowed_shingles.txt. Only hashes are tracked, never the documents.
Chain: pre-commit passes staged paths -> exit 1 blocks; CI reruns with --all-tracked.
"""

import hashlib
import pathlib
import re
import sys

from gatelib import fail, is_text, read, target_files

HERE = pathlib.Path(__file__).resolve().parent
FINGERPRINTS = HERE / "fingerprints.txt"
ALLOWED = HERE / "allowed_shingles.txt"
K = 10  # words per window
WORD = re.compile(r"[a-z0-9_]+")  # tokens after lowercasing; punctuation is dropped
# The hash files themselves are never scanned.
SKIP = {"scripts/gates/fingerprints.txt", "scripts/gates/allowed_shingles.txt"}


def shingles(text):
    """Yield (word_index, window) for every K-word window of the lowercased text.

    Text shorter than K words yields nothing. Shared with build_fingerprints.py.
    """
    words = WORD.findall(text.lower())
    for i in range(len(words) - K + 1):
        yield i, " ".join(words[i : i + K])


def h(shingle):
    """Return the first 12 hex chars of the window's SHA-256; the stored fingerprint."""
    return hashlib.sha256(shingle.encode()).hexdigest()[:12]


def load(path):
    """Return the set of hashes in a hash file (first token per line).

    Blank lines and # lines are skipped; a missing file gives an empty set.
    """
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
    """Scan target text files; fail if any window matches a non-allowed fingerprint.

    A missing or empty fingerprints.txt also fails, so the gate cannot pass vacuously.
    Output lists at most 5 matching windows per file.
    """
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
