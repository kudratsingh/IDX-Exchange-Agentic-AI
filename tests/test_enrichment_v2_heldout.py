"""No real data, paid calls, or held-out annotations are used here."""

import hashlib

from scripts import extract_enrichment_v2_heldout as heldout


def test_heldout_refuses_changed_dev_contract_before_loading_test(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "docs").mkdir()
    prompt = b"invented prompt"
    (tmp_path / "docs" / "ENRICHMENT_EXTRACTION_V2.md").write_bytes(prompt)
    monkeypatch.setattr(heldout, "ROOT", tmp_path)
    monkeypatch.setattr(heldout, "PRIVATE", tmp_path)
    monkeypatch.setattr(heldout, "PROMPT_HASH", hashlib.sha256(prompt).hexdigest())
    monkeypatch.setattr(heldout, "verify_freeze", lambda: None)
    monkeypatch.setattr(heldout, "contract_hashes", lambda: {"code": "new"})
    monkeypatch.setattr(
        heldout,
        "_read_private",
        lambda *_: {
            "haiku_within_three_points": True,
            "contract_hashes": {"code": "old"},
        },
    )
    monkeypatch.setattr(
        heldout,
        "_sample_jsonl",
        lambda *_: (_ for _ in ()).throw(AssertionError("test loaded")),
    )
    monkeypatch.setattr(
        heldout.consent,
        "start_paid_run",
        lambda: (_ for _ in ()).throw(AssertionError("paid run started")),
    )
    monkeypatch.setattr(heldout.consent, "abort_paid_run", lambda _: None)
    monkeypatch.setattr(
        heldout.sys, "argv", ["script", "--approved-provider-disclosure"]
    )
    assert heldout.main() == 1
    assert '"requests_made": 0' in capsys.readouterr().out
