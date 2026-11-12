"""WO-034 owner acceptance checks 3 and 4 (2026-11-04), on invented files only.

Check 3: dry runs and failed local preconditions read no key, build no client, open no
socket and spend no token. Check 4: resumes never resend, reset or over-grant, an
exhausted run never resumes, and no stop path releases a prediction or a score."""

# Check 3 covers the Phase C runner, the comparator, both preflights and the Phase D
# command; "no token spent" means the consent directory is unchanged byte for byte.
# Before the held-out lock exists, Phase D refuses before it opens a held-out remark or
# gold file (the files are unreadable sentinels). Check 4 includes the edge where the
# 600th call fails or is interrupted: the run is exhausted and final.

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import enrichment_v3_io as io
from scripts import extract_enrichment_v3_dev as dev
from scripts import extract_enrichment_v3_heldout as driver
from tests.enrichment_v3_guards import Touched, guarded, snapshot
from tests.enrichment_v3_synthetic import (
    DEV,
    TEST,
    block_network,
    make_private,
    remark_of,
    response_for,
)
from tests.paid_token import grant_paid, run_as, token_state

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
GOLD = "labels-v5.json"
CONFIGS = ("v2", "v3")
DEV_COMMAND = "python scripts/extract_enrichment_v3_dev.py --invented-phase-c"
# Every private file holding held-out remarks, held-out membership, gold or held-out
# predictions in the invented layout.
HELDOUT_FILES = (
    "sample.jsonl",
    "splits.json",
    GOLD,
    "labels.json",
    "predictions-test-heldout.json",
    "v3-heldout-exclusions-v1.json",
)
RELEASE_KEYS = {
    "release",
    "verdict",
    "metrics",
    "configurations",
    "f1",
    "precision",
    "recall",
    "span_quality",
    "labels",
    "annotations",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _lines(capsys) -> list:
    out = capsys.readouterr().out.strip().splitlines()
    return [json.loads(x) if x.startswith("{") else x for x in out]


# ----- Phase D fixtures ---------------------------------------------------------------


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
    value = SimpleNamespace(
        root=root, private=private, consent=paid_consent_dir, monkeypatch=monkeypatch
    )
    _write_json(root / driver.LOCK, driver.build_lock(root))
    _write_json(root / driver.FREEZE, driver.build_seal(root, private, GOLD))
    value.seal = _sha(root / driver.FREEZE)
    value.command = driver.COMMAND.format(seal=value.seal)
    value.run_dir = private / driver.RUN_DIR
    return value


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


def _d_argv(env, *extra, seal=None) -> list[str]:
    return [
        "--seal-sha256",
        seal or env.seal,
        "--private-dir",
        str(env.private),
        *extra,
    ]


def _paid_d(env, capsys, fake, cap=None):
    """One paid Phase D invocation with a fake transport (no sentinels)."""
    run_as(env.command)
    if cap is not None:
        grant_paid(env.command, cap)
    env.monkeypatch.setattr(driver, "transport", fake)
    capsys.readouterr()
    try:
        code = driver.main(_d_argv(env, "--approved-provider-disclosure"))
    finally:
        consent.reset_for_tests()
    return code, _lines(capsys)


def _ledger(env) -> dict:
    return json.loads((env.run_dir / "ledger.json").read_text())


def _evidence(env) -> list[dict]:
    text = (env.run_dir / "evidence.jsonl").read_text()
    return [json.loads(x) for x in text.splitlines()]


def _guarded_d(env, capsys, *extra, cap=600, command=None, seal=None, forbidden=()):
    """One Phase D invocation under every sentinel. Asserts that nothing guarded was
    used, the consent directory and the private directory are byte for byte
    unchanged and no paid run started; returns (exit code, output lines)."""
    dry = "--dry-run" in extra
    run_as(command or (env.command + (" --dry-run" if dry else "")))
    if cap is not None:
        grant_paid(env.command, cap)
    sent = []
    env.monkeypatch.setattr(driver, "transport", lambda *a: sent.append(a))
    consent_before, private_before = snapshot(env.consent), snapshot(env.private)
    capsys.readouterr()
    try:
        with guarded(*forbidden) as guard:
            code = driver.main(_d_argv(env, *extra, seal=seal))
    except Touched as touched:  # pragma: no cover - the failure message
        pytest.fail(f"guarded resource used: {touched}")
    finally:
        budget = consent.active_budget()
        consent.reset_for_tests()
    assert guard.events == [] and sent == []
    assert budget is None, "a paid run started"
    assert snapshot(env.consent) == consent_before, "the consent directory changed"
    assert snapshot(env.private) == private_before, "a private file changed"
    if cap is not None:
        assert token_state() == "valid"
    lines = _lines(capsys)
    for line in lines:
        assert not _keys(line) & RELEASE_KEYS, line
    return code, lines


# ----- Check 3, Phase D ---------------------------------------------------------------


def test_phase_d_dry_run_reads_no_key_client_socket_or_token(env, capsys):
    code, lines = _guarded_d(env, capsys, "--dry-run")
    assert code == 0 and lines[-1]["mode"] == "dry_run"
    assert lines[-1]["status"] == "not_started" and lines[-1]["requests_made"] == 0
    assert not env.run_dir.exists()


def _missing_freeze(env):
    (env.root / driver.FREEZE).unlink()


def _missing_gold(env):
    (env.private / GOLD).unlink()


def _wrong_hash_gold(env):
    path = env.private / GOLD
    path.write_bytes(path.read_bytes() + b"\n")


def _seal_mismatch(env):
    path = env.root / "docs/ENRICHMENT_SCORING_V1.md"
    path.write_bytes(path.read_bytes() + b"\n")


def _mutated_lock(env):
    path = env.root / driver.LOCK
    _write_json(path, {**json.loads(path.read_text()), "work_order": "WO-999"})


LOCAL = {
    "missing freeze": (_missing_freeze, "the Phase D final freeze is missing"),
    "missing gold": (_missing_gold, "the revised held-out gold file is missing"),
    "wrong-hash gold": (_wrong_hash_gold, "a sealed input changed"),
    "seal mismatch": (_seal_mismatch, "a sealed input changed"),
    "mutated lock": (_mutated_lock, "the Phase D lock does not verify"),
}


@pytest.mark.parametrize("dry_run", [False, True], ids=["paid", "dry_run"])
@pytest.mark.parametrize("case", sorted(LOCAL))
def test_phase_d_local_preconditions_refuse_with_no_key_client_socket_or_token(
    env, capsys, case, dry_run
):
    change, reason = LOCAL[case]
    change(env)
    extra = ("--dry-run",) if dry_run else ("--approved-provider-disclosure",)
    code, lines = _guarded_d(env, capsys, *extra)
    assert code == 1 and lines[-1]["status"] == "refused"
    assert lines[-1]["reason"] == reason and lines[-1]["released"] is False
    assert not env.run_dir.exists()


@pytest.mark.parametrize("dry_run", [False, True], ids=["paid", "dry_run"])
def test_phase_d_freeze_hash_mismatch_refuses_with_nothing_guarded_used(
    env, capsys, dry_run
):
    extra = ("--dry-run",) if dry_run else ("--approved-provider-disclosure",)
    code, lines = _guarded_d(env, capsys, *extra, seal="f" * 64)
    assert code == 1 and lines[-1]["reason"] == "final freeze hash mismatch"


TOKENS = {
    "missing token": (None, None, "no usable paid token (missing)"),
    "token for another command": (
        None,
        "other",
        "no usable paid token (command_mismatch)",
    ),
    "first token of 599": (599, None, "the first token must carry exactly 600 calls"),
    "first token of 601": (601, None, "the first token must carry exactly 600 calls"),
}


@pytest.mark.parametrize("case", sorted(TOKENS))
def test_phase_d_token_preconditions_refuse_before_the_key_and_leave_it_unspent(
    env, capsys, case
):
    cap, other, reason = TOKENS[case]
    if other:
        grant_paid(env.command + " --other", 600)
    code, lines = _guarded_d(env, capsys, "--approved-provider-disclosure", cap=cap)
    assert code == 1 and lines[-1]["status"] == "refused"
    assert lines[-1]["reason"] == reason
    assert not env.run_dir.exists()


def test_phase_d_without_the_disclosure_flag_refuses_with_nothing_guarded_used(
    env, capsys
):
    code, lines = _guarded_d(env, capsys)
    assert code == 2 and lines == ["Explicit provider disclosure is required."]


@pytest.mark.parametrize("freeze_present", [True, False], ids=["freeze", "no_freeze"])
@pytest.mark.parametrize("dry_run", [False, True], ids=["paid", "dry_run"])
def test_before_the_lock_exists_phase_d_refuses_before_any_heldout_file_is_opened(
    env, capsys, freeze_present, dry_run
):
    (env.root / driver.LOCK).unlink()
    if not freeze_present:
        (env.root / driver.FREEZE).unlink()
    forbidden = [env.private / name for name in HELDOUT_FILES]
    modes = [p.stat().st_mode for p in forbidden]
    extra = ("--dry-run",) if dry_run else ("--approved-provider-disclosure",)
    code, lines = _guarded_d(env, capsys, *extra, forbidden=forbidden)
    assert code == 1 and lines[-1]["status"] == "refused"
    assert lines[-1]["reason"] == "the Phase D lock is missing"
    # The sentinels were unreadable (mode 000) during the call and are restored.
    assert [p.stat().st_mode for p in forbidden] == modes


def test_the_lock_refusal_comes_from_verify_seal_itself(env):
    (env.root / driver.LOCK).unlink()
    forbidden = [env.private / name for name in HELDOUT_FILES]
    with guarded(*forbidden) as guard:
        with pytest.raises(driver.v3.ContractError, match="lock is missing"):
            driver.verify_seal(env.root, env.private, env.seal)
    assert guard.events == []


def test_phase_d_seal_verification_reads_no_key_client_socket_or_token(env):
    before = snapshot(env.consent)
    with guarded() as guard:
        ctx = driver.verify_seal(env.root, env.private, env.seal)
    assert guard.events == [] and len(ctx["cases"]) == TEST
    assert snapshot(env.consent) == before


# ----- Check 3, Phase C and the comparator --------------------------------------------


@pytest.fixture
def private(tmp_path, monkeypatch, paid_consent_dir):
    block_network(monkeypatch)
    path = make_private(tmp_path)
    monkeypatch.setattr(dev, "V2_PREDICTIONS_SHA256", _sha(path / dev.V2_PREDICTIONS))
    monkeypatch.setattr(io, "read_key", lambda: "invented-key")
    monkeypatch.setattr(io.time, "sleep", lambda _seconds: None)
    return SimpleNamespace(
        path=path, consent=paid_consent_dir, monkeypatch=monkeypatch, tmp=tmp_path
    )


def _c_argv(private, gold=GOLD, digest=None) -> list[str]:
    path = private.path / gold
    if digest is None:
        digest = _sha(path) if path.exists() else "0" * 64
    return ["--gold", gold, "--gold-sha256", digest, "--private-dir", str(private.path)]


def _guarded_c(private, capsys, *extra, cap=300, gold=GOLD, digest=None):
    dry = "--dry-run" in extra
    run_as(DEV_COMMAND + (" --dry-run" if dry else ""))
    if cap is not None:
        grant_paid(DEV_COMMAND, cap)
    sent = []
    private.monkeypatch.setattr(io, "attempt", lambda *a: sent.append(a))
    consent_before, private_before = snapshot(private.consent), snapshot(private.path)
    capsys.readouterr()
    try:
        with guarded() as guard:
            code = dev.main([*_c_argv(private, gold=gold, digest=digest), *extra])
    except Touched as touched:  # pragma: no cover - the failure message
        pytest.fail(f"guarded resource used: {touched}")
    finally:
        budget = consent.active_budget()
        consent.reset_for_tests()
    assert guard.events == [] and sent == []
    assert budget is None, "a paid run started"
    assert snapshot(private.consent) == consent_before, "the consent directory changed"
    assert snapshot(private.path) == private_before, "a private file changed"
    if cap is not None:
        assert token_state() == "valid"
    return code, _lines(capsys)


def test_phase_c_dry_run_reads_no_key_client_socket_or_token(private, capsys):
    code, lines = _guarded_c(private, capsys, "--dry-run")
    assert code == 0 and lines[-1]["mode"] == "dry_run"
    assert lines[-1]["requests_made"] == 0


def test_the_comparator_reads_no_key_client_socket_or_token(private, capsys):
    code, lines = _guarded_c(private, capsys, "--comparator")
    assert code == 0 and lines[-1]["mode"] == "comparator"


def test_phase_c_preconditions_read_no_key_client_socket_or_token(private):
    before = snapshot(private.consent)
    with guarded() as guard:
        ctx = dev.preconditions(ROOT, private.path, GOLD, _sha(private.path / GOLD))
    assert guard.events == [] and len(ctx["cases"]) == dev.CASES
    assert snapshot(private.consent) == before


def _repo_copy(private, relative: str | None, *, delete: bool = False) -> None:
    root = private.tmp / "repo"
    for name in [*dev.PINNED, dev.v3.FREEZE_FILE, dev.v3.CONTRACT_DOC]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, root / name)
    if relative is not None:
        target = root / relative
        if delete:
            target.unlink()
        else:
            target.write_bytes(target.read_bytes() + b"\n")
    private.monkeypatch.setattr(dev, "ROOT", root)


