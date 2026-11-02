"""WO-020 local-model adapter and the model leg of measurement cases, model-free.

The Ollama API is an in-process stub on 127.0.0.1; no model is downloaded or run.
Model transcripts are injected as stubbed routes; `main()` is never called with
`--suite local`."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from evals import measurement, ollama
from evals import run as runner


class Stub:
    """A loopback Ollama stand-in: records each request, answers with `reply`."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - the stdlib's name
                body = self.rfile.read(int(self.headers["Content-Length"]))
                stub.requests.append((self.path, dict(self.headers), json.loads(body)))
                data = json.dumps(stub.reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    server = Stub({})
    yield server
    server.close()


PAYLOAD = {
    "model": "invented-local",
    "messages": [
        {"role": "system", "content": "route the words"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "h1",
                    "type": "function",
                    "function": {"name": "health", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "h1", "content": "ok"},
        {"role": "user", "content": "homes in Pasadena"},
    ],
    "tools": [{"type": "function", "function": {"name": "search_listings"}}],
    "temperature": 0,
}


def test_a_tool_call_maps_to_the_driver_shape_and_sends_no_key(stub, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invented-should-never-be-sent")
    stub.reply = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "search_listings", "arguments": {"city": "X"}}}
            ],
        }
    }
    budget = ollama.LocalBudget(2)
    reply = ollama.chat(PAYLOAD, {"IDX_EVAL_BASE_URL": stub.url}, budget)
    (call,) = reply["choices"][0]["message"]["tool_calls"]
    assert call["function"] == {"name": "search_listings", "arguments": '{"city": "X"}'}
    path, headers, body = stub.requests[0]
    assert path == "/api/chat" and body["stream"] is False
    assert body["options"] == {"temperature": 0}
    assert body["messages"][1]["tool_calls"][0]["function"]["arguments"] == {}
    assert "tool_call_id" not in body["messages"][2]
    lowered = {k.lower() for k in headers}
    assert "authorization" not in lowered and "x-api-key" not in lowered
    assert "sk-invented" not in json.dumps(body)
    assert budget.calls_made == 1


def test_a_plain_answer_maps_to_content_only(stub):
    stub.reply = {"message": {"role": "assistant", "content": "I can't help."}}
    reply = ollama.chat(PAYLOAD, {"IDX_EVAL_BASE_URL": stub.url}, ollama.LocalBudget(1))
    assert reply["choices"][0]["message"] == {
        "role": "assistant",
        "content": "I can't help.",
    }


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"message": "text"},
        {"message": {"role": "user", "content": ""}},
        {"message": {"role": "assistant", "content": 3}},
        {"message": {"role": "assistant", "tool_calls": [{"function": {}}]}},
        {"message": {"role": "assistant", "tool_calls": "call"}},
    ],
)
def test_an_unsupported_reply_aborts(stub, reply):
    stub.reply = reply
    with pytest.raises(ollama.LocalModelRefused):
        ollama.chat(PAYLOAD, {"IDX_EVAL_BASE_URL": stub.url}, ollama.LocalBudget(1))


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://127.0.0.1:11434",
        "http://10.0.0.5:11434",
        "http://example.com:11434",
        "http://127.0.0.1.example.com",
        "http://user:pw" + chr(64) + "127.0.0.1:11434",  # credentials in the URL
        "http://127.0.0.1:11434/?key=1",
    ],
)
def test_a_non_loopback_url_is_refused_before_any_request(url):
    def never(url, body):
        raise AssertionError("a request was sent")

    with pytest.raises(ollama.LocalModelRefused):
        ollama.chat(PAYLOAD, {"IDX_EVAL_BASE_URL": url}, ollama.LocalBudget(1), never)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"]
)
def test_loopback_urls_are_accepted(url):
    assert ollama.base_url({"IDX_EVAL_BASE_URL": url}) == url.rstrip("/")


def test_the_call_ceiling_holds_without_a_token(stub):
    stub.reply = {"message": {"role": "assistant", "content": "ok"}}
    budget = ollama.LocalBudget(1)
    ollama.chat(PAYLOAD, {"IDX_EVAL_BASE_URL": stub.url}, budget)
    with pytest.raises(ollama.LocalModelRefused, match="ceiling"):
        ollama.chat(PAYLOAD, {"IDX_EVAL_BASE_URL": stub.url}, budget)
    assert len(stub.requests) == 1


# --- synthetic data only ---


def test_real_data_settings_are_refused_not_ignored():
    clean = {}.get
    assert ollama.synthetic_problem("fixture", clean) is None
    assert "fixture" in ollama.synthetic_problem("real", clean)
    for name in ollama.REAL_DATA_SETTINGS:
        problem = ollama.synthetic_problem("fixture", {name: "x"}.get)
        assert problem and name in problem


