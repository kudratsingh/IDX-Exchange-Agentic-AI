"""WO-034 owner decision 1 (2026-11-04): the held-out exclusion in Phase D, on
invented files only.

All 150 held-out cases are still requested by both configurations. The primary
verdict (micro F1 against production v2, the per-facet support and F1 rule, the
not-evaluable rule) is computed on the cases not in the sealed exclusion file; the
full-150 score is a diagnostic from the same outputs; both are released only after
both configurations complete. The exclusion file is sealed by path and SHA-256, and a
missing or changed file refuses before a token. The excluded case here is invented."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import enrichment_v3_io as io
from scripts import extract_enrichment_v3_heldout as driver
from tests.enrichment_v3_synthetic import (
    DEV,
    EXCLUDED_TEST_INDEX,
    TEST,
    block_network,
    case_id,
    exclusions,
    make_private,
    remark_of,
    response_for,
)
from tests.paid_token import grant_paid, run_as, token_state

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
GOLD = "labels-v5.json"
EXCLUDED_ID = case_id(DEV + EXCLUDED_TEST_INDEX)
GARAGE = "facet.exterior_lot.garage"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _seal(env) -> None:
    _write_json(env.root / driver.LOCK, driver.build_lock(env.root))
    _write_json(
        env.root / driver.FREEZE, driver.build_seal(env.root, env.private, GOLD)
    )
    env.seal = _sha(env.root / driver.FREEZE)
    env.command = driver.COMMAND.format(seal=env.seal)


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
        root=root,
        private=private,
        monkeypatch=monkeypatch,
        run_dir=private / driver.RUN_DIR,
    )
    _seal(value)
    return value


def _no_decisions() -> bytes:
    """A well-formed v3 tool call that records nothing (a v3 miss on that case)."""
    return json.dumps(
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "record_facet_decisions",
                    "input": {"decisions": []},
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
    ).encode("utf-8")


class Fake:
    """Answers every request; v3 records nothing on the cases in `v3_misses`."""

    def __init__(self, v3_misses=()):
        self.sent, self.v3_misses = [], set(v3_misses)

    def __call__(self, body, key):
        assert key == "invented-key"
        config = "v3" if body["tools"][0]["name"] == "record_facet_decisions" else "v2"
        case = int(remark_of(body).split()[2].rstrip(":")) - DEV
        self.sent.append((config, case))
        if config == "v3" and case in self.v3_misses:
            return _no_decisions()
        return response_for(body)


def _invoke(env, capsys, fake, cap=600, *, dry_run=False):
    run_as(env.command + (" --dry-run" if dry_run else ""))
    if cap is not None:
        grant_paid(env.command, cap)
    env.monkeypatch.setattr(driver, "transport", fake)
    capsys.readouterr()
    mode = "--dry-run" if dry_run else "--approved-provider-disclosure"
    try:
        code = driver.main(
            ["--seal-sha256", env.seal, "--private-dir", str(env.private), mode]
        )
    finally:
        consent.reset_for_tests()
    out = capsys.readouterr().out
    return code, [json.loads(x) for x in out.strip().splitlines()], out


def test_the_seal_records_the_exclusion_by_path_hash_and_counts_only(env):
    text = (env.root / driver.FREEZE).read_text()
    entry = json.loads(text)["private_files"]["exclusions"]
    assert entry == {
        "file": "v3-heldout-exclusions-v1.json",
        "sha256": _sha(env.private / driver.EXCLUSIONS),
        "excluded": 1,
        "primary_n": 149,
        "diagnostic_n": 150,
    }
    assert f'"{EXCLUDED_ID}"' not in text  # the seal never holds a case id


def test_all_150_are_requested_and_the_primary_verdict_uses_the_other_149(env, capsys):
    # v3 misses only on the excluded case: the primary passes, the diagnostic shows
    # the miss, and the diagnostic does not decide.
    fake = Fake(v3_misses={EXCLUDED_TEST_INDEX})
    code, lines, out = _invoke(env, capsys, fake)
    assert code == 0 and len(fake.sent) == 300
    assert ("v2", EXCLUDED_TEST_INDEX) in fake.sent
    assert ("v3", EXCLUDED_TEST_INDEX) in fake.sent
    for line in lines[:-1]:  # nothing scored is printed before the release
        assert set(line) == {"calls_used", "calls_left", "complete"}
    release = lines[-1]["release"]
    assert release["population"] == {
        "requested_per_configuration": 150,
        "primary_n": 149,
        "diagnostic_n": 150,
        "excluded": 1,
        "exclusions_sha256": _sha(env.private / driver.EXCLUSIONS),
    }
    verdict = release["verdict"]
    assert verdict["pass"] is True
    assert verdict["micro"] == {"v3_f1": 1.0, "v2_f1": 1.0, "v3_meets_v2": True}
    assert verdict["facets"][GARAGE] == {"support": 149, "f1": 1.0, "status": "meets"}
    diagnostic = release["diagnostic_full_150"]
    assert "pass" not in diagnostic
    assert diagnostic["note"].startswith("owner decision 1")
    assert diagnostic["micro"]["v2_f1"] == 1.0
    assert diagnostic["micro"]["v3_f1"] < 1.0 and not diagnostic["micro"]["v3_meets_v2"]
    assert diagnostic["facets"][GARAGE]["support"] == 150
    v3_report = release["configurations"]["v3"]
    assert (
        v3_report["metrics"]["overall"]["expected"] + 1
        <= (v3_report["diagnostic_metrics"]["overall"]["expected"])
    )
    assert v3_report["usage"]["per_remark"]["output_tokens"] == 20
    assert (
        release["v1_reference"]["diagnostic_metrics"]["overall"]["expected"]
        == (
            release["configurations"]["v2"]["diagnostic_metrics"]["overall"]["expected"]
        )
    )
    stored = json.loads((env.run_dir / "result.json").read_text())
    assert stored == release
    assert f'"{EXCLUDED_ID}"' not in out  # no case id is ever printed
    assert token_state() != "valid"  # the one token was spent on this run


def test_a_miss_outside_the_exclusion_decides_the_primary_verdict(env, capsys):
    fake = Fake(v3_misses={EXCLUDED_TEST_INDEX + 1})
    code, lines, _ = _invoke(env, capsys, fake)
    release = lines[-1]["release"]
    assert release["verdict"]["pass"] is False
    assert release["verdict"]["micro"]["v3_f1"] < release["verdict"]["micro"]["v2_f1"]
    assert release["diagnostic_full_150"]["micro"]["v3_meets_v2"] is False


def _missing(env):
    (env.private / driver.EXCLUSIONS).unlink()


def _changed(env):
    path = env.private / driver.EXCLUSIONS
    _write_json(path, exclusions([case_id(DEV + 8)]))


def _unrecorded(env):
    path = env.root / driver.FREEZE
    seal = json.loads(path.read_text())
    del seal["private_files"]["exclusions"]
    _write_json(path, seal)
    env.seal = _sha(path)
    env.command = driver.COMMAND.format(seal=env.seal)


REFUSALS = {
    "missing": (_missing, "the held-out exclusion file is missing"),
    "changed": (_changed, "held-out exclusion hash mismatch"),
    "not in the seal": (_unrecorded, "the seal does not record the held-out exclusion"),
}


@pytest.mark.parametrize("dry_run", [False, True], ids=["paid", "dry_run"])
@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_a_missing_changed_or_unsealed_exclusion_refuses_before_a_token(
    env, capsys, case, dry_run
):
    change, reason = REFUSALS[case]
    change(env)
    env.monkeypatch.setattr(io, "read_key", lambda: pytest.fail("key read"))
    fake = Fake()
    code, lines, _ = _invoke(env, capsys, fake, dry_run=dry_run)
    assert code == 1 and fake.sent == [] and token_state() == "valid"
    assert lines[-1]["status"] == "refused" and lines[-1]["reason"] == reason
    assert not env.run_dir.exists()


def _sealable(env, value: dict) -> None:
    path = env.private / driver.EXCLUSIONS
    _write_json(path, value)
    env.monkeypatch.setattr(driver, "EXCLUSIONS_SHA256", _sha(path))


INVALID = {
    "a dev case": lambda: exclusions([case_id(3)]),
    "an unknown case": lambda: exclusions(["9999999"]),
    "a duplicate": lambda: {
        **exclusions([EXCLUDED_ID, EXCLUDED_ID]),
        "primary_n": TEST - 1,
    },
    "no case": lambda: exclusions([]),
    "a wrong primary count": lambda: {**exclusions([EXCLUDED_ID]), "primary_n": 150},
    "a wrong diagnostic count": lambda: {
        **exclusions([EXCLUDED_ID]),
        "diagnostic_n": 149,
    },
    "another split": lambda: {**exclusions([EXCLUDED_ID]), "split": "dev"},
    "an extra field": lambda: {**exclusions([EXCLUDED_ID]), "note": "invented"},
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_an_invalid_exclusion_cannot_be_sealed(env, case):
    _sealable(env, INVALID[case]())
    with pytest.raises(driver.v3.ContractError) as raised:
        driver.build_seal(env.root, env.private, GOLD)
    assert str(raised.value) == "invalid held-out exclusion"
    assert EXCLUDED_ID not in str(raised.value)


def test_only_the_frozen_exclusion_file_can_be_sealed(env):
    env.monkeypatch.setattr(driver, "EXCLUSIONS_SHA256", "0" * 64)
    with pytest.raises(driver.v3.ContractError, match="not the frozen file"):
        driver.build_seal(env.root, env.private, GOLD)


def test_the_tracked_pin_is_the_owner_recorded_exclusion_hash():
    assert driver.EXCLUSIONS == "v3-heldout-exclusions-v1.json"
    recorded = "2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0"
    assert driver.EXCLUSIONS_SHA256 == recorded
    doc = (ROOT / "docs/ENRICHMENT_EXTRACTION_V3.md").read_text(encoding="utf-8")
    assert recorded in doc
