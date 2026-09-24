"""Text preparation and embedders: paid OpenAI, and hashing for tests (WO-010).

`prepare_text` is the one text rule for the build and every query. `OpenAIEmbedder`
imports `openai` lazily and checks the `paid` token and key before every request
(failures are `ProviderError`); `HashingEmbedder` is NumPy-only, for tests and CI."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from idx_agent.db.pool import env_setting
from idx_agent.observability.logging import redact as redact_text
from idx_agent.safety.consent import paid_consent_active

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_DIMS",
    "DEFAULT_MODEL",
    "HASHING_DIMS",
    "MAX_CHARS",
    "MIN_CHARS",
    "OPENAI_DIMS",
    "TEST_MODEL",
    "TEXT_PREP_VERSION",
    "UNIT_TOLERANCE",
    "Embedder",
    "HashingEmbedder",
    "OpenAIEmbedder",
    "PreparedText",
    "ProviderError",
    "embed_settings",
    "make_embedder",
    "model_label",
    "prepare",
    "prepare_text",
    "redact_enabled",
]

# The spike's profile: the longest active remark is 4,000 characters, so this cut
# keeps every remark whole and stays far under the model's input limit.
MAX_CHARS = 4000
# Shorter text (after collapsing whitespace) carries too little to embed usefully.
MIN_CHARS = 20
# Bump when prepare_text changes; the index records it so old and new never mix.
TEXT_PREP_VERSION = 1
DEFAULT_MODEL = "openai:text-embedding-3-small"
DEFAULT_DIMS = 1536
# The dimensions the API is asked for: full size, or 512 under the cold-start rule.
OPENAI_DIMS = frozenset({512, 1536})
TEST_MODEL = "test:hashing"
HASHING_DIMS = 64
# Inputs per embeddings request; the API allows more, smaller batches fail cheaper.
BATCH_SIZE = 100
# Seconds one request may take; the tool's whole call must fit the 30 s MCP limit.
TIMEOUT_S = 10.0
# How far from length 1 a vector may be: the one tolerance for the embedders, the
# build, the index checks, and the tool.
UNIT_TOLERANCE = 1e-3
_OPENAI_PREFIX = "openai:"
# Links become a placeholder too (redact() covers emails, phones, and secrets).
_LINK = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")


class ProviderError(RuntimeError):
    """The embedding provider was not called or did not answer usably.

    `reason` is one of: missing_key, no_consent, missing_package, timeout, failed,
    bad_response. The message is fixed text; provider detail is never kept.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"embedding provider unavailable: {reason}")
        self.reason = reason


class Embedder(Protocol):
    """Turns texts into unit-length float32 rows of width `dims`."""

    name: str
    dims: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass(frozen=True)
class PreparedText:
    """prepare()'s result: the text (None when unusable) and what changed on the way."""

    text: str | None
    truncated: bool = False
    redacted: bool = False


def prepare(
    remarks: str | None, max_chars: int = MAX_CHARS, redact: bool = True
) -> PreparedText:
    """Collapse whitespace; None under MIN_CHARS; mask links, emails, phones; cut.

    `redacted` is True when masking changed the text; `truncated` when the cut did.
    """
    if remarks is None:
        return PreparedText(None)
    text = _WHITESPACE.sub(" ", str(remarks)).strip()
    if len(text) < MIN_CHARS:
        return PreparedText(None)
    redacted = False
    if redact:
        masked = redact_text(_LINK.sub("[link]", text))
        redacted = masked != text
        text = masked
    truncated = len(text) > max_chars
    return PreparedText(text[:max_chars], truncated=truncated, redacted=redacted)


def prepare_text(
    remarks: str | None, max_chars: int = MAX_CHARS, redact: bool = True
) -> str | None:
    """The text to embed for one remark, or None when it is missing or too short."""
    return prepare(remarks, max_chars, redact).text


def model_label(model: str, dims: int) -> str:
    """The model string results carry: "openai:text-embedding-3-small@1536"."""
    return f"{model}@{dims}"


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to length 1 in float32; a zero row stays zero."""
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


class HashingEmbedder:
    """Deterministic bag-of-words vectors for tests: sha256 of each token picks a slot
    and a sign. Unusable text (prepare_text gives None, or no a-z/0-9 token) gives a
    zero row, which `rank` and the build treat as unusable."""

    name = TEST_MODEL

    def __init__(self, dims: int = HASHING_DIMS) -> None:
        if dims < 1:
            raise ValueError("dims must be at least 1")
        self.dims = dims
        self.last_usage_tokens: int | None = None

    def vector(self, text: str) -> np.ndarray:
        """One unit (or zero) row for `text`, float32."""
        row = np.zeros(self.dims, dtype=np.float32)
        prepared = prepare_text(text)
        if prepared is None:
            return row
        for token in _TOKEN.findall(prepared.lower()):
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            row[h % self.dims] += 1.0 if (h >> 8) % 2 == 0 else -1.0
        return _unit_rows(row[None, :])[0]

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Rows for `texts`, shape (len(texts), dims)."""
        rows = [self.vector(text) for text in texts]
        if not rows:
            return np.zeros((0, self.dims), dtype=np.float32)
        return np.vstack(rows)


