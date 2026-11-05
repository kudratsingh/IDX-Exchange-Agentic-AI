"""WO-034 Phase D resume and run-state validation (owner decisions 2 to 4,
2026-11-04) and the pending review fixes (a) to (c), on invented files only. A fake
transport replaces the Messages API; the network is blocked; no key is read."""

# Decision 2: an interrupted invocation may resume only when the sealed inputs
# re-verify, the ledger, the run evidence and every checkpoint agree, calls remain and
# nothing is released; each invocation needs a fresh token capped at the calls left;
# completed requests are never resent and ambiguous attempts stay counted; corrupt or
# unverifiable state stops the run and marks it final. Decision 3: a failed or
# interrupted 600th attempt exhausts the run. Decision 4: no token content is written to
# stdout, the ledger, the evidence or any run file. Review fixes: no ledger is recreated
# over existing state (a), a resume needs the stop's record (b), and an interrupt in the
# back-off sleep or the token spend goes through the interrupted path (c).

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import enrichment_v3_io as io
from scripts import extract_enrichment_v3_heldout as driver
from tests.enrichment_v3_synthetic import (
    DEV,
    block_network,
    make_private,
    remark_of,
    response_for,
)
from tests.paid_token import grant_paid, run_as, token_state

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
GOLD = "labels-v5.json"
MARKED = "the run is final (unverifiable: the run was marked final)"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


@pytest.fixture
def env(tmp_path, monkeypatch, paid_consent_dir):
    block_network(monkeypatch)
    root = tmp_path / "repo"
    for name in driver.SEALED_FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, root / name)
    private = make_private(tmp_path)
    monkeypatch.setattr(
        driver, "V1_REFERENCE_SHA256", _sha(private / driver.V1_REFERENCE)
    )
    monkeypatch.setattr(driver, "EXCLUSIONS_SHA256", _sha(private / driver.EXCLUSIONS))
    monkeypatch.setattr(driver, "ROOT", root)
    monkeypatch.setattr(io, "read_key", lambda: "invented-key")
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)
    _write_json(root / driver.LOCK, driver.build_lock(root))
    _write_json(root / driver.FREEZE, driver.build_seal(root, private, GOLD))
    seal = _sha(root / driver.FREEZE)
    return SimpleNamespace(
        root=root,
        private=private,
        consent=paid_consent_dir,
        monkeypatch=monkeypatch,
        seal=seal,
        command=driver.COMMAND.format(seal=seal),
        run_dir=private / driver.RUN_DIR,
    )


class Fake:
    """Records (configuration, case) per request; `fail(call, config, case)` may
    return an exception to raise, or raise one itself."""

    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def __call__(self, body, key):
        assert key == "invented-key"
        config = "v3" if body["tools"][0]["name"] == "record_facet_decisions" else "v2"
        case = int(remark_of(body).split()[2].rstrip(":")) - DEV
        self.sent.append((config, case))
        error = self.fail and self.fail(len(self.sent), config, case)
        if error:
            raise error
        return response_for(body)


def _invoke(env, capsys, fake=None, cap=None, *, dry_run=False):
    """One invocation; returns (exit code, output lines)."""
    run_as(env.command + (" --dry-run" if dry_run else ""))
    if cap is not None:
        grant_paid(env.command, cap)
    env.monkeypatch.setattr(driver, "transport", fake or Fake())
    capsys.readouterr()
    mode = "--dry-run" if dry_run else "--approved-provider-disclosure"
    argv = ["--seal-sha256", env.seal, "--private-dir", str(env.private), mode]
    try:
        code = driver.main(argv)
    finally:
        consent.reset_for_tests()
    out = capsys.readouterr().out.strip().splitlines()
    return code, [json.loads(x) for x in out]


def _interrupted(env, capsys, fake, cap=600) -> None:
    with pytest.raises(KeyboardInterrupt):
        _invoke(env, capsys, fake, cap)
    capsys.readouterr()


def _ledger(env) -> dict:
    return json.loads((env.run_dir / "ledger.json").read_text())


