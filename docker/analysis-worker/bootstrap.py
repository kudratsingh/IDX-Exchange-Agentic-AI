"""Fixed analysis bootstrap for the WO-017 worker image (ADR-0013).

Trusted and fixed: it ships in the image and is never written by a model. It reads
the bounded sample and the model's code from the read-only /input mount, runs the
code with `rows` bound to a fresh list of dictionaries, and prints the `result`
dictionary the code must bind as one compact JSON line. On any failure it writes a
fixed line to stderr, without a traceback or any input, and exits with code 3.

This is not a sandbox. The container flags are the boundary; the host parser is
strict about what comes back. Only the standard library is used here; the host
package is not in the image.
"""

import json
import os
import shutil
import sys

SAMPLE_PATH = "/input/sample.json"
CODE_PATH = "/input/analysis.py"
FONT_CACHE = "/opt/mpl-cache"  # built into the image, read-only
FAILED = 3


def _fail() -> None:
    try:
        os.write(2, b"analysis run failed\n")
    finally:
        os._exit(FAILED)


def _seed_font_cache() -> None:
    """Copy the prebuilt font list into the tmpfs so importing matplotlib is quick."""
    target = os.environ.get("MPLCONFIGDIR")
    if target and os.path.isdir(FONT_CACHE):
        try:
            shutil.copytree(FONT_CACHE, target, dirs_exist_ok=True)
        except OSError:
            pass


def _load():
    with open(SAMPLE_PATH, encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError
    with open(CODE_PATH, encoding="utf-8") as handle:
        code = handle.read()
    return rows, code


def main() -> None:
    out = sys.stdout
    try:
        rows, code = _load()
        _seed_font_cache()
        namespace = {
            "__name__": "__analysis__",
            "__builtins__": __builtins__,
            "rows": [dict(row) for row in rows],
        }
        exec(compile(code, "analysis.py", "exec"), namespace)
        result = namespace.get("result")
        if type(result) is not dict:
            raise ValueError
        line = json.dumps(result, allow_nan=False, separators=(",", ":")) + "\n"
        out.write(line)
        out.flush()
    except BaseException:  # noqa: B036 - SystemExit from model code is a failure too
        _fail()
    # Skip atexit hooks and threads the model code may have left behind.
    os._exit(0)


if __name__ == "__main__":
    main()