PHASE_C = {
    "missing freeze": dict(repo=(dev.v3.FREEZE_FILE, True)),
    "mismatched freeze": dict(repo=(dev.v3.FREEZE_FILE, False)),
    "pinned file changed": dict(repo=("src/idx_agent/enrichment/v3.py", False)),
    "original labels": dict(
        gold="labels.json", reason="a revised gold file is required, not labels.json"
    ),
    "missing gold": dict(
        gold="labels-missing.json", reason="the revised gold file is missing"
    ),
    "wrong-hash gold": dict(digest="f" * 64, reason="revised gold hash mismatch"),
}


@pytest.mark.parametrize("mode", ["--approved-provider-disclosure", "--dry-run"])
@pytest.mark.parametrize("case", sorted(PHASE_C))
def test_phase_c_local_preconditions_refuse_with_no_key_client_socket_or_token(
    private, capsys, case, mode
):
    spec = PHASE_C[case]
    if "repo" in spec:
        relative, delete = spec["repo"]
        _repo_copy(private, relative, delete=delete)
    code, lines = _guarded_c(
        private, capsys, mode, gold=spec.get("gold", GOLD), digest=spec.get("digest")
    )
    assert code == 1 and lines[-1]["status"] in {"refused", "stopped"}
    assert lines[-1]["requests_made"] == 0
    if "reason" in spec:
        assert lines[-1]["reason"] == spec["reason"]


