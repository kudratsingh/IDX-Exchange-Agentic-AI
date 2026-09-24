"""Optional OpenTelemetry spans for tool calls, exported to a local collector (WO-007).

Off unless IDX_OTLP_ENDPOINT names a loopback http URL and the `tracing` extra is
installed; when off, `span()` is a no-op and the SDK is never imported. Attributes
pass the ALLOWED_ATTRIBUTES filter, then `redact()`. See docs/TRACING.md.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

from idx_agent import __version__
from idx_agent.db.pool import env_setting
from idx_agent.observability.logging import log_event, new_trace_id, redact

ENDPOINT_ENV = "IDX_OTLP_ENDPOINT"
# Resource attributes: the service name our spans appear under in the viewer.
SERVICE_NAME = "idx-mcp"
# Seconds one export may take; exports run on the batch thread, never in a call.
EXPORT_TIMEOUT_S = 2.0
# At most one "trace_export_failed" log line per this many seconds.
EXPORT_FAILURE_LOG_INTERVAL_S = 60.0

# Every attribute name a span may carry (WO-007 contract); anything else is dropped.
# Pinned in tests/test_tracing.py, so a new name has to be added in both places.
FILTER_FIELDS = (
    "city",
    "postal_code",
    "min_price",
    "max_price",
    "min_beds",
    "min_baths",
    "min_sqft",
    "property_subtype",
    "pool",
    "view",
    "max_hoa_monthly",
    "page",
    "limit",
)
ALLOWED_ATTRIBUTES = frozenset(
    {
        "idx.trace_id",
        "idx.tool",
        "idx.ok",
        "idx.error",
        "idx.error_type",
        "idx.mode",
        "idx.key_prefix",
        "idx.rows",
        "idx.skipped",
        "idx.total_matches",
        "idx.clarification",
        "idx.field",
        "idx.cleared",
        "idx.last_page",
        "idx.count_error",
        "idx.meta_keys",
        # WO-008 get_market_stats: its outcome, sales after exclusions, window used.
        "idx.outcome",
        "idx.sample_count",
        "idx.months",
        # WO-010 find_similar_listings: counts, one boolean, the embedding model name
        # and its dimension. Never the text, a vector, a remark, or a listing key.
        "idx.k",
        "idx.text_words",
        "idx.text_chars",
        "idx.rows_ranked",
        "idx.keys_fetched",
        "idx.dropped",
        "idx.matches",
        "idx.stale_index",
        "idx.model",
        "idx.dims",
        # WO-011 recommend: the subject's comps level ("city" or "postal_code") and
        # count, listings returned, and how the subject was named ("key", "position").
        "idx.level",
        "idx.comps",
        "idx.recommendations",
        "idx.resolved_by",
        *(f"idx.filters.{name}" for name in FILTER_FIELDS),
    }
)
# The only attribute whose value may be a list (of strings: the meta key names).
LIST_ATTRIBUTES = frozenset({"idx.meta_keys"})

AttrValue = str | bool | int | float | list[str | bool | int | float]
_PRIMITIVES = (str, bool, int, float)


def span_attributes(fields: Mapping[str, object]) -> dict[str, AttrValue]:
    """Log-line fields to span attributes: prefix, flatten, allowlist, then redact.

    `trace_id` becomes `idx.trace_id`; the `filters` dict becomes one
    `idx.filters.<field>` each. Names outside ALLOWED_ATTRIBUTES, None values,
    and non-primitive values are dropped (lists only for LIST_ATTRIBUTES).
    """
    flat: dict[str, object] = {}
    for key, value in fields.items():
        name = key if key.startswith("idx.") else f"idx.{key}"
        if name == "idx.filters" and isinstance(value, Mapping):
            flat.update({f"idx.filters.{k}": v for k, v in value.items()})
        else:
            flat[name] = value
    attrs: dict[str, AttrValue] = {}
    for name, value in flat.items():
        if name not in ALLOWED_ATTRIBUTES or value is None:
            continue
        if isinstance(value, _PRIMITIVES):
            attrs[name] = redact(value)
        elif (
            name in LIST_ATTRIBUTES
            and isinstance(value, list | tuple)
            and all(isinstance(v, _PRIMITIVES) for v in value)
        ):
            attrs[name] = redact(list(value))
    return attrs


class SpanHandle:
    """What `span()` yields: `set(fields)` adds allowlisted attributes, or does
    nothing when tracing is off."""

    def __init__(self, otel_span: Any = None) -> None:
        self._span = otel_span

    def set(self, fields: Mapping[str, object]) -> None:
        if self._span is None:
            return
        try:
            self._span.set_attributes(span_attributes(fields))
        except Exception as exc:  # noqa: BLE001 - tracing never fails a call
            _report_error(exc)


_NOOP = SpanHandle()
# Process state: one tracer, built on first use; a test tracer wins when installed.
_lock = threading.Lock()
_tracer: Any = None
_provider: Any = None
_test_provider: Any = None
_setup_failed = False
_error_reported = False
# IDX_OTLP_ENDPOINT, read once per process on first use: a changed endpoint needs a
# restart. _UNREAD until then; configure_for_tests(None) sets it back.
_UNREAD: Any = object()
_endpoint_value: Any = _UNREAD


def _report_error(exc: BaseException) -> None:
    """Log the first tracing error of the process by its type; later ones are silent."""
    global _error_reported
    if _error_reported:
        return
    _error_reported = True
    try:
        log_event("tracing_error", new_trace_id(), error=type(exc).__name__)
    except Exception:  # noqa: BLE001, S110 - the log line is best effort
        pass


def _host(endpoint: str) -> str | None:
    """The URL's host when the URL parses with a well-formed port, else None."""
    try:
        parts = urlsplit(endpoint)
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    return parts.hostname


