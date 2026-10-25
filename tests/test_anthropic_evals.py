"""Anthropic request/response compatibility, consent and error paths; no network."""

import json

import pytest
from evals import run

from idx_agent.safety import consent


def payload():
    return {
        "model": "test-claude-model",
        "temperature": 0,
        "reasoning_effort": "none",
        "messages": [
            {"role": "system", "content": "Invented instructions"},
            {"role": "user", "content": "Homes in Pasadena"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-a",
                        "function": {
                            "name": "search_listings",
                            "arguments": '{"city":"Pasadena"}',
                        },
                    },
                    {
                        "id": "call-b",
                        "function": {
                            "name": "get_market_stats",
                            "arguments": '{"city":"Pasadena"}',
                        },
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-a", "content": "Invented homes"},
            {"role": "tool", "tool_call_id": "call-b", "content": "Invented market"},
        ],
        "tools": [
            {
                "function": {
                    "name": "search_listings",
                    "description": "Find homes",
                    "parameters": {"type": "object", "properties": {}},
                }
            }
        ],
    }


def test_messages_translate_system_and_parallel_tool_results_in_order():
    request = run._anthropic_payload(payload())
    assert request["system"] == "Invented instructions"
    assert "temperature" not in request and "reasoning_effort" not in request
    assert request["max_tokens"] == 4096
    assert request["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    messages = request["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in messages[-1]["content"]] == ["call-a", "call-b"]
    assert messages[1]["content"][0]["input"] == {"city": "Pasadena"}


def test_tool_response_normalizes_ids_and_arguments():
    reply = run._anthropic_reply(
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "Checking"},
                {
                    "type": "tool_use",
                    "id": "toolu-a",
                    "name": "search_listings",
                    "input": {"city": "Pasadena"},
                },
            ],
        }
    )
    call = reply["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == "toolu-a" and json.loads(call["function"]["arguments"]) == {
        "city": "Pasadena"
    }


@pytest.mark.parametrize(
    "reply",
    [
        {"stop_reason": "max_tokens", "content": []},
        {"stop_reason": "tool_use", "content": []},
        {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "input": "invalid"}],
        },
        {"stop_reason": "end_turn", "content": [{"type": "server_tool_use"}]},
    ],
)
def test_incomplete_or_malformed_reply_is_not_a_false_pass(reply):
    with pytest.raises(ValueError):
        run._anthropic_reply(reply)


