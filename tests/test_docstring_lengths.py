"""Keep production docstrings within the repository's five-line convention."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# This baseline is intentionally sorted and may shrink, but never grow.
ALLOWLIST = [
    "evals/run.py::<module>",
    "evals/run.py::model_tool_call",
    "evals/run.py::run_turns",
    "src/idx_agent/channels/format.py::format_listing_card",
    "src/idx_agent/channels/format.py::format_search_reply",
    "src/idx_agent/db/comps.py::build_comps_sql",
    "src/idx_agent/db/listings.py::build_candidate_sql",
    "src/idx_agent/db/market.py::<module>",
    "src/idx_agent/db/market.py::_median",
    "src/idx_agent/db/market.py::_sample",
    "src/idx_agent/db/pool.py::dotenv_values",
    "src/idx_agent/db/pool.py::env_setting",
    "src/idx_agent/domain/comps.py::CompsAggregate",
    "src/idx_agent/domain/comps.py::contains_forbidden",
    "src/idx_agent/domain/comps.py::price_check",
    "src/idx_agent/domain/comps.py::reference_price_check",
    "src/idx_agent/domain/market.py::MarketAggregates",
    "src/idx_agent/domain/market.py::build_market_stats",
    "src/idx_agent/domain/models.py::CompEvidence",
    "src/idx_agent/domain/models.py::MarketStats",
    "src/idx_agent/domain/models.py::MarketStatsRequest",
    "src/idx_agent/domain/models.py::PropertySearchFilters",
    "src/idx_agent/domain/models.py::PropertySearchFilters.from_input",
    "src/idx_agent/domain/models.py::RecommendRequest",
    "src/idx_agent/domain/models.py::RecommendationResult",
    "src/idx_agent/domain/models.py::RetrievedChunk",
    "src/idx_agent/domain/models.py::SearchResult",
    "src/idx_agent/domain/models.py::SimilarListingsRequest",
    "src/idx_agent/domain/models.py::SimilarListingsRequest.from_input",
    "src/idx_agent/domain/models.py::SimilarResult",
    "src/idx_agent/domain/results.py::<module>",
    "src/idx_agent/domain/results.py::AgentResult",
    "src/idx_agent/domain/results.py::HealthData",
    "src/idx_agent/domain/results.py::PendingAction",
    "src/idx_agent/domain/results.py::ToolError",
    "src/idx_agent/mcp_server/server.py::_guarded",
    "src/idx_agent/mcp_server/server.py::_page_total",
    "src/idx_agent/mcp_server/server.py::find_similar_listings",
    "src/idx_agent/mcp_server/server.py::market_result",
    "src/idx_agent/mcp_server/server.py::rag_result",
    "src/idx_agent/mcp_server/server.py::recommend_result",
    "src/idx_agent/mcp_server/server.py::request_meta_summary",
    "src/idx_agent/mcp_server/server.py::search_listings",
    "src/idx_agent/mcp_server/server.py::search_result",
    "src/idx_agent/mcp_server/server.py::similar_result",
    "src/idx_agent/memory/identity.py::sender_key",
    "src/idx_agent/memory/merge.py::merge_filters",
    "src/idx_agent/observability/logging.py::archive_path",
    "src/idx_agent/observability/logging.py::log_event",
    "src/idx_agent/observability/logging.py::redact",
    "src/idx_agent/observability/tracing.py::span",
    "src/idx_agent/observability/tracing.py::span_attributes",
    "src/idx_agent/rag/store.py::<module>",
    "src/idx_agent/rag/store.py::write_doc_index",
    "src/idx_agent/safety/columns.py::<module>",
    "src/idx_agent/safety/columns.py::check_column",
    "src/idx_agent/semantic/build_index.py::build",
    "src/idx_agent/semantic/embedder.py::OpenAIEmbedder",
    "src/idx_agent/semantic/index.py::rank",
    "src/idx_agent/semantic/query.py::RankedFetch",
    "src/idx_agent/semantic/query.py::SimilarOutcome",
    "src/idx_agent/semantic/query.py::fetch_in_rank_order",
    "src/idx_agent/semantic/query.py::find_similar",
]


def _files() -> list[Path]:
    paths = [*sorted((ROOT / "src").rglob("*.py")), ROOT / "evals" / "run.py"]
    paths.extend(sorted((ROOT / "scripts").glob("*.py")))
    paths.extend(sorted((ROOT / "tests").glob("*.py")))
    return paths


def _overlong_docstrings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        docstring = ast.get_docstring(node, clean=False)
        if docstring is not None and len(docstring.splitlines()) > 5:
            name = ".".join(parents) or "<module>"
            found.append(f"{path.relative_to(ROOT)}::{name}")
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, (*parents, child.name))
            else:
                visit_children(child, parents)

    def visit_children(node: ast.AST, parents: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, (*parents, child.name))
            else:
                visit_children(child, parents)

    visit(tree)
    return found


def test_docstrings_over_five_lines_are_allowlisted() -> None:
    """Pin current exceptions while future work shortens the list."""
    assert ALLOWLIST == sorted(ALLOWLIST)
    unexpected = sorted(
        name
        for path in _files()
        for name in _overlong_docstrings(path)
        if name not in ALLOWLIST
    )

    assert not unexpected, "\n".join(unexpected)
