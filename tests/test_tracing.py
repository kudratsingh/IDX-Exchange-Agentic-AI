"""WO-007 spans: the attribute allowlist, redaction, off means nothing, and the span
tree each tool call emits.

Spans go to the SDK's in-memory exporter; no collector, network, or database. The
db layer is faked as in test_mcp_search.py. All ids and listings are invented.
"""

import asyncio
import hashlib
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from mcp import Client
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from idx_agent import __version__
from idx_agent.db import listings as db_listings
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import Listing, PropertySearchFilters
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore
from idx_agent.observability import tracing

ASOF = AsOfDates(sold=date(2026, 6, 30), active=date(2026, 7, 2))
REMARK = "Invented remark text that must stay out of every span"
SRC = str(pathlib.Path(mcp.__file__).resolve().parents[2])

# The WO-007 contract, written out: changing the allowlist means changing this too.
EXPECTED_ATTRIBUTES = {
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
    "idx.outcome",
    "idx.sample_count",
    "idx.months",
    "idx.filters.city",
    "idx.filters.postal_code",
    "idx.filters.min_price",
    "idx.filters.max_price",
    "idx.filters.min_beds",
    "idx.filters.min_baths",
    "idx.filters.min_sqft",
    "idx.filters.property_subtype",
    "idx.filters.pool",
    "idx.filters.view",
    "idx.filters.max_hoa_monthly",
    "idx.filters.page",
    "idx.filters.limit",
}


@pytest.fixture(autouse=True)
def _tracing_reset(monkeypatch):
    """Every test starts with tracing off and no endpoint, and leaves it that way.
    The endpoint is read once per process, so a test sets it before its first span."""
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", "")
    monkeypatch.setenv("IDX_LOG_FILE", "")
    tracing.configure_for_tests(None)
    yield
    tracing.configure_for_tests(None)


@pytest.fixture
def exporter():
    """Tracing on, into an in-memory exporter (spans are exported synchronously)."""
    memory = InMemorySpanExporter()
    tracing.configure_for_tests(memory)
    return memory


def _listing(key):
    """One invented listing, with a remark that must never reach a span."""
    return Listing(
        listing_key=key,
        listing_id=f"TEST{key}",
        address=f"{key} Example Lane",
        city="Pasadena",
        postal_code="91100",
        list_price=1_000_000 + key,
        bedrooms=3,
        bathrooms=2.0,
        living_area=1600,
        property_subtype="SingleFamilyResidence",
        status="Active",
        days_on_market=12,
        photo_count=20,
        remarks=REMARK,
    )


@pytest.fixture
def fake_db(monkeypatch):
    """Patch pool, as-of, and search: a short page of two invented rows."""

    class Conn:
        def close(self):
            pass

    def search(filters, conn):
        return db_listings.SearchOutcome(listings=[_listing(1), _listing(2)])

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", lambda config=None: Conn())
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)


def _by_name(memory):
    """Finished spans keyed by name (each name appears once per test here)."""
    spans = memory.get_finished_spans()
    named = {s.name: s for s in spans}
    assert len(named) == len(spans), [s.name for s in spans]
    return named


def _parent(named, name):
    """The name of the span's parent among `named`, or None for our root."""
    parent = named[name].parent
    if parent is None:
        return None
    return next(n for n, s in named.items() if s.context.span_id == parent.span_id)


def _all_text(memory):
    """Every span name, attribute name, and attribute value, as one string."""
    parts = []
    for s in memory.get_finished_spans():
        parts.append(s.name)
        parts.append(json.dumps(dict(s.attributes), default=str))
        parts.extend(json.dumps(dict(e.attributes or {})) for e in s.events)
    return "\n".join(parts)


# --- the allowlist and redaction (no SDK needed) ---


def test_the_allowlist_is_pinned():
    """An attribute name joins the allowlist only by editing this test too."""
    assert tracing.ALLOWED_ATTRIBUTES == EXPECTED_ATTRIBUTES
    assert tracing.LIST_ATTRIBUTES == {"idx.meta_keys"}


def test_one_filter_attribute_per_validated_filter_field():
    assert set(tracing.FILTER_FIELDS) == set(PropertySearchFilters.model_fields)