class ProbeConn:
    def __init__(self, n, real_like):
        self.row = {"n": n, "real_like": real_like}
        self.statements = []

    def cursor(self):
        conn = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                conn.statements.append((sql, params))

            def fetchall(self):
                return [conn.row]

        return Cursor()

    def close(self):
        pass


def test_the_probe_accepts_only_a_fixture_sized_invented_database():
    assert ollama.probe_problem(ProbeConn(117, 0)) is None
    assert "larger" in ollama.probe_problem(ProbeConn(55_212, 0))
    assert "invented" in ollama.probe_problem(ProbeConn(10, 1))
    conn = ProbeConn(1, 0)
    ollama.probe_problem(conn)
    assert all(params == ("^9[0-9]{5,6}$",) for _, params in conn.statements)


def test_admission_checks_everything_before_the_first_request(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_BASE_URL", "http://127.0.0.1:11434")
    for name in ollama.REAL_DATA_SETTINGS:
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(runner.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(runner.db_pool, "connect", lambda: ProbeConn(117, 0))
    cases, _ = runner.load_cases(runner.DEFAULT_CASES_DIR)
    chosen = [c for c in cases if c.check == measurement.CHECK][:3]
    ctx = runner.RunContext(database_kind="fixture")
    assert runner._admit_local_model(chosen, ctx) is None
    assert ctx.synthetic_only and runner._local_budget.max_calls == 3 * 4
    real = runner.RunContext(database_kind="real")
    assert "fixture" in runner._admit_local_model(chosen, real)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invented")
    assert "OPENAI_API_KEY" in runner._admit_local_model(
        chosen, runner.RunContext(database_kind="fixture")
    )
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(runner.db_pool, "connect", lambda: ProbeConn(55_212, 0))
    assert "larger" in runner._admit_local_model(
        chosen, runner.RunContext(database_kind="fixture")
    )


def test_a_failed_local_request_ends_the_run(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "ollama")
    monkeypatch.setenv("IDX_EVAL_BASE_URL", "http://10.1.1.1:11434")
    monkeypatch.setattr(runner, "_local_budget", ollama.LocalBudget(1))
    with pytest.raises(runner.PaidRunAborted, match="loopback"):
        runner._paid_post(PAYLOAD, "")


# --- the model leg of measurement cases: injected transcripts, three scores ---


def _case(family):
    cases, _ = runner.load_cases(runner.DEFAULT_CASES_DIR)
    return next(c for c in cases if c.check == measurement.CHECK and c.family == family)


def _leg(monkeypatch, case, calls):
    facts = case.expect["facts"]
    monkeypatch.setattr(
        runner,
        "call_tool",
        lambda raw, tool: SimpleNamespace(data=SimpleNamespace(**facts)),
    )
    ctx = runner.RunContext(route=lambda text, history, trace: calls)
    monkeypatch.setattr(ctx, "database_available", lambda: True)
    return runner.run_case(case, ctx)


def test_a_right_model_transcript_scores_three_ones(monkeypatch):
    case = _case("search")
    record = _leg(
        monkeypatch, case, [runner.ToolCall(case.tool, dict(case.input_filters))]
    )
    assert record["result"] == runner.PASS
    assert record["scores"] == {"route": 1, "args": 1, "answer": 1}
    assert record["split"] == case.split and record["family"] == "search"


def test_wrong_route_and_wrong_arguments_are_scored_apart(monkeypatch):
    case = _case("search")
    wrong_route = _leg(
        monkeypatch, case, [runner.ToolCall("get_market_stats", {"city": "Pasadena"})]
    )
    assert wrong_route["scores"] == {"route": 0, "args": 0, "answer": 0}
    args = dict(case.input_filters, min_beds=9)
    wrong_args = _leg(monkeypatch, case, [runner.ToolCall(case.tool, args)])
    assert wrong_args["scores"] == {"route": 1, "args": 0, "answer": 1}
    assert wrong_args["result"] == runner.FAIL


def test_measurement_cases_join_a_local_run_only_when_named():
    cases, _ = runner.load_cases(runner.DEFAULT_CASES_DIR)
    bare, _ = runner.select_cases(cases, "local")
    assert not any(c.check == measurement.CHECK for c in bare)
    named, errors = runner.select_cases(cases, "local", ["measurement"])
    assert errors == [] and len(named) == len(measurement.load_entries())
    ci, _ = runner.select_cases(cases, "ci", ["measurement"])
    assert len(ci) == len(named)
