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
    monkeypatch.setattr(driver, "EXCLUSIONS_SHA256", _sha(private / driver.EXCLUSIONS))
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


def _lifecycle(env) -> list[tuple[str, str | None]]:
    """The invocation starts and stops in the evidence (attempt, response and
    settlement lines left out)."""
    return [
        (e["event"], e.get("reason"))
        for e in _evidence(env)
        if e["event"] in ("initial", "resume", "stop")
    ]


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


def _always_failing(*failing):
    """Every attempt of the named (configuration, case) requests fails, retryably."""
    return lambda _, c, i: (
        (c, i) in failing and io.AttemptError("ServerError", True, None)
    )


def _failed_request_lines(env) -> list[tuple[str, int]]:
    return [
        (e["config"], e["case"])
        for e in _evidence(env)
        if e["event"] == "failed_request"
    ]


def test_a_remark_failing_three_attempts_is_a_failed_request_scored_empty(
    env, monkeypatch, capsys
):
    # Owner, 2026-11-05, item 2: the run goes on; the remark is recorded as a failed
    # request, scored as an empty prediction for that configuration, and counted.
    fake = Fake(_always_failing(("v2", 5)))
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 0 and len(fake.sent) == 302
    assert fake.sent[300:] == [("v2", 5), ("v2", 5)]
    _only_progress(lines[:-1])
    ledger = _ledger(env)
    assert ledger["status"] == "released" and ledger["calls_used"] == 302
    assert ledger["items"]["v2"][5] == {"attempts": 3, "state": "failed"}
    assert _failed_request_lines(env) == [("v2", 5)]
    release = lines[-1]["release"]
    v2, v3 = release["configurations"]["v2"], release["configurations"]["v3"]
    assert (v2["failed_requests"], v3["failed_requests"]) == (1, 0)
    assert v2["attempts"] == 152 and v3["attempts"] == 150
    # The empty prediction is scored by the same scorer: one missed gold group.
    garage = "facet.exterior_lot.garage"
    assert v2["metrics"][garage]["expected"] == v3["metrics"][garage]["expected"]
    assert v2["metrics"][garage]["correct"] == v3["metrics"][garage]["correct"] - 1
    assert release["verdict"]["micro"]["v2_f1"] < 1.0
    assert release["verdict"]["micro"]["v3_f1"] == 1.0
    predictions = json.loads((env.run_dir / "predictions-v2.json").read_text())
    assert predictions["labels"][5]["annotations"] == []
    ctx = driver.verify_seal(env.root, env.private, env.seal)
    mapped, _, _ = driver.v3.map_payload(
        predictions, ctx["sample"], ctx["subtypes"], "test"
    )
    primary, full = driver.score_both(
        ctx["sample"], ctx["gold"], mapped, ctx["excluded"]
    )
    assert v2["metrics"] == driver.v3.counts_json(primary)
    assert v2["diagnostic_metrics"] == driver.v3.counts_json(full)


def test_two_failed_requests_in_each_configuration_still_release(
    env, monkeypatch, capsys
):
    failing = (("v2", 1), ("v2", 2), ("v3", 4), ("v3", 9))
    fake = Fake(_always_failing(*failing))
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 0 and len(fake.sent) == 308
    assert sorted(_failed_request_lines(env)) == sorted(failing)
    configurations = lines[-1]["release"]["configurations"]
    assert configurations["v2"]["failed_requests"] == 2
    assert configurations["v3"]["failed_requests"] == 2


