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
