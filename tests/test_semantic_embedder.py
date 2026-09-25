"""Unit tests for semantic/embedder.py (WO-010); no key, no net.

The OpenAI embedder runs against a stub client only: the request shape, batching,
unit rows, usage tokens, and every refusal or failure mapped to ProviderError. The
paid budget it spends from is tested in test_consent_gate.py.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from idx_agent.safety import consent
from idx_agent.semantic import embedder as emb
from idx_agent.semantic.embedder import (
    HashingEmbedder,
    OpenAIEmbedder,
    ProviderError,
    embed_settings,
    prepare,
    prepare_text,
)

ROOT = Path(__file__).resolve().parents[1]
# Invented values: a key-shaped string that is not a real key, and a unique marker.
FAKE_KEY = "sk-" + "test-not-a-real-key"
MARKER = "zebracorn"


def _vec(text: str, dims: int) -> list[float]:
    """A deterministic, deliberately non-unit vector for one input text."""
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    return list(np.random.default_rng(seed).normal(size=dims) * 3.0)


class StubEmbeddings:
    """Records each create() call; returns rows in reverse index order, with usage."""

    def __init__(self, dims: int, fail: Exception | None = None) -> None:
        self.dims = dims
        self.fail = fail
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        data = [
            SimpleNamespace(index=i, embedding=_vec(text, self.dims))
            for i, text in enumerate(kwargs["input"])
        ]
        usage = SimpleNamespace(total_tokens=7 * len(data))
        return SimpleNamespace(data=list(reversed(data)), usage=usage)


def _embedder(dims: int = 1536, fail: Exception | None = None, **kwargs):
    """An OpenAIEmbedder over a stub client, with an unlimited stand-in budget and a
    fake key by default."""
    stub = StubEmbeddings(dims, fail)
    options = {"environ": {"OPENAI_API_KEY": FAKE_KEY}, "spend": lambda n: None}
    options.update(kwargs)
    client = SimpleNamespace(embeddings=stub)
    return OpenAIEmbedder(dims=dims, client=client, **options), stub


# --- prepare_text ---


def test_prepare_text_collapses_whitespace_and_keeps_short_text_out():
    assert prepare_text(None) is None
    assert prepare_text("  too   short  ") is None
    assert prepare_text("x" * 19) is None
    assert prepare_text("x" * 20) == "x" * 20
    assert prepare_text("Quiet  street,\n\tbig yard  here") == (
        "Quiet street, big yard here"
    )


# Built at runtime so this file never holds a literal address or number.
EMAIL = "someone" + "@" + "example.invalid"
PHONE = "555" + "-010-" + "0199"


def test_prepare_text_masks_links_emails_and_phones():
    text = (
        "Lovely home, see https://example.invalid/tour or www.example.invalid, "
        f"write to {EMAIL} or call {PHONE} today."
    )
    result = prepare(text)
    assert result.redacted is True
    assert "example.invalid" not in result.text
    assert PHONE not in result.text
    assert "[link]" in result.text
    assert "[email]" in result.text
    assert "[phone]" in result.text


def test_prepare_text_redaction_can_be_switched_off():
    text = f"Call {PHONE} for a showing of this home."
    assert prepare_text(text, redact=False) == text
    assert prepare(text, redact=False).redacted is False


def test_prepare_text_cuts_at_max_chars_and_says_so():
    long = "word " * 1000
    result = prepare(long, max_chars=4000)
    assert len(result.text) == 4000
    assert result.truncated is True
    assert prepare("a plain remark about a home", max_chars=4000).truncated is False
    assert emb.MAX_CHARS == 4000


# --- HashingEmbedder ---


def test_hashing_embedder_follows_the_shared_algorithm():
    text = "Quiet mid-century home with a big yard"
    got = HashingEmbedder(64).embed([text])[0]
    expected = np.zeros(64, dtype=np.float32)
    for token in ("quiet", "mid", "century", "home", "with", "a", "big", "yard"):
        h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        expected[h % 64] += 1.0 if (h >> 8) % 2 == 0 else -1.0
    expected /= np.linalg.norm(expected)
    assert got.dtype == np.float32
    assert np.allclose(got, expected, atol=1e-6)
    assert abs(float(np.linalg.norm(got)) - 1.0) < 1e-5


def test_hashing_embedder_is_deterministic_and_zero_for_unusable_text():
    embedder = HashingEmbedder()
    first = embedder.embed(["a bright condo with city views", "tiny"])
    second = embedder.embed(["a bright condo with city views", "tiny"])
    assert embedder.name == "test:hashing" and embedder.dims == 64
    assert first.shape == (2, 64)
    assert np.array_equal(first, second)
    assert not first[1].any()
    assert embedder.embed([]).shape == (0, 64)


# --- OpenAIEmbedder against a stub client ---


def test_request_names_the_model_and_configured_dimensions():
    embedder, stub = _embedder(512)
    rows = embedder.embed(["a quiet home with a big yard"])
    assert rows.shape == (1, 512)
    call = stub.calls[0]
    assert call["model"] == "text-embedding-3-small"
    assert call["dimensions"] == 512
    assert call["input"] == ["a quiet home with a big yard"]
    assert call["timeout"] == emb.TIMEOUT_S


def test_batches_stay_within_the_batch_size_and_keep_input_order():
    embedder, stub = _embedder(1536)
    texts = [f"invented remark number {i} about a home" for i in range(250)]
    rows = embedder.embed(texts)
    assert [len(c["input"]) for c in stub.calls] == [100, 100, 50]
    assert rows.shape == (250, 1536) and rows.dtype == np.float32
    assert np.allclose(np.linalg.norm(rows, axis=1), 1.0, atol=1e-5)
    # Rows come back reversed from the stub; the embedder restores input order.
    expected = np.asarray(_vec(texts[3], 1536), dtype=np.float32)
    assert np.allclose(rows[3], expected / np.linalg.norm(expected), atol=1e-5)
    assert embedder.last_usage_tokens == 7 * 250


def test_missing_key_makes_no_call():
    embedder, stub = _embedder(environ={})
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert info.value.reason == "missing_key"
    assert stub.calls == []


def test_the_key_falls_back_to_the_env_file(monkeypatch, tmp_path):
    """The tool server under OpenClaw has no shell environment, so .env fills the key
    the way it fills the database password (human decision, 2026-09-24)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    embedder, stub = _embedder(environ={})
    rows = embedder.embed(["a quiet home with a big yard"])
    assert rows.shape[0] == 1 and len(stub.calls) == 1
    # The environment still wins over the file.
    other, stub2 = _embedder(environ={"OPENAI_API_KEY": "from-environment"})
    other.embed(["a quiet home with a big yard"])
    assert other._key() == "from-environment" and len(stub2.calls) == 1