def test_a_third_failed_request_in_one_configuration_makes_the_run_failed_and_final(
    env, monkeypatch, capsys
):
    fake = Fake(_always_failing(("v3", 1), ("v3", 2), ("v3", 3)))
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    # 300 initial, three second attempts, then the third attempts; the third failure
    # stops the run.
    assert code == 1 and len(fake.sent) == 306
    assert (lines[-1]["status"], lines[-1]["stop_reason"]) == (
        "failed",
        "failed_requests",
    )
    _only_progress(lines[:-2])
    _nothing_released(env, lines)
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("failed", "failed_requests")
    # The evidence records why: the failed requests and the stop with the counts.
    assert _failed_request_lines(env) == [("v3", 1), ("v3", 2), ("v3", 3)]
    stop = _evidence(env)[-1]
    assert (stop["event"], stop["reason"]) == ("stop", "failed_requests")
    assert stop["failed_requests"] == {"v2": 0, "v3": 3}
    state = _dry_state(env, monkeypatch, capsys)
    assert (state["status"], state["resumable"], state["max_token_calls"]) == (
        "failed",
        False,
        0,
    )
    again = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, again, 294)
    assert (
        code == 1
        and again.sent == []
        and lines[-1]["reason"] == ("the run is final (failed)")
    )
    assert token_state() == "valid"


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
    assert _lifecycle(env) == [
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


def _refused_and_unchanged(
    env, monkeypatch, capsys, cap, reason="the run cannot be resumed"
) -> None:
    before = (env.run_dir / "ledger.json").read_text()
    events = len(_evidence(env))
    fake = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, fake, cap)
    assert code == 1 and fake.sent == [] and token_state() == "valid"
    assert lines[-1]["reason"] == reason
    assert (env.run_dir / "ledger.json").read_text() == before
    assert len(_evidence(env)) == events
    _nothing_released(env, lines)


def test_a_token_cap_stop_resumes_under_a_fresh_token_capped_at_the_calls_left(
    env, monkeypatch, capsys
):
    # Owner, 2026-11-05, open question 1: a spent token resumes under decision 2's
    # conditions; the 600-call ledger bounds spend, not the token.
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
    state = _dry_state(env, monkeypatch, capsys)
    assert (state["status"], state["stop_reason"]) == ("stopped", "token_cap")
    assert state["resumable"] is True and state["max_token_calls"] == 592
    assert state["calls_left"] == 592
    # A token above the calls left is still refused before any call.
    _refused_and_unchanged(
        env, monkeypatch, capsys, 593, "the token ceiling exceeds the calls left"
    )
    # A second small token runs out again: still resumable, nothing reset.
    again = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, again, 2)
    assert code == 1 and len(again.sent) == 2
    assert lines[-1]["stop_reason"] == "token_cap" and lines[-1]["calls_used"] == 10
    _nothing_released(env, lines)
    last = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, last, 590)
    sent = first.sent + small.sent + again.sent
    # 290 initial requests left, then the provider-failed fifth request, retried.
    assert code == 0 and len(last.sent) == 291 and last.sent[-1] == first.sent[4]
    assert not set(sent[:4] + sent[5:]) & set(last.sent)
    ledger = _ledger(env)
    assert ledger["calls_used"] == 301
    assert [x["token_max_calls"] for x in ledger["invocations"]] == [600, 3, 2, 590]
    assert _lifecycle(env) == [
        ("initial", None),
        ("stop", "provider_failure"),
        ("resume", None),
        ("stop", "token_cap"),
        ("resume", None),
        ("stop", "token_cap"),
        ("resume", None),
    ]
    assert lines[-1]["release"]["calls_used"] == 301


def test_a_refused_token_mid_run_resumes_under_a_fresh_token(env, monkeypatch, capsys):
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
    _nothing_released(env, lines)
    monkeypatch.setattr(consent, "spend_paid_call", original)
    state = _dry_state(env, monkeypatch, capsys)
    assert (state["status"], state["stop_reason"]) == ("stopped", "token_refused")
    assert state["resumable"] is True and state["calls_used"] == 11
    assert state["max_token_calls"] == 589
    _refused_and_unchanged(
        env, monkeypatch, capsys, 590, "the token ceiling exceeds the calls left"
    )
    second = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, second, 589)
    # The refusal came before the twelfth spend: no call was counted for it.
    assert code == 0 and len(second.sent) == 289
    assert not set(fake.sent) & set(second.sent)
    assert _ledger(env)["calls_used"] == 300
    assert _lifecycle(env) == [
        ("initial", None),
        ("stop", "token_refused"),
        ("resume", None),
    ]


