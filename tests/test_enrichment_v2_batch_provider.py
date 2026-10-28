"""Provider calls are mocked; no live service or credentials are used."""

import io
import urllib.error

import pytest
from scripts import extract_enrichment_v2_batch as batch


def test_get_retries_transient_errors_and_spends_each_attempt(monkeypatch):
    attempts, spent, slept = [], [], []

    def open_stub(request, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(
                "private", 429, "private", {}, io.BytesIO(b"private")
            )
        return io.BytesIO(b"{}")

    monkeypatch.setattr(batch.consent, "spend_paid_call", lambda: spent.append(1))
    monkeypatch.setattr(batch.urllib.request, "urlopen", open_stub)
    monkeypatch.setattr(batch.time, "sleep", slept.append)
    assert batch.request_http("/batches/id", "fake") == b"{}"
    assert len(attempts) == len(spent) == 3 and slept == [1, 2]


def test_post_timeout_is_not_retried(monkeypatch):
    attempts, spent = [], []

    def fail(request, timeout):
        attempts.append(1)
        raise TimeoutError("private")

    monkeypatch.setattr(batch.consent, "spend_paid_call", lambda: spent.append(1))
    monkeypatch.setattr(batch.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="provider_request_failed"):
        batch.request_http("/batches", "fake", payload={"requests": []})
    assert len(attempts) == len(spent) == 1
