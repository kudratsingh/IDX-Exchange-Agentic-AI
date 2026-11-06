"""Invented, versioned tool replies for routing-only evaluation (WO-019).

No tool bodies or external I/O. Inputs are actual calls, never expected routes,
case IDs or expected filters. Boundary models and pure formatters define the shape.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pydantic_core
from pydantic import ValidationError

from idx_agent.analysis import tool as analysis_tool
from idx_agent.analysis.mcp_result import analysis_message
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
from idx_agent.domain.analysis_outcome import (
    DEFAULT_CAVEATS,
    AnalysisView,
    ChartView,
    FigureView,
)
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
from idx_agent.mcp_server.server import ONE_COPY_TOOLS
from idx_agent.mcp_server.wire import javascript_json, one_copy
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


# How a served reply reaches the model (relay cases, P1-4 follow-up 2026-11-05; Layer 2
# of the relay fix the same day). compact: one compact JSON block (the routing
# driver's original shape). openclaw_two_copy: OpenClaw 2026.9.5's projection of the
# payload as the server sent it before Layer 2 (a whole float such as 4.0 kept, so the
# card reaches the model twice: P1-4). openclaw_one_copy: the same projection of the
# payload the card tools send now (mcp_server/wire.one_copy: the card once).
SERVED_SHAPES = ("compact", "openclaw_two_copy", "openclaw_one_copy")
# The card numbers a relay case may set per served listing (synthetic values only).
SERVED_LISTING_FIELDS = frozenset(
    {
        "list_price",
        "bedrooms",
        "bathrooms",
        "living_area",
        "days_on_market",
        "photo_count",
        "year_built",
    }
)
STRUCTURED_PREFIX = "structuredContent:\n"


def compact_json(result: AgentResult) -> str:
    """One compact JSON block, nulls dropped: the routing driver's original shape."""
    return json.dumps(result.model_dump(mode="json", exclude_none=True))


def _js_numbers(value: Any) -> Any:
    """JSON.stringify prints an integral float as an integer (5.0 -> 5)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _js_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_js_numbers(v) for v in value]
    return value


def _js_stringify(value: Any, sort_keys: bool = False) -> str:
    """JSON.stringify(value, null, 2), for the JSON values a tool result holds: numbers
    and strings spelled as JavaScript does (wire.javascript_json; 1e-6 is 0.000001)."""
    return javascript_json(_js_numbers(value), sort_keys=sort_keys)


def openclaw_projection(
    sdk_texts: Sequence[str], structured: Mapping[str, Any]
) -> list[dict[str, str]]:
    """OpenClaw 2026.9.5's projectMcpCallToolResultContent for a result with
    structuredContent and text blocks (dist/mcp-content-Dj8o6nFL.mjs:106-116): first
    "structuredContent:" and the key-sorted JSON, then every SDK text block except one
    whose text equals JSON.stringify(structuredContent, null, 2) (line 113). The
    structured content is the JSON the gateway parsed, so it crosses the wire first."""
    parsed = json.loads(json.dumps(structured))
    mirrored = _js_stringify(_js_key_order(parsed))
    blocks = [{"type": "text", "text": STRUCTURED_PREFIX + _js_stringify(parsed, True)}]
    blocks += [{"type": "text", "text": text} for text in sdk_texts if text != mirrored]
    return blocks


def _js_key_order(value: Any) -> Any:
    """JSON.parse lists an object's integer-like keys first, ascending (ES spec)."""
    if isinstance(value, dict):
        index = sorted(
            (
                k
                for k in value
                if k == "0"
                or (k.isascii() and k.isdigit() and k[0] != "0" and int(k) < 2**32 - 1)
            ),
            key=int,
        )
        seen = set(index)
        rest = [k for k in value if k not in seen]
        return {k: _js_key_order(value[k]) for k in [*index, *rest]}
    if isinstance(value, list):
        return [_js_key_order(v) for v in value]
    return value


def openclaw_blocks(result: AgentResult, one: bool = False) -> list[dict[str, str]]:
    """The text blocks OpenClaw 2026.9.5 gives the model for one of our tool results.

    The server returns its envelope as a dict (mcp_server/server.py), so the MCP SDK
    sends it as structuredContent plus an indented-JSON text block
    (pydantic_core.to_json, indent 2), and openclaw_projection keeps that text block
    unless it mirrors the structured content. Before Layer 2 the dict was
    `model_dump(mode="json")`: Python writes an integral float as 5.0 and JS as 5, so a
    card with whole bathrooms reached the model twice (the P1-4 shape). With `one`, the
    dict is the card tools' payload now (wire.one_copy) and the text block is written
    with wire.javascript_json, as server._CardServer writes it, so it is dropped (1e-6
    included). Without `one` the legacy two-copy path is unchanged.
    """
    structured = result.model_dump(mode="json")
    if one:
        structured = one_copy(structured)
        sdk_text = javascript_json(structured)
    else:
        sdk_text = pydantic_core.to_json(structured, indent=2).decode()
    return openclaw_projection([sdk_text], structured)


