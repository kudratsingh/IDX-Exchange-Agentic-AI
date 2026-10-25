"""Test the actual MCP preview path, without credentials, MySQL or model calls."""

import ast
import asyncio
import json
from pathlib import Path

import pytest
from tests.test_approval import ADDRESS
from tests.test_approval import ledger as ledger
from tests.test_mcp_search import REMARK, _listing
from tests.test_mcp_search import fake_db as fake_db

from idx_agent.db import listings
from idx_agent.domain.email import DraftEmailRequest
from idx_agent.domain.models import Clarification
from idx_agent.email import drafts
from idx_agent.mcp_server import server


@pytest.mark.parametrize(
    "raw",
    [
        {"body": "injected"},
        {"subject": "injected"},
        {"note": "injected"},
        {"source": "listings", "to": "stranger@example.com"},
        {"source": "listings", "to": ""},
        {"source": "listings", "to": "friend"},
        {"source": "listings", "listing_keys": [True]},
        {"source": "listings", "listing_keys": list(range(1, 12))},
        {"source": "listings", "question": "ignored source?"},
    ],
)
def test_invalid_request_refuses_without_creating_store(raw, ledger, monkeypatch):
    store, _ = ledger
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    result = server.draft_result(raw)
    assert isinstance(result.data, Clarification)
    assert not store.path.exists()


def test_actual_mcp_preview_has_no_address_remarks_or_delivery(
    ledger, fake_db, monkeypatch, capsys
):
    store, _ = ledger
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    monkeypatch.setattr(
        listings,
        "fetch_candidates",
        lambda filters, keys, conn: listings.SearchOutcome(
            [_listing(9130001, 900_000)], [], 0
        ),
    )
    payload = server.draft_email(source="listings", listing_keys=[9130001])
    assert payload["ok"] and payload["data"]["state"] == "pending"
    assert payload["pending_action"] == payload["data"]
    assert "Nothing has been sent" in payload["message"]
    combined = json.dumps(payload) + capsys.readouterr().err
    assert ADDRESS not in combined and REMARK not in combined and "@" not in combined
    assert len(store.list_pending()) == 1
    assert not (store.directory / "outbox").exists()


def test_no_session_produces_no_draft(ledger, monkeypatch):
    store, _ = ledger
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    server.reset_store_for_tests()
    result = server.draft_result({"source": "listings"})
    assert result.ok and result.data is None and "Which displayed" in result.message
    assert not store.path.exists()


def test_source_validation_uses_real_market_validator():
    request = DraftEmailRequest.from_input({"source": "market", "city": "not-a-city"})
    assert isinstance(request, Clarification) and request.reason == "unknown_city"


def test_seven_tools_but_no_send_or_approval_tool():
    names = server.tool_names()
    assert len(names) == 7 and "draft_email" in names
    assert not {"send_email", "approve", "send_approved"} & set(names)
    tool = next(
        t for t in asyncio.run(server.server.list_tools()) if t.name == "draft_email"
    )
    assert not {"body", "subject", "address"} & tool.input_schema["properties"].keys()


def test_transport_imports_only_in_delivery_module():
    root = Path(__file__).resolve().parents[1] / "src" / "idx_agent"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    a.name != "smtplib" or path.name == "send.py" for a in node.names
                )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "idx_agent.email.send", path