def _evidence(env) -> list[dict]:
    text = (env.run_dir / "evidence.jsonl").read_text()
    return [json.loads(x) for x in text.splitlines()]


def _lifecycle(env) -> list[tuple[str, str | None]]:
    return [
        (e["event"], e.get("reason"))
        for e in _evidence(env)
        if e["event"] in ("initial", "resume", "stop")
    ]


def _interrupt_at(n):
    def fail(call, *_):
        if call == n:
            raise KeyboardInterrupt

    return fail


def _auth_at(n):
    return lambda call, *_: (
        call == n and io.AttemptError("AuthenticationError", False, b"{}")
    )


def _attempt_lines(env) -> list[dict]:
    return [e for e in _evidence(env) if e["event"] == "attempt"]


# ----- Decision 2: interrupted runs resume under validated state ----------------------


def test_an_interrupted_request_stays_counted_and_resumes_under_a_fresh_token(
    env, capsys
):
    first = Fake(_interrupt_at(7))
    _interrupted(env, capsys, first)
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert ledger["calls_used"] == 7
    assert ledger["items"]["v2"][3] == {"attempts": 1, "state": "in_flight"}
    assert _lifecycle(env) == [("initial", None), ("stop", "interrupted")]
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["resumable"] is True and lines[-1]["max_token_calls"] == 593
    # Each invocation needs a fresh token: the first one was consumed.
    code, lines = _invoke(env, capsys, Fake())
    assert code == 1 and lines[-1]["reason"].startswith("no usable paid token")
    assert _ledger(env) == ledger
    # A fresh token above the calls left is refused before any call.
    code, lines = _invoke(env, capsys, Fake(), 594)
    assert lines[-1]["reason"] == "the token ceiling exceeds the calls left"
    assert token_state() == "valid" and _ledger(env) == ledger
    second = Fake()
    code, lines = _invoke(env, capsys, second, 593)
    assert code == 0 and len(second.sent) == 294
    assert not set(first.sent[:6]) & set(second.sent)  # completed: never resent
    assert second.sent[-1] == ("v2", 3)  # the ambiguous request, retried last
    final = _ledger(env)
    assert final["calls_used"] == 301 and final["items"]["v2"][3]["attempts"] == 2
    assert [x["kind"] for x in final["invocations"]] == ["initial", "resume"]
    assert _lifecycle(env) == [
        ("initial", None),
        ("stop", "interrupted"),
        ("resume", None),
    ]
    settled = [e for e in _evidence(env) if e["event"] == "settled"]
    assert [(e["config"], e["case"], e["state"]) for e in settled] == [
        ("v2", 3, "retry")
    ]
    assert len(_attempt_lines(env)) == final["calls_used"]
    assert lines[-1]["release"]["calls_used"] == 301


def test_an_interrupt_in_the_back_off_sleep_is_persisted_and_resumable(env, capsys):
    def server_error_first(call, *_):
        return call == 1 and io.AttemptError("ServerError", True, None)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    env.monkeypatch.setattr(driver.time, "sleep", interrupt)
    first = Fake(server_error_first)
    _interrupted(env, capsys, first)
    assert len(first.sent) == 300  # the sleep comes before the first retry
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert ledger["calls_used"] == 300
    assert ledger["items"]["v2"][0] == {"attempts": 1, "state": "retry"}
    assert _evidence(env)[-1]["event"] == "stop"
    env.monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)
    second = Fake()
    code, lines = _invoke(env, capsys, second, 300)
    assert code == 0 and second.sent == [("v2", 0)]
    assert _ledger(env)["calls_used"] == 301


def test_an_interrupt_in_the_token_spend_is_persisted_and_resumable(env, capsys):
    original = consent.spend_paid_call
    spent = []

    def spend(n=1):
        spent.append(n)
        if len(spent) == 5:
            raise KeyboardInterrupt
        original(n)

    env.monkeypatch.setattr(consent, "spend_paid_call", spend)
    first = Fake()
    _interrupted(env, capsys, first)
    env.monkeypatch.setattr(consent, "spend_paid_call", original)
    ledger = _ledger(env)
    assert len(first.sent) == 4 and ledger["calls_used"] == 4
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert not any(
        x["state"] == "in_flight" for c in ("v2", "v3") for x in ledger["items"][c]
    )
    second = Fake()
    code, _ = _invoke(env, capsys, second, 596)
    assert code == 0 and len(second.sent) == 296 and _ledger(env)["calls_used"] == 300