def test_an_interrupted_invocation_keeps_its_request_counted_and_may_resume(
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
    # The interrupt is persisted (stopped, interrupted), the request stays counted.
    assert ledger["status"] == "stopped" and ledger["stop_reason"] == "interrupted"
    assert ledger["calls_used"] == 7
    assert ledger["items"]["v2"][3] == {"attempts": 1, "state": "in_flight"}
    state = _dry_state(env, monkeypatch, capsys)
    assert state["status"] == "stopped" and state["stop_reason"] == "interrupted"
    # Owner decision 2: the validated state may resume, capped at the calls left.
    assert state["resumable"] is True and state["max_token_calls"] == 593
    assert state["calls_used"] == 7 and state["calls_left"] == 593
    _refused_and_unchanged(
        env, monkeypatch, capsys, 594, "the token ceiling exceeds the calls left"
    )
    second = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, second, 593)
    # Six completed requests are not resent; the ambiguous one stays counted and is
    # retried after every initial request.
    assert code == 0 and len(second.sent) == 294 and second.sent[-1] == ("v2", 3)
    ledger = _ledger(env)
    assert ledger["calls_used"] == 301 and ledger["items"]["v2"][3]["attempts"] == 2
    assert lines[-1]["release"]["calls_used"] == 301


def test_a_local_error_after_a_written_checkpoint_counts_and_is_never_resent(
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
    state = _dry_state(env, monkeypatch, capsys)
    assert state["stop_reason"] == "interrupted" and state["max_token_calls"] == 596
    second = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, second, 596)
    # The checkpoint verified against its evidence line: complete, not resent.
    assert code == 0 and len(second.sent) == 296 and ("v3", 1) not in second.sent
    assert _ledger(env)["items"]["v3"][1] == {"attempts": 1, "state": "done"}
    assert _ledger(env)["calls_used"] == 300
    settled = [e for e in _evidence(env) if e["event"] == "settled"]
    assert settled == [
        {"event": "settled", "config": "v3", "case": 1, "attempt": 1, "state": "done"}
    ]


@pytest.mark.parametrize(
    ("status", "reason", "resumable"),
    [
        ("stopped", "auth_failure", True),
        ("stopped", "provider_failure", True),
        ("stopped", "interrupted", True),
        ("stopped", "token_cap", True),
        ("stopped", "token_refused", True),
        ("running", None, False),
        ("exhausted", "budget_exhausted", False),
        ("failed", "retry_limit", False),
        ("failed", "failed_requests", False),
        ("released", None, False),
    ],
)
def test_only_the_recorded_resumable_stops_may_resume(status, reason, resumable):
    ledger = driver.new_ledger("0" * 64)
    ledger.update(calls_used=40, status=status, stop_reason=reason)
    ledger["items"]["v2"][0]["attempts"] = 40
    state = driver.ledger_state(ledger)
    assert state["resumable"] is resumable
    assert state["max_token_calls"] == (560 if resumable else 0)


@pytest.mark.parametrize("failed", [1, 2])
def test_up_to_two_failed_requests_leave_a_stopped_run_resumable(failed):
    ledger = driver.new_ledger("0" * 64)
    ledger.update(
        calls_used=3 * failed, status="stopped", stop_reason="provider_failure"
    )
    for index in range(failed):
        ledger["items"]["v2"][index].update(attempts=3, state="failed")
    state = driver.ledger_state(ledger)
    assert (state["status"], state["stop_reason"]) == ("stopped", "provider_failure")
    assert state["resumable"] is True and state["max_token_calls"] == 600 - 3 * failed


@pytest.mark.parametrize("config", ["v2", "v3"])
def test_a_third_failed_request_in_either_configuration_is_reported_final(config):
    ledger = driver.new_ledger("0" * 64)
    ledger.update(calls_used=9, status="stopped", stop_reason="provider_failure")
    for index in range(3):
        ledger["items"][config][index].update(attempts=3, state="failed")
    state = driver.ledger_state(ledger)
    assert (state["status"], state["stop_reason"]) == ("failed", "failed_requests")
    assert state["resumable"] is False and state["max_token_calls"] == 0


