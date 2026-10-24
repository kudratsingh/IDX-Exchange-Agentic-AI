"""Operator-only email delivery: one claim, one attempt, no automatic retries."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from idx_agent.domain.results import SendReceipt
from idx_agent.email.recipients import resolve_recipient, validate_address
from idx_agent.email.settings import setting
from idx_agent.safety import consent
from idx_agent.safety.approval import ApprovalRefused, ApprovalStore


def send(
    store: ApprovalStore, draft_id: str, *, transport: str = "sink", smtp_factory=None
) -> SendReceipt:
    """Write a local .eml or deliver with Gmail SSL; failures remain locked forever."""
    if transport not in {"sink", "smtp"}:
        raise ApprovalRefused("unknown_transport")
    action = store.get(draft_id)
    if action.recipient != resolve_recipient(action.recipient_label):
        raise ApprovalRefused("recipient_not_allowed")
    message = EmailMessage()
    message["To"] = action.recipient
    message["Subject"] = action.subject
    if transport == "smtp":
        # Credentials are read only here; Gmail host and SSL port are fixed.
        user = setting("EMAIL_USER", sending=True) or ""
        password = setting("EMAIL_PASSWORD", sending=True) or ""
        sender = validate_address(setting("EMAIL_FROM", sending=True) or user)
        if not user or not password:
            raise ApprovalRefused("smtp_not_configured")
        message["From"] = sender
        # Exact process argv and single-call ceiling are enforced by the existing gate.
        consent.start_paid_run()
        consent.spend_paid_call(1)
    else:
        message["From"] = action.recipient
    message.set_content(action.body)
    if action.source in {"property", "recommendations"}:
        from idx_agent.email.photos import render_html

        message.add_alternative(render_html(action.body), subtype="html")
    # The journal claim serializes concurrent sends and is durable before any transport.
    action = store.claim_send(draft_id)
    try:
        if transport == "sink":
            outbox = store.directory / "outbox"
            outbox.mkdir(mode=0o700, exist_ok=True)
            if outbox.is_symlink():
                raise ApprovalRefused("unsafe_store")
            target = outbox / (draft_id + ".eml")
            _write_sink(target, message.as_bytes())
        else:
            factory = smtp_factory or smtplib.SMTP_SSL
            with factory(
                "smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20
            ) as smtp:
                smtp.login(user, password)
                refused = smtp.send_message(message)
                if refused:
                    raise ApprovalRefused("delivery_refused")
    except Exception:
        store.record_delivery(draft_id, False)
        if transport == "smtp":
            consent.abort_paid_run("smtp_failed")
        raise ApprovalRefused("delivery_failed_locked") from None
    store.record_delivery(draft_id, True)
    return SendReceipt(
        id=action.id,
        transport=transport,
        sent_at=store.clock(),
        digest_prefix=action.digest[:12],
    )


def _write_sink(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
