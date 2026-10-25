"""Snapshot report is deterministic and never overwrites existing run evidence."""

import pytest
from tests.test_approval import ADDRESS
from tests.test_approval import ledger as ledger
from tests.test_mcp_search import ASOF

from idx_agent.email.report import draft_report, render_report, write_report
from idx_agent.safety.approval import ApprovalRefused


def test_report_is_byte_identical_and_dated_from_data():
    dates = ASOF.to_envelope()
    first = render_report(["Invented city card"], dates)
    assert first == render_report(["Invented city card"], dates)
    assert str(dates.sold) in first and str(dates.active) in first
    assert "snapshot" in first and "forecast" not in first


def test_report_never_overwrites(tmp_path):
    path = tmp_path / "data" / "reports" / "weekly.txt"
    kwargs = {"data_root": tmp_path / "data", "is_ignored": lambda _: True}
    write_report(path, "First", **kwargs)
    with pytest.raises(ApprovalRefused, match="report_exists"):
        write_report(path, "Second", **kwargs)
    assert path.read_text() == "First"


def test_report_draft_idempotent_without_second_record(ledger):
    store, _ = ledger
    text = render_report(["Invented city card"], ASOF.to_envelope())
    args = (store, ADDRESS, text, ASOF.to_envelope(), ["Pasadena"])
    first = draft_report(*args)
    assert draft_report(*args).id == first.id
    assert len(store.list_pending()) == 1
