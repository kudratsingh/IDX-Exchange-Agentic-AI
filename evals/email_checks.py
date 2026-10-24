"""Offline approval scenarios using temporary ledgers and the actual local transport."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from idx_agent.safety.approval import ApprovalRefused, ApprovalStore

OPERATIONS = {
    "draft",
    "approve",
    "approve_with_digest",
    "reject",
    "expire",
    "advance_minutes",
    "alter_field",
    "send",
    "claim",
    "unknown_send",
}


def validate_steps(expect):
    steps = expect.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        return "expect.steps must contain 1 to 100 steps"
    for step in steps:
        if not isinstance(step, dict) or step.get("do") not in OPERATIONS:
            return "each approval step must name a supported do operation"
        if not isinstance(step.get("outcome"), str) or not step["outcome"]:
            return "each approval step needs an outcome code"
        if set(step) - {"do", "outcome", "minutes", "field", "digest"}:
            return "approval step has unsupported fields"
        if step["do"] == "advance_minutes" and (
            type(step.get("minutes")) is not int or step["minutes"] < 0
        ):
            return "advance_minutes requires nonnegative integer minutes"
        if step["do"] == "alter_field" and step.get("field") not in {
            "recipient",
            "subject",
            "body",
        }:
            return "alter_field requires recipient, subject or body"
    return None


def run_steps(steps):
    # Delivery imported only within this offline operator simulation, never by MCP.
    from idx_agent.email.send import send

    with tempfile.TemporaryDirectory(prefix="idx-email-eval-") as scratch:
        root = Path(scratch)
        now = [datetime(2026, 10, 24, tzinfo=UTC)]
        store = ApprovalStore(
            root / "data" / "email",
            data_root=root / "data",
            is_ignored=lambda _: True,
            clock=lambda: now[0],
        )
        record = None
        with patch(
            "idx_agent.email.send.resolve_recipient", return_value="owner@example.com"
        ):
            for number, step in enumerate(steps, 1):
                try:
                    op = step["do"]
                    if op == "draft":
                        record = store.create_draft(
                            recipient_label="owner",
                            recipient="owner@example.com",
                            source="market",
                            subject="Invented report",
                            body="Invented closed-sale figures.",
                        )
                        actual = record.state
                    elif op == "unknown_send":
                        store.claim_send("draft-" + "f" * 12)
                        actual = "unexpected_success"
                    elif op == "advance_minutes":
                        now[0] += timedelta(minutes=step["minutes"])
                        actual = "advanced"
                    elif record is None:
                        return False, f"step {number}: no draft"
                    elif op in {"approve", "approve_with_digest"}:
                        actual = store.approve(
                            record.id, step.get("digest", record.digest[:12])
                        ).state
                    elif op in {"reject", "expire"}:
                        actual = getattr(store, op)(record.id).state
                    elif op == "claim":
                        actual = store.claim_send(record.id).state
                    elif op == "send":
                        send(store, record.id)
                        actual = "sent"
                    else:
                        events = [
                            json.loads(line)
                            for line in store.path.read_text().splitlines()
                        ]
                        events[-1]["record"][step["field"]] = (
                            "changed@example.com"
                            if step["field"] == "recipient"
                            else "Changed"
                        )
                        store.path.write_text(
                            "".join(json.dumps(e) + "\n" for e in events)
                        )
                        actual = "altered"
                except ApprovalRefused as exc:
                    actual = exc.reason
                if actual != step["outcome"]:
                    return (
                        False,
                        f"step {number}: expected {step['outcome']}, got {actual}",
                    )
        return True, f"{len(steps)} approval steps passed"
