import pytest

from idx_agent.enrichment.v21 import parameters, schema


def test_haiku_thinking_disabled_and_quote_limited():
    request = parameters("prompt", "invented")
    assert request["thinking"] == {"type": "disabled"}
    assert request["model"] == "claude-haiku-5-5"
    quote = schema()["input_schema"]["properties"]["annotations"]["items"][
        "properties"
    ]["quote"]
    assert "maxLength" not in quote and "pattern" not in quote


def test_long_quote_is_a_miss():
    from idx_agent.enrichment.v21 import parse

    text = "x" * 81
    response = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {
                    "annotations": [
                        {
                            "kind": "facet",
                            "group": "exterior_lot",
                            "facet_value": "garage",
                            "quote": text,
                            "polarity": "affirmed",
                            "temporality": "current",
                        }
                    ]
                },
            }
        ]
    }
    accepted, diagnostics = parse(response, text)
    assert accepted == [] and diagnostics[0]["rule"] == "quote_exceeds_80"


def test_provider_sends_disabled_thinking_with_one_spent_call(monkeypatch):
    import io
    import json

    from scripts import extract_enrichment_v21_dev as driver

    spent, payloads = [], []

    def fake_open(request, timeout):
        payloads.append(json.loads(request.data))
        return io.BytesIO(b'{"content": [], "usage": {}}')

    monkeypatch.setattr(driver.consent, "spend_paid_call", lambda: spent.append(1))
    monkeypatch.setattr(driver.urllib.request, "urlopen", fake_open)
    driver.send("invented", "prompt", "fake", {})
    assert spent == [1] and payloads[0]["thinking"] == {"type": "disabled"}
    quote = payloads[0]["tools"][0]["input_schema"]["properties"]["annotations"][
        "items"
    ]["properties"]["quote"]
    assert "maxLength" not in quote and "pattern" not in quote


def test_runner_processes_100_synthetic_cases(tmp_path, monkeypatch, capsys):
    import hashlib
    import json
    from types import SimpleNamespace

    from evals import run
    from scripts import extract_enrichment_v21_dev as driver

    private = tmp_path / "data" / "enrichment"
    private.mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    prompt = "invented prompt"
    (tmp_path / "docs/ENRICHMENT_EXTRACTION_V21.md").write_text(prompt)
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "PRIVATE", private)
    monkeypatch.setattr(
        driver, "PROMPT_HASH", hashlib.sha256(prompt.encode()).hexdigest()
    )
    monkeypatch.setattr(driver, "verify_freeze", lambda: None)
    monkeypatch.setattr(driver, "verify_v21_freeze", lambda: None)
    # The report hashes the implementation and driver; use invented files.
    (tmp_path / "src/idx_agent/enrichment").mkdir(parents=True)
    (tmp_path / "src/idx_agent/enrichment/v21.py").write_text("invented")
    sample = {
        "version": 1,
        "dataset_id": "invented",
        "cases": [{"id": str(i), "split": "dev", "text": "garage"} for i in range(100)],
    }
    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": str(i), "annotations": []} for i in range(100)],
    }
    monkeypatch.setattr(driver, "_sample_jsonl", lambda *_: sample)
    monkeypatch.setattr(driver, "_read_private", lambda *_: gold)
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake")
    budget = SimpleNamespace(max_calls=300, calls_made=0)
    monkeypatch.setattr(driver.consent, "start_paid_run", lambda: budget)
    monkeypatch.setattr(driver.consent, "abort_paid_run", lambda _: None)
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
        "output_tokens_details": {"thinking_tokens": 0},
    }

    def send(*_):
        budget.calls_made += 1
        return response, usage, json.dumps(response).encode()

    monkeypatch.setattr(driver, "send", send)
    monkeypatch.setattr(
        driver.sys, "argv", ["script", "--approved-provider-disclosure"]
    )
    assert driver.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["requests_made"] == 100 and report["thinking_tokens"] == 0
    assert report["bulk_eligible"] is False


@pytest.mark.parametrize(
    "changed", ["src/idx_agent/enrichment/v21.py", "src/idx_agent/enrichment/v2.py"]
)
def test_mutated_dependency_stops_before_paid_run(
    tmp_path, monkeypatch, capsys, changed
):
    import json

    from scripts import extract_enrichment_v21_dev as driver

    original = driver.ROOT
    raw = (original / "docs/ENRICHMENT_V21_FREEZE.json").read_bytes()
    manifest = json.loads(raw)
    for name in manifest["files"]:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((original / name).read_bytes())
    target = tmp_path / changed
    target.write_bytes(target.read_bytes() + b"\n# changed\n")
    (tmp_path / "docs/ENRICHMENT_V21_FREEZE.json").write_bytes(raw)
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(
        driver.sys, "argv", ["script", "--approved-provider-disclosure"]
    )
    monkeypatch.setattr(
        driver.consent,
        "start_paid_run",
        lambda: (_ for _ in ()).throw(AssertionError("paid run started")),
    )
    monkeypatch.setattr(driver.consent, "abort_paid_run", lambda _: None)
    assert driver.main() == 1
    assert '"requests_made": 0' in capsys.readouterr().out