def test_unknown_and_non_primitive_fields_are_dropped():
    """ms, meta_shape, event, sender_id, remarks and anything unknown never pass."""
    attrs = tracing.span_attributes(
        {
            "trace_id": "0123456789abcdef",
            "tool": "search_listings",
            "ok": True,
            "ms": 12.5,
            "event": "tool_call",
            "ts": "2026-07-02T12:00:00.000+00:00",
            "meta_shape": {"sessionKey": {"len": 3}},
            "meta_keys": ["sessionKey", "outer.inner"],
            "sender_id": "sender-a",
            "remarks": REMARK,
            "filters": {"city": "Pasadena", "min_beds": 3, "colour": "red"},
            "rows": None,
            "error_type": {"nested": "dict"},
            "idx.not_listed": 1,
        }
    )
    assert attrs == {
        "idx.trace_id": "0123456789abcdef",
        "idx.tool": "search_listings",
        "idx.ok": True,
        "idx.meta_keys": ["sessionKey", "outer.inner"],
        "idx.filters.city": "Pasadena",
        "idx.filters.min_beds": 3,
    }


def test_a_list_is_kept_only_for_meta_keys():
    attrs = tracing.span_attributes(
        {"tool": ["a", "b"], "meta_keys": ["k", {"x": 1}], "field": ("city",)}
    )
    assert attrs == {}


def test_attribute_values_are_redacted():
    """An email- or phone-shaped value in any allowed field comes out scrubbed."""
    # Built at runtime so this file never holds a literal address or number.
    email = "agent" + "@" + "brokerage.com"
    phone = "310" + "-555-" + "0100"
    attrs = tracing.span_attributes(
        {
            "field": f"city {email}",
            "clarification": f"call {phone}",
            "filters": {"city": email},
            "meta_keys": [email, "ok"],
        }
    )
    text = json.dumps(attrs)
    assert email not in text and phone not in text
    assert attrs["idx.field"] == "city [email]"
    assert attrs["idx.clarification"] == "call [phone]"
    assert attrs["idx.filters.city"] == "[email]"
    assert attrs["idx.meta_keys"] == ["[email]", "ok"]


# --- tracing off ---


def test_off_without_an_endpoint_span_is_a_no_op():
    assert tracing.tracing_enabled() is False
    with tracing.span("idx.tool_call", tool="health") as handle:
        handle.set({"ok": True})
    assert handle is tracing._NOOP
    assert mcp.health()["ok"] is True


@pytest.mark.parametrize(
    ("endpoint", "loopback"),
    [
        ("http://127.0.0.1:4318", True),
        ("http://localhost:4318/", True),
        ("http://[::1]:4318", True),
        ("http://127.0.0.2:4318", True),
        ("https://127.0.0.1:4318", False),
        ("http://10.0.0.5:4318", False),
        ("http://collector.example.test:4318", False),
        ("http://127.0.0.1.example.test:4318", False),
        ("http://localhost.example.test:4318", False),
        ("127.0.0.1:4318", False),
        ("http://127.0.0.1:99999", False),
        ("http://[::1", False),
        ("", False),
    ],
)
def test_only_an_http_loopback_endpoint_is_accepted(endpoint, loopback):
    assert tracing.loopback_url(endpoint) is loopback


def test_a_remote_endpoint_is_refused_once_and_tracing_stays_off(monkeypatch, capsys):
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", "http://collector.example.test:4318/x?k=v")
    assert tracing.tracing_enabled() is False
    mcp.health()
    assert tracing.tracing_enabled() is False
    lines = [json.loads(x) for x in capsys.readouterr().err.strip().splitlines()]
    refused = [x for x in lines if x["event"] == "tracing_refused"]
    assert len(refused) == 1 and refused[0]["host"] == "collector.example.test"
    assert "k=v" not in json.dumps(refused)
    assert lines[-1]["event"] == "tool_call"


def test_the_endpoint_is_read_once_per_process(monkeypatch, capsys):
    """Not on every span: a later change needs a restart (or configure_for_tests)."""
    reads = []

    def counting(name, environ=None):
        reads.append(name)
        return os.environ.get(name)

    monkeypatch.setattr(tracing, "env_setting", counting)
    for _ in range(3):
        mcp.health()
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", "http://collector.example.test:4318")
    mcp.health()
    assert reads == ["IDX_OTLP_ENDPOINT"] and tracing.tracing_enabled() is False
    assert _events(capsys, "tracing_refused") == []
    tracing.configure_for_tests(None)
    assert tracing.tracing_enabled() is False
    assert reads == ["IDX_OTLP_ENDPOINT"] * 2
    assert len(_events(capsys, "tracing_refused")) == 1


