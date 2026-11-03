"""WO-017 Phase C: the `bounded_analysis` tool's pieces, registered only when enabled.

Argument checks, the pinned-image setting, and the MCP content blocks. The tool body in
the server calls `service.run_bounded_analysis`; nothing here touches the database.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from typing import Any

from mcp.types import ImageContent, TextContent

from idx_agent.analysis.executor import MAX_CODE_CHARS
from idx_agent.analysis.png import check_png
from idx_agent.domain.analysis_worker import IMAGE_ENV, ExecutorConfig
from idx_agent.domain.models import Clarification, MarketStatsRequest

__all__ = [
    "PLACE_ARGS",
    "TOOL_NAME",
    "TOOL_SETTING",
    "code_problem",
    "content_blocks",
    "enabled",
    "executor_config",
    "request_from",
]

TOOL_NAME = "bounded_analysis"
# Off unless exactly "1": registration is a separate, owner-approved activation step.
TOOL_SETTING = "IDX_ANALYSIS_TOOL"
# The only place arguments; the window counts back from the sold as-of date.
PLACE_ARGS = ("city", "postal_code", "property_subtype", "months")


def enabled(setting: Callable[[str], str | None]) -> bool:
    """True only when IDX_ANALYSIS_TOOL is exactly "1" (no surrounding spaces)."""
    return setting(TOOL_SETTING) == "1"


def executor_config(
    setting: Callable[[str], str | None],
) -> tuple[ExecutorConfig | None, str | None]:
    """The pinned worker config, or (None, reason): unset, or not pinned by digest.

    Either way the run answers `unavailable`; there is never a host fallback.
    """
    try:
        config = ExecutorConfig.from_env({IMAGE_ENV: setting(IMAGE_ENV) or ""})
    except ValueError:
        return None, "image_not_pinned"
    return config, None if config is not None else "image_unset"


def request_from(raw: Mapping[str, object]) -> MarketStatsRequest | Clarification:
    """The sample request from the place arguments only, as get_market_stats checks
    them; anything else (extended figures, columns, SQL) is not an argument."""
    return MarketStatsRequest.from_input(
        {k: v for k, v in raw.items() if k in PLACE_ARGS and v is not None}
    )


def code_problem(code: object) -> str | None:
    """Why the code is refused before any database read, or None."""
    if not isinstance(code, str) or not code.strip():
        return "code_missing"
    if len(code) > MAX_CODE_CHARS:
        return "code_too_long"
    if "\x00" in code:
        return "code_has_nul"
    try:
        code.encode("utf-8")
    except UnicodeEncodeError:
        return "code_not_utf8"
    return None


def content_blocks(payload: Mapping[str, Any], png: bytes | None) -> list[Any]:
    """The envelope JSON as text, plus the PNG only for an ok run whose image passes
    the host's own check again; a refused or failed run never carries an image."""
    text = json.dumps(dict(payload), sort_keys=True)
    blocks: list[Any] = [TextContent(type="text", text=text)]
    if payload.get("ok") and png is not None and check_png(png):
        data = base64.b64encode(png).decode("ascii")
        blocks.append(ImageContent(type="image", data=data, mimeType="image/png"))
    return blocks
