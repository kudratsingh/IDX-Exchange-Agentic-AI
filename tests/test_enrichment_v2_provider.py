"""Exercise the v2 provider boundary without network calls."""

import io
import json

from scripts import extract_enrichment_v2_dev as driver

from idx_agent.enrichment.v2 import message_parameters


def test_v2_request_and_paid_gate(monkeypatch):
    sent, spent = [], []

    def fake_open(request, timeout):
        sent.append(json.loads(request.data))
        return io.BytesIO(b'{"content": [], "usage": {}}')

    monkeypatch.setattr(
        driver.provider.consent, "spend_paid_call", lambda: spent.append(1)
    )
    monkeypatch.setattr(driver.provider.urllib.request, "urlopen", fake_open)
    original_schema = driver.provider._tool_schema
    driver.send_v2("invented", "prompt", "claude-haiku-5-5", "fake", {})
    assert len(spent) == 1
    assert sent == [message_parameters("claude-haiku-5-5", "prompt", "invented")]
    assert driver.provider._tool_schema is original_schema


def test_complete_dev_comparison_writes_metrics_with_one_budget(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace

    from evals import run

    private = tmp_path / "data" / "enrichment"
    private.mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    prompt = "invented prompt"
    (tmp_path / "docs" / "ENRICHMENT_EXTRACTION_V2.md").write_text(prompt)
    import hashlib

    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "PRIVATE", private)
    monkeypatch.setattr(
        driver, "PROMPT_HASH", hashlib.sha256(prompt.encode()).hexdigest()
    )
    monkeypatch.setattr(driver, "verify_freeze", lambda: None)
    monkeypatch.setattr(driver, "contract_hashes", lambda: {"test": "hash"})
    cases = [{"id": str(i), "split": "dev", "text": "garage"} for i in range(100)]
    sample = {"version": 1, "dataset_id": "invented", "cases": cases}
    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": str(i), "annotations": []} for i in range(100)],
    }
    monkeypatch.setattr(driver, "_sample_jsonl", lambda *_: sample)
    monkeypatch.setattr(driver, "_read_private", lambda *_: gold)
    budget = SimpleNamespace(max_calls=600, calls_made=0)
    monkeypatch.setattr(driver.consent, "start_paid_run", lambda: budget)
    monkeypatch.setattr(driver.consent, "abort_paid_run", lambda _: None)
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake")
    response = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": []},
            }
        ]
    }
    usage = {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    def send(*args):
        budget.calls_made += 1
        return response, usage, json.dumps(response).encode()

    monkeypatch.setattr(driver, "send_v2", send)
    monkeypatch.setattr(
        driver.sys, "argv", ["script", "--approved-provider-disclosure"]
    )
    assert driver.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["requests_made"] == 200
    assert report["sonnet"]["cases"] == report["haiku"]["cases"] == 100
    assert report["sonnet"]["requests_made"] == report["haiku"]["requests_made"] == 100
    assert report["haiku"]["model"] == "claude-haiku-5-5"
    assert report["haiku_within_three_points"] is False
    assert (private / "predictions-dev-v2-sonnet.json").exists()
    assert (private / "predictions-dev-v2-haiku.json").exists()