def loopback_url(endpoint: str) -> bool:
    """True for an http URL whose host is localhost or a loopback IP (no DNS)."""
    host = _host(endpoint)
    if not host or not endpoint.lower().startswith("http://"):
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _read_endpoint() -> str | None:
    """IDX_OTLP_ENDPOINT when it is a loopback URL; else None. A refused value is
    logged by its host only (never a path or query). Called once per process."""
    endpoint = (env_setting(ENDPOINT_ENV) or "").strip()
    if not endpoint:
        return None
    if loopback_url(endpoint):
        return endpoint
    log_event(
        "tracing_refused",
        new_trace_id(),
        reason="IDX_OTLP_ENDPOINT must be an http URL on a loopback host",
        host=_host(endpoint) or "-",
    )
    return None


def _direct_session() -> Any:
    """A requests session that ignores HTTP(S)_PROXY, ALL_PROXY, and .netrc, so no
    proxy setting can route spans off the machine."""
    import requests

    session = requests.Session()
    session.trust_env = False
    return session


def _build_tracer(endpoint: str) -> Any:
    """Import the SDK and build the batch export pipeline; None if anything fails.

    A missing extra or any other error (a bad OTEL_* variable, say) sets
    _setup_failed and logs one line; tracing then stays off for the process.
    """
    global _provider, _setup_failed
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        _setup_failed = True
        log_event(
            "tracing_unavailable",
            new_trace_id(),
            reason="install the tracing extra: pip install -e '.[tracing]'",
        )
        return None
    provider = None
    try:
        url = endpoint.rstrip("/")
        if not url.endswith("/v1/traces"):
            url += "/v1/traces"
        # The exporter's own per-batch warnings are silenced; _ThrottledExporter
        # logs failures instead, at most once per interval.
        logging.getLogger("opentelemetry.exporter.otlp.proto.http").setLevel(
            logging.CRITICAL
        )
        exporter = OTLPSpanExporter(
            endpoint=url, timeout=EXPORT_TIMEOUT_S, session=_direct_session()
        )
        provider = _new_provider(BatchSpanProcessor(_ThrottledExporter(exporter)))
        tracer = provider.get_tracer("idx_agent", __version__)
    except Exception as exc:  # noqa: BLE001 - tracing never fails a call
        _setup_failed = True
        if provider is not None:
            _shutdown_quietly(provider)
        log_event("tracing_setup_failed", new_trace_id(), error=type(exc).__name__)
        return None
    _provider = provider
    return tracer


def _shutdown_quietly(provider: Any) -> None:
    """Shut a provider down (its batch thread stops); an error is ignored."""
    try:
        provider.shutdown()
    except Exception:  # noqa: BLE001, S110 - already failing open
        pass


