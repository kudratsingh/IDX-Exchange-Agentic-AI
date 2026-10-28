"""Exercise provider boundary with a stub and invented input only."""

import io
import json

import pytest
from scripts import extract_enrichment_dev as driver


def test_provider_never_called_without_budget(monkeypatch):
    called = []

    def refuse():
        raise RuntimeError("no budget")

    monkeypatch.setattr(driver.consent, "spend_paid_call", refuse)
    monkeypatch.setattr(
        driver.urllib.request, "urlopen", lambda *args, **kwargs: called.append(True)
    )
    with pytest.raises(RuntimeError, match="budget"):
        driver._send("invented", "spec", "sonnet-test", "fake-key")
    assert called == []


def test_provider_request_uses_dev_text_and_actual_usage(monkeypatch):
    called = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_open(request, timeout):
        called.append(json.loads(request.data))
        return Response(
            json.dumps(
                {
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "record_extractions",
                            "input": {"annotations": []},
                        }
                    ],
                    "usage": {"input_tokens": 20, "output_tokens": 3},
                }
            ).encode()
        )

    monkeypatch.setattr(driver.consent, "spend_paid_call", lambda: None)
    monkeypatch.setattr(driver.urllib.request, "urlopen", fake_open)
    response, usage, raw = driver._send("invented", "spec", "sonnet-test", "fake-key")
    assert response["content"][0]["input"] == {"annotations": []}
    assert called[0]["tools"][0]["strict"] is True
    assert called[0]["tool_choice"] == {"type": "auto"}
    assert "Always call the record_extractions tool exactly once" in called[0]["system"]
    assert usage == {"input_tokens": 20, "output_tokens": 3}
    assert json.loads(raw) == response
    assert json.loads(called[0]["messages"][0]["content"]) == {"remark": "invented"}


def test_loader_keeps_only_dev_cases(tmp_path):
    splits = {str(i): "dev" if i < 100 else "test" for i in range(250)}
    (tmp_path / "splits.json").write_text(
        json.dumps({"version": 1, "dataset_id": "invented", "splits": splits}),
        encoding="utf-8",
    )
    with (tmp_path / "sample.jsonl").open("w", encoding="utf-8") as handle:
        for key, split in splits.items():
            handle.write(
                json.dumps(
                    {"key": key, "subtype": "house", "remark": f"invented {split}"}
                )
                + "\n"
            )
    dataset, cases = driver._load_dev(tmp_path)
    assert dataset == "invented"
    assert len(cases) == 100
    assert all(text == "invented dev" for _, text in cases)


def test_dev_loader_does_not_parse_held_out_remarks(tmp_path):
    splits = {str(i): "dev" if i < 100 else "test" for i in range(250)}
    (tmp_path / "splits.json").write_text(
        json.dumps({"version": 1, "dataset_id": "invented", "splits": splits}),
        encoding="utf-8",
    )
    with (tmp_path / "sample.jsonl").open("w", encoding="utf-8") as handle:
        for key, split in splits.items():
            if split == "dev":
                handle.write(
                    json.dumps({"key": key, "subtype": "house", "remark": "invented"})
                    + "\n"
                )
            else:
                handle.write('{"key": "' + key + '", "remark": malformed}\n')
    _, cases = driver._load_dev(tmp_path)
    assert len(cases) == 100