class RoutingFixtures:
    """One isolated case, seeded only by structured prior search calls.

    State is local values, never the runtime store. Historical cards stay in the
    authored history; seeding does not rewrite those model inputs.
    """

    def __init__(
        self,
        listings: Sequence[Mapping[str, Any]] = (),
        shape: str = "compact",
    ) -> None:
        """`listings` (a relay case's `served.listings`) replaces the invented card
        numbers of every search page, one listing per entry; `shape` is how a reply
        reaches the model, one of SERVED_SHAPES (see openclaw_blocks)."""
        if shape not in SERVED_SHAPES:
            raise ValueError(f"unknown served shape {shape!r}")
        self.filters: PropertySearchFilters | None = None
        self.last_keys: list[int] = []
        self.served = [dict(entry) for entry in listings]
        self.shape = shape

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

    def result(self, name: str, arguments: Mapping[str, Any]) -> AgentResult:
        """The envelope a call gets (a validation error for unusable arguments)."""
        name = name.removeprefix("idx__").removeprefix("idx_alerts__")
        args = {k: v for k, v in arguments.items() if v is not None}
        try:
            return self._reply(name, args)
        except (ValidationError, ValueError, TypeError):
            message = "Please use the supported tool arguments."
            return AgentResult(
                ok=False,
                message=message,
                warnings=[NOTICE],
                provenance=Provenance(tool=name, trace_id=TRACE),
                error=ToolError(category="validation", message=message, trace_id=TRACE),
            )

    def reply(self, name: str, arguments: Mapping[str, Any]) -> str:
        return compact_json(self.result(name, arguments))

    def content(self, result: AgentResult) -> str | list[dict[str, str]]:
        """The tool message content in this case's shape."""
        if self.shape == "openclaw_two_copy":
            return openclaw_blocks(result)
        if self.shape == "openclaw_one_copy":
            # Only the card tools send the one-copy payload (server.ONE_COPY_TOOLS).
            card = result.provenance.tool in ONE_COPY_TOOLS
            return openclaw_blocks(result, one=card)
        return compact_json(result)

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
        if name == analysis_tool.TOOL_NAME:
            return self._analysis(args)
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

    def _analysis(self, args: dict[str, Any]) -> AgentResult:
        """The opt-in bounded_analysis tool (WO-027): the tool's own place and code
        checks, then one invented verified figure in the tool's own wording."""
        req = analysis_tool.request_from(args)
        if isinstance(req, Clarification):
            return self._envelope(analysis_tool.TOOL_NAME, req, req.question)
        if analysis_tool.code_problem(args.get("code")) is not None:
            raise ValueError("the analysis code was refused")
        window = _window(req.months)
        view = AnalysisView(
            status="ok",
            city=req.city,
            postal_code=req.postal_code,
            property_subtype=req.property_subtype,
            months=req.months,
            window_start=window.start,
            window_end=window.end,
            sold_as_of=DATES.sold,
            active_as_of=DATES.active,
            n=12,
            eligible=12,
            caveats=DEFAULT_CAVEATS,
            figures=(
                FigureView(
                    index=1,
                    kind="pearson",
                    x="living_area",
                    y="close_price",
                    status="verified",
                    reason=None,
                    trusted=0.5,
                    n=12,
                ),
            ),
            chart=ChartView(status="not_requested"),
        )
        return self._envelope(analysis_tool.TOOL_NAME, view, analysis_message(view))

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
        if self.served:
            first = 9190001 + (checked.page - 1) * checked.limit
            # Validated, so whole bathrooms become floats exactly as the server's are.
            listings = [
                Listing.model_validate(
                    {**_listing(checked, first + i).model_dump(), **numbers}
                )
                for i, numbers in enumerate(self.served)
            ]
            total = len(listings)
        else:
            listings = (
                [
                    _listing(checked, 9190001 + (checked.page - 1) * checked.limit + i)
                    for i in range(checked.limit)
                ]
                if checked.page <= 2
                else []
            )
            total = 2 * checked.limit
        self.last_keys = [listing.listing_key for listing in listings]
        data = SearchResult(
            listings=listings,
            applied_filters=checked,
            total_matches=total,
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