def _new_provider(processor: Any) -> Any:
    """A TracerProvider with exactly our two resource attributes (no telemetry.sdk.*,
    no OTEL_RESOURCE_ATTRIBUTES). Not installed globally, so the MCP SDK's own spans
    (tool arguments among them) stay no-ops."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource({"service.name": SERVICE_NAME, "service.version": __version__})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    return provider


class _ThrottledExporter:
    """Wraps the OTLP exporter: never raises, and logs a failed export at most once
    per EXPORT_FAILURE_LOG_INTERVAL_S (a down collector costs one line a minute)."""

    def __init__(self, inner: Any, clock: Any = time.monotonic) -> None:
        self._inner = inner
        self._clock = clock
        self._last_logged: float | None = None

    def export(self, spans: Sequence[Any]) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self._inner.export(spans)
        except Exception as exc:  # noqa: BLE001 - tracing never fails a call
            result, error = SpanExportResult.FAILURE, type(exc).__name__
        else:
            error = "export_failed"
        if result is not SpanExportResult.SUCCESS:
            now = self._clock()
            last = self._last_logged
            if last is None or now - last >= EXPORT_FAILURE_LOG_INTERVAL_S:
                self._last_logged = now
                log_event(
                    "trace_export_failed", new_trace_id(), error=error, spans=len(spans)
                )
        return result

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def _get_tracer() -> Any:
    """The tracer to use now, or None when tracing is off (the common case)."""
    global _tracer, _endpoint_value
    if _test_provider is not None:
        return _test_provider.get_tracer("idx_agent", __version__)
    if _tracer is not None:
        return _tracer  # built once; a changed endpoint needs a restart
    if _endpoint_value is None or _setup_failed:
        return None  # off: decided once, no lock and no environment read
    with _lock:
        if _endpoint_value is _UNREAD:
            _endpoint_value = _read_endpoint()
        if _tracer is None and _endpoint_value is not None and not _setup_failed:
            _tracer = _build_tracer(_endpoint_value)
        return _tracer


def tracing_enabled() -> bool:
    """True only with a loopback IDX_OTLP_ENDPOINT and the SDK installed (or a test
    exporter configured). Builds the export pipeline on the first True."""
    try:
        return _get_tracer() is not None
    except Exception as exc:  # noqa: BLE001 - tracing never fails a call
        _report_error(exc)
        return False


@contextmanager
def span(name: str, **attrs: object) -> Iterator[SpanHandle]:
    """Open a child of the current span (or a root) named `name`; yields a SpanHandle.

    `attrs` are log-line field names (tool=..., trace_id=...), filtered by
    span_attributes. The body's exceptions pass through, unrecorded. Fails open:
    a tracing error is logged once and never reaches the caller.
    """
    manager: Any = None
    try:
        tracer = _get_tracer()
        if tracer is not None:
            manager = tracer.start_as_current_span(
                redact(name),
                attributes=span_attributes(attrs),
                record_exception=False,
                set_status_on_exception=False,
            )
            handle = SpanHandle(manager.__enter__())
    except Exception as exc:  # noqa: BLE001 - tracing never fails a call
        _report_error(exc)
        manager = None
    if manager is None:
        yield _NOOP
        return
    try:
        yield handle
    except BaseException as exc:
        _exit_quietly(manager, exc)
        raise
    _exit_quietly(manager, None)


def _exit_quietly(manager: Any, exc: BaseException | None) -> None:
    """End the span, passing the body's exception (if any) as `with` would; an
    error raised by tracing itself is reported, not raised."""
    try:
        if exc is None:
            manager.__exit__(None, None, None)
        else:
            manager.__exit__(type(exc), exc, exc.__traceback__)
    except Exception as err:  # noqa: BLE001 - tracing never fails a call
        if err is not exc:
            _report_error(err)


def flush() -> None:
    """Export every finished span now (tests, and before a manual check)."""
    for provider in (_test_provider, _provider):
        if provider is not None:
            provider.force_flush()


def configure_for_tests(exporter: Any | None) -> None:
    """Send spans synchronously to `exporter` (e.g. InMemorySpanExporter), or with
    None forget every tracer and cached decision so the next call starts clean."""
    global _test_provider, _tracer, _provider, _setup_failed, _endpoint_value
    global _error_reported
    with _lock:
        if exporter is None:
            _test_provider = None
        else:
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor

            _test_provider = _new_provider(SimpleSpanProcessor(exporter))
        if _provider is not None:
            _provider.shutdown()
        _tracer, _provider, _setup_failed = None, None, False
        _endpoint_value, _error_reported = _UNREAD, False