def test_failed_run_reports_partial_aggregate_without_text(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace

    from evals import run

    private = tmp_path / "data" / "enrichment"
    private.mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ENRICHMENT_ANNOTATION.md").write_text(
        "spec", encoding="utf-8"
    )
    budget = SimpleNamespace(max_calls=100, calls_made=0)

    def send(*args):
        budget.calls_made += 1
        if budget.calls_made == 2:
            raise RuntimeError("invented private error")
        response = {
            "content": [
                {
                    "type": "tool_use",
                    "name": "record_extractions",
                    "input": {"annotations": []},
                }
            ]
        }
        return (
            response,
            {"input_tokens": 10, "output_tokens": 2},
            json.dumps(response).encode(),
        )

    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "PRIVATE", private)
    monkeypatch.setattr(
        driver,
        "_load_dev",
        lambda _: ("invented", [(str(i), "invented private text") for i in range(100)]),
    )
    monkeypatch.setattr(driver, "_send", send)
    monkeypatch.setattr(driver.consent, "start_paid_run", lambda: budget)
    monkeypatch.setattr(driver.consent, "abort_paid_run", lambda _: None)
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake-key")
    monkeypatch.setattr(
        driver.sys,
        "argv",
        ["script", "--model", "sonnet-test", "--approved-provider-disclosure"],
    )
    assert driver.main() == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["requests_made"] == 2
    assert result["usage_from_complete_responses_only"] == {
        "responses_with_usage": 1,
        "input_tokens": 10,
        "output_tokens": 2,
        "no_tool_calls": 0,
    }
    assert "private text" not in output and "private error" not in output
    assert not (private / "predictions-dev.json").exists()


def test_failed_remark_writes_private_raw_response_and_continues(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace

    from evals import run

    private = tmp_path / "data" / "enrichment"
    private.mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ENRICHMENT_ANNOTATION.md").write_text(
        "spec", encoding="utf-8"
    )
    budget = SimpleNamespace(max_calls=100, calls_made=0)

    def send(*args):
        budget.calls_made += 1
        annotations = (
            [
                {
                    "kind": "facet",
                    "group": "exterior_lot",
                    "facet_value": "pool",
                    "polarity": "affirmed",
                    "temporality": "current",
                    "quote": "unmatched private quote",
                }
            ]
            if budget.calls_made == 1
            else []
        )
        response = {
            "content": [
                {
                    "type": "tool_use",
                    "name": "record_extractions",
                    "input": {"annotations": annotations},
                }
            ]
        }
        return (
            response,
            {"input_tokens": 10, "output_tokens": 2},
            json.dumps(response).encode(),
        )

    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "PRIVATE", private)
    monkeypatch.setattr(
        driver,
        "_load_dev",
        lambda _: ("invented", [(str(i), "invented private text") for i in range(100)]),
    )
    monkeypatch.setattr(driver, "_send", send)
    monkeypatch.setattr(driver.consent, "start_paid_run", lambda: budget)
    monkeypatch.setattr(driver.consent, "abort_paid_run", lambda _: None)
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake-key")
    monkeypatch.setattr(
        driver.sys,
        "argv",
        ["script", "--model", "sonnet-test", "--approved-provider-disclosure"],
    )
    assert driver.main() == 0
    output = capsys.readouterr().out
    assert "quote_not_found" in output and "annotations[0].quote" in output
    assert (
        "unmatched private quote" not in output
        and "invented private text" not in output
    )
    files = list((private / "debug").glob("*.json"))
    assert len(files) == 1 and files[0].stat().st_mode & 0o077 == 0
    raw = files[0].read_bytes()
    assert b"unmatched private quote" in raw
    from idx_agent.enrichment.dev_extraction import parse_response

    replayed, diagnostics = parse_response(json.loads(raw), "invented private text")
    assert replayed == [] and diagnostics[0]["rule"] == "quote_not_found"
    assert (private / "predictions-dev.json").is_file()


def test_http_error_body_is_private_and_aborts(monkeypatch):
    from idx_agent.enrichment.dev_extraction import ProviderFailure

    def fail(request, timeout):
        raise driver.urllib.error.HTTPError(
            "https://provider.invalid",
            401,
            "denied",
            {},
            io.BytesIO(b"invented private body"),
        )

    monkeypatch.setattr(driver.consent, "spend_paid_call", lambda: None)
    monkeypatch.setattr(driver.urllib.request, "urlopen", fail)
    with pytest.raises(ProviderFailure) as caught:
        driver._send("invented", "spec", "sonnet-test", "fake-key")
    assert caught.value.raw == b"invented private body"
    assert str(caught.value) == "provider_http_error"
    assert "private body" not in str(caught.value)