def test_every_request_resolved_with_two_failed_is_reported_complete():
    ledger = driver.new_ledger("0" * 64)
    ledger.update(calls_used=304, status="stopped", stop_reason="interrupted")
    for config in ("v2", "v3"):
        for item in ledger["items"][config]:
            item.update(attempts=1, state="done")
    for index in (0, 1):
        ledger["items"]["v2"][index].update(attempts=3, state="failed")
    state = driver.ledger_state(ledger)
    assert state["status"] == "complete" and state["complete"]["v2"] == 148


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
        "private:v3-heldout-exclusions-v1.json",
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


def _one_request_left_at_599() -> dict:
    """599 calls used, in one invocation; every request answered except ("v2", 0), on
    its third attempt next, which is the 600th call. The driver's own validation
    accepts it."""
    ledger = driver.new_ledger("0" * 64)
    every = [x for c in ("v2", "v3") for x in ledger["items"][c]]
    for item in every:
        item.update(attempts=2, state="done")
    every[1].update(attempts=1)
    ledger["items"]["v2"][0].update(attempts=2, state="retry")
    ledger["calls_used"] = 599
    ledger["invocations"].append(
        {
            "number": 1,
            "kind": "initial",
            "token_max_calls": 600,
            "calls_at_start": 0,
            "calls": 599,
            "stop_reason": None,
        }
    )
    driver.check_ledger(ledger, "0" * 64)
    return ledger


@pytest.mark.parametrize(
    "error",
    [
        io.AttemptError("ServerError", True, None),
        io.AttemptError("AuthenticationError", False, b"{}"),
        io.AttemptError("ClientError", False, None),
    ],
    ids=["retryable", "auth", "provider"],
)
def test_a_failed_600th_call_on_the_last_requests_third_attempt_exhausts_the_run(
    monkeypatch, error
):
    """Owner, 2026-11-11, option (b): a failed 600th call is exhausted and final, also
    when it was the last unanswered request; the remark is a failed request, but the
    run is not complete and nothing is released."""
    monkeypatch.setattr(consent, "spend_paid_call", lambda n=1: None)
    ledger = _one_request_left_at_599()

    def send(*_):
        raise error

    run = driver.Run(ledger, lambda _: None, None, lambda _: None, lambda _: None)
    assert run.execute(SimpleNamespace(remaining=1), send) == "exhausted"
    assert ledger["calls_used"] == 600
    assert (ledger["status"], ledger["stop_reason"]) == (
        "exhausted",
        "budget_exhausted",
    )
    assert ledger["items"]["v2"][0] == {"attempts": 3, "state": "failed"}
    state = driver.ledger_state(ledger)
    assert (state["status"], state["resumable"], state["max_token_calls"]) == (
        "exhausted",
        False,
        0,
    )


def test_a_600th_call_answered_on_the_last_request_still_completes(monkeypatch):
    monkeypatch.setattr(consent, "spend_paid_call", lambda n=1: None)
    ledger = _one_request_left_at_599()
    run = driver.Run(
        ledger, lambda _: None, lambda *_: None, lambda _: None, lambda _: None
    )
    assert run.execute(SimpleNamespace(remaining=1), lambda *_: b"{}") == "complete"
    assert ledger["calls_used"] == 600 and ledger["status"] == "complete"
    assert ledger["items"]["v2"][0] == {"attempts": 3, "state": "done"}


def test_a_third_failed_request_on_the_600th_call_still_makes_the_run_failed(
    monkeypatch,
):
    # The more-than-two rule keeps its precedence over exhaustion at the 600th call.
    monkeypatch.setattr(consent, "spend_paid_call", lambda n=1: None)
    ledger = _one_request_left_at_599()
    for index in (1, 2):
        ledger["items"]["v2"][index].update(attempts=3, state="failed")
    for index in (3, 4, 5):  # the three extra attempts, taken back from answered ones
        ledger["items"]["v2"][index].update(attempts=1)
    driver.check_ledger(ledger, "0" * 64)  # still 599 attempts in all

    def send(*_):
        raise io.AttemptError("ServerError", True, None)

    run = driver.Run(ledger, lambda _: None, None, lambda _: None, lambda _: None)
    assert run.execute(SimpleNamespace(remaining=1), send) == "failed"
    assert (ledger["status"], ledger["stop_reason"]) == ("failed", "failed_requests")


