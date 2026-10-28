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
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": '{"annotations":[]}'}],
                    "usage": {"input_tokens": 20, "output_tokens": 3},
                }
            ).encode()
        )

    monkeypatch.setattr(driver.consent, "spend_paid_call", lambda: None)
    monkeypatch.setattr(driver.urllib.request, "urlopen", fake_open)
    text, usage = driver._send("invented", "spec", "sonnet-test", "fake-key")
    assert text == '{"annotations":[]}'
    assert usage == {"input_tokens": 20, "output_tokens": 3}
    assert json.loads(called[0]["messages"][0]["content"]) == {"remark": "invented"}


def test_loader_keeps_only_dev_cases(tmp_path):
    splits = {str(i): "dev" if i < 100 else "test" for i in range(250)}
    (tmp_path / "splits.json").write_text(
        json.dumps({"version": 1, "dataset_id": "invented", "splits": splits}),
        encoding="utf-8",
    )
    with (tmp_path / "sample.jsonl").open("w", encoding="utf-8") as handle:
        for key, split in splits.items():
            handle.write(json.dumps({"key": key, "remark": f"invented {split}"}) + "\n")
    dataset, cases = driver._load_dev(tmp_path)
    assert dataset == "invented"
    assert len(cases) == 100
    assert all(text == "invented dev" for _, text in cases)
