"""Render a deterministic sold-data report; optionally store an email draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.email.recipients import configured_store, resolve_recipient  # noqa: E402
from idx_agent.email.report import (  # noqa: E402
    DEFAULT_CITIES,
    collect_report,
    draft_report,
    write_report,
)
from idx_agent.safety.approval import ApprovalRefused  # noqa: E402


def main(argv=None, *, result_fn=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", default=",".join(DEFAULT_CITIES))
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--to", default="owner", choices=("owner",))
    args = parser.parse_args(argv)
    if result_fn is None:
        from idx_agent.mcp_server.server import market_result

        result_fn = market_result
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    try:
        text, dates = collect_report(cities, result_fn)
        if args.print_only:
            print(text)
        if args.draft:
            action = draft_report(
                configured_store(), resolve_recipient(args.to), text, dates, cities
            )
            print(action.id, action.state, "nothing sent")
        if not args.print_only and not args.draft:
            import hashlib

            suffix = hashlib.sha256(text.encode()).hexdigest()[:12]
            target = (
                ROOT
                / "data"
                / "reports"
                / "weekly"
                / f"weekly-{dates.sold}-{suffix}.txt"
            )
            write_report(target, text, data_root=ROOT / "data" / "reports")
            print("Report saved under data/reports/weekly.")
        return 0
    except (ApprovalRefused, OSError) as exc:
        reason = getattr(exc, "reason", "report_unavailable")
        print(f"refused: {reason}", file=sys.stderr)
        return 3 if reason == "report_unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
