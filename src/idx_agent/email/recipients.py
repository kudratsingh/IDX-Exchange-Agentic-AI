"""Owner-only recipient resolution, separate from model-passed identity."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from idx_agent.email.settings import setting as env_setting
from idx_agent.safety.approval import ROOT, ApprovalRefused, ApprovalStore


def validate_address(address: str) -> str:
    if (
        not isinstance(address, str)
        or len(address) > 254
        or not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",
            address,
        )
    ):
        raise ApprovalRefused("recipient_not_allowed")
    return address


def resolve_recipient(label: str = "owner") -> str:
    if label != "owner":
        raise ApprovalRefused("recipient_not_allowed")
    try:
        recipients = json.loads(env_setting("IDX_EMAIL_RECIPIENTS") or "{}")
        if not isinstance(recipients, dict) or set(recipients) != {"owner"}:
            raise ApprovalRefused("recipient_not_configured")
        return validate_address(recipients["owner"])
    except (ValueError, TypeError, KeyError):
        raise ApprovalRefused("recipient_not_configured") from None


def configured_store() -> ApprovalStore:
    directory = Path(env_setting("IDX_EMAIL_STORE_DIR") or ROOT / "data" / "email")
    if not directory.is_absolute():
        directory = ROOT / directory
    try:
        ttl = float(env_setting("IDX_EMAIL_DRAFT_TTL_HOURS") or "24")
        window = float(env_setting("IDX_EMAIL_APPROVAL_MINUTES") or "30")
        if not (0 < ttl <= 168 and 0 < window <= 60):
            raise ValueError
    except ValueError:
        raise ApprovalRefused("invalid_email_settings") from None
    return ApprovalStore(
        directory, ttl=timedelta(hours=ttl), approval_window=timedelta(minutes=window)
    )