def test_a_failed_600th_call_with_another_request_unanswered_still_exhausts(
    monkeypatch,
):
    monkeypatch.setattr(consent, "spend_paid_call", lambda n=1: None)
    ledger = _one_request_left_at_599()
    ledger["items"]["v3"][0].update(state="retry")  # attempts 2, still unanswered

    def send(*_):
        raise io.AttemptError("AuthenticationError", False, b"{}")

    run = driver.Run(ledger, lambda _: None, None, lambda _: None, lambda _: None)
    assert run.execute(SimpleNamespace(remaining=1), send) == "exhausted"
    assert ledger["stop_reason"] == "budget_exhausted"


def _to_the_600th_call(error, *open_requests):
    """Every request fails its first attempt, retryably, except (v3, TEST - 1), which
    never fails; (v2, 0) and each of `open_requests` fail their second attempt too.
    That is 300 initial calls and 299 second attempts, so the 600th call is the third
    attempt of (v2, 0), and it fails with `error`."""
    attempts = Counter()
    retryable = io.AttemptError("ServerError", True, None)

    def fail(call, config, case):
        attempts[config, case] += 1
        if call == driver.BUDGET:
            assert (config, case, attempts[config, case]) == ("v2", 0, 3)
            return error
        if (config, case) == ("v3", TEST - 1):
            return None
        if attempts[config, case] == 1:
            return retryable
        if attempts[config, case] == 2 and (config, case) in {
            ("v2", 0),
            *open_requests,
        }:
            return retryable
        return None

    return fail


ERRORS_AT_600 = pytest.mark.parametrize(
    "error",
    [
        io.AttemptError("ServerError", True, None),
        io.AttemptError("AuthenticationError", False, b"{}"),
        io.AttemptError("ClientError", False, None),
    ],
    ids=["retryable", "auth", "provider"],
)


def _assert_exhausted_at_600(env, monkeypatch, capsys, held="failed") -> None:
    """The ledger is written exhausted and final with all 600 calls counted and
    (v2, 0) `held` (failed, or in flight until settled), nothing is released and the
    dry run reports the run exhausted, not resumable."""
    ledger = _ledger(env)
    assert ledger["calls_used"] == 600
    assert (ledger["status"], ledger["stop_reason"]) == (
        "exhausted",
        "budget_exhausted",
    )
    assert ledger["items"]["v2"][0] == {"attempts": 3, "state": held}
    assert _evidence(env)[-1]["event"] == "stop"
    assert _evidence(env)[-1]["status"] == "exhausted"
    assert not (env.run_dir / "result.json").exists()
    assert not list(env.run_dir.glob("predictions-*.json"))
    state = _dry_state(env, monkeypatch, capsys)
    assert (state["status"], state["stop_reason"]) == ("exhausted", "budget_exhausted")
    assert (state["resumable"], state["max_token_calls"], state["calls_left"]) == (
        False,
        0,
        0,
    )


# Owner, 2026-11-11 (WO-034, option (b)): a failed 600th call is exhausted and final,
# including when it was the third attempt of the last unanswered request. Before the
# decision this case completed the run and released it with one failed request.
@ERRORS_AT_600
def test_command_a_failed_600th_call_on_the_last_unanswered_request_exhausts(
    env, monkeypatch, capsys, error
):
    fake = Fake(_to_the_600th_call(error))
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and len(fake.sent) == 600 and fake.sent[-1] == ("v2", 0)
    assert lines[-1]["status"] == "exhausted" and lines[-1]["released"] is False
    assert lines[-1]["calls_left"] == 0
    _nothing_released(env, lines)
    assert driver.failed_requests(_ledger(env)) == {"v2": 1, "v3": 0}
    assert _failed_request_lines(env) == [("v2", 0)]
    _assert_exhausted_at_600(env, monkeypatch, capsys)
    # Final: a later paid invocation refuses with no call and the token unspent.
    again = Fake()
    code, lines = _invoke(env, monkeypatch, capsys, again, 1)
    assert code == 1 and again.sent == [] and token_state() == "valid"
    assert lines[-1]["reason"] == "the run is final (exhausted)"
    _nothing_released(env, lines)


