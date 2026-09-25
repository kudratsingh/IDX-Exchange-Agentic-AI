"""Save the Week 5 market cards as text for the document index (WO-012, decision 11).

Runs `market_result` (get_market_stats's body) per city at the default window and
writes the card to data/knowledge/summaries/<City>.txt (gitignored); the card is our
own text, so it is printed. Read-only database. Run: python scripts/market_summaries.py
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Read the package from this checkout's src, as scripts/market_spike.py does.
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.semantic.build_index import (  # noqa: E402
    BuildRefused,
    check_output_dir,
    git_ignored,
)
from idx_agent.semantic.index import replace_with  # noqa: E402

# The cities the Week 5 demo used.
CITIES = ("Pasadena", "Glendale", "Duarte")
DATA_ROOT = ROOT / "data"
DEFAULT_OUT = DATA_ROOT / "knowledge" / "summaries"
HEADER = "Market summary: {city}"
# The first line of every file: the summaries are snapshots, so each carries the day
# it was saved as well as the card's own as-of dates.
SAVED_ON = "Saved on {day}"


def summary_text(city: str, message: str, saved_on: date) -> str:
    """The file body: the saved-on line, our header line (the chunker keys on it),
    then the card."""
    saved = SAVED_ON.format(day=saved_on.isoformat())
    return f"{saved}\n{HEADER.format(city=city)}\n{message.strip()}\n"


def file_for(out_dir: Path, city: str) -> Path:
    """`<out_dir>/<City>.txt`, spaces as underscores."""
    return Path(out_dir) / f"{city.replace(' ', '_')}.txt"


def write_summaries(
    out_dir: Path,
    cities: Sequence[str],
    result_fn: Callable[[Mapping[str, object]], Any],
    *,
    data_root: Path = DATA_ROOT,
    is_ignored: Callable[[Path], bool] = git_ignored,
    echo: Callable[[str], None] = print,
    saved_on: date | None = None,
) -> int:
    """Write one card per city, each dated `saved_on` (default today, UTC); return
    how many were written. Refuses (BuildRefused) a folder outside data/ or not
    ignored. A city whose call fails or asks a question is skipped and named.
    """
    check_output_dir(Path(out_dir), data_root, is_ignored)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    day = saved_on or datetime.now(UTC).date()
    written = 0
    for city in cities:
        result = result_fn({"city": city})
        stats = getattr(result, "data", None)
        if not result.ok or type(stats).__name__ != "MarketStats":
            category = result.error.category if result.error else "clarification"
            echo(f"skipped {city}: {category}")
            continue
        text = summary_text(city, result.message or "", day)
        replace_with(file_for(out_dir, city), lambda fh, t=text: fh.write(t.encode()))
        written += 1
        echo(text)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Run the script; 0 when every city was written, 1 otherwise, 2 refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cities", default=",".join(CITIES))
    args = parser.parse_args(argv)
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    from idx_agent.mcp_server.server import market_result

    try:
        written = write_summaries(args.out, cities, market_result)
    except BuildRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"{written} of {len(cities)} summaries written")
    return 0 if written == len(cities) else 1


if __name__ == "__main__":
    sys.exit(main())
