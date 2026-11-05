"""WO-034 Phase B: the Phase D command contract, on invented files only.

The command is never run against real data here. A synthetic repository copy holds a
lock and final freeze built by the driver's own builders; a fake transport replaces
the standard Messages API; the network is blocked and no key is read."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import enrichment_v3_io as io
from scripts import extract_enrichment_v3_heldout as driver
from tests.enrichment_v3_synthetic import (
    DEV,
    TEST,
    block_network,
    make_private,
    remark_of,
    response_for,
    subtype,
)
from tests.paid_token import grant_paid, run_as, token_state

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
GOLD = "labels-v5.json"
PROGRESS_KEYS = {"calls_used", "calls_left", "complete"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _seal(env) -> str:
    _write_json(env.root / driver.LOCK, driver.build_lock(env.root))
    _write_json(
        env.root / driver.FREEZE, driver.build_seal(env.root, env.private, env.gold)
    )
    return _sha(env.root / driver.FREEZE)


@pytest.fixture
def env(tmp_path, monkeypatch):
    block_network(monkeypatch)
    root = tmp_path / "repo"
    for name in driver.SEALED_FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, root / name)
    private = make_private(tmp_path)
    monkeypatch.setattr(
        driver, "V1_REFERENCE_SHA256", _sha(private / driver.V1_REFERENCE)
    )
    monkeypatch.setattr(driver, "ROOT", root)
    monkeypatch.setattr(io, "read_key", lambda: "invented-key")
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)
    value = SimpleNamespace(root=root, private=private, gold=GOLD)
    value.seal = _seal(value)
    value.command = driver.COMMAND.format(seal=value.seal)
    value.run_dir = private / driver.RUN_DIR
    return value


class Fake:
    """Records (configuration, case) per request; `fail(call, config, case)` may
    return an exception to raise instead of a response."""

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


def _invoke(env, monkeypatch, capsys, fake, max_calls=None, *extra):
    run_as(env.command + "".join(f" {w}" for w in extra))
    if max_calls is not None:
        grant_paid(env.command, max_calls)
    monkeypatch.setattr(driver, "transport", fake)
    capsys.readouterr()
    code = driver.main(
        [
            "--seal-sha256",
            env.seal,
            "--approved-provider-disclosure",
            "--private-dir",
            str(env.private),
            *extra,
        ]
    )
    consent.reset_for_tests()
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    return code, lines


def _ledger(env) -> dict:
    return json.loads((env.run_dir / "ledger.json").read_text())


def _evidence(env) -> list[dict]:
    path = env.run_dir / "evidence.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()]


def _nothing_released(env, lines) -> None:
    assert not (env.run_dir / "result.json").exists()
    assert not list(env.run_dir.glob("predictions-*.json"))
    assert not list(env.run_dir.glob("mapping-*.json"))
    for line in lines:
        assert "release" not in line and "metrics" not in json.dumps(line)


def _only_progress(lines) -> None:
    for line in lines:
        assert set(line) == PROGRESS_KEYS, line
        assert set(line["complete"]) == {"v2", "v3"}


def test_a_complete_run_sends_300_initial_requests_and_releases_once(
    env, monkeypatch, capsys
):
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 0 and len(fake.sent) == 300
    assert fake.sent[:4] == [("v2", 0), ("v3", 0), ("v2", 1), ("v3", 1)]
    assert Counter(fake.sent) == Counter(
        (c, i) for c in ("v2", "v3") for i in range(TEST)
    )
    _only_progress(lines[:-1])
    assert lines[-2] == {
        "calls_used": 300,
        "calls_left": 300,
        "complete": {"v2": 150, "v3": 150},
    }
    release = lines[-1]["release"]
    assert release["verdict"]["pass"] is True
    assert (
        release["verdict"]["micro"]["v3_f1"]
        == release["verdict"]["micro"]["v2_f1"]
        == 1.0
    )
    facets = release["verdict"]["facets"]
    assert facets["facet.exterior_lot.garage"]["status"] == "meets"
    assert facets["facet.location_views.water_view"]["status"] == "not_evaluable"
    assert release["calls_used"] == 300 and release["budget"] == 600
    assert release["v1_reference"]["note"].startswith("historical reference only")
    assert release["subtype_counts"] == dict(
        sorted(Counter(subtype(DEV + i) for i in range(TEST)).items())
    )
    v3_report = release["configurations"]["v3"]
    assert v3_report["span_quality"]["matched"]["rate"] == 1.0
    assert (
        v3_report["removed_by_polarity"]
        == release["configurations"]["v2"]["removed_by_polarity"]
    )
    assert v3_report["usage"]["per_remark"]["output_tokens"] == 20
    assert _ledger(env)["status"] == "released"
    assert (env.run_dir / "result.json").stat().st_mode & 0o777 == 0o600
    assert env.run_dir.stat().st_mode & 0o077 == 0
    out = json.dumps(lines)
    assert "Invented home" not in out and "attached garage" not in out
    # A released run is final.
    again = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, again, 300)
    assert code == 1 and again.sent == [] and "final" in lines[-1]["reason"]
    assert token_state() == "valid"


def test_budget_exhaustion_stops_marks_incomplete_and_refuses_more(
    env, monkeypatch, capsys
):
    fake = Fake(lambda *_: io.AttemptError("ServerError", True, None))
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and len(fake.sent) == 600
    assert lines[-1]["status"] == "exhausted" and lines[-1]["released"] is False
    assert lines[-1]["calls_left"] == 0
    _only_progress(lines[:-1])
    _nothing_released(env, lines)
    ledger = _ledger(env)
    assert ledger["calls_used"] == 600 and ledger["stop_reason"] == "budget_exhausted"
    assert all(x["attempts"] == 2 for c in ("v2", "v3") for x in ledger["items"][c])
    again = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, again, 1)
    assert code == 1 and again.sent == [] and "final" in lines[-1]["reason"]
    assert token_state() == "valid"


def test_the_exhausted_gate_refuses_a_call_even_with_token_calls_left():
    ledger = driver.new_ledger("0" * 64)
    ledger["calls_used"] = driver.BUDGET
    for item in ledger["items"]["v2"]:
        item.update(attempts=2, state="retry")
    for item in ledger["items"]["v3"]:
        item.update(attempts=2, state="done")
    ledger["invocations"].append({"number": 1, "token_max_calls": 600, "calls": 0})
    sent = []
    run = driver.Run(ledger, lambda _: None, None, lambda _: None, sent.append)
    budget = SimpleNamespace(remaining=10)
    assert run.execute(budget, lambda *_: pytest.fail("sent")) == "exhausted"
    assert sent == []


def test_retries_come_after_all_initial_requests_and_share_the_ledger(
    env, monkeypatch, capsys
):
    failures = {1: "ServerError", 2: "RateLimitError", 7: "TimeoutError"}

    def fail(call, *_):
        return failures.get(call) and io.AttemptError(failures[call], True, None)

    fake = Fake(fail)
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 0 and len(fake.sent) == 303
    assert fake.sent[300:] == [("v2", 0), ("v3", 0), ("v2", 3)]
    ledger = _ledger(env)
    assert ledger["calls_used"] == 303
    assert ledger["errors_by_class"] == {
        "v2": {"ServerError": 1, "TimeoutError": 1},
        "v3": {"RateLimitError": 1},
    }
    assert lines[-1]["release"]["configurations"]["v2"]["attempts"] == 152


def test_three_failed_attempts_end_the_run_as_final(env, monkeypatch, capsys):
    fake = Fake(
        lambda _, c, i: (
            (c, i) == ("v2", 5) and io.AttemptError("ServerError", True, None)
        )
    )
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and len(fake.sent) == 302
    assert lines[-1]["status"] == "failed" and lines[-1]["stop_reason"] == "retry_limit"
    _nothing_released(env, lines)
    code, lines = _invoke(env, monkeypatch, capsys, Fake(), 298)
    assert code == 1 and "final" in lines[-1]["reason"] and token_state() == "valid"


def test_auth_failure_then_resume_with_a_new_token_continues_the_same_ledger(
    env, monkeypatch, capsys
):
    first = Fake(
        lambda call, *_: (
            call == 10 and io.AttemptError("AuthenticationError", False, b"{}")
        )
    )
    code, lines = _invoke(env, monkeypatch, capsys, first, 600)
    assert code == 1 and len(first.sent) == 10
    assert (
        lines[-1]["status"] == "stopped" and lines[-1]["stop_reason"] == "auth_failure"
    )
    _nothing_released(env, lines)
    assert _ledger(env)["calls_used"] == 10
    # A token above the calls left is refused before any call; nothing resets.
    refused = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, refused, 591)
    assert code == 1 and refused.sent == []
    assert lines[-1]["reason"] == "the token ceiling exceeds the calls left"
    assert _ledger(env)["calls_used"] == 10 and len(_ledger(env)["invocations"]) == 1
    # A new token capped at the calls left resumes; completed cases are not resent.
    second = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, second, 590)
    assert code == 0 and len(second.sent) == 291
    assert not set(first.sent[:9]) & set(second.sent)
    assert second.sent[-1] == first.sent[9]  # the failed request, retried last
    ledger = _ledger(env)
    assert ledger["calls_used"] == 301
    failed = first.sent[9]
    assert ledger["items"][failed[0]][failed[1]]["attempts"] == 2
    assert [x["kind"] for x in ledger["invocations"]] == ["initial", "resume"]
    events = [(e["event"], e.get("reason")) for e in _evidence(env)]
    assert events == [
        ("initial", None),
        ("stop", "auth_failure"),
        ("resume", None),
    ]
    assert lines[-1]["release"]["calls_used"] == 301


@pytest.mark.parametrize("cap", [1, 10, 300, 599])
def test_a_first_token_below_600_is_refused_before_any_call(
    env, monkeypatch, capsys, cap
):
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, cap)
    assert code == 1 and fake.sent == []
    assert lines[-1]["reason"] == "the first token must carry exactly 600 calls"
    assert not (env.run_dir / "ledger.json").exists()
    # Refused before any call: the next invocation still starts a new run.
    full = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, full, 600)
    assert code == 0 and len(full.sent) == 300
    assert [x["kind"] for x in _ledger(env)["invocations"]] == ["initial"]


def _dry_state(env, monkeypatch, capsys) -> dict:
    code, lines = _invoke(env, monkeypatch, capsys, Fake(), None, "--dry-run")
    assert code == 0
    return lines[-1]


def _refused_and_unchanged(env, monkeypatch, capsys, cap) -> None:
    before = (env.run_dir / "ledger.json").read_text()
    events = len(_evidence(env))
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, cap)
    assert code == 1 and fake.sent == [] and token_state() == "valid"
    assert lines[-1]["reason"] == "the run cannot be resumed"
    assert (env.run_dir / "ledger.json").read_text() == before
    assert len(_evidence(env)) == events
    _nothing_released(env, lines)


def test_resume_with_a_smaller_cap_stops_at_the_cap_and_the_run_is_final(
    env, monkeypatch, capsys
):
    first = Fake(
        lambda call, *_: call == 5 and io.AttemptError("ClientError", False, None)
    )
    code, lines = _invoke(env, monkeypatch, capsys, first, 600)
    assert lines[-1]["stop_reason"] == "provider_failure" and len(first.sent) == 5
    small = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, small, 3)
    assert code == 1 and len(small.sent) == 3
    assert lines[-1]["stop_reason"] == "token_cap" and lines[-1]["calls_used"] == 8
    _nothing_released(env, lines)
    # A spent token is not a provider or auth failure: no further resume.
    state = _dry_state(env, monkeypatch, capsys)
    assert state["resumable"] is False and state["max_token_calls"] == 0
    assert state["calls_left"] == 592
    _refused_and_unchanged(env, monkeypatch, capsys, 592)
    assert _ledger(env)["calls_used"] == 8
    assert [x["token_max_calls"] for x in _ledger(env)["invocations"]] == [600, 3]


def test_a_refused_token_mid_run_leaves_the_run_final(env, monkeypatch, capsys):
    original = consent.spend_paid_call
    spent = []

    def expiring(n=1):
        spent.append(n)
        if len(spent) == 12:
            raise consent.PaidRunRefused("expired")
        original(n)

    monkeypatch.setattr(consent, "spend_paid_call", expiring)
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and len(fake.sent) == 11
    assert lines[-1]["stop_reason"] == "token_refused"
    monkeypatch.setattr(consent, "spend_paid_call", original)
    state = _dry_state(env, monkeypatch, capsys)
    assert state["resumable"] is False and state["calls_used"] == 11
    _refused_and_unchanged(env, monkeypatch, capsys, 589)


def test_an_interrupted_invocation_keeps_its_request_counted_and_is_final(
    env, monkeypatch, capsys
):
    def fail(call, *_):
        if call == 7:
            raise KeyboardInterrupt

    run_as(env.command)
    grant_paid(env.command, 600)
    monkeypatch.setattr(driver, "transport", Fake(fail))
    with pytest.raises(KeyboardInterrupt):
        driver.main(
            [
                "--seal-sha256",
                env.seal,
                "--approved-provider-disclosure",
                "--private-dir",
                str(env.private),
            ]
        )
    consent.reset_for_tests()
    ledger = _ledger(env)
    assert ledger["status"] == "running" and ledger["calls_used"] == 7
    assert ledger["items"]["v2"][3] == {"attempts": 1, "state": "in_flight"}
    state = _dry_state(env, monkeypatch, capsys)
    assert state["status"] == "stopped" and state["stop_reason"] == "interrupted"
    assert state["resumable"] is False and state["max_token_calls"] == 0
    assert state["calls_used"] == 7 and state["calls_left"] == 593
    _refused_and_unchanged(env, monkeypatch, capsys, 593)


def test_a_local_error_after_a_written_checkpoint_counts_and_is_final(
    env, monkeypatch, capsys
):
    original = io.write_checkpoint
    calls = []

    def flaky(path, raw, usage):
        original(path, raw, usage)
        calls.append(path)
        if len(calls) == 4:
            raise OSError("invented failure after the checkpoint was written")

    monkeypatch.setattr(io, "write_checkpoint", flaky)
    first = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, first, 600)
    assert code == 1 and lines[-1]["status"] == "stopped" and len(first.sent) == 4
    assert _ledger(env)["items"]["v3"][1]["state"] == "in_flight"
    assert _ledger(env)["calls_used"] == 4 and calls[-1].exists()
    monkeypatch.setattr(io, "write_checkpoint", original)
    assert _dry_state(env, monkeypatch, capsys)["stop_reason"] == "interrupted"
    _refused_and_unchanged(env, monkeypatch, capsys, 596)


@pytest.mark.parametrize(
    ("status", "reason", "resumable"),
    [
        ("stopped", "auth_failure", True),
        ("stopped", "provider_failure", True),
        ("stopped", "token_cap", False),
        ("stopped", "token_refused", False),
        ("running", None, False),
        ("exhausted", "budget_exhausted", False),
        ("failed", "retry_limit", False),
        ("released", None, False),
    ],
)
def test_only_a_provider_or_auth_failure_is_resumable(status, reason, resumable):
    ledger = driver.new_ledger("0" * 64)
    ledger.update(calls_used=40, status=status, stop_reason=reason)
    ledger["items"]["v2"][0]["attempts"] = 40
    state = driver.ledger_state(ledger)
    assert state["resumable"] is resumable
    assert state["max_token_calls"] == (560 if resumable else 0)


def test_a_provider_failure_on_a_third_attempt_is_reported_final():
    ledger = driver.new_ledger("0" * 64)
    ledger.update(calls_used=3, status="stopped", stop_reason="provider_failure")
    ledger["items"]["v2"][0].update(attempts=3, state="failed")
    state = driver.ledger_state(ledger)
    assert (state["status"], state["stop_reason"]) == ("failed", "retry_limit")
    assert state["resumable"] is False and state["max_token_calls"] == 0


def test_dry_run_reports_the_state_with_no_key_token_or_write(env, monkeypatch, capsys):
    monkeypatch.setattr(io, "read_key", lambda: pytest.fail("key read"))
    code, lines = _invoke(env, monkeypatch, capsys, Fake(), 600, "--dry-run")
    assert code == 0
    assert lines[-1] == {
        "mode": "dry_run",
        "paid_command": env.command,
        "status": "not_started",
        "calls_used": 0,
        "calls_left": 600,
        "max_token_calls": 600,
        "requests_made": 0,
    }
    assert not env.run_dir.exists() and token_state() == "valid"


def test_a_wrong_seal_hash_or_command_is_refused_before_a_token(
    env, monkeypatch, capsys
):
    good = env.seal
    env.seal = "f" * 64
    code, lines = _invoke(env, monkeypatch, capsys, Fake(), 600)
    assert code == 1 and lines[-1]["reason"] == "final freeze hash mismatch"
    env.seal = good
    run_as(env.command + " --extra")
    grant_paid(env.command + " --extra", 600)
    monkeypatch.setattr(driver, "transport", Fake())
    assert (
        driver.main(
            [
                "--seal-sha256",
                good,
                "--approved-provider-disclosure",
                "--private-dir",
                str(env.private),
            ]
        )
        == 1
    )
    assert "sealed command" in json.loads(capsys.readouterr().out)["reason"]
    assert token_state() == "valid"


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/extract_enrichment_v3_heldout.py",
        "scripts/enrichment_v3_io.py",
        "src/idx_agent/enrichment/v3.py",
        "src/idx_agent/enrichment/v2.py",
        "src/idx_agent/enrichment/private_scoring.py",
        "docs/ENRICHMENT_SCORING_V1.md",
        "docs/ENRICHMENT_EXTRACTION_V2.md",
        "docs/ENRICHMENT_EXTRACTION_V3.md",
        "docs/ENRICHMENT_V3_D_LOCK.json",
        "private:labels-v5.json",
        "private:sample.jsonl",
        "private:splits.json",
        "private:predictions-test-heldout.json",
    ],
)
def test_a_mutated_sealed_input_stops_before_a_token(
    env, monkeypatch, capsys, relative
):
    if relative.startswith("private:"):
        target = env.private / relative.split(":", 1)[1]
    else:
        target = env.root / relative
    target.write_bytes(target.read_bytes() + b"\n")
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and fake.sent == [] and lines[-1]["status"] == "refused"
    assert token_state() == "valid" and not env.run_dir.exists()


def test_a_mutated_mapper_rule_stops_before_a_token(env, monkeypatch, capsys):
    rule = dict(driver.v3.SUBTYPE_RULE, remove_when_condominium=[])
    monkeypatch.setattr(driver.v3, "SUBTYPE_RULE", rule)
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and fake.sent == [] and token_state() == "valid"


def test_a_tampered_ledger_is_refused(env, monkeypatch, capsys):
    stop = Fake(
        lambda call, *_: (
            call == 2 and io.AttemptError("AuthenticationError", False, None)
        )
    )
    _invoke(env, monkeypatch, capsys, stop, 600)
    path = env.run_dir / "ledger.json"
    saved = path.read_text()
    for change in ({"budget": 700}, {"calls_used": 0}, {"seal_sha256": "0" * 64}):
        path.write_text(json.dumps({**json.loads(saved), **change}))
        fake = Fake()
        code, lines = _invoke(env, monkeypatch, capsys, fake, 100)
        assert code == 1 and fake.sent == [] and token_state() == "valid"


def test_a_gold_that_contradicts_the_subtype_cannot_be_sealed_or_run(
    env, monkeypatch, capsys
):
    shutil.copyfile(
        env.private / "labels.json", env.private / "labels-unrelabelled.json"
    )
    env.gold = "labels-unrelabelled.json"
    env.seal = _seal(env)
    env.command = driver.COMMAND.format(seal=env.seal)
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert (
        code == 1 and fake.sent == [] and "contradicts subtype" in lines[-1]["reason"]
    )
    with pytest.raises(driver.v3.ContractError):
        driver.build_seal(env.root, env.private, "labels.json")


def test_the_seal_records_the_budget_command_and_no_paid_call(env):
    seal = json.loads((env.root / driver.FREEZE).read_text())
    assert seal["paid_calls_before_freeze"] == 0
    assert (
        seal["budget"],
        seal["initial_per_configuration"],
        seal["max_attempts"],
    ) == (
        600,
        150,
        3,
    )
    assert seal["configurations"] == ["v2", "v3"]
    assert set(seal["repo_files"]) == set(driver.SEALED_FILES)
    assert seal["contracts"]["v3"]["prompt_sha256"] == driver.v3.PROMPT_SHA256
    assert seal["contracts"]["v2"]["prompt_sha256"] == driver.V2_PROMPT_SHA256
    assert seal["private_files"]["gold"]["file"] == GOLD
    assert "{seal}" in seal["command"]