def _run_python(code, cwd, **env):
    """Run `code` in a fresh interpreter in `cwd`; return its stdout.

    Settings a real .env may hold are set empty here, and the environment wins.
    """
    full_env = {
        **os.environ,
        "PYTHONPATH": SRC,
        "MYSQL_HOST": "",
        "IDX_LOG_FILE": "",
        **env,
    }
    done = subprocess.run(
        [sys.executable, "-c", code],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


# Imports the server, makes one call of each tool, then reports what got loaded.
_OFF_PROBE = """
import json, sys, threading
import idx_agent.mcp_server.server as s
from idx_agent.observability import tracing
s.health()
s.search_listings(city="Pasadena")
sdk = sorted(m for m in sys.modules
             if m.startswith(("opentelemetry.sdk", "opentelemetry.exporter")))
print(json.dumps({"enabled": tracing.tracing_enabled(), "sdk": sdk,
                  "provider": tracing._provider is None,
                  "threads": threading.active_count()}))
"""


@pytest.mark.parametrize("endpoint", ["", "http://collector.example.test:4318"])
def test_off_never_imports_the_sdk_or_starts_a_thread(endpoint, tmp_path):
    """In a fresh process: no SDK or exporter module, no provider, one thread.
    (The MCP SDK itself imports the OpenTelemetry API; that is not ours.)"""
    out = json.loads(_run_python(_OFF_PROBE, tmp_path, IDX_OTLP_ENDPOINT=endpoint))
    assert out == {"enabled": False, "sdk": [], "provider": True, "threads": 1}


# --- tracing on: the span tree per outcome ---


def test_a_search_with_results_emits_the_root_and_stage_spans(exporter, fake_db):
    payload = mcp.search_listings(city="pasadena", min_beds=3)
    named = _by_name(exporter)
    assert set(named) == {
        "idx.tool_call",
        "idx.search.merge",
        "idx.search.validate",
        "idx.search.query",
        "idx.search.format",
    }
    assert _parent(named, "idx.tool_call") is None
    assert _parent(named, "idx.search.merge") == "idx.tool_call"
    assert _parent(named, "idx.search.validate") == "idx.search.merge"
    assert _parent(named, "idx.search.query") == "idx.tool_call"
    assert _parent(named, "idx.search.format") == "idx.tool_call"
    root = named["idx.tool_call"].attributes
    assert root["idx.trace_id"] == payload["provenance"]["trace_id"]
    assert root["idx.tool"] == "search_listings" and root["idx.ok"] is True
    assert root["idx.mode"] == "replace" and root["idx.key_prefix"] == "-"
    assert root["idx.filters.city"] == "Pasadena" and root["idx.filters.min_beds"] == 3
    assert root["idx.rows"] == 2 and root["idx.total_matches"] == 2
    assert tuple(root["idx.meta_keys"]) == ()
    resource = named["idx.tool_call"].resource.attributes
    assert resource["service.name"] == "idx-mcp"
    assert resource["service.version"] == __version__
    assert REMARK not in _all_text(exporter) and "Example Lane" not in _all_text(
        exporter
    )


def test_every_attribute_on_every_span_is_allowlisted(exporter, fake_db):
    mcp.search_listings(city="Pasadena", max_price=900_000, pool=True)
    mcp.search_listings(city="Not A Real Town")
    mcp.health()
    names = {k for s in exporter.get_finished_spans() for k in s.attributes}
    assert names and names <= tracing.ALLOWED_ATTRIBUTES


def test_a_full_page_adds_the_count_span(exporter, fake_db, monkeypatch):
    def full_page(filters, conn):
        return db_listings.SearchOutcome(
            listings=[_listing(k) for k in range(1, filters.limit + 1)]
        )

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", full_page)
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", lambda f, c: 51)
    mcp.search_listings(city="Pasadena")
    named = _by_name(exporter)
    assert _parent(named, "idx.search.count") == "idx.tool_call"
    assert named["idx.tool_call"].attributes["idx.total_matches"] == 51


def test_a_clarification_has_no_query_span(exporter, fake_db):
    mcp.search_listings(city="Not A Real Town")
    named = _by_name(exporter)
    assert set(named) == {"idx.tool_call", "idx.search.merge", "idx.search.validate"}
    root = named["idx.tool_call"].attributes
    assert root["idx.clarification"] == "unknown_city" and root["idx.field"] == "city"
    assert root["idx.ok"] is True
    assert "Not A Real Town" not in _all_text(exporter)  # unvalidated input


def test_a_reset_with_no_filters_is_the_root_alone(exporter, monkeypatch):
    keys = {"sender-a": "a1" * 32}
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: keys.get(raw))
    clock = lambda: datetime(2026, 7, 2, 12, 0, tzinfo=UTC)  # noqa: E731
    mcp.reset_store_for_tests(InMemorySessionStore(timedelta(minutes=30), 10, clock))
    try:
        mcp.search_listings(mode="reset", sender_id="sender-a")
    finally:
        mcp.reset_store_for_tests()
    named = _by_name(exporter)
    assert set(named) == {"idx.tool_call"}
    root = named["idx.tool_call"].attributes
    assert root["idx.cleared"] is True and root["idx.mode"] == "reset"
    assert root["idx.key_prefix"] == "a1" * 4
    assert "sender-a" not in _all_text(exporter)


