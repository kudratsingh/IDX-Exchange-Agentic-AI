"""Email content is deterministic, restricted-field-free, and never model-authored."""

from types import SimpleNamespace

import pytest
from tests.test_mcp_search import ASOF, REMARK, _listing

from idx_agent.email.bodies import check_content, document_body, listing_body
from idx_agent.safety.approval import ApprovalRefused


@pytest.mark.parametrize(
    "content",
    [
        "ListAgentEmail",
        "PrivateRemarks",
        "user@example.com",
        "555-010-0100",
        "+15550100100",
        "secret: sensitive",
    ],
)
def test_contact_or_sensitive_content_is_refused(content):
    with pytest.raises(ApprovalRefused, match="safety_refusal"):
        check_content("Preview", content)


def test_listing_body_uses_cards_never_remarks():
    subject, body = listing_body([_listing(9130001, 900_000)], ASOF.to_envelope())
    assert "$900,000" in body and REMARK not in body
    assert str(ASOF.active) in subject and str(ASOF.sold) in body


def test_confidential_passage_and_unregistered_source_never_exported():
    chunks = [
        SimpleNamespace(source_doc=source, section_or_field="term", text=text)
        for source, text in [
            ("glossary", "Own words."),
            ("primer", "CONFIDENTIAL-SENTINEL"),
            ("unknown", "INJECTED-SENTINEL"),
        ]
    ]
    _, body = document_body(chunks)
    assert "Own words." in body and "Licensed" in body
    assert "SENTINEL" not in body


def test_confidential_only_answer_cannot_create_email():
    with pytest.raises(ApprovalRefused, match="no_shareable_answer"):
        document_body([SimpleNamespace(source_doc="trestle", text="Hidden")])


def test_headers_are_single_line():
    with pytest.raises(ApprovalRefused):
        check_content("Preview\nBcc: injected", "Safe text")