def test_an_attempt_counted_before_its_evidence_line_stays_counted(env, capsys):
    """Interrupted between the ledger save and the attempt line: the ledger may
    hold exactly that one attempt more than the evidence; the resume writes the
    missing line, and every later check still balances."""
    begin = driver.Run.begin

    def patched(self, *args, **kwargs):
        begin(self, *args, **kwargs)
        inner = self.record

        def record(entry):
            if entry["event"] == "attempt" and entry["call"] == 5:
                raise KeyboardInterrupt
            inner(entry)

        self.record = record

    env.monkeypatch.setattr(driver.Run, "begin", patched)
    first = Fake()
    _interrupted(env, capsys, first)
    env.monkeypatch.setattr(driver.Run, "begin", begin)
    assert len(first.sent) == 4  # the fifth request was never sent
    ledger = _ledger(env)
    assert ledger["calls_used"] == 5 and len(_attempt_lines(env)) == 4
    assert ledger["items"]["v2"][2] == {"attempts": 1, "state": "in_flight"}
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["resumable"] is True and lines[-1]["calls_left"] == 595
    second = Fake()
    code, _ = _invoke(env, capsys, second, 595)
    assert code == 0 and second.sent[-1] == ("v2", 2)
    late = [e for e in _attempt_lines(env) if e.get("recorded_late")]
    assert [(e["config"], e["case"], e["call"]) for e in late] == [("v2", 2, 5)]
    assert len(_attempt_lines(env)) == _ledger(env)["calls_used"] == 301
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["status"] == "released"  # the full history still verifies


def test_a_resume_reverifies_the_sealed_inputs_first(env, capsys):
    _interrupted(env, capsys, Fake(_interrupt_at(3)))
    before = (env.run_dir / "ledger.json").read_bytes()
    target = env.root / "docs/ENRICHMENT_SCORING_V1.md"
    target.write_bytes(target.read_bytes() + b"\n")
    fake = Fake()
    code, lines = _invoke(env, capsys, fake, 597)
    assert code == 1 and fake.sent == [] and token_state() == "valid"
    assert lines[-1]["reason"] == "a sealed input changed"
    assert (env.run_dir / "ledger.json").read_bytes() == before
    assert not (env.run_dir / driver.FINAL_MARKER).exists()


# ----- Corrupt or unverifiable state stops the run (decision 2; fixes a and b) --------


def _stopped_run(env, capsys) -> None:
    """An auth failure on call 10: stopped, resumable, nine checkpoints."""
    code, lines = _invoke(env, capsys, Fake(_auth_at(10)), 600)
    assert lines[-1]["stop_reason"] == "auth_failure"
    assert _invoke(env, capsys, dry_run=True)[1][-1]["resumable"] is True


def _edit_ledger(env, change) -> None:
    path = env.run_dir / "ledger.json"
    ledger = json.loads(path.read_text())
    change(ledger)
    path.write_text(json.dumps(ledger))


def _below_evidence(ledger) -> None:
    # Drop the failed tenth attempt from the ledger, keeping it self-consistent.
    item = ledger["items"]["v3"][4]
    assert item == {"attempts": 1, "state": "retry"}
    item.update(attempts=0, state="pending")
    ledger["calls_used"] = 9
    ledger["invocations"][0]["calls"] = 9


def _rewrite_checkpoint(path: Path) -> None:
    stored = json.loads(path.read_text())
    stored["raw"] = base64.b64encode(b'{"content": []}').decode("ascii")
    path.write_text(json.dumps(stored))


def _drop_last_line(path: Path) -> None:
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(lines[:-1]))


def _checkpoint(env, config, case) -> Path:
    return env.run_dir / "checkpoints" / config / f"{case + 1:03d}.json"


