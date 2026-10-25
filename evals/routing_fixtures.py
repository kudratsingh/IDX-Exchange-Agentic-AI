"""Invented, versioned tool replies for routing-only evaluation (WO-019).

No tool bodies or external I/O. Inputs are actual calls, never expected routes,
case IDs or expected filters. Boundary models and pure formatters define the shape.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from idx_agent.channels.format import (
    RAG_NOT_FOUND,
    format_filters,
    format_market_reply,
    format_rag_passages,
    format_recommendations,
    format_search_reply,
    format_similar_reply,
)
from idx_agent.domain.alerts import SavedSearchView
from idx_agent.domain.analytics import format_analytics
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.email import DraftEmailRequest
from idx_agent.domain.market import month_keys
from idx_agent.domain.models import (
    Clarification,
    CompEvidence,
    Geography,
    Listing,
    MarketAnalytics,
    MarketStats,
    MarketStatsRequest,
    MonthAnalytics,
    MonthRow,
    PropertySearchFilters,
    RagAnswer,
    RagRequest,
    RecommendationResult,
    RecommendRequest,
    RetrievedChunk,
    SearchResult,
    SimilarListingsRequest,
    SimilarMatch,
    SimilarResult,
    StatsWindow,
)
from idx_agent.domain.results import (
    AgentResult,
    EmailDraftView,
    HealthData,
    Provenance,
    ToolError,
)
from idx_agent.memory.merge import merge_filters, next_page

ROUTING_FIXTURE_VERSION = "contract-v1"
NOTICE = "Synthetic routing fixture; no live lookup or persisted action."
DATES = AsOfDates(active=date(2026, 9, 18), sold=date(2026, 9, 17))
STAMP = datetime(2026, 9, 18, tzinfo=UTC)
EXPIRY = datetime(2026, 9, 19, tzinfo=UTC)
TRACE = "routing-fixture"


def _window(months: int = 6) -> StatsWindow:
    start, end = DATES.window(months)
    return StatsWindow(start=start, end=end, months=months)


def _listing(filters: PropertySearchFilters, key: int = 9190001) -> Listing:
    price = max(
        filters.min_price or 0,
        min(filters.max_price if filters.max_price is not None else 900000, 900000),
    )
    return Listing(
        listing_key=key,
        listing_id=f"FIXTURE-{key}",
        address=f"{key - 9190000} Synthetic Example Lane",
        city=filters.city,
        postal_code=filters.postal_code,
        list_price=price,
        bedrooms=filters.min_beds or 3,
        bathrooms=filters.min_baths or 2,
        living_area=filters.min_sqft or 1500,
        property_subtype=filters.property_subtype or "SingleFamilyResidence",
        status="Active",
        pool=filters.pool,
        view=filters.view,
        days_on_market=20,
        hoa_fee_monthly=min(
            filters.max_hoa_monthly if filters.max_hoa_monthly is not None else 400, 400
        ),
    )


class RoutingFixtures:
    """One isolated case, seeded only by structured prior search calls.

    State is local values, never the runtime store. Historical cards stay in the
    authored history; seeding does not rewrite those model inputs.
    """

    def __init__(self) -> None:
        self.filters: PropertySearchFilters | None = None
        self.last_keys: list[int] = []

    def seed(self, name: str, arguments: Mapping[str, Any]) -> None:
        if name.removeprefix("idx__") == "search_listings":
            self.reply(name, arguments)

    def _envelope(self, name: str, data: Any, message: str) -> AgentResult:
        return AgentResult(
            ok=True,
            data=data,
            message=message,
            warnings=[NOTICE],
            provenance=Provenance(tool=name, trace_id=TRACE),
        )

    def reply(self, name: str, arguments: Mapping[str, Any]) -> str:
        name = name.removeprefix("idx__").removeprefix("idx_alerts__")
        args = {k: v for k, v in arguments.items() if v is not None}
        try:
            result = self._reply(name, args)
        except (ValidationError, ValueError, TypeError):
            message = "Please use the supported tool arguments."
            result = AgentResult(
                ok=False,
                message=message,
                warnings=[NOTICE],
                provenance=Provenance(tool=name, trace_id=TRACE),
                error=ToolError(category="validation", message=message, trace_id=TRACE),
            )
        return json.dumps(result.model_dump(mode="json", exclude_none=True))

    def _reply(self, name: str, args: dict[str, Any]) -> AgentResult:
        if name == "health":
            data = HealthData(
                server_time=STAMP,
                version="0.0.1",
                database="ok",
                as_of=DATES.to_envelope(),
            )
            return self._envelope(
                name,
                data,
                "Synthetic IDX assistant 0.0.1 is up. Database: ok, "
                "active as of 2026-09-18, sold as of 2026-09-17.",
            )
        if name == "search_listings":
            return self._search(args)
        if name == "get_market_stats":
            return self._market(args)
        if name == "rag_answer":
            return self._rag(args)
        if name == "recommend":
            return self._recommend(args)
        if name == "find_similar_listings":
            req = SimilarListingsRequest.from_input(args)
            if isinstance(req, Clarification):
                return self._envelope(name, req, req.question)
            filters = req.hard_filters()
            data = SimilarResult(
                matches=[SimilarMatch(rank=1, score=0.8, listing=_listing(filters))],
                applied_filters=filters,
                k=req.k,
                rows_ranked=1,
                index_as_of=DATES.active,
                model="synthetic-fixture",
            )
            return self._envelope(name, data, format_similar_reply(data, DATES.active))
        if name == "draft_email":
            return self._draft(args)
        if name in {"save_search", "list_saved_searches"}:
            return self._saved(name, args)
        if name in {"delete_saved_search", "forget_me"}:
            return self._envelope(
                name,
                None,
                "Remove the saved search? Reply with confirmation code ABC123 "
                "within 10 minutes."
                if name == "delete_saved_search"
                else "Stop alerts and remove saved searches? Reply with confirmation "
                "code ABC123 within 10 minutes.",
            )
        raise ValueError("unknown tool")

    def _search(self, args: dict[str, Any]) -> AgentResult:
        args = dict(args)
        args.pop("sender_id", None)
        mode = args.pop("mode", "replace")
        clear = args.pop("clear", ())
        if mode == "reset" and not args:
            self.filters, self.last_keys = None, []
            return self._envelope("search_listings", None, "Cleared your search.")
        if mode == "more":
            checked = (
                next_page(self.filters)
                if self.filters
                else Clarification(
                    field="city",
                    reason="missing_location",
                    question="Which city or ZIP code should I search in?",
                )
            )
        else:
            checked = merge_filters(self.filters, args, mode, clear)
        if isinstance(checked, Clarification):
            return self._envelope("search_listings", checked, checked.question)
        if not checked.city and not checked.postal_code:
            checked = Clarification(
                field="city",
                reason="missing_location",
                question="Which city or ZIP code should I search in?",
            )
            return self._envelope("search_listings", checked, checked.question)
        self.filters = checked
        listings = (
            [
                _listing(checked, 9190001 + (checked.page - 1) * checked.limit + i)
                for i in range(checked.limit)
            ]
            if checked.page <= 2
            else []
        )
        self.last_keys = [listing.listing_key for listing in listings]
        data = SearchResult(
            listings=listings,
            applied_filters=checked,
            total_matches=2 * checked.limit,
        )
        return self._envelope(
            "search_listings",
            data,
            format_search_reply(
                data.listings,
                DATES.active,
                format_filters(checked),
                checked.page,
            ),
        )

    def _market(self, args: dict[str, Any]) -> AgentResult:
        req = MarketStatsRequest.from_input(args)
        if isinstance(req, Clarification):
            return self._envelope("get_market_stats", req, req.question)
        window = _window(req.months)
        trend = [
            MonthRow(
                month=month,
                sample_count=12 if month == "2026-09" else 0,
                median_close_price=900000 if month == "2026-09" else None,
            )
            for month in month_keys(window)
        ]
        data = MarketStats(
            geography=Geography(city=req.city, postal_code=req.postal_code),
            property_subtype=req.property_subtype or "SingleFamilyResidence",
            window=window,
            as_of=DATES.sold,
            sample_count=12,
            low_sample=False,
            median_close_price=900000,
            mean_close_price=900000,
            median_price_per_sqft=600,
            median_dom=20,
            dom_band="low",
            sale_to_list_ratio=1,
            sale_to_list_reading="at asking",
            market_lean="seller",
            trend=trend,
            analytics=MarketAnalytics(
                active_count=20,
                active_as_of=DATES.active,
                sold_count=12,
                mean_close_price=900000,
                mean_dom=20,
                mean_price_per_sqft=600,
                months=[
                    MonthAnalytics(
                        month=row.month,
                        sample_count=row.sample_count,
                        partial=row.month
                        in {window.start.strftime("%Y-%m"), "2026-09"},
                        mean_close_price=row.median_close_price,
                        mean_dom=20 if row.sample_count else None,
                        median_price_per_sqft=600 if row.sample_count else None,
                    )
                    for row in trend
                ],
                notes=[
                    "Year-over-year comparison unavailable in this synthetic sample."
                ],
            )
            if req.include_extended
            else None,
        )
        message = format_market_reply(
            data,
            [],
            DATES.sold,
            default_subtype=req.property_subtype is None,
        )
        if req.include_extended:
            message += "\n\n" + format_analytics(data)
        return self._envelope("get_market_stats", data, message)

    def _rag(self, args: dict[str, Any]) -> AgentResult:
        req = RagRequest.from_input(args)
        if isinstance(req, Clarification):
            return self._envelope("rag_answer", req, req.question)
        question = req.question.casefold()
        passages = {
            "DOM": "DOM stands for days on market. It records the duration a home "
            "was marketed; this synthetic field reference uses calendar days.",
            "sale-to-list": "Sale-to-list ratio divides a home's closing price by "
            "its asking price. A ratio of one means those two prices are equal.",
        }
        key = (
            "DOM"
            if "dom" in question or "days on market" in question
            else (
                "sale-to-list"
                if "ratio" in question or "list-to-close" in question
                else None
            )
        )
        chunks = (
            []
            if key is None
            else [
                RetrievedChunk(
                    text=passages[key],
                    source_doc="Synthetic routing reference",
                    section_or_field=key,
                    page=1,
                    score=1,
                    match="exact_name",
                    confidential=False,
                )
            ]
        )
        data = RagAnswer(
            found=bool(chunks),
            chunks=chunks,
            sources=[]
            if key is None
            else [f"Synthetic routing reference: {key}, p. 1"],
            route="synthetic",
            index_built_at=DATES.active,
        )
        return self._envelope(
            "rag_answer",
            data,
            format_rag_passages(data) if data.found else RAG_NOT_FOUND,
        )

    def _recommend(self, args: dict[str, Any]) -> AgentResult:
        req = RecommendRequest.from_input(args)
        if isinstance(req, Clarification):
            return self._envelope("recommend", req, req.question)
        key = req.listing_key
        if key is None:
            if req.position > len(self.last_keys):
                req = RecommendRequest.clarification("no_session")
                return self._envelope("recommend", req, req.question)
            key = self.last_keys[req.position - 1]
        data = RecommendationResult(
            subject=_listing(PropertySearchFilters(), key),
            subject_check=CompEvidence(
                count=0,
                window_months=6,
                sufficient=False,
                sentence="Not enough comparable sales to check this listing.",
            ),
            k=req.k,
            index_as_of=DATES.active if req.k else None,
            comps_window=_window(),
        )
        return self._envelope("recommend", data, format_recommendations(data, DATES))

    def _draft(self, args: dict[str, Any]) -> AgentResult:
        req = DraftEmailRequest.from_input(args)
        if isinstance(req, Clarification):
            return self._envelope("draft_email", req, req.question)
        body = f"Synthetic {req.source} preview. Nothing has been sent."
        if req.source == "listings":
            keys = req.listing_keys or self.last_keys
            if not keys:
                return self._envelope(
                    "draft_email", None, "Which listings should I draft?"
                )
            body += "\nListing identifiers: " + ", ".join(map(str, keys))
        data = EmailDraftView(
            id="routing-fixture-draft",
            recipient_label="owner",
            source=req.source,
            subject="Synthetic IDX preview",
            body=body,
            expires_at=EXPIRY,
            digest_prefix="0123456789ab",
            state="pending",
        )
        result = self._envelope(
            "draft_email",
            data,
            f"Email draft {data.id} for owner is pending human "
            f"approval. Nothing sent.\n\n{data.subject}\n\n{body}",
        )
        return result.model_copy(update={"pending_action": data})

    def _saved(self, name: str, args: dict[str, Any]) -> AgentResult:
        raw = {k: v for k, v in args.items() if k != "sender_id"}
        filters = (
            PropertySearchFilters(city="Pasadena")
            if name == "list_saved_searches"
            else PropertySearchFilters.from_input(raw)
        )
        if isinstance(filters, Clarification):
            return self._envelope(name, filters, filters.question)
        if not filters.city and not filters.postal_code:
            return self._envelope(name, None, "Which city or ZIP code should I save?")
        view = SavedSearchView(
            number=1,
            filters=filters,
            checked_as_of=DATES.active,
            expires_at=EXPIRY,
        )
        return self._envelope(
            name,
            [view] if name == "list_saved_searches" else view,
            f"Saved search 1: {format_filters(filters)}. "
            "New matches create drafts only; every send needs human approval.",
        )
