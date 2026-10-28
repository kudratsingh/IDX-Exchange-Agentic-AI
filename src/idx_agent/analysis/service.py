"""WO-017 step 6: one bounded analysis from steps 1-5; no tool is registered.

As-of window -> sample reader -> worker run -> figure checks -> chart data from the
trusted sample -> render run -> PNG check. Failures are status codes; logs get codes.
"""

from __future__ import annotations

import threading
from typing import Any

from idx_agent.analysis import executor
from idx_agent.analysis.chart import ChartSpecError, build_chart
from idx_agent.analysis.png import check_png
from idx_agent.analysis.verify import verify_figures
from idx_agent.db import analysis as db_analysis
from idx_agent.db import asof as db_asof
from idx_agent.domain.analysis import AnalysisSample
from idx_agent.domain.analysis_chart import ChartData
from idx_agent.domain.analysis_outcome import DEFAULT_CAVEATS, AnalysisOutcome
from idx_agent.domain.analysis_output import ChartRequest
from idx_agent.domain.analysis_worker import ExecutorConfig
from idx_agent.domain.models import MarketStatsRequest, StatsWindow
from idx_agent.observability.logging import new_trace_id

__all__ = ["analyse_sample", "reset_sweep_for_tests", "run_bounded_analysis"]

_sweep_lock = threading.Lock()
_swept = False


def _sweep_once(config: ExecutorConfig) -> None:
    """Clear leftovers of a killed earlier process, once per process, before a run.

    The analysis is not a registered tool, so there is no server start-up hook;
    the first run pays for the sweep. A failing sweep never blocks the run.
    """
    global _swept
    with _sweep_lock:
        if _swept:
            return
        _swept = True
        try:
            executor.sweep_leftovers(config)
        except Exception:  # noqa: BLE001 - best effort; the run still cleans up
            pass


def reset_sweep_for_tests() -> None:
    global _swept
    with _sweep_lock:
        _swept = False


def _chart_args(request: ChartRequest) -> dict[str, Any]:
    """build_chart arguments from a validated chart request (kind, fields, bins)."""
    args: dict[str, Any] = {"kind": request.kind, "x": request.x}
    if request.kind != "histogram":
        args["y"] = request.y
    if request.kind != "scatter":
        args["bins"] = request.bins
    return args


def _log_counts(log: dict[str, Any], outcome: AnalysisOutcome) -> AnalysisOutcome:
    statuses: dict[str, int] = {}
    for check in outcome.checks:
        statuses[check.status] = statuses.get(check.status, 0) + 1
    log.update(
        outcome=outcome.status,
        reason=outcome.reason,
        sample_count=outcome.n,
        eligible=outcome.eligible,
        figure_count=len(outcome.checks),
        figure_statuses=statuses,
        chart_status=outcome.chart_status,
    )
    return outcome


def analyse_sample(
    sample: AnalysisSample,
    code: str,
    config: ExecutorConfig | None,
    *,
    trace_id: str | None = None,
    log_fields: dict[str, Any] | None = None,
) -> AnalysisOutcome:
    """Run model code over an already-read sample and check everything it claims."""
    trace_id = trace_id or new_trace_id()
    log = log_fields if log_fields is not None else {}
    base: dict[str, Any] = dict(
        trace_id=trace_id,
        scope=sample.scope,
        window=sample.window,
        as_of=sample.as_of,
        n=len(sample.rows),
        eligible=sample.eligible,
        caveats=sample.caveats(),
    )
    if not sample.rows:
        return _log_counts(log, AnalysisOutcome(status="no_sales", **base))
    if config is None:
        return _log_counts(log, AnalysisOutcome(status="unavailable", **base))
    _sweep_once(config)
    run = executor.run_analysis(config, sample, code)
    if run.status != "ok" or run.output is None:
        status = "failed" if run.status == "ok" else run.status
        return _log_counts(
            log, AnalysisOutcome(status=status, reason=run.reason, **base)
        )
    checks = verify_figures(sample, run.output)
    chart: ChartData | None = None
    png: bytes | None = None
    chart_status = "not_requested"
    if run.output.chart is not None:
        try:
            chart = build_chart(sample, **_chart_args(run.output.chart))
        except (ChartSpecError, ValueError):
            chart, chart_status = None, "refused"
        if chart is not None:
            rendered = executor.render_chart(config, chart)
            if rendered.status == "ok" and check_png(rendered.png):
                png, chart_status = rendered.png, "rendered"
            else:
                ok = rendered.status == "ok"
                chart_status = "invalid_png" if ok else rendered.status
    outcome = AnalysisOutcome(
        status="ok",
        checks=checks,
        chart_status=chart_status,
        chart=chart,
        png=png,
        **base,
    )
    return _log_counts(log, outcome)


def run_bounded_analysis(
    request: MarketStatsRequest,
    code: str,
    conn: Any,
    config: ExecutorConfig | None,
    *,
    trace_id: str | None = None,
    log_fields: dict[str, Any] | None = None,
) -> AnalysisOutcome:
    """Read the bounded sample for `request` on `conn`, then `analyse_sample`.

    The chart request, if any, comes from the worker's own output, never from an
    argument. `config` None (no pinned image configured) gives `unavailable`.
    """
    trace_id = trace_id or new_trace_id()
    log = log_fields if log_fields is not None else {}
    try:
        as_of = db_asof.get_asof_dates(conn)
        start, end = as_of.window(request.months)
        window = StatsWindow(start=start, end=end, months=request.months)
        sample = db_analysis.fetch_analysis_sample(request, window, as_of, conn)
    except Exception as exc:  # noqa: BLE001 - a status code, never raised or echoed
        timed_out = isinstance(exc, db_analysis.AnalysisDeadlineExceeded)
        if not timed_out:
            log["error_type"] = type(exc).__name__
        outcome = AnalysisOutcome(
            trace_id=trace_id,
            status="db_timeout" if timed_out else "db_error",
            scope=request,
            caveats=DEFAULT_CAVEATS,
        )
        return _log_counts(log, outcome)
    return analyse_sample(sample, code, config, trace_id=trace_id, log_fields=log)