CORRUPT = {
    "ledger deleted": (
        lambda env: (env.run_dir / "ledger.json").unlink(),
        "run state exists without a ledger",
    ),
    "ledger and evidence deleted": (
        lambda env: [
            (env.run_dir / n).unlink() for n in ("ledger.json", "evidence.jsonl")
        ],
        "run state exists without a ledger",
    ),
    "ledger below the evidence": (
        lambda env: _edit_ledger(env, _below_evidence),
        "the ledger's totals are below the run evidence",
    ),
    "ledger truncated": (
        lambda env: (env.run_dir / "ledger.json").write_text(
            (env.run_dir / "ledger.json").read_text()[:100]
        ),
        "the ledger is unreadable",
    ),
    "ledger of another seal": (
        lambda env: _edit_ledger(env, lambda x: x.update(seal_sha256="0" * 64)),
        "the ledger does not belong to this sealed run",
    ),
    "evidence deleted": (
        lambda env: (env.run_dir / "evidence.jsonl").unlink(),
        "the run evidence is missing",
    ),
    "evidence truncated": (
        lambda env: (env.run_dir / "evidence.jsonl").write_text(
            (env.run_dir / "evidence.jsonl").read_text()[:-2]
        ),
        "the run evidence is unreadable",
    ),
    "stop not recorded": (
        lambda env: _drop_last_line(env.run_dir / "evidence.jsonl"),
        "the stop is not recorded in the run evidence",
    ),
    "checkpoint hash mismatch": (
        lambda env: _rewrite_checkpoint(_checkpoint(env, "v2", 0)),
        "a checkpoint does not verify",
    ),
    "checkpoint deleted": (
        lambda env: _checkpoint(env, "v2", 0).unlink(),
        "a completed request has no checkpoint",
    ),
    "checkpoint for a pending request": (
        lambda env: shutil.copyfile(
            _checkpoint(env, "v2", 0), _checkpoint(env, "v2", 149)
        ),
        "a checkpoint for a request not completed",
    ),
    "results before completion": (
        lambda env: (env.run_dir / "result.json").write_text("{}"),
        "results exist before both configurations are complete",
    ),
    "stray file": (
        lambda env: (env.run_dir / "notes.txt").write_text("invented"),
        "an unexpected file in the run directory",
    ),
}


@pytest.mark.parametrize("case", sorted(CORRUPT))
def test_corrupt_or_unverifiable_state_stops_the_run_and_marks_it_final(
    env, capsys, case
):
    _stopped_run(env, capsys)
    change, reason = CORRUPT[case]
    change(env)
    ledger_path = env.run_dir / "ledger.json"
    before = ledger_path.read_bytes() if ledger_path.exists() else None
    # The dry run reports it and writes nothing.
    code, lines = _invoke(env, capsys, dry_run=True)
    assert code == 0 and lines[-1]["status"] == "unverifiable"
    assert lines[-1]["stop_reason"] == reason and lines[-1]["max_token_calls"] == 0
    assert not (env.run_dir / driver.FINAL_MARKER).exists()
    # A paid invocation refuses before any key, token or call, and marks it final.
    env.monkeypatch.setattr(io, "read_key", lambda: pytest.fail("key read"))
    fake = Fake()
    code, lines = _invoke(env, capsys, fake, 590)
    assert code == 1 and fake.sent == [] and token_state() == "valid"
    assert lines[-1]["status"] == "refused"
    assert lines[-1]["reason"] == f"the run is final (unverifiable: {reason})"
    marker = json.loads((env.run_dir / driver.FINAL_MARKER).read_text())
    assert marker == {"status": "unverifiable", "reason": reason}
    # A ledger is never recreated or rewritten over the existing state.
    assert (ledger_path.read_bytes() if ledger_path.exists() else None) == before
    assert not (env.run_dir / "result.json").exists() or case.startswith("results")
    # Final: every later invocation refuses, whatever is restored.
    code, lines = _invoke(env, capsys, Fake(), 590)
    assert code == 1 and lines[-1]["reason"] == MARKED and token_state() == "valid"