def test_a_database_error_keeps_its_text_out_of_the_spans(
    exporter, fake_db, monkeypatch
):
    """The query span closes without a recorded exception; the root says why."""

    def broken(filters, conn):
        raise RuntimeError("internal-only-text from the driver")

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", broken)
    payload = mcp.search_listings(city="Pasadena")
    named = _by_name(exporter)
    assert set(named) == {
        "idx.tool_call",
        "idx.search.merge",
        "idx.search.validate",
        "idx.search.query",
    }
    root = named["idx.tool_call"].attributes
    assert root["idx.ok"] is False and root["idx.error"] == "db"
    assert root["idx.error_type"] == "RuntimeError"
    assert root["idx.trace_id"] == payload["provenance"]["trace_id"]
    assert all(not s.events for s in named.values())
    assert "internal-only-text" not in _all_text(exporter)


def test_health_emits_the_root_and_the_check_span(exporter):
    payload = mcp.health()
    named = _by_name(exporter)
    assert set(named) == {"idx.tool_call", "idx.health.check"}
    assert _parent(named, "idx.health.check") == "idx.tool_call"
    root = named["idx.tool_call"].attributes
    assert root["idx.tool"] == "health" and root["idx.ok"] is True
    assert root["idx.trace_id"] == payload["provenance"]["trace_id"]


def test_the_sender_id_never_reaches_a_span(exporter, fake_db, monkeypatch):
    """With the real HMAC: only the 8-character key prefix is on the root."""
    secret = hashlib.sha256(b"invented tracing test secret").hexdigest()
    monkeypatch.setenv("IDX_SENDER_KEY", secret)
    clock = lambda: datetime(2026, 7, 2, 12, 0, tzinfo=UTC)  # noqa: E731
    mcp.reset_store_for_tests(InMemorySessionStore(timedelta(minutes=30), 10, clock))
    # Country code 1, the fictional 555-010x range, then four digits; never a literal.
    digits = "".join(["1", "555", "010", "7", "3", "4", "2"])
    try:
        mcp.search_listings(city="Pasadena", sender_id="+" + digits)
    finally:
        mcp.reset_store_for_tests()
    text = _all_text(exporter)
    assert digits not in text and digits[1:] not in text and digits[-7:] not in text
    prefix = _by_name(exporter)["idx.tool_call"].attributes["idx.key_prefix"]
    assert len(prefix) == 8 and prefix not in (digits, "-")


def test_the_log_line_is_unchanged_with_tracing_on(exporter, fake_db, capsys):
    """Same fields as with tracing off; the span adds nothing to the line."""
    mcp.search_listings(city="Pasadena")
    on = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    tracing.configure_for_tests(None)
    mcp.search_listings(city="Pasadena")
    off = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    for line in (on, off):
        line.pop("ts"), line.pop("trace_id"), line.pop("ms")
    assert on == off