@pytest.mark.parametrize(
    ("cap", "other", "reason"),
    [
        (None, False, "no usable paid token (missing)"),
        (None, True, "no usable paid token (command_mismatch)"),
        (299, False, "the Phase C token ceiling must be 300"),
        (301, False, "the Phase C token ceiling must be 300"),
    ],
)
def test_phase_c_token_preconditions_refuse_before_the_key_and_leave_it_unspent(
    private, capsys, cap, other, reason
):
    if other:
        grant_paid(DEV_COMMAND + " --other", 300)
    code, lines = _guarded_c(private, capsys, "--approved-provider-disclosure", cap=cap)
    assert code == 1 and lines[-1]["reason"] == reason
    assert lines[-1]["requests_made"] == 0


def test_phase_c_existing_output_refuses_with_no_key_client_socket_or_token(
    private, capsys
):
    (private.path / dev.OUTPUT).write_text("{}")
    code, lines = _guarded_c(private, capsys, "--approved-provider-disclosure")
    assert code == 1 and lines[-1]["reason"] == "existing output"


# ----- Check 4, resume ----------------------------------------------------------------


def _auth_at(n):
    return lambda call, *_: (
        call == n and io.AttemptError("AuthenticationError", False, b"{}")
    )


def _client_error_at(n):
    return lambda call, *_: call == n and io.AttemptError("ClientError", False, None)