def test_hidden_files_are_not_run_state(env, capsys):
    """Operating-system metadata (a Finder `.DS_Store`) is never read as run state;
    a visible stray file is (the "stray file" case above)."""
    _stopped_run(env, capsys)
    for folder in (env.run_dir, env.run_dir / "checkpoints" / "v2"):
        (folder / ".DS_Store").write_bytes(b"invented")
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["resumable"] is True and lines[-1]["max_token_calls"] == 590
    fake = Fake()
    code, _ = _invoke(env, capsys, fake, 590)
    assert code == 0 and len(fake.sent) == 291


def test_a_ledger_left_running_with_no_recorded_stop_is_final(env, capsys):
    """A hard kill writes no stop: a resume needs the stop's record (fix b)."""
    env.monkeypatch.setattr(driver.Run, "interrupted", lambda self: None)
    _interrupted(env, capsys, Fake(_interrupt_at(7)))
    assert _ledger(env)["status"] == "running"
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["status"] == "unverifiable"
    assert lines[-1]["stop_reason"] == "the stop is not recorded in the run evidence"
    fake = Fake()
    code, lines = _invoke(env, capsys, fake, 593)
    assert code == 1 and fake.sent == [] and "unverifiable" in lines[-1]["reason"]
    assert _invoke(env, capsys, Fake(), 593)[1][-1]["reason"] == MARKED


def test_run_files_without_a_ledger_refuse_a_fresh_start(env, capsys):
    """Fix (a): evidence or checkpoints with no ledger never start a new run."""
    (env.run_dir / "checkpoints" / "v2").mkdir(parents=True)
    (env.run_dir / "evidence.jsonl").write_text('{"event": "initial"}\n')
    fake = Fake()
    code, lines = _invoke(env, capsys, fake, 600)
    assert code == 1 and fake.sent == [] and token_state() == "valid"
    assert lines[-1]["reason"] == (
        "the run is final (unverifiable: run state exists without a ledger)"
    )
    assert not (env.run_dir / "ledger.json").exists()


def test_empty_run_directories_alone_are_not_run_state(env, capsys):
    for config in ("v2", "v3"):
        (env.run_dir / "checkpoints" / config).mkdir(mode=0o700, parents=True)
    for path in (env.run_dir, env.run_dir / "checkpoints"):
        path.chmod(0o700)
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["status"] == "not_started"
    fake = Fake()
    code, _ = _invoke(env, capsys, fake, 600)
    assert code == 0 and len(fake.sent) == 300


# ----- Decision 3: the 600th attempt --------------------------------------------------


def _server_errors_then(last):
    def fail(call, *_):
        if call < 600:
            return io.AttemptError("ServerError", True, None)
        return last()

    return fail


def _raise_interrupt():
    raise KeyboardInterrupt


@pytest.mark.parametrize(
    "last",
    [
        lambda: io.AttemptError("ServerError", True, None),
        lambda: io.AttemptError("AuthenticationError", False, None),
        _raise_interrupt,
    ],
    ids=["retryable", "auth", "interrupt"],
)
def test_a_failed_or_interrupted_600th_attempt_exhausts_with_no_refund(
    env, capsys, last
):
    fake = Fake(_server_errors_then(last))
    try:
        _invoke(env, capsys, fake, 600)
    except KeyboardInterrupt:
        pass
    ledger = _ledger(env)
    assert len(fake.sent) == 600 and ledger["calls_used"] == 600
    assert (ledger["status"], ledger["stop_reason"]) == (
        "exhausted",
        "budget_exhausted",
    )
    # The failed requests are not refunded: all 600 stay counted.
    assert sum(x["attempts"] for c in ("v2", "v3") for x in ledger["items"][c]) == 600
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["status"] == "exhausted" and lines[-1]["max_token_calls"] == 0
    code, lines = _invoke(env, capsys, Fake(), 1)
    assert code == 1 and lines[-1]["reason"] == "the run is final (exhausted)"
    assert token_state() == "valid"


# ----- Decision 4: no token content is ever written ----------------------------------


