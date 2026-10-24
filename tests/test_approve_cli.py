"""Operator CLI requires a terminal and binds approval to the displayed digest."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from tests.test_approval import create
from tests.test_approval import ledger as ledger

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_approval_refuses_pipe_but_accepts_operator_terminal(ledger, capsys):
    store, _ = ledger
    record = create(store)
    cli = load_script("approve")
    args = ["approve", record.id, "--digest", record.digest[:12]]
    assert cli.main(args, store=store, stdin=SimpleNamespace(isatty=lambda: False)) == 1
    assert store.get(record.id).state == "pending"
    assert cli.main(args, store=store, stdin=SimpleNamespace(isatty=lambda: True)) == 0
    assert store.get(record.id).state == "approved"


def test_sink_cli_receipt_and_duplicate_refusal(ledger):
    store, _ = ledger
    record = create(store)
    store.approve(record.id, record.digest[:12])
    cli = load_script("send_approved")
    assert cli.main([record.id, "--transport", "sink"], store=store) == 0
    assert cli.main([record.id, "--transport", "sink"], store=store) == 1
