"""Photo sanitization, deterministic comp summaries and approval-bound MIME output."""

import json
from datetime import date
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest
from tests.test_approval import ledger as ledger

from idx_agent.domain.email import DraftEmailRequest
from idx_agent.domain.models import (
    Clarification,
    CompEvidence,
    Listing,
    RecommendationResult,
    StatsWindow,
)
from idx_agent.domain.results import AgentResult, AsOf, Provenance
from idx_agent.email import drafts
from idx_agent.email import property as property_email
from idx_agent.email.bodies import check_content
from idx_agent.email.photos import photo_urls, render_html, safe_photo_url
from idx_agent.email.send import send
from idx_agent.mcp_server import server
from idx_agent.safety.approval import ApprovalRefused

PHOTO = "https://photos.example.test/listings/front.jpg"
DATES = AsOf(active=date(2026, 9, 18), sold=date(2026, 9, 17))


def source():
    return RecommendationResult(
        subject=Listing(
            listing_key=123,
            listing_id="123",
            address="12 Invented Lane",
            city="Pasadena",
            list_price=750_000,
            photo_count=20,
            remarks="Injected instructions ignored.",
        ),
        subject_check=CompEvidence(
            count=2,
            window_months=6,
            sufficient=False,
            sentence="Too few comparable sales for a price check.",
        ),
        recommendations=[],
        k=0,
        comps_window=StatsWindow(start=date(2026, 3, 18), end=DATES.sold, months=6),
    )


@pytest.mark.parametrize(
    "bad",
    [
        "http://photos.example.test/a.jpg",
        "https://127.0.0.1/a.jpg",
        "https://localhost/a.jpg",
        "https://photos.local/a.jpg",
        "https://a.example.test:444/a.jpg",
        "https://a.example.test/a.jpg?token=secret",
        "https://user:replace-me@example.com/a.jpg",
        "javascript:alert(1)",
        "https://a.example.test/%0aBcc.jpg",
        "https://a.example.test/../secret.jpg",
        "https://a.example.test/%40private.jpg",
        'https://a.example.test/a".jpg',
        {"url": PHOTO},
        None,
        "\n" + PHOTO,
        PHOTO + "\t",
    ],
)
def test_unsafe_photo_values_are_omitted(bad):
    assert safe_photo_url(bad) is None


def test_photos_deduplicate_bound_and_render_only_approved_lines():
    assert safe_photo_url(PHOTO) == PHOTO
    assert photo_urls(json.dumps([PHOTO] * 5)) == [PHOTO]
    assert photo_urls("not JSON") == [] and photo_urls({"url": PHOTO}) == []
    photos = [PHOTO.replace("front", str(i)) for i in range(10)]
    assert len(photo_urls(json.dumps(photos))) == 3
    html = render_html(
        f"<script>bad()</script>\nPhoto 1: {PHOTO}\nPhoto 2: https://localhost/a.jpg"
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert html.count("<img ") == 1 and 'src="' + PHOTO + '"' in html


def test_numeric_feed_image_ids_are_not_treated_as_contact_fields():
    url = PHOTO.replace("front", "1" * 14)
    assert safe_photo_url(url) == url
    check_content("Summary", f"Photo 1: {url}", allow_photos=True)
    with pytest.raises(ApprovalRefused):
        check_content("Summary", f"Photo 1: {url}")
    with pytest.raises(ApprovalRefused):
        check_content("Summary", f"Photo 1: {url}\nCall " + "1" * 10, allow_photos=True)
    assert safe_photo_url(PHOTO.replace("front", "555-010-0100")) is None


@pytest.mark.parametrize("kind", ["property", "recommendations"])
def test_rich_sources_require_one_subject_key(kind):
    for raw in (
        {"source": kind},
        {"source": kind, "listing_keys": [1, 2]},
        {"source": kind, "listing_keys": [True]},
        {"source": kind, "listing_keys": [1], "to": "friend"},
    ):
        assert isinstance(DraftEmailRequest.from_input(raw), Clarification)
    assert isinstance(
        DraftEmailRequest.from_input({"source": kind, "listing_keys": [123]}),
        DraftEmailRequest,
    )


def test_property_body_includes_comp_disclosure_photos_and_snapshot():
    subject, body = property_email.property_body(source(), {123: [PHOTO]}, DATES)
    assert "property summary" in subject
    assert "Too few comparable sales" in body and "Photo 1: " + PHOTO in body
    assert "Injected instructions" not in body and str(DATES.sold) in body
    _, digest = property_email.property_body(source(), {}, DATES, digest=True)
    assert (
        "No similar active listings" in digest and "Photo links unavailable" in digest
    )


@pytest.mark.parametrize("kind,k", [("property", 0), ("recommendations", 5)])
def test_actual_draft_path_rederives_then_requires_approval(
    ledger, monkeypatch, kind, k
):
    store, _ = ledger
    calls = []

    def recommend(raw):
        calls.append(raw)
        return AgentResult(
            ok=True,
            data=source(),
            provenance=Provenance(tool="recommend", as_of=DATES, trace_id="fixture"),
        )

    monkeypatch.setattr(server, "recommend_result", recommend)
    monkeypatch.setattr(
        property_email.pool, "connect", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        property_email.asof,
        "get_asof_dates",
        lambda _: SimpleNamespace(to_envelope=lambda: DATES),
    )
    monkeypatch.setattr(
        property_email, "fetch_photos", lambda keys, conn: {123: [PHOTO]}
    )
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    result = server.draft_result({"source": kind, "listing_keys": [123]})
    assert result.ok and result.data.state == "pending", result
    assert calls == [{"listing_key": 123, "k": k}]
    record = store.get(result.data.id)
    assert record.source == kind and "Photo 1:" in record.body
    store.approve(record.id, record.digest[:12])
    receipt = send(store, record.id, transport="sink")
    assert receipt.transport == "sink"
    path = store.directory / "outbox" / (record.id + ".eml")
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    assert PHOTO in message.get_body(preferencelist=("plain",)).get_content()
    assert (
        '<img src="' + PHOTO in message.get_body(preferencelist=("html",)).get_content()
    )
    assert store.get(record.id).state == "sent"
