"""Human operator: inspect, approve by digest, reject or list email drafts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from idx_agent.email.recipients import configured_store  # noqa: E402
from idx_agent.safety.approval import ApprovalRefused  # noqa: E402


def main(argv=None, *, store=None, stdin=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    for command in ("show", "approve", "reject"):
        child = sub.add_parser(command)
        child.add_argument("id")
        if command == "approve":
            child.add_argument("--digest", required=True)
    args = parser.parse_args(argv)
    try:
        store = store or configured_store()
        if args.command == "list":
            for record in store.list_pending():
                print(
                    record.id,
                    record.recipient_label,
                    record.subject,
                    record.created_at,
                    record.expires_at,
                )
        elif args.command == "show":
            record = store.get(args.id)
            print(
                f"{record.id} [{record.state}]\nTo: {record.recipient}\n"
                f"Subject: {record.subject}\n\n{record.body}"
            )
            print(f"\nDigest: {record.digest[:12]}\nExpires: {record.expires_at}")
        elif args.command == "approve":
            if not (stdin or sys.stdin).isatty():
                raise ApprovalRefused("terminal_required")
            print(store.approve(args.id, args.digest).id, "approved")
        else:
            print(store.reject(args.id).id, "rejected")
        return 0
    except (ApprovalRefused, OSError) as exc:
        print(
            f"refused: {getattr(exc, 'reason', 'store_unavailable')}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