@ERRORS_AT_600
def test_command_a_failed_600th_call_with_another_request_unanswered_exhausts(
    env, monkeypatch, capsys, error
):
    fake = Fake(_to_the_600th_call(error, ("v3", 0)))
    code, lines = _invoke(env, monkeypatch, capsys, fake, 600)
    assert code == 1 and len(fake.sent) == 600 and fake.sent[-1] == ("v2", 0)
    assert lines[-1]["status"] == "exhausted" and lines[-1]["released"] is False
    assert lines[-1]["calls_left"] == 0
    _nothing_released(env, lines)
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == (
        "exhausted",
        "budget_exhausted",
    )
    assert ledger["items"]["v2"][0] == {"attempts": 3, "state": "failed"}
    assert ledger["items"]["v3"][0] == {"attempts": 2, "state": "retry"}
    assert _failed_request_lines(env) == [("v2", 0)]
    state = _dry_state(env, monkeypatch, capsys)
    assert (state["status"], state["resumable"], state["max_token_calls"]) == (
        "exhausted",
        False,
        0,
    )


def _interrupt_the_600th(
    env, monkeypatch, capsys, where, plan=None, last=("v2", 0)
) -> None:
    """The 600th call is the third attempt of `last`, the last unanswered request
    (`plan`, `_to_the_600th_call` by default), and an interrupt arrives: during the
    request (`in_flight`), after a retryable error while its failed request line is
    written (`failure_line`), or after the ledger holds it failed, in the progress
    line (`progress`)."""
    plan = plan or _to_the_600th_call
    if where == "in_flight":
        fake = Fake(plan(KeyboardInterrupt()))
    else:
        fake = Fake(plan(io.AttemptError("ServerError", True, None)))
    line, emit = driver.failed_request_line, driver._emit

    def interrupting_line(config, index, **extra):
        if where == "failure_line" and extra.get("call") == driver.BUDGET:
            raise KeyboardInterrupt
        return line(config, index, **extra)

    def interrupting_emit(value):
        if where == "progress" and value.get("calls_used") == driver.BUDGET:
            raise KeyboardInterrupt
        emit(value)

    monkeypatch.setattr(driver, "failed_request_line", interrupting_line)
    monkeypatch.setattr(driver, "_emit", interrupting_emit)
    with pytest.raises(KeyboardInterrupt):
        _invoke(env, monkeypatch, capsys, fake, 600)
    consent.reset_for_tests()
    capsys.readouterr()
    monkeypatch.setattr(driver, "failed_request_line", line)
    monkeypatch.setattr(driver, "_emit", emit)
    assert len(fake.sent) == 600 and fake.sent[-1] == last


INTERRUPTS_AT_600 = pytest.mark.parametrize(
    "where", ["in_flight", "failure_line", "progress"]
)


# Owner, 2026-11-11 (WO-034, option (b)): an interrupted 600th call is exhausted and
# final too, also on the last unanswered request, wherever the interrupt arrives.
@INTERRUPTS_AT_600
def test_command_an_interrupted_600th_call_on_the_last_unanswered_request_exhausts(
    env, monkeypatch, capsys, where
):
    _interrupt_the_600th(env, monkeypatch, capsys, where)
    stop = _evidence(env)[-1]
    assert (stop["status"], stop["reason"], stop["error_class"]) == (
        "exhausted",
        "budget_exhausted",
        "interrupted",
    )
    held = "in_flight" if where == "in_flight" else "failed"
    _assert_exhausted_at_600(env, monkeypatch, capsys, held)


