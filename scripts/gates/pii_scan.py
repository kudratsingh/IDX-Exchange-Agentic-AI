"""Gate: no email addresses or phone numbers in tracked files (RULES.md, rule 3)."""

import pathlib
import re
import sys

from gatelib import fail, is_text, read, target_files

HERE = pathlib.Path(__file__).resolve().parent
ALLOWED = HERE / "allowed_pii.txt"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
SAFE_EMAIL = re.compile(
    r"(@(example\.(com|org|net)|test|invalid|localhost)$)|(^replace-me@)", re.I
)
SAFE_PHONE = re.compile(r"^\(?555\)?[-.\s]")
SKIP = {"scripts/gates/pii_scan.py", "scripts/gates/allowed_pii.txt"}


def load_allowed():
    if not ALLOWED.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWED.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def find_pii(text, allowed=frozenset()):
    hits = []
    for m in EMAIL.finditer(text):
        v = m.group(0)
        if not SAFE_EMAIL.search(v) and v not in allowed:
            hits.append(("email", v))
    for m in PHONE.finditer(text):
        v = m.group(0)
        if not SAFE_PHONE.match(v) and v not in allowed:
            hits.append(("phone", v))
    return hits


def main(argv):
    allowed = load_allowed()
    files = [
        p for p in target_files(argv) if is_text(p) and p.replace("\\", "/") not in SKIP
    ]
    problems = [(p, find_pii(read(p), allowed)) for p in files]
    problems = [(p, hits) for p, hits in problems if hits]
    if problems:
        lines = [
            "BLOCKED by the PII gate (RULES.md, rule 3). Use placeholders (replace-me@example.com, 555-010-0100) or remove:"
        ]
        for p, hits in problems:
            for kind, v in hits[:10]:
                lines.append(f"  {p}: {kind} {v}")
        fail("\n".join(lines))
    print(f"pii_scan: ok ({len(files)} text files)")


if __name__ == "__main__":
    main(sys.argv)
