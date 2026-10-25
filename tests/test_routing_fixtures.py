"""Fixtures obey public boundary shapes and stay isolated from live tools."""

import json

import pytest
from evals.routing_fixtures import NOTICE, RoutingFixtures

from idx_agent.domain.alerts import SavedSearchView
from idx_agent.domain.models import (
    Clarification,
    MarketStats,
    RagAnswer,
    RecommendationResult,
    SearchResult,
    SimilarResult,
)
from idx_agent.domain.results import AgentResult, EmailDraftView, HealthData


@pytest.mark.parametrize(
    "name,args,model,fragment",
    [
        ("health", {}, HealthData, "Database: ok"),
        (
            "search_listings",
            {"city": "Pasadena"},
            SearchResult,
            "Synthetic Example Lane",
        ),
        ("get_market_stats", {"city": "Monrovia"}, MarketStats, "Median price"),
        (
            "get_market_stats",
            {"postal_code": "91101", "include_extended": True},
            MarketStats,
            "Active inventory",
        ),
        ("rag_answer", {"question": "What does DOM mean?"}, RagAnswer, "Sources:"),
        (
            "rag_answer",
            {"question": "What is sale-to-list ratio?"},
            RagAnswer,
            "closing price",
        ),
        (
            "recommend",
            {"listing_key": 9120002, "k": 0},
            RecommendationResult,
            "Not enough comparable sales",
        ),
        (
            "recommend",
            {"listing_key": 9120002},
            RecommendationResult,
            "Not enough comparable sales",
        ),
        (
            "find_similar_listings",
            {"text": "a cozy cottage", "city": "Pasadena"},
            SimilarResult,
            "Closest matches",
        ),
        (
            "draft_email",
            {"source": "market", "city": "Pasadena"},
            EmailDraftView,
            "pending human approval",
        ),
        ("save_search", {"city": "Glendale"}, SavedSearchView, "Saved search 1"),
    ],
)
def test_typed_complete_replies(name, args, model, fragment):
    result = AgentResult[model].model_validate_json(RoutingFixtures().reply(name, args))
    assert result.ok and isinstance(result.data, model)
    assert fragment in result.message
    assert result.provenance.tool == name
    assert result.provenance.tables == []  # No invented claim of a database read.
    assert result.warnings == [NOTICE]
    assert "The result was shown to the user" not in result.message


def reply(fixtures, name="search_listings", **args):
    return json.loads(fixtures.reply(name, args))


def test_search_seeding_refinement_paging_clear_reset_and_case_isolation():
    fixtures = RoutingFixtures()
    fixtures.seed("search_listings", {"city": "Pasadena", "max_price": 1200000})
    result = reply(fixtures, mode="update", property_subtype="Condominium")
    filters = result["data"]["applied_filters"]
    assert (filters["city"], filters["max_price"], filters["page"]) == (
        "Pasadena",
        1200000,
        1,
    )
    assert filters["property_subtype"] == "Condominium"
    first_keys = [row["listing_key"] for row in result["data"]["listings"]]
    second = reply(fixtures, mode="more")
    assert second["data"]["applied_filters"]["page"] == 2
    second_keys = [row["listing_key"] for row in second["data"]["listings"]]
    assert not set(first_keys) & set(second_keys)
    assert "page 2" in second["message"]
    assert "No active listings" in reply(fixtures, mode="more")["message"]
    cleared = reply(fixtures, mode="update", clear=["max_price"])
    assert "max_price" not in cleared["data"]["applied_filters"]
    assert "city" in cleared["data"]["applied_filters"]
    assert reply(fixtures, mode="reset")["message"] == "Cleared your search."
    assert "Which city" in reply(fixtures, mode="more")["message"]
    assert (
        "Which city"
        in reply(RoutingFixtures(), mode="update", property_subtype="Condominium")[
            "message"
        ]
    )


def test_results_respect_actual_filters_not_expected_answers():
    fixtures = RoutingFixtures()
    result = reply(
        fixtures,
        city="Glendale",
        max_price=400000,
        min_beds=5,
        min_sqft=2500,
        property_subtype="Condominium",
        max_hoa_monthly=100,
    )
    for listing in result["data"]["listings"]:
        assert listing["city"] == "Glendale"
        assert listing["list_price"] <= 400000
        assert listing["bedrooms"] >= 5
        assert listing["living_area"] >= 2500
        assert listing["property_subtype"] == "Condominium"
        assert listing["hoa_fee_monthly"] <= 100


