"""Deep-merge the rendered IDX fragment(s) into the OpenClaw config, keeping a backup.

Usage: python3 scripts/openclaw_merge_config.py <fragment .json5> [...] <openclaw.json>
Fragments: JSON5 with // comments and trailing commas, merged in order; target: plain
JSON, rewritten once. Fragment lists replace target lists (allow/deny win).
"""

import json
import pathlib
import re
import shutil
import sys


def load_json5(path: pathlib.Path) -> dict:
    """Parse the small JSON5 subset used by the fragment and return it as a dict.

    Strips // line comments (outside strings, so a rendered URL survives) and
    trailing commas and quotes bare keys, then uses json.loads.
    """
    text = path.read_text(encoding="utf-8")
    # A string literal is kept whole; a // comment outside one is dropped.
    text = re.sub(r'("(?:[^"\\\n]|\\.)*")|//[^\n]*', lambda m: m.group(1) or "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)  # trailing commas
    text = re.sub(
        r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text
    )  # bare keys
    return json.loads(text)


def deep_merge(base: dict, extra: dict) -> dict:
    """Return a new dict: base with extra merged in; base is not modified.

    Nested dicts merge key by key; any other value in extra (lists included)
    replaces the value in base.
    """
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def main(argv: list[str]) -> int:
    """Merge argv[1:-1] (fragments, in order) into argv[-1] (config); returns 0.

    1) read the target JSON; 2) parse and deep-merge each fragment; 3) copy the
    target to <name>.json.pre-idx.bak (one backup per run); 4) write the result back.
    """
    fragments = [pathlib.Path(arg).expanduser() for arg in argv[1:-1]]
    target = pathlib.Path(argv[-1]).expanduser()
    merged = json.loads(target.read_text(encoding="utf-8"))
    for fragment in fragments:
        merged = deep_merge(merged, load_json5(fragment))
    backup = target.with_suffix(".json.pre-idx.bak")
    shutil.copy2(target, backup)
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(str(fragment) for fragment in fragments)
    print(f"merged {names} into {target}; backup at {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