def test_a_span_lets_an_exception_through_and_records_none(exporter):
    with pytest.raises(ValueError), tracing.span("idx.search.query"):
        raise ValueError("internal-only-text")
    (finished,) = exporter.get_finished_spans()
    assert not finished.events and "internal-only-text" not in _all_text(exporter)


def test_a_traceparent_in_meta_becomes_the_parent(exporter):
    """If the runtime ever passes W3C trace context in `_meta` (ADR-0006 reversal),
    our root joins that trace; our own 16-hex trace id is unchanged."""
    trace_hex, span_hex = "ab" * 16, "cd" * 8
    meta = {"traceparent": f"00-{trace_hex}-{span_hex}-01"}

    async def call():
        async with Client(mcp.server) as client:
            return await client.call_tool("health", {}, meta=meta)

    asyncio.run(call())
    root = _by_name(exporter)["idx.tool_call"]
    assert root.context.trace_id == int(trace_hex, 16)
    assert root.parent is not None and root.parent.span_id == int(span_hex, 16)
    assert len(root.attributes["idx.trace_id"]) == 16
    assert "traceparent" in root.attributes["idx.meta_keys"]


# --- the real export pipeline (loopback endpoint, nothing listening) ---


def _closed_port():
    """A loopback port with nothing listening (bound, then released)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_down_collector_never_delays_a_call_and_is_logged_once(monkeypatch, capsys):
    """Export runs on the batch thread: the call returns at once. The failed
    export is one `trace_export_failed` line, not one per span."""
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")
    assert tracing.tracing_enabled() is True
    start = time.perf_counter()
    for _ in range(3):
        assert mcp.health()["ok"] is True
    assert time.perf_counter() - start < 0.5
    tracing.configure_for_tests(None)  # shuts the provider down: the final export
    lines = [json.loads(x) for x in capsys.readouterr().err.strip().splitlines()]
    failed = [x for x in lines if x["event"] == "trace_export_failed"]
    assert len(failed) == 1 and failed[0]["spans"] == 6


class _FailingExporter:
    """Stands in for the OTLP exporter: fails, or raises, every export."""

    def __init__(self, raise_error=False):
        self.raise_error = raise_error
        self.calls = 0

    def export(self, spans):
        self.calls += 1
        if self.raise_error:
            raise ConnectionError("collector down")
        return SpanExportResult.FAILURE


@pytest.mark.parametrize("raise_error", [False, True])
def test_export_failures_are_logged_at_most_once_a_minute(raise_error, capsys):
    now = [1000.0]
    inner = _FailingExporter(raise_error)
    throttled = tracing._ThrottledExporter(inner, clock=lambda: now[0])
    for step in (0, 10, 59):  # three failures inside one interval
        now[0] = 1000.0 + step
        assert throttled.export([]) is SpanExportResult.FAILURE
    now[0] = 1060.0
    throttled.export([])
    lines = [json.loads(x) for x in capsys.readouterr().err.strip().splitlines()]
    assert inner.calls == 4 and len(lines) == 2
    expected = "ConnectionError" if raise_error else "export_failed"
    assert {x["error"] for x in lines} == {expected}


# --- the pipeline itself: resource, proxies, the global provider ---

OUR_RESOURCE = {"service.name": "idx-mcp", "service.version": __version__}


def test_the_resource_holds_our_two_attributes_only(monkeypatch):
    """No telemetry.sdk.* attributes, and nothing from OTEL_RESOURCE_ATTRIBUTES or
    OTEL_SERVICE_NAME (a host name there would otherwise ride on every span)."""
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "host.name=invented-host,a=b")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "invented-service")
    memory = InMemorySpanExporter()
    tracing.configure_for_tests(memory)
    mcp.health()
    resources = [dict(s.resource.attributes) for s in memory.get_finished_spans()]
    assert resources and all(r == OUR_RESOURCE for r in resources)


class _Recorder:
    """Wraps the real OTLP exporter class and keeps each session it is given."""

    def __init__(self, real):
        self.real = real
        self.sessions = []

    def __call__(self, *args, **kwargs):
        self.sessions.append(kwargs.get("session"))
        return self.real(*args, **kwargs)


def test_the_exporter_ignores_proxy_settings(monkeypatch):
    """HTTP_PROXY or ALL_PROXY never routes a span off the machine."""
    import requests
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    recorder = _Recorder(trace_exporter.OTLPSpanExporter)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", recorder)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://proxy.example.test:3128")
    endpoint = f"http://127.0.0.1:{_closed_port()}"
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", endpoint)
    assert tracing.tracing_enabled() is True
    (session,) = recorder.sessions
    assert session.trust_env is False
    url = endpoint + "/v1/traces"
    assert (
        session.merge_environment_settings(url, {}, None, None, None)["proxies"] == {}
    )
    # The control: a default session would have picked the proxy up.
    default = requests.Session().merge_environment_settings(url, {}, None, None, None)
    assert default["proxies"]
    assert dict(tracing._provider.resource.attributes) == OUR_RESOURCE


@pytest.mark.parametrize("pipeline", ["memory", "otlp"])
def test_the_global_tracer_provider_is_never_an_sdk_provider(pipeline, monkeypatch):
    """Ours stays private, so the MCP SDK's own spans (tool arguments) stay no-ops."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.delenv("OTEL_PYTHON_TRACER_PROVIDER", raising=False)
    if pipeline == "memory":
        tracing.configure_for_tests(InMemorySpanExporter())
    else:
        monkeypatch.setenv("IDX_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")
    assert tracing.tracing_enabled() is True
    assert mcp.health()["ok"] is True
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)