def _token_secrets(consent_dir: Path) -> set[str]:
    """Every line of the paid token file and its expiry and grant times. The
    command words and the ceiling are not secrets (the command is printed by the
    dry run as the sealed command, and the ceiling is recorded as a count)."""
    path = consent_dir / "paid"
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        found.add(line)
        key, _, value = line.partition("=")
        if key in ("expiry", "granted") and value:
            found.add(value)
    return found


def test_no_token_content_reaches_stdout_the_ledger_evidence_or_run_files(env, capsys):
    secrets = set()
    outputs = []
    run_as(env.command)
    for cap, fail in ((600, _auth_at(10)), (590, _interrupt_at(5)), (585, None)):
        grant_paid(env.command, cap)
        secrets |= _token_secrets(env.consent)
        env.monkeypatch.setattr(driver, "transport", Fake(fail))
        argv = [
            "--seal-sha256",
            env.seal,
            "--private-dir",
            str(env.private),
            "--approved-provider-disclosure",
        ]
        run_as(env.command)
        try:
            driver.main(argv)
        except KeyboardInterrupt:
            pass
        finally:
            consent.reset_for_tests()
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
        secrets |= _token_secrets(env.consent)  # after the spend, too
    outputs.append(
        "".join(json.dumps(x) for x in _invoke(env, capsys, dry_run=True)[1])
    )
    assert secrets and all(len(s) >= 8 for s in secrets)
    written = [
        p.read_text(encoding="utf-8") for p in env.run_dir.rglob("*") if p.is_file()
    ]
    assert '"release"' in outputs[-2]  # the run completed and released
    for text in [*outputs, *written]:
        for secret in secrets:
            assert secret not in text


# ----- An interrupt while an invocation starts (review of 74fe559) -------------------


def _record_raising_once(env, event, *, signal_after=False):
    """Wrap each Run's evidence writer: the first `event` line raises KeyboardInterrupt
    before it is written or, with `signal_after`, sends this process a real SIGINT
    once it is written."""
    init = driver.Run.__init__
    fired = []

    def patched(self, ledger, save, write_checkpoint, record, out):
        def wrapped(entry):
            if entry["event"] == event and not fired:
                fired.append(entry["event"])
                if not signal_after:
                    raise KeyboardInterrupt
                record(entry)
                os.kill(os.getpid(), signal.SIGINT)
                return
            record(entry)

        init(self, ledger, save, write_checkpoint, wrapped, out)

    env.monkeypatch.setattr(driver.Run, "__init__", patched)
    return fired


def _assert_unique_lifecycle(env) -> None:
    starts = [
        (e["event"], e["invocation"])
        for e in _evidence(env)
        if e["event"] in ("initial", "resume")
    ]
    assert len(starts) == len(set(starts))


def test_an_interrupt_before_the_initial_start_line_is_resumable(env, capsys):
    fired = _record_raising_once(env, "initial")
    first = Fake()
    _interrupted(env, capsys, first)
    assert fired and first.sent == []
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert ledger["calls_used"] == 0
    assert _lifecycle(env) == [("initial", None), ("stop", "interrupted")]
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["resumable"] is True and lines[-1]["max_token_calls"] == 600
    second = Fake()
    code, lines = _invoke(env, capsys, second, 600)
    assert code == 0 and len(second.sent) == 300 and "release" in lines[-1]
    _assert_unique_lifecycle(env)


def test_an_interrupt_while_a_resume_records_its_settlement_is_resumable(env, capsys):
    _interrupted(env, capsys, Fake(_interrupt_at(7)))
    fired = _record_raising_once(env, "settled")
    second = Fake()
    with pytest.raises(KeyboardInterrupt):
        _invoke(env, capsys, second, 593)
    capsys.readouterr()
    assert fired and second.sent == []
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert ledger["items"]["v2"][3] == {"attempts": 1, "state": "retry"}
    assert _lifecycle(env) == [
        ("initial", None),
        ("stop", "interrupted"),
        ("resume", None),
        ("stop", "interrupted"),
    ]
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["resumable"] is True and lines[-1]["max_token_calls"] == 593
    third = Fake()
    code, lines = _invoke(env, capsys, third, 593)
    assert code == 0 and len(third.sent) == 294 and "release" in lines[-1]
    settled = [e for e in _evidence(env) if e["event"] == "settled"]
    assert [(e["config"], e["case"], e["state"]) for e in settled] == [
        ("v2", 3, "retry")
    ]
    _assert_unique_lifecycle(env)


