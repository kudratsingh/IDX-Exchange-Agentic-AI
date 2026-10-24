"""Append-only email approval ledger; only operator commands approve or claim sends.

The filesystem is the trust boundary, not a model-passed sender id. A failed or
interrupted send stays locked. Journal corruption fails closed, without rewriting.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from idx_agent.domain.results import EmailDraftView, PendingAction

ROOT = Path(__file__).resolve().parents[3]
_LOCK = threading.RLock()
_ID = re.compile(r"^draft-[0-9a-f]{12}$")


class ApprovalRefused(Exception):
    """A fixed refusal code, never journal content or credentials."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def digest(record: PendingAction) -> str:
    """Bind content, recipient and immutable metadata to the stored draft id."""
    values = [
        record.id,
        record.kind,
        record.recipient,
        record.recipient_label,
        record.source,
        record.subject,
        record.body,
        record.created_at.isoformat(),
        record.expires_at.isoformat() if record.expires_at else None,
        record.idempotency_key,
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()


def view(record: PendingAction) -> EmailDraftView:
    """Return a preview containing no recipient address."""
    return EmailDraftView(
        id=record.id,
        recipient_label=record.recipient_label,
        source=record.source,
        subject=record.subject,
        body=record.body,
        expires_at=record.expires_at,
        digest_prefix=record.digest[:12],
        state=record.state,
    )


def ignored(path: Path, root: Path = ROOT) -> bool:
    """Check the actual Git ignore policy without changing it."""
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", str(path)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


class ApprovalStore:
    """One locked 0600 JSON-lines journal under ignored data; each event is durable."""

    def __init__(
        self,
        directory: Path,
        *,
        data_root: Path = ROOT / "data",
        is_ignored: Callable[[Path], bool] = ignored,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ttl: timedelta = timedelta(hours=24),
        approval_window: timedelta = timedelta(minutes=30),
    ):
        directory, data_root = Path(directory).absolute(), Path(data_root).resolve()
        if directory.is_symlink() or not directory.resolve().is_relative_to(data_root):
            raise ApprovalRefused("unsafe_store")
        if (
            not is_ignored(directory)
            or ttl <= timedelta(0)
            or approval_window <= timedelta(0)
        ):
            raise ApprovalRefused("unsafe_store")
        self.directory, self.clock = directory.resolve(), clock
        self.ttl, self.approval_window = ttl, approval_window
        self.path = self.directory / "pending.jsonl"

    @contextmanager
    def _journal(self) -> Iterator[tuple[object, dict[str, PendingAction]]]:
        with _LOCK:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Resolve again after mkdir; refuse symlink redirection at use time too.
            if self.directory.resolve() != self.directory or self.path.is_symlink():
                raise ApprovalRefused("unsafe_store")
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "r+", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                fcntl.flock(handle, fcntl.LOCK_EX)
                records: dict[str, PendingAction] = {}
                try:
                    for line in handle:
                        event = json.loads(line)
                        action = PendingAction.model_validate(event["record"])
                        if action.digest != digest(action):
                            raise ApprovalRefused("changed_since_approval")
                        previous = records.get(action.id)
                        allowed = {
                            None: {"pending"},
                            "pending": {"approved", "rejected", "expired"},
                            "approved": {"sending", "rejected", "expired"},
                            "sending": {"sending", "sent"},
                        }
                        old_state = previous.state if previous else None
                        if action.state not in allowed.get(old_state, set()):
                            raise ApprovalRefused("invalid_journal")
                        if previous and (
                            previous.digest != action.digest
                            or (
                                old_state != "pending"
                                and previous.approved_at != action.approved_at
                            )
                        ):
                            raise ApprovalRefused("changed_since_approval")
                        records[action.id] = action
                except (ValueError, KeyError, TypeError):
                    raise ApprovalRefused("invalid_journal") from None
                yield handle, records

    def _append(self, handle, action: PendingAction, event: str) -> PendingAction:
        record = action.model_dump(mode="json")
        record["recipient"] = action.recipient
        handle.seek(0, os.SEEK_END)
        handle.write(
            json.dumps(
                {
                    "event": event,
                    "at": self.clock().isoformat(),
                    "record": record,
                }
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
        return action

    def _current(self, handle, records, draft_id: str) -> PendingAction:
        if not _ID.fullmatch(draft_id) or draft_id not in records:
            raise ApprovalRefused("unknown_draft")
        action = records[draft_id]
        if action.state in {"pending", "approved"} and (
            action.expires_at is None or self.clock() >= action.expires_at
        ):
            action = action.model_copy(update={"state": "expired"})
            self._append(handle, action, "expired")
            records[draft_id] = action
        return action

    def create_draft(
        self,
        *,
        recipient_label: str,
        recipient: str,
        source: str,
        subject: str,
        body: str,
        idempotency_key: str | None = None,
    ) -> PendingAction:
        from idx_agent.email.bodies import check_content
        from idx_agent.email.recipients import validate_address

        if recipient_label != "owner":
            raise ApprovalRefused("recipient_not_allowed")
        validate_address(recipient)
        check_content(subject, body)
        now = self.clock()
        with self._journal() as (handle, records):
            if idempotency_key:
                for action in records.values():
                    if action.idempotency_key == idempotency_key:
                        return self._current(handle, records, action.id)
            action = PendingAction(
                id="draft-" + secrets.token_hex(6),
                recipient=recipient,
                recipient_label=recipient_label,
                source=source,
                subject=subject,
                body=body,
                created_at=now,
                expires_at=now + self.ttl,
                idempotency_key=idempotency_key,
            )
            action = action.model_copy(update={"digest": digest(action)})
            return self._append(handle, action, "created")

    def get(self, draft_id: str) -> PendingAction:
        with self._journal() as (handle, records):
            return self._current(handle, records, draft_id)

    def list_pending(self) -> list[PendingAction]:
        with self._journal() as (handle, records):
            return [
                action
                for key in list(records)
                if (action := self._current(handle, records, key)).state == "pending"
            ]

    def approve(self, draft_id: str, digest_prefix: str) -> PendingAction:
        with self._journal() as (handle, records):
            action = self._current(handle, records, draft_id)
            if action.state != "pending":
                raise ApprovalRefused(action.state)
            if len(digest_prefix) != 12 or not hmac.compare_digest(
                action.digest[:12], digest_prefix
            ):
                raise ApprovalRefused("changed_since_approval")
            action = action.model_copy(
                update={"state": "approved", "approved_at": self.clock()}
            )
            return self._append(handle, action, "approved")

    def _finish(self, draft_id: str, state: str) -> PendingAction:
        with self._journal() as (handle, records):
            action = self._current(handle, records, draft_id)
            if action.state not in {"pending", "approved"}:
                raise ApprovalRefused(action.state)
            action = action.model_copy(update={"state": state})
            return self._append(handle, action, state)

    def reject(self, draft_id: str) -> PendingAction:
        return self._finish(draft_id, "rejected")

    def expire(self, draft_id: str) -> PendingAction:
        return self._finish(draft_id, "expired")

    def claim_send(self, draft_id: str) -> PendingAction:
        with self._journal() as (handle, records):
            action = self._current(handle, records, draft_id)
            reasons = {
                "pending": "not_approved",
                "sending": "locked",
                "sent": "already_sent",
            }
            if action.state != "approved":
                raise ApprovalRefused(reasons.get(action.state, action.state))
            if (
                not action.approved_at
                or self.clock() - action.approved_at >= self.approval_window
            ):
                raise ApprovalRefused("stale_approval")
            action = action.model_copy(update={"state": "sending"})
            return self._append(handle, action, "send_started")

    def record_delivery(self, draft_id: str, success: bool) -> PendingAction:
        with self._journal() as (handle, records):
            action = self._current(handle, records, draft_id)
            if action.state != "sending":
                raise ApprovalRefused("not_sending")
            action = action.model_copy(
                update={"state": "sent" if success else "sending"}
            )
            return self._append(handle, action, "sent" if success else "send_failed")