# --- fail open: no tracing error ever reaches a tool call ---


def _events(capsys, name):
    """The stderr log lines with event `name`."""
    lines = [json.loads(x) for x in capsys.readouterr().err.strip().splitlines()]
    return [x for x in lines if x["event"] == name]


class _Unbuildable:
    """Stands in for the OTLP exporter class: construction always fails."""

    def __init__(self, *args, **kwargs):
        raise ValueError("invented setup failure")


def test_an_exporter_that_cannot_be_built_leaves_tracing_off(
    monkeypatch, fake_db, capsys
):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", _Unbuildable)
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")
    assert mcp.health()["ok"] is True
    assert mcp.search_listings(city="Pasadena")["ok"] is True
    assert tracing.tracing_enabled() is False and tracing._provider is None
    (failed,) = _events(capsys, "tracing_setup_failed")
    assert failed["error"] == "ValueError"


def test_a_bad_otel_variable_leaves_tracing_off(monkeypatch, fake_db, capsys):
    """An unknown compression makes the real exporter raise ValueError at build."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_COMPRESSION", "invented")
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")
    assert mcp.search_listings(city="Pasadena")["ok"] is True
    assert tracing.tracing_enabled() is False
    (failed,) = _events(capsys, "tracing_setup_failed")
    assert failed["error"] == "ValueError"


def test_a_bad_otel_timeout_is_overridden_by_ours(monkeypatch):
    """OTEL_EXPORTER_OTLP_TRACES_TIMEOUT is never parsed: we pass our own timeout."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT", "bad")
    monkeypatch.setenv("IDX_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")
    assert tracing.tracing_enabled() is True


class _Broken:
    """A tracer, span manager, and span in one, raising RuntimeError at `where`."""

    def __init__(self, where):
        self.where = where

    def _maybe_raise(self, step):
        if self.where == step:
            raise RuntimeError(f"invented {step} failure")

    def start_as_current_span(self, name, **kwargs):
        self._maybe_raise("start")
        return self

    def __enter__(self):
        self._maybe_raise("enter")
        return self

    def __exit__(self, *exc):
        self._maybe_raise("exit")
        return False

    def set_attributes(self, attrs):
        self._maybe_raise("set")


@pytest.mark.parametrize("where", ["lookup", "start", "enter", "set", "exit"])
def test_a_tracing_error_never_crosses_the_mcp_boundary(
    where, monkeypatch, fake_db, capsys
):
    """Wherever tracing breaks, the call returns its normal result and the error
    is logged once; the body's own exception still passes through unchanged."""

    def lookup():
        if where == "lookup":
            raise RuntimeError("invented lookup failure")
        return _Broken(where)

    monkeypatch.setattr(tracing, "_get_tracer", lookup)
    assert mcp.health()["ok"] is True
    payload = mcp.search_listings(city="Pasadena")
    assert payload["ok"] is True and payload["data"]["listings"]
    with pytest.raises(KeyError), tracing.span("idx.search.query"):
        raise KeyError("body")
    (error,) = _events(capsys, "tracing_error")
    assert error["error"] == "RuntimeError"