def test_no_consent_never_reaches_anthropic(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")

    def forbid(*args, **kwargs):
        raise AssertionError("Network was attempted")

    monkeypatch.setattr(run, "_post_json", forbid)
    with pytest.raises(run.PaidRunAborted, match="budget refused"):
        run._paid_post(payload(), "invented-key")


def test_stubbed_request_uses_anthropic_headers_and_no_bearer(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")
    calls = []
    monkeypatch.setattr(consent, "spend_paid_call", lambda: calls.append("consent"))

    def fake_post(url, request, headers):
        calls.append((url, request, headers))
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(run, "_post_json", fake_post)
    response = run._paid_post(payload(), "invented-key")
    assert calls[0] == "consent"
    assert calls[1][0] == run.ANTHROPIC_URL
    assert calls[1][2] == {
        "x-api-key": "invented-key",
        "anthropic-version": "2023-06-01",
    }
    assert response["choices"][0]["message"]["content"] == "Done"


def test_driver_failure_aborts_once_without_resend(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")
    calls, aborted = [], []
    monkeypatch.setattr(consent, "spend_paid_call", lambda: None)
    monkeypatch.setattr(consent, "abort_paid_run", aborted.append)

    def fail(*args):
        calls.append(1)
        raise TimeoutError("Invented timeout")

    monkeypatch.setattr(run, "_post_json", fail)
    with pytest.raises(run.PaidRunAborted):
        run._paid_post(payload(), "invented-key")
    assert calls == [1] and aborted == ["driver_error"]


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_explicit_effort_uses_native_fields(effort):
    request = run._anthropic_payload(payload() | {"reasoning_effort": effort})
    assert request["output_config"] == {"effort": effort}
    assert request["thinking"] == {"type": "adaptive"}
    assert "temperature" not in request and "reasoning_effort" not in request


@pytest.mark.parametrize("effort", ["off", "adaptive", "unknown"])
def test_invalid_effort_fails_before_a_request(effort):
    with pytest.raises(ValueError, match="effort"):
        run._anthropic_payload(payload() | {"reasoning_effort": effort})


@pytest.mark.parametrize("effort", [None, "none"])
def test_unspecified_effort_keeps_native_default_not_disabled(effort):
    request = run._anthropic_payload(payload() | {"reasoning_effort": effort})
    assert "output_config" not in request and "thinking" not in request


def test_thinking_and_tool_blocks_survive_continuation_but_not_trace(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")
    monkeypatch.setattr(consent, "spend_paid_call", lambda: None)
    native = [
        {"type": "thinking", "thinking": "", "signature": "opaque-signature-sentinel"},
        {"type": "redacted_thinking", "data": "opaque-redacted-sentinel"},
        {
            "type": "tool_use",
            "id": "toolu-test",
            "name": "search_listings",
            "input": {"city": "Pasadena"},
        },
    ]
    sent = []

    def fake_post(url, request, headers):
        sent.append(request)
        if len(sent) == 1:
            return {"stop_reason": "tool_use", "content": native}
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(run, "_post_json", fake_post)
    trace = {}
    calls = run.model_route(
        "Invented request",
        "test-claude-model",
        "invented-key",
        prompt="Invented instructions",
        tools=payload()["tools"],
        shape=run.RouteShape(True, "medium"),
        trace=trace,
    )
    assert len(calls) == 1 and len(sent) == 2
    assert sent[1]["messages"][-2]["content"] == native
    assert sent[1]["messages"][-1]["content"][0]["tool_use_id"] == "toolu-test"
    assert all(p["output_config"]["effort"] == "medium" for p in sent)
    assert trace["reply_preview"] == "Done"
    assert "opaque-signature-sentinel" not in json.dumps(trace)
    assert "opaque-redacted-sentinel" not in json.dumps(trace)


@pytest.mark.parametrize(
    "block",
    [
        {"type": "thinking", "thinking": "", "signature": "opaque-sentinel"},
        {"type": "redacted_thinking", "data": "opaque-sentinel"},
        {"type": "thinking", "thinking": "", "signature": ""},
        {"type": "thinking", "thinking": ""},
        {"type": "redacted_thinking", "data": ""},
    ],
)
def test_hidden_only_or_malformed_response_is_not_a_pass(block):
    with pytest.raises(ValueError):
        run._anthropic_reply({"stop_reason": "end_turn", "content": [block]})


def test_single_tool_fill_also_uses_medium(monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")
    monkeypatch.setattr(consent, "spend_paid_call", lambda: None)
    monkeypatch.setattr(run, "system_prompt", lambda _: "Invented instructions")
    monkeypatch.setattr(run, "tool_schema", lambda _: payload()["tools"][0])
    sent = []

    def fake_post(url, request, headers):
        sent.append(request)
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu-a",
                    "name": "search_listings",
                    "input": {"city": "Pasadena"},
                }
            ],
        }

    monkeypatch.setattr(run, "_post_json", fake_post)
    fill = run._model_fill(
        "test-claude-model", "invented-key", run.RouteShape(True, "medium")
    )
    assert fill("Invented request") == {"city": "Pasadena"}
    assert sent[0]["output_config"] == {"effort": "medium"}
    assert "temperature" not in sent[0]


def test_local_report_never_overwrites_existing_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")
    monkeypatch.setenv("IDX_EVAL_MODEL", "test-claude-model")
    path = tmp_path / "one-run.json"
    first = run.write_report(path, "local", [], reasoning_effort="medium")
    original = path.read_bytes()
    assert first["provider"] == "anthropic" and first["model"] == "test-claude-model"
    with pytest.raises(FileExistsError):
        run.write_report(path, "local", [])
    assert path.read_bytes() == original


def test_existing_report_refused_before_budget_or_plan(tmp_path, monkeypatch):
    path = tmp_path / "old.json"
    path.write_text("previous evidence")

    def forbid(*args, **kwargs):
        raise AssertionError("budget or plan was reached")

    monkeypatch.setattr(run, "_local_plan", forbid)
    monkeypatch.setattr(consent, "start_paid_run", forbid)
    with pytest.raises(SystemExit) as caught:
        run.main(["--suite", "local", "--allow-paid", "--out", str(path)])
    assert caught.value.code == 2
    assert path.read_text() == "previous evidence"


def test_anthropic_plan_accepts_medium_and_rejects_bad_effort(monkeypatch):
    import io

    monkeypatch.setenv("IDX_EVAL_PROVIDER", "anthropic")
    monkeypatch.setattr(run, "_local_setting", lambda name: "configured")
    monkeypatch.setattr(run, "_print_paid_run", lambda cases, out: None)
    ready, problem = run._local_plan(
        [], True, out=io.StringIO(), shape=run.RouteShape(True, "medium")
    )
    assert ready and problem is None
    ready, problem = run._local_plan(
        [], True, out=io.StringIO(), shape=run.RouteShape(True, "off")
    )
    assert not ready and "effort" in problem
