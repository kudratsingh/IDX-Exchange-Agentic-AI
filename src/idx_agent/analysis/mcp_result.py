"""WO-017 step 6: MCP content blocks for an analysis outcome; no tool is registered.

One TextContent (AgentResult JSON: statuses, trusted values, caveats; no code, worker
numbers or rows) plus one ImageContent when a PNG is present and passes check_png.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from mcp.types import ImageContent, TextContent

from idx_agent.analysis.chart import LABELS
from idx_agent.analysis.fields import UNITS
from idx_agent.analysis.png import check_png
from idx_agent.domain.analysis_outcome import AnalysisOutcome, AnalysisView, FigureView
from idx_agent.domain.market import DEFAULT_SUBTYPE
from idx_agent.domain.results import AgentResult, AsOf, Provenance, ToolError

ANALYSIS_TOOL = "bounded_analysis"  # provenance name only; not a registered tool
SOLD_TABLE = "california_sold"

_FAILURES: dict[str, tuple[str, str]] = {
    "unavailable": ("internal", "Analysis is not available on this server right now."),
    "busy": ("rate_limit", "The analysis worker is busy; try again shortly."),
    "timeout": ("timeout", "The analysis ran past its time limit and was stopped."),
    "output_too_large": (
        "safety_refusal",
        "The analysis printed more than allowed and was stopped.",
    ),
    "failed": ("internal", "The analysis code did not finish."),
    "invalid_code": ("validation", "The analysis code was refused before it ran."),
    "invalid_output": ("safety_refusal", "The analysis output was refused."),
    "db_error": ("db", "The sales data could not be read."),
    "db_timeout": ("timeout", "Reading the sales data took too long."),
}
_CHART_LINES: dict[str, str] = {
    "rendered": "Chart: attached.",
    "refused": "Chart: the requested chart is not supported; none was drawn.",
    "not_requested": "",
}
_CHART_FAILED = "Chart: could not be drawn this time."
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _with_ref(message: str, trace_id: str) -> str:
    base = message[:-1] if message.endswith(".") else message
    return f"{base} (ref {trace_id[:6]})."


def _number(value: float, kind: str, unit: str | None) -> str:
    if kind == "count":
        return f"{value:,.0f} sales"
    if unit == "USD":
        return f"${value:,.2f}"
    if unit == "percent":
        return f"{value:,.2f}%"
    if unit is None:
        return f"{value:,.4f}"
    return f"{value:,.2f} {unit}"


def _figure_line(figure: FigureView) -> str:
    x = LABELS[figure.x].lower() if figure.x else "?"
    what = f"{figure.kind} of {x}"
    if figure.y is not None:
        y = LABELS[figure.y].lower()
        joint = figure.kind in ("pearson", "spearman")
        what = (
            f"{figure.kind} of {x} and {y}"
            if joint
            else f"{figure.kind} of {y} on {x}"  # least squares, y on x
        )
    if figure.kind == "other":
        return f"{figure.index}. {what}: not checked; no trusted value."
    if figure.trusted is None:
        return f"{figure.index}. {what}: unavailable ({figure.reason}, n={figure.n})."
    one = figure.y is None
    trusted = _number(figure.trusted, figure.kind, UNITS[figure.x] if one else None)
    if figure.status == "verified":
        return f"{figure.index}. {what}: {trusted}, verified (n={figure.n})."
    return (
        f"{figure.index}. {what}: the worker's number did not match "
        f"({figure.reason}); the trusted value is {trusted} (n={figure.n})."
    )


def _place(view: AnalysisView) -> str:
    place = view.city if view.city is not None else f"ZIP {view.postal_code}"
    subtype = _CAMEL.sub(" ", view.property_subtype or DEFAULT_SUBTYPE)
    return f"{place}, {subtype}"


def analysis_message(view: AnalysisView) -> str:
    """Plain summary from trusted values and fixed wording only."""
    if view.status == "no_sales":
        return (
            f"No eligible sales in {_place(view)} closed {view.window_start} to "
            f"{view.window_end}; nothing was analysed."
        )
    lines = [
        f"Bounded analysis of {view.n} sales in {_place(view)}, closed "
        f"{view.window_start} to {view.window_end} (sold data as of "
        f"{view.sold_as_of}). Only trusted values are shown."
    ]
    lines += [_figure_line(figure) for figure in view.figures]
    if not view.figures:
        lines.append("No figures were reported.")
    chart = _CHART_LINES.get(view.chart.status, _CHART_FAILED)
    if chart:
        lines.append(chart)
    lines.append("Caveats: " + " ".join(view.caveats))
    return "\n".join(lines)


def analysis_result(outcome: AnalysisOutcome) -> AgentResult[AnalysisView]:
    """The AgentResult envelope for an outcome; data is the view, never the PNG."""
    view = outcome.view()
    provenance = Provenance(
        tables=[SOLD_TABLE] if outcome.as_of is not None else [],
        as_of=outcome.as_of.to_envelope() if outcome.as_of is not None else AsOf(),
        tool=ANALYSIS_TOOL,
        trace_id=outcome.trace_id,
    )
    if outcome.status in _FAILURES:
        category, message = _FAILURES[outcome.status]
        return AgentResult[AnalysisView](
            ok=False,
            data=view,
            message=_with_ref(message, outcome.trace_id),
            warnings=list(outcome.caveats),
            provenance=provenance,
            error=ToolError(
                category=category,
                message=_with_ref(message, outcome.trace_id),
                trace_id=outcome.trace_id,
            ),
        )
    return AgentResult[AnalysisView](
        ok=True,
        data=view,
        message=analysis_message(view),
        warnings=list(outcome.caveats),
        provenance=provenance,
    )


def analysis_content(outcome: AnalysisOutcome) -> list[Any]:
    """[TextContent] plus an ImageContent when a checked PNG is present."""
    result = analysis_result(outcome)
    text = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    blocks: list[Any] = [TextContent(type="text", text=text)]
    if outcome.png is not None and check_png(outcome.png):
        blocks.append(
            ImageContent(
                type="image",
                data=base64.b64encode(outcome.png).decode("ascii"),
                mimeType="image/png",
            )
        )
    return blocks
