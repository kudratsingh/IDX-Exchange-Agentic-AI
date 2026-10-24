"""Email settings only; credentials are read solely by the operator delivery module."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_SETTINGS = {
    "IDX_EMAIL_RECIPIENTS",
    "IDX_EMAIL_STORE_DIR",
    "IDX_EMAIL_DRAFT_TTL_HOURS",
    "IDX_EMAIL_APPROVAL_MINUTES",
}
SEND_SETTINGS = {"EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"}


def setting(name: str, *, sending: bool = False) -> str | None:
    if name not in PUBLIC_SETTINGS and (not sending or name not in SEND_SETTINGS):
        return None
    if name in os.environ:
        return os.environ[name]
    try:
        lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("\"'")
    return None