def test_resumes_never_resend_reset_or_release_before_both_complete(env, capsys):
    plan = [
        (600, _auth_at(10)),
        (590, _client_error_at(50)),
        (540, None),
    ]
    fakes, ledgers, checkpoints, outputs = [], [], [], []
    for cap, fail in plan:
        fake = Fake(fail)
        code, lines = _paid_d(env, capsys, fake, cap)
        fakes.append(fake)
        ledgers.append(_ledger(env))  # persisted state, read back from disk
        checkpoints.append(snapshot(env.run_dir / "checkpoints"))
        outputs.append((code, lines))
    assert [code for code, _ in outputs] == [1, 1, 0]
    assert [len(f.sent) for f in fakes] == [10, 50, 242]
    # Completed checkpoints are never resent: each item's total sends across the
    # three invocations equal its attempts, and nothing done before an invocation is
    # sent in it.
    final = ledgers[-1]
    total = Counter(sent for fake in fakes for sent in fake.sent)
    for config in CONFIGS:
        for index, item in enumerate(final["items"][config]):
            assert total[(config, index)] == item["attempts"]
            assert item["state"] == "done"
    for k in (1, 2):
        done = {
            (c, i)
            for c in CONFIGS
            for i, x in enumerate(ledgers[k - 1]["items"][c])
            if x["state"] == "done"
        }
        assert done and not done & set(fakes[k].sent)
        for name, data in checkpoints[k - 1].items():  # kept byte for byte
            assert checkpoints[k][name] == data
    # Attempts and spending never reset: totals and per-item attempts only grow.
    assert [x["calls_used"] for x in ledgers] == [10, 60, 302]
    for earlier, later in zip(ledgers, ledgers[1:], strict=False):
        for config in CONFIGS:
            for a, b in zip(
                earlier["items"][config], later["items"][config], strict=True
            ):
                assert b["attempts"] >= a["attempts"]
    assert [
        (x["kind"], x["token_max_calls"], x["calls_at_start"], x["calls"])
        for x in final["invocations"]
    ] == [("initial", 600, 0, 10), ("resume", 590, 10, 50), ("resume", 540, 60, 242)]
    assert sum(x["calls"] for x in final["invocations"]) == final["calls_used"]
    errors = Counter()
    for config in CONFIGS:
        errors.update(final["errors_by_class"][config])
    assert errors == {"AuthenticationError": 1, "ClientError": 1}
    # The failures and the resumes are in the evidence log.
    lifecycle = ("initial", "resume", "stop")
    assert [
        (e["event"], e.get("reason")) for e in _evidence(env) if e["event"] in lifecycle
    ] == [
        ("initial", None),
        ("stop", "auth_failure"),
        ("resume", None),
        ("stop", "provider_failure"),
        ("resume", None),
    ]
    # Nothing is released before both configurations are complete.
    for _, lines in outputs[:2]:
        for line in lines:
            assert not _keys(line) & RELEASE_KEYS
    assert outputs[2][1][-1]["release"]["calls_used"] == 302