class OpenAIEmbedder:
    """OpenAI embeddings (text-embedding-3-small), a paid call per request.

    Before every request: a valid `paid` consent token and OPENAI_API_KEY in the
    process environment, else ProviderError and no call. Inputs go in batches of at
    most `batch_size`; `last_usage_tokens` holds the tokens the API reported.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        dims: int = DEFAULT_DIMS,
        *,
        client: Any = None,
        environ: Mapping[str, str] | None = None,
        consent_check: Callable[[], bool] = paid_consent_active,
        timeout: float = TIMEOUT_S,
        batch_size: int = BATCH_SIZE,
        max_retries: int = 0,
    ) -> None:
        if not model.startswith(_OPENAI_PREFIX):
            raise ValueError("OpenAIEmbedder needs an 'openai:' model name")
        if dims not in OPENAI_DIMS:
            raise ValueError(f"dims must be one of {sorted(OPENAI_DIMS)}")
        if not 1 <= batch_size <= BATCH_SIZE:
            raise ValueError(f"batch_size must be 1..{BATCH_SIZE}")
        self.name = model
        self.dims = dims
        self.api_model = model.removeprefix(_OPENAI_PREFIX)
        self.timeout = timeout
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._client = client
        self._environ = environ
        self._consent_check = consent_check
        self.last_usage_tokens: int | None = None

    def _key(self) -> str:
        """OPENAI_API_KEY from the process environment only (not .env; never logged)."""
        env = os.environ if self._environ is None else self._environ
        key = (env.get("OPENAI_API_KEY") or "").strip()
        if not key:
            raise ProviderError("missing_key")
        return key

    def _get_client(self, key: str) -> Any:
        """The injected client, or a real one built on first use."""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ProviderError("missing_package") from None
            self._client = OpenAI(
                api_key=key, timeout=self.timeout, max_retries=self.max_retries
            )
        return self._client

    def _request(self, client: Any, batch: list[str]) -> tuple[np.ndarray, int | None]:
        """One embeddings request; returns the rows in input order and the usage."""
        try:
            response = client.embeddings.create(
                model=self.api_model,
                input=batch,
                dimensions=self.dims,
                timeout=self.timeout,
            )
        except Exception as exc:  # any provider failure; the detail is dropped
            timed_out = isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__
            raise ProviderError("timeout" if timed_out else "failed") from None
        try:
            items = sorted(response.data, key=lambda item: item.index)
            matrix = np.asarray([item.embedding for item in items], dtype=np.float32)
            usage = getattr(getattr(response, "usage", None), "total_tokens", None)
        except (AttributeError, TypeError, ValueError):
            raise ProviderError("bad_response") from None
        if matrix.shape != (len(batch), self.dims):
            raise ProviderError("bad_response")
        rows = _unit_rows(matrix)
        if np.any(np.abs(np.linalg.norm(rows, axis=1) - 1.0) > UNIT_TOLERANCE):
            raise ProviderError("bad_response")
        return rows, (int(usage) if usage is not None else None)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Unit rows for `texts` (each a non-empty string of at most MAX_CHARS).

        Raises ProviderError (no consent, no key, timeout, failure) before or instead
        of returning; nothing is logged here.
        """
        batch_texts = list(texts)
        for text in batch_texts:
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS:
                raise ValueError("each input must be non-empty text of <= MAX_CHARS")
        self.last_usage_tokens = None
        if not batch_texts:
            return np.zeros((0, self.dims), dtype=np.float32)
        if not self._consent_check():
            raise ProviderError("no_consent")
        client = self._get_client(self._key())
        parts: list[np.ndarray] = []
        usage_total: int | None = 0
        for start in range(0, len(batch_texts), self.batch_size):
            rows, usage = self._request(
                client, batch_texts[start : start + self.batch_size]
            )
            parts.append(rows)
            usage_total = (
                None if usage is None or usage_total is None else usage_total + usage
            )
        self.last_usage_tokens = usage_total
        return np.vstack(parts)


def redact_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """IDX_EMBED_REDACT: on unless set to 0, false, no, or off."""
    value = (env_setting("IDX_EMBED_REDACT", environ) or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def embed_settings(environ: Mapping[str, str] | None = None) -> tuple[str, int]:
    """(model, dims) from IDX_EMBED_MODEL and IDX_EMBED_DIMS (environment, then .env).

    Defaults: the OpenAI model at 1536; `test:hashing` defaults to 64. A bad value
    raises ValueError.
    """
    model = (env_setting("IDX_EMBED_MODEL", environ) or DEFAULT_MODEL).strip()
    if model not in {DEFAULT_MODEL, TEST_MODEL}:
        raise ValueError("IDX_EMBED_MODEL names an unknown model")
    raw = (env_setting("IDX_EMBED_DIMS", environ) or "").strip()
    if not raw:
        return model, HASHING_DIMS if model == TEST_MODEL else DEFAULT_DIMS
    try:
        dims = int(raw)
    except ValueError:
        raise ValueError("IDX_EMBED_DIMS must be a whole number") from None
    if model == DEFAULT_MODEL and dims not in OPENAI_DIMS:
        raise ValueError(f"IDX_EMBED_DIMS must be one of {sorted(OPENAI_DIMS)}")
    if dims < 1:
        raise ValueError("IDX_EMBED_DIMS must be at least 1")
    return model, dims


def make_embedder(model: str, dims: int, **kwargs: Any) -> Embedder:
    """The embedder for a model name; extra arguments go to OpenAIEmbedder."""
    if model == TEST_MODEL:
        return HashingEmbedder(dims)
    return OpenAIEmbedder(model, dims, **kwargs)