def test_zero_price_and_hoa_caps_are_not_replaced_by_defaults():
    result = reply(RoutingFixtures(), city="Pasadena", max_price=0, max_hoa_monthly=0)
    for listing in result["data"]["listings"]:
        assert listing["list_price"] == listing["hoa_fee_monthly"] == 0


def test_monthly_samples_sum_to_total_and_dates_follow_requested_window():
    result = reply(
        RoutingFixtures(),
        "get_market_stats",
        city="Pasadena",
        months=12,
        include_extended=True,
    )
    data = result["data"]
    assert data["window"] == {"start": "2025-09-18", "end": "2026-09-17", "months": 12}
    assert sum(row["sample_count"] for row in data["trend"]) == data["sample_count"]
    assert len(data["analytics"]["months"]) == len(data["trend"]) == 13
    assert all(row.get("price_yoy_pct") is None for row in data["analytics"]["months"])


def test_unknown_reference_has_complete_terminal_not_found_result():
    result = reply(RoutingFixtures(), "rag_answer", question="Unknown invented field?")
    assert not result["data"]["found"]
    assert result["data"]["chunks"] == []
    assert result["message"] == "That is not in the reference documents I have."


def test_rag_passages_are_in_message_and_sources_close_the_fence():
    result = reply(RoutingFixtures(), "rag_answer", question="What does DOM mean?")
    assert "DOM stands for days on market" in result["message"]
    assert "text" not in result["data"]["chunks"][0]
    assert result["data"]["sources"][0] in result["message"]
    assert result["message"].rfind("Sources:") > result["message"].rfind("```")


def test_search_then_draft_has_keys_but_creates_no_approval_or_delivery():
    fixtures = RoutingFixtures()
    result = reply(fixtures, city="Glendale")
    draft = reply(fixtures, "draft_email", source="listings")
    parsed = AgentResult[EmailDraftView].model_validate(draft)
    assert parsed.data.state == "pending"
    assert parsed.pending_action == parsed.data
    for listing in result["data"]["listings"]:
        assert str(listing["listing_key"]) in parsed.data.body
    assert "Nothing sent" in parsed.message
    refused = reply(
        fixtures, "draft_email", source="market", city="Pasadena", to="someone-else"
    )
    assert "owner only" in refused["message"]
    assert "pending_action" not in refused


@pytest.mark.parametrize(
    "tool,args",
    [
        ("delete_saved_search", {"number": 1}),
        ("forget_me", {}),
    ],
)
def test_removal_only_displays_confirmation(tool, args):
    fixtures = RoutingFixtures()
    result = reply(fixtures, tool, **args)
    assert "confirmation code" in result["message"]
    assert "Removed" not in result["message"]
    assert reply(fixtures, "list_saved_searches")["data"]


def test_bad_arguments_are_safe_boundary_results():
    fixtures = RoutingFixtures()
    result = reply(fixtures, "get_market_stats", city="Pasadena", months=-1)
    assert Clarification.model_validate(result["data"])
    invalid = reply(fixtures, mode="unsupported", city="Pasadena")
    assert not invalid["ok"] and invalid["error"]["category"] == "validation"


def test_tool_bodies_stores_and_database_are_never_called(monkeypatch):
    from idx_agent.alerts import server as alerts
    from idx_agent.db import pool
    from idx_agent.mcp_server import server

    def forbidden(*args, **kwargs):
        raise AssertionError("live dependency touched")

    for name in (
        "health",
        "search_listings",
        "get_market_stats",
        "rag_answer",
        "recommend",
        "find_similar_listings",
        "draft_email",
        "_get_store",
    ):
        monkeypatch.setattr(server, name, forbidden)
    monkeypatch.setattr(pool, "connect", forbidden)
    monkeypatch.setattr(alerts, "configured_store", forbidden)
    fixtures = RoutingFixtures()
    for name, args in (
        ("health", {}),
        ("search_listings", {"city": "Pasadena"}),
        ("get_market_stats", {"city": "Pasadena"}),
        ("rag_answer", {"question": "What does DOM mean?"}),
        ("recommend", {"listing_key": 9120002}),
        ("find_similar_listings", {"text": "a cozy cottage"}),
        ("draft_email", {"source": "listings"}),
        ("save_search", {"city": "Pasadena"}),
        ("list_saved_searches", {}),
        ("delete_saved_search", {"number": 1}),
        ("forget_me", {}),
    ):
        assert reply(fixtures, name, **args)["ok"]
