"""Temporary saved-search flows through the real MCP bodies and draft-only job."""

import hashlib
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from idx_agent.alerts import server
from idx_agent.alerts.run import run_job
from idx_agent.alerts.store import AlertStore
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import Listing
from idx_agent.safety.approval import ApprovalRefused, ApprovalStore

OPERATIONS = {
    "save",
    "list",
    "request_delete",
    "delete",
    "bad_delete",
    "request_forget",
    "forget",
    "refresh",
    "empty_refresh",
    "dry_run",
    "claim",
}


def validate_steps(expect):
    steps = expect.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        return "saved-search steps must contain 1 to 100 operations"
    for step in steps:
        if not isinstance(step, dict) or step.get("do") not in OPERATIONS:
            return "unsupported saved-search operation"
        if set(step) - {"do", "sender", "number", "outcome"}:
            return "unsupported saved-search step field"
        if step.get("sender", "a") not in {"a", "b"}:
            return "sender must be an invented fixture label"
        if "number" in step and (type(step["number"]) is not int or step["number"] < 1):
            return "number must be positive"
        if not isinstance(step.get("outcome"), str):
            return "every step needs an outcome"
    return None


def run_steps(steps):
    with tempfile.TemporaryDirectory(prefix="idx-alerts-eval-") as scratch:
        root = Path(scratch) / "data"

        def clock():
            return datetime(2026, 10, 24, tzinfo=UTC)

        store = AlertStore(
            root / "state/alerts.sqlite",
            data_root=root,
            is_ignored=lambda _: True,
            clock=clock,
        )
        gate = ApprovalStore(
            root / "email", data_root=root, is_ignored=lambda _: True, clock=clock
        )
        baseline = AsOfDates(active=date(2026, 9, 17), sold=date(2026, 9, 16))
        refreshed = AsOfDates(active=date(2026, 9, 18), sold=date(2026, 9, 17))
        codes = {}
        with (
            patch.object(server, "configured_store", return_value=store),
            patch.object(server, "configured_gate", return_value=gate),
            patch.object(
                server,
                "memory_key",
                side_effect=lambda label: hashlib.sha256(label.encode()).hexdigest(),
            ),
            patch.object(
                server.pool, "connect", return_value=SimpleNamespace(close=lambda: None)
            ),
            patch.object(server.asof, "get_asof_dates", return_value=baseline),
        ):
            for index, step in enumerate(steps, 1):
                op, sender, number = (
                    step["do"],
                    step.get("sender", "a"),
                    step.get("number", 1),
                )
                actual = "refused"
                if op == "save":
                    result = server.result(
                        "save_search", sender, raw={"city": "Pasadena", "min_beds": 3}
                    )
                    actual = "saved" if result.ok else "refused"
                elif op == "list":
                    result = server.result("list_saved_searches", sender)
                    actual = f"listed:{len(result.data)}" if result.ok else "refused"
                elif op.startswith("request_"):
                    action = "delete" if op == "request_delete" else "forget"
                    result = server.result(
                        "delete_saved_search" if action == "delete" else "forget_me",
                        sender,
                        number=number,
                    )
                    found = re.search(r"code ([a-f0-9]{8})", result.message or "")
                    if found:
                        codes[(sender, action, number)] = found[1]
                        actual = "confirmation"
                elif op in {"delete", "bad_delete", "forget"}:
                    action = "forget" if op == "forget" else "delete"
                    code = (
                        "wrong"
                        if op == "bad_delete"
                        else codes.get((sender, action, number), "missing")
                    )
                    result = server.result(
                        "forget_me" if action == "forget" else "delete_saved_search",
                        sender,
                        number=number,
                        confirm_code=code,
                    )
                    actual = "removed" if result.ok else "refused"
                elif op in {"refresh", "empty_refresh", "dry_run"}:
                    matches = (
                        []
                        if op == "empty_refresh"
                        else [
                            Listing(
                                listing_key=123,
                                listing_id="123",
                                city="Pasadena",
                                list_price=750_000,
                            )
                        ]
                    )
                    summary = run_job(
                        store,
                        gate,
                        reader=lambda *_, found=matches: (len(found), found),
                        dates=refreshed,
                        recipient="owner" + "@" + "example.test",
                        dry_run=op == "dry_run",
                    )
                    actual = (
                        f"drafts:{summary['drafts']}"
                        if not summary["failed"]
                        else "failed"
                    )
                elif op == "claim":
                    pending = gate.list_pending()
                    if pending:
                        try:
                            gate.claim_send(pending[0].id)
                            actual = "unexpected_success"
                        except ApprovalRefused as exc:
                            actual = exc.reason
                if actual != step["outcome"]:
                    return False, f"step {index}: {actual}; expected {step['outcome']}"
        return True, f"{len(steps)} saved-search operations matched"
