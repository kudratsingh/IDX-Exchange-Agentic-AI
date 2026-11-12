"""Shared private-file, usage and transport helpers for the WO-034 v3 drivers.

The transport is the standard Messages API over `urllib`, as in the v2.1 driver; no
provider SDK is imported. Nothing here reads a key or sends a request unless a paid
run, after `paid_token_preflight` (read-only), calls `attempt` with a key."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts.extract_enrichment_dev import ENDPOINT, _write_new  # noqa: E402
from scripts.score_enrichment_private import (  # noqa: E402
    _private_path,
    _read_private,
    _sample_jsonl,
)

from idx_agent.enrichment.dev_extraction import ProviderFailure  # noqa: E402
from idx_agent.safety import consent  # noqa: E402

ORIGINAL_GOLD_SHA256 = (
    "6aab5483839e534615e753d100a66acddd9b7a121f50c03e2ba85f4f250ebde7"
)
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
_KEY = re.compile(r'^\s*\{\s*"key"\s*:\s*"([0-9]+)"')

__all__ = [
    "ENDPOINT",
    "ORIGINAL_GOLD_SHA256",
    "USAGE_FIELDS",
    "AttemptError",
    "ProviderFailure",
    "Usage",
    "atomic_write",
    "decode",
    "attempt",
    "file_sha256",
    "load_split",
    "paid_token_preflight",
    "private_subdir",
    "read_checkpoint",
    "read_key",
    "read_private",
    "revised_gold",
    "send_with_retries",
    "write_checkpoint",
    "write_new",
]

read_private = _read_private
write_new = _write_new


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_split(root: Path, split: str) -> tuple[dict, dict[str, str]]:
    """The scorer's sample (id, split, text) plus the split's subtypes beside it.

    `_sample_jsonl` validates the files and drops the subtype; this second pass
    keeps the subtype for the mapper only. `score_v2` never receives it."""
    sample = _sample_jsonl(root, split)
    splits = _read_private(root, "splits.json")["splits"]
    subtypes: dict[str, str] = {}
    with _private_path(root, "sample.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            key = _KEY.match(line).group(1)
            if splits[key] == split:
                subtypes[key] = json.loads(line)["subtype"]
    ids = {case["id"] for case in sample["cases"] if case["split"] == split}
    if set(subtypes) != ids:
        raise ValueError("invalid private sample")
    return sample, subtypes


def revised_gold(root: Path, name: str, expected_sha256: str) -> tuple[dict, str]:
    """Load a revised gold file by name and recorded hash; never `labels.json`."""
    if not isinstance(name, str) or Path(name).name != name or name == "labels.json":
        raise ValueError("a revised gold file is required, not labels.json")
    if not (root / name).is_file():
        raise ValueError("the revised gold file is missing")
    path = _private_path(root, name)
    digest = file_sha256(path)
    if digest == ORIGINAL_GOLD_SHA256:
        raise ValueError("the gold file is the original labels.json")
    if digest != expected_sha256:
        raise ValueError("revised gold hash mismatch")
    return _read_private(root, name), digest


def private_subdir(path: Path, *, exist_ok: bool) -> Path:
    """Create (or reuse) an owner-only directory under the private root."""
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("invalid private directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=exist_ok)
    if path.stat().st_mode & 0o077:
        raise ValueError("invalid private directory permissions")
    return path


def atomic_write(path: Path, value: dict) -> None:
    """Replace a private JSON file durably (temporary file, fsync, rename). An
    interrupted write leaves the old file and removes its own temporary file."""
    temporary = _temporary(path)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
    _fsync_directory(path.parent)


def _temporary(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")


def _fsync_directory(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_checkpoint(path: Path, raw: bytes, usage) -> None:
    """Write a checkpoint once and whole: a temporary file, fsync, then a hard link
    that fails if the checkpoint exists. An interrupted write leaves either no
    checkpoint or the complete one, never a partial file."""
    temporary = _temporary(path)
    try:
        _write_new(
            temporary, {"raw": base64.b64encode(raw).decode("ascii"), "usage": usage}
        )
        os.link(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
    _fsync_directory(path.parent)


def read_checkpoint(path: Path) -> tuple[object, object, bytes]:
    """(response, usage, raw) from a checkpoint written by `write_checkpoint`."""
    stored = json.loads(path.read_text(encoding="utf-8"))
    raw = base64.b64decode(stored["raw"])
    return decode(raw)[0], stored.get("usage"), raw


def paid_token_preflight() -> int:
    """The call ceiling of the `paid` token minted for this process's own command
    line, read without spending it: no key read, no token or audit-log write. A
    missing, expired, consumed, malformed or mismatched token is a ValueError, so a
    run refuses before the key is read. `consent.start_paid_run` stays the
    authoritative check; the driver repeats the ceiling check on its grant."""
    module = consent.reader()
    reason = module.paid_reason(consent.invocation_argv())
    if reason not in (None, "admitted"):
        raise ValueError(f"no usable paid token ({reason})")
    max_calls = module.paid_token_status().get("max_calls")
    if type(max_calls) is not int or max_calls < 1:
        raise ValueError("no usable paid token (malformed)")
    return max_calls


def read_key() -> str:
    """The provider key, read only by a paid run after every precondition."""
    from evals.run import _local_setting

    return _local_setting("ANTHROPIC_API_KEY")


class AttemptError(RuntimeError):
    """One failed request: a sanitized error class, whether the frozen retry gate
    retries it, whether it is an auth failure, and the private response bytes."""

    def __init__(self, category: str, retryable: bool, raw: bytes | None) -> None:
        super().__init__(category)
        self.category, self.retryable, self.raw = category, retryable, raw
        self.auth = category == "AuthenticationError"


def attempt(body: dict, key: str, timeout: float = 90) -> bytes:
    """Send one standard Messages API request and return the response bytes.

    Classification is the v2.1 retry gate's: 429, 5xx, timeouts and connection
    errors are retryable; 401/403 are auth failures; other HTTP errors are not
    retryable."""
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        if exc.code == 429:
            raise AttemptError("RateLimitError", True, raw) from None
        if 500 <= exc.code <= 599:
            raise AttemptError("ServerError", True, raw) from None
        if exc.code in (401, 403):
            raise AttemptError("AuthenticationError", False, raw) from None
        raise AttemptError("ClientError", False, raw) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        category = (
            "TimeoutError" if isinstance(reason, TimeoutError) else "ConnectionError"
        )
        raise AttemptError(category, True, None) from None


def decode(raw: bytes):
    """(response, usage) from response bytes; invalid JSON is a parser miss."""
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"invalid_response": True}, None
    return response, response.get("usage") if isinstance(response, dict) else None


def send_with_retries(body, key, retries, spend, send=None, sleep=None):
    """The v2.1 retry gate: at most three attempts, one spent call each, retrying
    only retryable errors. Returns (response, usage, raw); raises ProviderFailure."""
    send, sleep = send or attempt, sleep or time.sleep
    retry_cause = None
    for number in range(1, 4):
        spend()
        if retry_cause is not None:
            retries[retry_cause] = retries.get(retry_cause, 0) + 1
        try:
            raw = send(body, key)
            break
        except AttemptError as error:
            last = error
        print(
            json.dumps(
                {
                    "provider_error": {
                        "error_class": last.category,
                        "attempt": number,
                        "retrying": last.retryable and number < 3,
                    }
                }
            ),
            flush=True,
        )
        if not last.retryable or number == 3:
            raise ProviderFailure(last.raw, "provider_failure") from None
        retry_cause = last.category
        sleep(2 ** (number - 1))
    response, usage = decode(raw)
    return response, usage, raw


class Usage:
    """Provider-reported token totals; a field is reported only when every
    counted response carried it."""

    def __init__(self) -> None:
        self.totals = dict.fromkeys(USAGE_FIELDS, 0)
        self.known = dict.fromkeys(USAGE_FIELDS, 0)
        self.responses = 0

    def add(self, usage) -> None:
        self.responses += 1
        if not isinstance(usage, dict):
            return
        for field in USAGE_FIELDS:
            if type(usage.get(field)) is int and usage[field] >= 0:
                self.totals[field] += usage[field]
                self.known[field] += 1

    def report(self, cases: int) -> dict:
        complete = {f: self.known[f] == cases for f in USAGE_FIELDS}
        return {
            "totals": {
                f: self.totals[f] if complete[f] else None for f in USAGE_FIELDS
            },
            "per_remark": {
                f: self.totals[f] / cases if complete[f] else None for f in USAGE_FIELDS
            },
        }
