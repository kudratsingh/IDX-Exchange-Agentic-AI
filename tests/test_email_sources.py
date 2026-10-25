"""The remaining source paths re-derive their content with no provider calls."""

from dataclasses import replace

import pytest
from tests import rag_fixture, test_mcp_market
from tests.test_approval import ADDRESS
from tests.test_approval import ledger as ledger

from idx_agent.domain.market import MonthAggregate
from idx_agent.email import drafts
from idx_agent.email.recipients import resolve_recipient, validate_address
from idx_agent.email.report import collect_report
from idx_agent.mcp_server import server
from idx_agent.safety.approval import ApprovalRefused

market_db = test_mcp_market.fake_db


def test_market_draft_uses_actual_market_math(ledger, market_db, monkeypatch):
    store, _ = ledger
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    result = server.draft_result({"source": "market", "city": "Pasadena"})
    assert result.ok and result.data.state == "pending"
    assert "11 sales" in result.data.body and "$1,050,000" in result.data.body
    assert result.provenance.tables == ["california_sold"]
    assert ADDRESS not in result.model_dump_json()


def test_too_few_sales_never_store_empty_market_draft(ledger, market_db, monkeypatch):
    store, _ = ledger
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    market_db["aggregates"] = test_mcp_market._few(2)
    result = server.draft_result({"source": "market", "city": "Pasadena"})
    assert result.ok and result.data is None
    assert not store.path.exists()


def test_missing_listing_database_is_not_misreported_as_email_settings(
    ledger, monkeypatch
):
    store, _ = ledger
    monkeypatch.setattr(drafts, "configured_store", lambda: store)
    monkeypatch.setattr(server.db_pool, "database_configured", lambda: False)
    result = server.draft_result({"source": "listings", "listing_keys": [9130001]})
    assert not result.ok and result.error.category == "db"
    assert not store.path.exists()


def test_reference_draft_never_constructs_query_embedder(ledger, tmp_path, monkeypatch):
    store, _ = ledger
    path = rag_fixture.build_fixture_index(tmp_path, route="hybrid")
    for key, value in rag_fixture.fixture_env(path).items():
        monkeypatch.setenv(key, value)
    server.reset_rag_for_tests()
    monkeypatch.setattr(drafts, "configured_store", lambda: store)

    def forbidden(*args):
        raise AssertionError("Email reference retrieval must not construct a provider")

    monkeypatch.setattr(server, "_rag_embedder", forbidden)
    try:
        result = server.draft_result(
            {"source": "document", "question": "what does DOM mean?"}
        )
        assert result.ok and result.data.state == "pending", result
        assert "days on market" in result.data.body.lower()
        assert "Trestle field" not in result.data.body
    finally:
        server.reset_rag_for_tests()


def test_full_weekly_report_renders_three_windows_per_city(market_db, monkeypatch):
    original = server.db_market.fetch_market_aggregates

    def fetch(request, window, dates, conn):
        aggregate = original(request, window, dates, conn)
        # Eleven invented September sales are inside each of the three windows.
        month = MonthAggregate("2026-09", 11, aggregate.price_middles)
        return replace(aggregate, months=(month,))

    monkeypatch.setattr(server.db_market, "fetch_market_aggregates", fetch)
    text, dates = collect_report(
        ["Pasadena", "Glendale", "Duarte"], server.market_result
    )
    assert text.splitlines().count("11 sales") == 9 and str(dates.sold) in text
    assert len(market_db["fetch"]) == 9


@pytest.mark.parametrize(
    "address",
    [
        "a,b@example.com",
        "a;b@example.com",
        "a@example.com\nBcc: b@example.com",
        "Owner <a@example.com>",
    ],
)
def test_recipient_cannot_be_a_list_or_injected_header(address):
    with pytest.raises(ApprovalRefused, match="recipient_not_allowed"):
        validate_address(address)


def test_recipient_label_is_not_an_address_argument(monkeypatch):
    monkeypatch.setenv("IDX_EMAIL_RECIPIENTS", '{"owner":"owner@example.com"}')
    assert resolve_recipient() == ADDRESS
    with pytest.raises(ApprovalRefused, match="recipient_not_allowed"):
        resolve_recipient("outsider")