def test_a_refused_budget_makes_no_call():
    def refuse(n: int) -> None:
        raise consent.PaidRunRefused("over_budget")

    embedder, stub = _embedder(spend=refuse)
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert (info.value.reason, info.value.refusal) == ("no_consent", "over_budget")
    assert stub.calls == []


def test_every_batch_spends_one_call_before_its_request():
    spent: list[int] = []
    embedder, stub = _embedder(spend=spent.append, batch_size=2)
    embedder.embed([f"a quiet home number {i} with a yard" for i in range(5)])
    assert spent == [1, 1, 1] and len(stub.calls) == 3
    assert OpenAIEmbedder.max_retries == 0 and embedder.max_retries == 0


def test_no_budget_never_builds_a_real_client():
    """With no injected client and no paid run, nothing is imported or constructed."""
    embedder = OpenAIEmbedder(environ={"OPENAI_API_KEY": FAKE_KEY})
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert (info.value.reason, info.value.refusal) == ("no_consent", "no_budget")
    assert embedder._client is None


class APITimeoutError(Exception):
    """Named like the SDK's timeout error; carries text that must not leak."""


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (APITimeoutError(f"timed out {FAKE_KEY}"), "timeout"),
        (TimeoutError("slow"), "timeout"),
        (RuntimeError(f"Incorrect API key provided: {FAKE_KEY}"), "failed"),
    ],
)
def test_provider_failures_map_to_provider_error_without_detail(error, reason):
    embedder, stub = _embedder(fail=error)
    with pytest.raises(ProviderError) as info:
        embedder.embed([f"a quiet home with a big yard {MARKER}"])
    assert info.value.reason == reason
    assert FAKE_KEY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert len(stub.calls) == 1


def test_a_short_or_malformed_response_is_bad_response():
    embedder, stub = _embedder(1536)
    stub.create = lambda **kw: SimpleNamespace(data=[], usage=None)
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert info.value.reason == "bad_response"


def test_inputs_are_checked_before_any_call():
    embedder, stub = _embedder()
    with pytest.raises(ValueError):
        embedder.embed(["x" * 4001])
    with pytest.raises(ValueError):
        embedder.embed(["   "])
    assert stub.calls == []
    assert embedder.embed([]).shape == (0, 1536)
    with pytest.raises(ValueError):
        OpenAIEmbedder(dims=1000)
    with pytest.raises(ValueError):
        OpenAIEmbedder(model="test:hashing")


def test_neither_the_key_nor_any_input_reaches_logs(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    embedder, _ = _embedder()
    embedder.embed([f"a quiet home with a big yard {MARKER}"])
    failing, _ = _embedder(fail=RuntimeError(FAKE_KEY))
    with pytest.raises(ProviderError):
        failing.embed([f"another quiet home {MARKER}"])
    out = capsys.readouterr()
    for text in (caplog.text, out.out, out.err):
        assert FAKE_KEY not in text
        assert MARKER not in text


# --- settings ---


def test_embed_settings_defaults_and_overrides():
    assert embed_settings({}) == ("openai:text-embedding-3-small", 1536)
    assert embed_settings({"IDX_EMBED_DIMS": "512"}) == (
        "openai:text-embedding-3-small",
        512,
    )
    assert embed_settings({"IDX_EMBED_MODEL": "test:hashing"}) == ("test:hashing", 64)
    for bad in ({"IDX_EMBED_MODEL": "other"}, {"IDX_EMBED_DIMS": "700"}):
        with pytest.raises(ValueError):
            embed_settings(bad)
    with pytest.raises(ValueError):
        embed_settings({"IDX_EMBED_DIMS": "many"})


def test_redact_defaults_on():
    assert emb.redact_enabled({}) is True
    assert emb.redact_enabled({"IDX_EMBED_REDACT": "0"}) is False
    assert emb.redact_enabled({"IDX_EMBED_REDACT": "1"}) is True


def test_make_embedder_picks_by_model():
    assert isinstance(emb.make_embedder("test:hashing", 64), HashingEmbedder)
    made = emb.make_embedder(
        "openai:text-embedding-3-small", 1536, environ={}, spend=lambda n: None
    )
    assert isinstance(made, OpenAIEmbedder) and made._client is None


# --- lazy imports and statelessness ---


def test_semantic_package_imports_neither_openai_nor_memory():
    code = (
        "import sys, idx_agent.semantic, idx_agent.semantic.build_index; "
        "print(sorted(m for m in sys.modules "
        "if m == 'openai' or m.startswith('idx_agent.memory')))"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert out.stdout.strip() == "[]"