@pytest.mark.parametrize(
    ("cap", "accepted"),
    [(591, False), (600, False), (590, True), (291, True), (1, True)],
)
def test_a_fresh_grant_is_accepted_only_up_to_the_calls_left(
    env, capsys, cap, accepted
):
    code, _ = _paid_d(env, capsys, Fake(_auth_at(10)), 600)
    assert code == 1 and _ledger(env)["calls_used"] == 10
    code, lines = _guarded_d(env, capsys, "--dry-run", cap=None)
    assert lines[-1]["resumable"] is True and lines[-1]["max_token_calls"] == 590
    if not accepted:
        ledger_before = (env.run_dir / "ledger.json").read_bytes()
        code, lines = _guarded_d(env, capsys, "--approved-provider-disclosure", cap=cap)
        assert code == 1
        assert lines[-1]["reason"] == "the token ceiling exceeds the calls left"
        assert (env.run_dir / "ledger.json").read_bytes() == ledger_before
        return
    fake = Fake()
    code, lines = _paid_d(env, capsys, fake, cap)
    assert len(fake.sent) == min(cap, 291)
    ledger = _ledger(env)
    assert ledger["invocations"][-1]["token_max_calls"] == cap
    assert ledger["invocations"][-1]["calls_at_start"] == 10
    assert ledger["calls_used"] == 10 + len(fake.sent)
    if cap >= 291:
        assert code == 0 and lines[-1]["release"]["calls_used"] == 301
    else:
        assert code == 1 and lines[-1]["stop_reason"] == "token_cap"


def _fail_600(kind):
    def fail(call, *_):
        if call < 600:
            return io.AttemptError("ServerError", True, None)
        if kind == "interrupt":
            raise KeyboardInterrupt
        return io.AttemptError(kind, False, b"{}")

    return fail


@pytest.mark.parametrize("kind", ["AuthenticationError", "ClientError", "interrupt"])
def test_a_failed_or_interrupted_600th_call_leaves_the_run_exhausted_and_final(
    env, capsys, kind
):
    fake = Fake(_fail_600(kind))
    if kind == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            _paid_d(env, capsys, fake, 600)
        lines = _lines(capsys)
    else:
        code, lines = _paid_d(env, capsys, fake, 600)
        assert code == 1 and lines[-1]["status"] == "exhausted"
    assert len(fake.sent) == 600
    ledger = _ledger(env)
    assert ledger["calls_used"] == 600
    assert ledger["status"] == "exhausted"
    assert ledger["stop_reason"] == "budget_exhausted"
    assert _evidence(env)[-1]["status"] == "exhausted"
    for line in lines:
        assert not _keys(line) & RELEASE_KEYS
    code, lines = _guarded_d(env, capsys, "--dry-run", cap=None)
    state = lines[-1]
    assert (state["status"], state["stop_reason"]) == ("exhausted", "budget_exhausted")
    assert state["resumable"] is False and state["max_token_calls"] == 0
    assert state["calls_left"] == 0
    code, lines = _guarded_d(env, capsys, "--approved-provider-disclosure", cap=1)
    assert code == 1 and lines[-1]["reason"] == "the run is final (exhausted)"
    _only_private_checkpoints(env)


