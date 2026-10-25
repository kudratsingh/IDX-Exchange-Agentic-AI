"""Offline approval boundary: tampering, expiry, races, restart and delivery failure."""

import json
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from idx_agent.email import settings
from idx_agent.email.send import send
from idx_agent.safety.approval import ApprovalRefused, ApprovalStore, view

ADDRESS = "owner@example.com"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    monkeypatch.setenv("IDX_EMAIL_RECIPIENTS", json.dumps({"owner": ADDRESS}))
    clock = SimpleNamespace(now=datetime(2026, 10, 24, tzinfo=UTC))
    store = ApprovalStore(
        tmp_path / "data" / "email",
        data_root=tmp_path / "data",
        is_ignored=lambda _: True,
        clock=lambda: clock.now,
    )
    return store, clock


def create(store, **kwargs):
    return store.create_draft(
        recipient_label="owner",
        recipient=ADDRESS,
        source="market",
        subject="Invented market report",
        body="Invented closed-sale summary.",
        **kwargs,
    )


def approve(store, record):
    return store.approve(record.id, record.digest[:12])


def test_no_send_without_approval(ledger):
    store, _ = ledger
    record = create(store)
    with pytest.raises(ApprovalRefused, match="not_approved"):
        send(store, record.id)
    assert not (store.directory / "outbox").exists()


def test_made_up_id_is_refused(ledger):
    with pytest.raises(ApprovalRefused, match="unknown_draft"):
        ledger[0].claim_send("draft-" + "f" * 12)


def test_approval_of_a_never_approves_b(ledger):
    store, _ = ledger
    a, b = create(store), create(store)
    approve(store, a)
    with pytest.raises(ApprovalRefused, match="not_approved"):
        store.claim_send(b.id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("recipient", "changed@example.com"),
        ("body", "Changed"),
        ("subject", "Changed"),
        ("source", "report"),
    ],
)
def test_alteration_after_approval_is_refused(ledger, field, value):
    store, _ = ledger
    record = create(store)
    approve(store, record)
    events = [json.loads(line) for line in store.path.read_text().splitlines()]
    events[-1]["record"][field] = value
    store.path.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ApprovalRefused, match="changed_since_approval"):
        store.claim_send(record.id)


def test_wrong_digest_never_approves(ledger):
    store, _ = ledger
    record = create(store)
    with pytest.raises(ApprovalRefused, match="changed_since_approval"):
        store.approve(record.id, "0" * 12)
    assert store.get(record.id).state == "pending"


def test_draft_expires_at_exact_deadline(ledger):
    store, clock = ledger
    record = create(store)
    clock.now += timedelta(hours=24)
    with pytest.raises(ApprovalRefused, match="expired"):
        approve(store, record)
    assert store.get(record.id).state == "expired"


def test_stale_approval_blocks_send(ledger):
    store, clock = ledger
    record = create(store)
    approve(store, record)
    clock.now += timedelta(minutes=30)
    with pytest.raises(ApprovalRefused, match="stale_approval"):
        store.claim_send(record.id)


@pytest.mark.parametrize("finish", ["reject", "expire"])
def test_rejected_or_expired_draft_cannot_send(ledger, finish):
    store, _ = ledger
    record = create(store)
    getattr(store, finish)(record.id)
    with pytest.raises(ApprovalRefused, match="rejected|expired"):
        store.claim_send(record.id)


def test_duplicate_send_refused_and_sink_is_private(ledger):
    store, _ = ledger
    record = create(store)
    approve(store, record)
    receipt = send(store, record.id)
    target = store.directory / "outbox" / (record.id + ".eml")
    content = target.read_bytes()
    assert receipt.transport == "sink" and b"Invented closed-sale summary" in content
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(ApprovalRefused, match="already_sent"):
        send(store, record.id)
    assert target.read_bytes() == content


def test_interrupted_send_stays_locked_across_store_restart(ledger):
    store, _ = ledger
    record = create(store)
    approve(store, record)
    store.claim_send(record.id)
    other = ApprovalStore(
        store.directory, data_root=store.directory.parent, is_ignored=lambda _: True
    )
    with pytest.raises(ApprovalRefused, match="locked"):
        other.claim_send(record.id)


def test_concurrent_claims_attempt_at_most_once(ledger):
    store, _ = ledger
    record = create(store)
    approve(store, record)

    def claim(_):
        try:
            return store.claim_send(record.id).state
        except ApprovalRefused as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(claim, range(4)))
    assert results.count("sending") == 1 and results.count("locked") == 3


def test_idempotent_creation_never_overwrites_or_duplicates(ledger):
    store, _ = ledger
    a = create(store, idempotency_key="invented-report")
    first = store.path.read_bytes()
    b = create(store, idempotency_key="invented-report")
    assert a == b and first == store.path.read_bytes()
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_partial_journal_fails_closed_without_rewriting(ledger):
    store, _ = ledger
    record = create(store)
    with store.path.open("a") as handle:
        handle.write('{"event":')
    original = store.path.read_bytes()
    with pytest.raises(ApprovalRefused, match="invalid_journal"):
        store.get(record.id)
    assert store.path.read_bytes() == original


def test_address_excluded_from_record_and_public_preview(ledger):
    record = create(ledger[0])
    assert ADDRESS not in record.model_dump_json()
    assert ADDRESS not in view(record).model_dump_json()
    assert ADDRESS not in repr(record)


def test_refuses_outside_or_unignored_store(tmp_path):
    for directory, ignored in [
        (tmp_path / "outside", True),
        (tmp_path / "data" / "email", False),
    ]:
        with pytest.raises(ApprovalRefused, match="unsafe_store"):
            ApprovalStore(
                directory,
                data_root=tmp_path / "data",
                is_ignored=lambda _, ignored=ignored: ignored,
            )