# The same case found on a later invocation: the request left in flight settles as a
# failed request, or a failed request line the interrupt kept from being written is
# recorded late, and every request then has a final record; the run stays exhausted
# and final, is never released, and a paid invocation refuses with no key, token or
# call and writes nothing.
@INTERRUPTS_AT_600
def test_a_failed_600th_on_the_last_request_found_by_settling_stays_exhausted(
    env, monkeypatch, capsys, where
):
    _interrupt_the_600th(env, monkeypatch, capsys, where)
    ledger, settled = driver.load_run(env.run_dir, env.seal)
    assert driver.resolved(ledger) and ledger["status"] == "exhausted"
    assert ledger["items"]["v2"][0] == {"attempts": 3, "state": "failed"}
    if where == "in_flight":
        assert [e["event"] for e in settled] == ["settled", "failed_request"]
        assert settled[0]["state"] == "failed"
    elif where == "failure_line":
        assert _failed_request_lines(env) == []
        assert settled == [driver.failed_request_line("v2", 0, recorded_late=True)]
    else:
        assert settled == [] and _failed_request_lines(env) == [("v2", 0)]
    state = driver.ledger_state(ledger)
    assert (state["status"], state["resumable"], state["max_token_calls"]) == (
        "exhausted",
        False,
        0,
    )
    before = {
        name: (env.run_dir / name).read_bytes()
        for name in ("ledger.json", "evidence.jsonl")
    }
    dry = _dry_state(env, monkeypatch, capsys)
    assert (dry["status"], dry["resumable"], dry["max_token_calls"]) == (
        "exhausted",
        False,
        0,
    )
    monkeypatch.setattr(io, "read_key", lambda: pytest.fail("key read"))
    for cap in (None, 1):
        fake = Fake()
        code, lines = _invoke(env, monkeypatch, capsys, fake, cap)
        assert code == 1 and fake.sent == []
        assert lines[-1]["reason"] == "the run is final (exhausted)"
        _nothing_released(env, lines)
    assert token_state() == "valid"
    for name, raw in before.items():
        assert (env.run_dir / name).read_bytes() == raw
    assert not (env.run_dir / driver.FINAL_MARKER).exists()


def _a_third_v2_failure_at_the_600th(error):
    """Every request fails its first attempt, retryably, except three v3 requests that
    never fail; (v2, 1), (v2, 2) and (v2, TEST - 1) fail their second attempt too, and
    (v2, 1) and (v2, 2) their third. That is 300 initial calls, 297 second attempts and
    3 third attempts, so the 600th call is the third attempt of (v2, TEST - 1), the last
    unanswered request; it fails with `error`, the third failed request in v2."""
    attempts = Counter()
    retryable = io.AttemptError("ServerError", True, None)
    never = {("v3", TEST - 1), ("v3", TEST - 2), ("v3", TEST - 3)}
    again = {("v2", 1), ("v2", 2), ("v2", TEST - 1)}

    def fail(call, config, case):
        key = (config, case)
        attempts[key] += 1
        if call == driver.BUDGET:
            assert (config, case, attempts[key]) == ("v2", TEST - 1, 3)
            return error
        if key in never:
            return None
        if attempts[key] == 1 or key in again:
            return retryable
        return None

    return fail


# The more-than-two failed requests rule keeps its precedence over option (b) on the
# interrupted path too: an interrupt after the 600th call made the third failed
# request in a configuration writes the run `failed`, not `exhausted`.
@pytest.mark.parametrize("where", ["failure_line", "progress"])
def test_an_interrupt_after_a_third_failed_request_at_the_600th_call_is_failed(
    env, monkeypatch, capsys, where
):
    plan, last = _a_third_v2_failure_at_the_600th, ("v2", TEST - 1)
    _interrupt_the_600th(env, monkeypatch, capsys, where, plan, last)
    ledger = _ledger(env)
    assert ledger["calls_used"] == 600
    assert (ledger["status"], ledger["stop_reason"]) == ("failed", "failed_requests")
    assert driver.failed_requests(ledger) == {"v2": 3, "v3": 0}
    stop = _evidence(env)[-1]
    assert (stop["event"], stop["status"], stop["reason"], stop["error_class"]) == (
        "stop",
        "failed",
        "failed_requests",
        "interrupted",
    )
    assert not (env.run_dir / "result.json").exists()
    state = _dry_state(env, monkeypatch, capsys)
    assert (state["status"], state["stop_reason"]) == ("failed", "failed_requests")
    assert (state["resumable"], state["max_token_calls"]) == (False, 0)