@pytest.mark.parametrize("status", ["stopped", "running"])
@pytest.mark.parametrize("reason", ["auth_failure", "provider_failure", None])
def test_a_ledger_with_no_calls_left_is_reported_exhausted(status, reason):
    ledger = driver.new_ledger("0" * 64)
    ledger.update(calls_used=600, status=status, stop_reason=reason)
    for config in CONFIGS:
        for item in ledger["items"][config]:
            item.update(attempts=2, state="retry")
    state = driver.ledger_state(ledger)
    assert (state["status"], state["stop_reason"]) == ("exhausted", "budget_exhausted")
    assert state["resumable"] is False and state["max_token_calls"] == 0


def _only_private_checkpoints(env) -> None:
    """Beyond the invented inputs, only the ledger, the evidence log and response
    checkpoints exist: no prediction, mapping or result file anywhere."""
    original = set(HELDOUT_FILES) | {"predictions-dev-v2-sonnet.json"}
    for path in env.private.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(env.private).as_posix()
        assert (
            relative in original
            or relative
            in {f"{driver.RUN_DIR}/ledger.json", f"{driver.RUN_DIR}/evidence.jsonl"}
            or relative.startswith(f"{driver.RUN_DIR}/checkpoints/")
        ), relative


def _server_error(call, *_):
    return io.AttemptError("ServerError", True, None)


def _failed_requests(_call, config, case):
    # Owner, 2026-11-05, item 2: a third failed request in one configuration.
    return (
        config == "v2"
        and case in (5, 6, 8)
        and io.AttemptError("ServerError", True, None)
    )


STOPS = {
    "auth_failure": (_auth_at(10), 600, "auth_failure"),
    "provider_failure": (_client_error_at(10), 600, "provider_failure"),
    "failed_requests": (_failed_requests, 600, "failed_requests"),
    "budget_exhausted": (_server_error, 600, "budget_exhausted"),
}


@pytest.mark.parametrize("case", sorted(STOPS))
def test_no_stop_path_releases_a_prediction_or_a_score(env, capsys, case):
    fail, cap, reason = STOPS[case]
    before = {name: _sha(env.private / name) for name in HELDOUT_FILES}
    code, lines = _paid_d(env, capsys, Fake(fail), cap)
    assert code == 1 and lines[-1]["stop_reason"] == reason
    assert lines[-1]["released"] is False
    for line in lines:
        assert not _keys(line) & RELEASE_KEYS, line
    _only_private_checkpoints(env)
    assert {name: _sha(env.private / name) for name in HELDOUT_FILES} == before


def test_a_token_cap_stop_and_an_interrupt_release_nothing(env, capsys):
    code, lines = _paid_d(env, capsys, Fake(_auth_at(3)), 600)
    code, lines = _paid_d(env, capsys, Fake(), 4)
    assert code == 1 and lines[-1]["stop_reason"] == "token_cap"
    for line in lines:
        assert not _keys(line) & RELEASE_KEYS
    _only_private_checkpoints(env)


def test_an_interrupt_with_calls_left_is_persisted_and_resumable(env, capsys):
    def fail(call, *_):
        if call == 7:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _paid_d(env, capsys, Fake(fail), 600)
    for line in _lines(capsys):
        assert not _keys(line) & RELEASE_KEYS
    ledger = _ledger(env)
    assert (ledger["status"], ledger["stop_reason"]) == ("stopped", "interrupted")
    assert ledger["calls_used"] == 7
    assert ledger["items"]["v2"][3]["state"] == "in_flight"
    assert _evidence(env)[-1]["reason"] == "interrupted"
    code, lines = _guarded_d(env, capsys, "--dry-run", cap=None)
    # Owner decision 2: resumable once the state validates, capped at the calls left.
    assert lines[-1]["resumable"] is True and lines[-1]["calls_left"] == 593
    assert lines[-1]["max_token_calls"] == 593
    code, lines = _guarded_d(env, capsys, "--approved-provider-disclosure", cap=594)
    assert code == 1
    assert lines[-1]["reason"] == "the token ceiling exceeds the calls left"
    _only_private_checkpoints(env)
