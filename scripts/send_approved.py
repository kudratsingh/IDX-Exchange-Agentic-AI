"""Human operator: deliver exactly one approved draft to sink or Gmail SMTP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from idx_agent.email.recipients import configured_store  # noqa: E402
from idx_agent.email.send import send  # noqa: E402
from idx_agent.safety.approval import ApprovalRefused  # noqa: E402
from idx_agent.safety.consent import PaidRunRefused  # noqa: E402


def main(argv=None, *, store=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id")
    parser.add_argument("--transport", choices=("sink", "smtp"), default="sink")
    args = parser.parse_args(argv)
    try:
        receipt = send(store or configured_store(), args.id, transport=args.transport)
        print(receipt.model_dump_json())
        return 0
    except (ApprovalRefused, PaidRunRefused, OSError) as exc:
        reason = (
            exc.reason
            if isinstance(exc, ApprovalRefused)
            else "delivery_not_authorized"
        )
        print(f"refused: {reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