def test_a_sigint_while_an_invocation_starts_is_held_until_it_is_recorded(env, capsys):
    """A real SIGINT arriving after the start line is written but before the
    invocation's start is complete is held, then goes through the interrupted path."""
    fired = _record_raising_once(env, "initial", signal_after=True)
    first = Fake()
    _interrupted(env, capsys, first)
    assert fired and first.sent == []
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert _lifecycle(env) == [("initial", None), ("stop", "interrupted")]
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    code, lines = _invoke(env, capsys, Fake(), 600)
    assert code == 0 and "release" in lines[-1]


def test_an_interrupt_while_the_first_ledger_is_written_leaves_no_partial_ledger(
    env, capsys
):
    """The first ledger is written whole (temporary file, then a hard link): an
    interrupt mid-write leaves no ledger, so the run has not started."""
    original = io.write_new

    def partial(path, value):
        Path(path).write_text(json.dumps(value)[:50])
        raise KeyboardInterrupt

    env.monkeypatch.setattr(io, "write_new", partial)
    first = Fake()
    _interrupted(env, capsys, first)
    env.monkeypatch.setattr(io, "write_new", original)
    assert first.sent == [] and not (env.run_dir / "ledger.json").exists()
    assert not (env.run_dir / "evidence.jsonl").exists()
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["status"] == "not_started"
    second = Fake()
    code, _ = _invoke(env, capsys, second, 600)
    assert code == 0 and len(second.sent) == 300


# ----- Decision 3: a stored exhaustion is final whatever settling finds --------------


def test_an_interrupted_600th_attempt_is_exhausted_even_with_its_checkpoint(
    env, capsys
):
    """300 initial requests fail (retryable), the 300 retries succeed, and the
    interrupt arrives once the 600th response's checkpoint is on disk, before the
    ledger marks it done: the run is exhausted and final, never released."""
    original = io.write_checkpoint
    written = []

    def checkpoint_then_interrupt(path, raw, usage):
        original(path, raw, usage)
        written.append(path)
        if len(written) == 300:
            raise KeyboardInterrupt

    env.monkeypatch.setattr(io, "write_checkpoint", checkpoint_then_interrupt)
    first = Fake(
        lambda call, *_: call <= 300 and io.AttemptError("ServerError", True, None)
    )
    _interrupted(env, capsys, first)
    env.monkeypatch.setattr(io, "write_checkpoint", original)
    ledger = _ledger(env)
    assert len(first.sent) == 600 and ledger["calls_used"] == 600
    assert (ledger["status"], ledger["stop_reason"]) == (
        "exhausted",
        "budget_exhausted",
    )
    code, lines = _invoke(env, capsys, dry_run=True)
    assert lines[-1]["status"] == "exhausted" and lines[-1]["max_token_calls"] == 0
    for cap in (None, 1):
        code, lines = _invoke(env, capsys, Fake(), cap)
        assert code == 1 and lines[-1]["reason"] == "the run is final (exhausted)"
        assert "release" not in lines[-1]
    assert not (env.run_dir / "result.json").exists()


def test_an_interrupt_after_the_600th_is_marked_done_completes_the_run(env, capsys):
    """Once the 600th request is checkpointed and the ledger marks it done, an
    interrupt does not turn the complete run into an exhausted one."""

    original = driver._emit

    def emit(value):
        if value.get("calls_used") == 600:
            raise KeyboardInterrupt
        original(value)

    env.monkeypatch.setattr(driver, "_emit", emit)
    _interrupted(
        env,
        capsys,
        Fake(
            lambda call, *_: call <= 300 and io.AttemptError("ServerError", True, None)
        ),
    )
    env.monkeypatch.setattr(driver, "_emit", original)
    assert _ledger(env)["status"] == "complete"
    code, lines = _invoke(env, capsys)
    assert code == 0 and lines[-1]["release"]["calls_used"] == 600
