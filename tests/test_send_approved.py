"""SMTP uses the exact-command consent gate and leaves failures locked."""

import pytest
from tests.test_approval import ADDRESS, approve, create
from tests.test_approval import ledger as ledger

from idx_agent.email import send as delivery
from idx_agent.safety import consent
from idx_agent.safety.approval import ApprovalRefused


def test_smtp_without_token_opens_no_connection(ledger, monkeypatch):
    store, _ = ledger
    record = create(store)
    approve(store, record)
    monkeypatch.setenv("EMAIL_USER", ADDRESS)
    monkeypatch.setenv("EMAIL_PASSWORD", "invented-test-password")

    def forbidden(*args, **kwargs):
        raise AssertionError("Network must not be opened")

    with pytest.raises(consent.PaidRunRefused):
        delivery.send(store, record.id, transport="smtp", smtp_factory=forbidden)
    assert store.get(record.id).state == "approved"


def test_smtp_failure_attempted_once_and_locked(ledger, monkeypatch):
    store, _ = ledger
    record = create(store)
    approve(store, record)
    monkeypatch.setenv("EMAIL_USER", ADDRESS)
    monkeypatch.setenv("EMAIL_PASSWORD", "invented-test-password")
    calls = []
    monkeypatch.setattr(consent, "start_paid_run", lambda: calls.append("consent"))
    monkeypatch.setattr(consent, "spend_paid_call", lambda count: calls.append(count))

    def fail(*args, **kwargs):
        calls.append("network")
        raise OSError("invented transport failure")

    with pytest.raises(ApprovalRefused, match="delivery_failed_locked"):
        delivery.send(store, record.id, transport="smtp", smtp_factory=fail)
    assert calls == ["consent", 1, "network"]
    with pytest.raises(ApprovalRefused, match="locked"):
        delivery.send(store, record.id, transport="sink")
