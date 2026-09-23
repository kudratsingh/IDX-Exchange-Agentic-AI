"""Deep-merge the rendered IDX fragment into the OpenClaw config, keeping a backup.

Usage:
  python3 scripts/openclaw_merge_config.py <rendered fragment .json5> <openclaw.json>
The fragment is JSON5 with // comments and trailing commas; the target is plain JSON.
Lists in the fragment replace lists in the target (allow/deny lists are authoritative).
"""

import json
import pathlib
import re
import shutil
import sys


def load_json5(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)  # line comments (no URLs inside this file)
    text = re.sub(r",(\s*[}\]])", r"\1", text)  # trailing commas
    text = re.sub(
        r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text
    )  # bare keys
    return json.loads(text)


def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def main(argv: list[str]) -> int:
    fragment, target = (
        pathlib.Path(argv[1]).expanduser(),
        pathlib.Path(argv[2]).expanduser(),
    )
    base = json.loads(target.read_text(encoding="utf-8"))
    merged = deep_merge(base, load_json5(fragment))
    backup = target.with_suffix(".json.pre-idx.bak")
    shutil.copy2(target, backup)
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"merged {fragment} into {target}; backup at {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
