"""Sender identity: a keyed hash of the normalized sender id, never the raw id.

`sender_key` is the only place a raw sender id is read. It returns an HMAC-SHA256
hex digest under IDX_SENDER_KEY (hex, 32+ characters), or None; nothing here logs
or stores the input.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from idx_agent.db.pool import env_setting

__all__ = ["SENDER_KEY_ENV", "key_prefix", "secret_configured", "sender_key"]

# Environment variable holding the HMAC secret; its value is never logged.
SENDER_KEY_ENV = "IDX_SENDER_KEY"
# A usable secret: hex, at least 32 characters (128 bits), either case. A placeholder
# or a short or non-hex value counts as "not configured", so nothing is remembered.
_SECRET = re.compile(r"^[0-9a-fA-F]{32,}$")
# Separators people and channels put inside a phone number; removed before hashing.
_SEPARATORS = re.compile(r"[\s\-().]")
# One E.164 number once separators are gone: optional +, no leading 0, 8-15 digits.
_E164 = re.compile(r"^\+?[1-9][0-9]{7,14}$")


def _normalize(raw_sender_id: str) -> str | None:
    """Return the id as "+<digits>" (one E.164 form), or None if it is not a number.

    Spaces, dashes, parentheses, and dots are removed; "+1 (555) ..." and "1555..."
    give the same result.
    """
    compact = _SEPARATORS.sub("", raw_sender_id)
    if not _E164.fullmatch(compact):
        return None
    return "+" + compact.lstrip("+")


def secret_configured(secret: str | None) -> bool:
    """True when `secret` is usable as the HMAC key: hex of at least 32 characters."""
    return isinstance(secret, str) and _SECRET.fullmatch(secret) is not None


def sender_key(raw_sender_id: str, secret: str | None = None) -> str | None:
    """Return a lowercase hex HMAC-SHA256 of the normalized id, or None.

    The secret is `secret`, else IDX_SENDER_KEY (environment, then .env). None when
    the secret is missing or not configured (see secret_configured) or the id does
    not normalize; there is no unkeyed fallback.
    """
    key = secret if secret is not None else env_setting(SENDER_KEY_ENV)
    if key is None or not secret_configured(key) or not isinstance(raw_sender_id, str):
        return None
    normalized = _normalize(raw_sender_id)
    if normalized is None:
        return None
    digest = hmac.new(key.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def key_prefix(key: str | None) -> str:
    """Return the first 8 characters of a sender key for log lines ("-" when None).

    Logs carry only this prefix, never the full key or the raw id.
    """
    return key[:8] if key else "-"
