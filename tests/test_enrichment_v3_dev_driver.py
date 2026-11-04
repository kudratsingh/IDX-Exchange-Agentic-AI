"""WO-034 Phase B: the Phase C dev runner and the mapped comparator, synthetic only.

A fake transport replaces the standard Messages API request; the network is
blocked, no key is read and no provider client exists."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from scripts import enrichment_v3_io as io
from scripts import extract_enrichment_v3_dev as driver
from tests.enrichment_v3_synthetic import block_network, make_private, response_for
from tests.paid_token import grant_paid, run_as, token_state

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
GOLD = "labels-v5.json"
COMMAND = "python scripts/extract_enrichment_v3_dev.py --invented-phase-c"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def private(tmp_path, monkeypatch):
    block_network(monkeypatch)
    path = make_private(tmp_path)
    monkeypatch.setattr(
        driver, "V2_PREDICTIONS_SHA256", _sha(path / driver.V2_PREDICTIONS)
    )
    monkeypatch.setattr(io, "read_key", lambda: "invented-key")
    monkeypatch.setattr(io.time, "sleep", lambda _seconds: None)
    return path


def _args(private: Path, *extra: str, gold: str = GOLD) -> list[str]:
    digest = _sha(private / gold) if (private / gold).exists() else "0" * 64
    return [
        "--gold",
        gold,
        "--gold-sha256",
        digest,
        "--private-dir",
        str(private),
        *extra,
    ]


def _last(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


class Fake:
    """Counts requests; optional failures by call number."""

    def __init__(self, failures=None, response=response_for):
        self.calls, self.failures, self.response = 0, failures or {}, response

    def __call__(self, body, key):
        assert key == "invented-key"
        self.calls += 1
        if self.calls in self.failures:
            raise self.failures[self.calls]
        return self.response(body)


def test_pins_match_the_tracked_files():
    for relative, expected in driver.PINNED.items():
        assert _sha(ROOT / relative) == expected, relative
    driver.verify_pins(ROOT)


def test_v1_v2_and_v21_freeze_and_scorer_files_are_unchanged():
    from scripts import extract_enrichment_test as v1
    from scripts import extract_enrichment_v2_dev as v2_dev
    from scripts import extract_enrichment_v21_dev as v21

    for relative, expected in v1.HASHES.items():
        assert _sha(ROOT / relative) == expected
    assert _sha(ROOT / "docs/ENRICHMENT_EXTRACTION_V2.md") == v2_dev.PROMPT_HASH
    assert _sha(ROOT / "docs/ENRICHMENT_V21_FREEZE.json") == v21.MANIFEST_HASH
    v21.verify_v21_freeze()


def test_driver_imports_no_provider_client():
    for name in ("scripts/extract_enrichment_v3_dev.py", "scripts/enrichment_v3_io.py"):
        tree = ast.parse((ROOT / name).read_text())
        modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(
            m.split(".")[0] in {"anthropic", "httpx", "requests"} for m in modules
        )


def test_comparator_maps_saved_v2_predictions_and_scores_against_revised_gold(
    private, capsys
):
    assert driver.main(_args(private, "--comparator")) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["mode"] == "comparator"
    assert report["comparator"]["overall"][3] == 1.0
    assert report["reference_unmapped_overall"][3] < 1.0
    assert report["removed_by_polarity"]["affirmed"] > 0
    assert report["removed_by_polarity"]["negated"] > 0
    assert report["gold_sha256"] == _sha(private / GOLD)
    assert set(report["comparator"]) == {"overall"} | {
        f"facet.{name}" for name in driver.v3.FACET_MAP
    }
    assert "Invented home" not in out and "attached garage" not in out


@pytest.mark.parametrize("mode", ["--comparator", "--dry-run"])
def test_original_labels_missing_gold_and_wrong_hash_are_refused(
    private, capsys, monkeypatch, mode
):
    assert driver.main(_args(private, mode, gold="labels.json")) == 1
    assert "not labels.json" in _last(capsys)["reason"]
    assert driver.main(_args(private, mode, gold="labels-missing.json")) == 1
    assert _last(capsys)["status"] == "refused"
    wrong = _args(private, mode)
    wrong[3] = "f" * 64
    assert driver.main(wrong) == 1
    assert _last(capsys)["reason"] == "revised gold hash mismatch"
    # A renamed copy of the original gold is refused by its hash.
    shutil.copyfile(private / "labels.json", private / "labels-copy.json")
    monkeypatch.setattr(io, "ORIGINAL_GOLD_SHA256", _sha(private / "labels.json"))
    assert driver.main(_args(private, mode, gold="labels-copy.json")) == 1
    assert _last(capsys)["reason"] == "the gold file is the original labels.json"


def test_a_gold_that_contradicts_the_subtype_fails_the_consistency_check(
    private, capsys
):
    shutil.copyfile(private / "labels.json", private / "labels-unrelabelled.json")
    assert (
        driver.main(_args(private, "--comparator", gold="labels-unrelabelled.json"))
        == 1
    )
    assert "contradicts subtype" in _last(capsys)["reason"]


def test_dry_run_checks_everything_with_no_key_token_network_or_write(
    private, capsys, monkeypatch
):
    run_as(COMMAND + " --dry-run")
    grant_paid(COMMAND, 300)
    monkeypatch.setattr(io, "read_key", lambda: pytest.fail("key read"))
    before = sorted(p.name for p in private.rglob("*"))
    assert driver.main(_args(private, "--dry-run")) == 0
    report = _last(capsys)
    assert report["mode"] == "dry_run" and report["cases"] == 100
    assert report["paid_ceiling"] == 300 and report["requests_made"] == 0
    assert report["paid_command"] == COMMAND
    assert sorted(p.name for p in private.rglob("*")) == before
    assert token_state() == "valid" and consent.active_budget() is None


def _paid(private, monkeypatch, fake, max_calls=300):
    command = COMMAND
    run_as(command)
    grant_paid(command, max_calls)
    monkeypatch.setattr(io, "attempt", fake)
    return _args(private, "--approved-provider-disclosure")


def test_paid_run_spends_one_call_per_attempt_and_writes_private_outputs(
    private, capsys, monkeypatch
):
    fake = Fake()
    assert driver.main(_paid(private, monkeypatch, fake)) == 0
    report = _last(capsys)
    assert fake.calls == 100 == report["requests_made"]
    assert consent.active_budget().calls_made == 100
    assert report["phase_c_clears"] is True
    assert report["metrics"]["overall"]["f1"] == 1.0
    assert report["removed_by_polarity"]["v3"] == report["removed_by_polarity"]["v2"]
    # Removed raw claims have no revised gold span, so only matched decisions pass.
    assert report["span_quality"]["matched"]["rate"] == 1.0
    assert report["span_quality"]["all"]["rate"] < 1.0
    assert report["usage"]["per_remark"]["cache_read_input_tokens"] == 100
    assert report["remarks_with_misses"] == 0
    for name in (driver.OUTPUT, driver.MAPPING, driver.USAGE):
        assert (private / name).stat().st_mode & 0o777 == 0o600
    journal = private.joinpath(*driver.JOURNAL)
    assert len(list(journal.iterdir())) == 100 and journal.stat().st_mode & 0o077 == 0
    mapping = json.loads((private / driver.MAPPING).read_text())
    flagged = [c for c in mapping["cases"].values() if c["flag"]]
    assert flagged and all("quote" not in r for c in flagged for r in c["removed"])
    raw = json.loads((private / driver.OUTPUT).read_text())
    condo = sum(
        a["value"] == "condominium" for row in raw["labels"] for a in row["annotations"]
    )
    assert condo > sum(len(c["removed"]) for c in flagged) > 0  # raw claims kept
    assert "anthropic" not in sys.modules


def test_retries_draw_one_call_each_under_the_v21_gate(private, capsys, monkeypatch):
    fake = Fake(
        {
            1: io.AttemptError("ServerError", True, None),
            5: io.AttemptError("RateLimitError", True, b"{}"),
        }
    )
    assert driver.main(_paid(private, monkeypatch, fake)) == 0
    report = _last(capsys)
    assert fake.calls == 102 == report["requests_made"]
    assert report["retries_by_error_class"] == {"ServerError": 1, "RateLimitError": 1}


def test_three_failed_attempts_stop_the_run_with_nothing_scored(
    private, capsys, monkeypatch
):
    error = io.AttemptError("ServerError", True, None)
    fake = Fake({1: error, 2: error, 3: error})
    assert driver.main(_paid(private, monkeypatch, fake)) == 1
    report = _last(capsys)
    assert report["status"] == "stopped" and report["requests_made"] == 3
    assert not (private / driver.OUTPUT).exists()
    assert not (private / driver.USAGE).exists()


def test_auth_failure_stops_at_once(private, capsys, monkeypatch):
    fake = Fake({1: io.AttemptError("AuthenticationError", False, b"{}")})
    assert driver.main(_paid(private, monkeypatch, fake)) == 1
    assert _last(capsys)["requests_made"] == 1 and fake.calls == 1


@pytest.mark.parametrize("max_calls", [299, 301, 600])
def test_a_token_ceiling_other_than_300_is_refused_before_any_call(
    private, capsys, monkeypatch, max_calls
):
    fake = Fake()
    assert driver.main(_paid(private, monkeypatch, fake, max_calls)) == 1
    assert fake.calls == 0 and _last(capsys)["requests_made"] == 0


def test_the_hard_ceiling_stops_the_loop(private, capsys, monkeypatch):
    monkeypatch.setattr(driver, "CEILING", 2)
    fake = Fake()
    assert driver.main(_paid(private, monkeypatch, fake, 2)) == 1
    report = _last(capsys)
    assert fake.calls == 2 and report["reason"] == "Phase C ceiling reached"


def test_without_a_token_nothing_is_sent(private, capsys, monkeypatch):
    run_as(COMMAND)
    fake = Fake()
    monkeypatch.setattr(io, "attempt", fake)
    assert driver.main(_args(private, "--approved-provider-disclosure")) == 1
    assert fake.calls == 0 and _last(capsys)["requests_made"] == 0


def test_validation_misses_are_counted_and_sanitized(private, capsys, monkeypatch):
    def response(body):
        if "home 4:" in json.loads(body["messages"][0]["content"])["remark"]:
            return b'{"content": [], "usage": {}}'
        return response_for(body)

    assert driver.main(_paid(private, monkeypatch, Fake(response=response))) == 0
    out = capsys.readouterr().out
    report = json.loads(out.strip().splitlines()[-1])
    assert report["remarks_with_misses"] == 1 and report["no_tool_calls"] == 1
    assert report["usage"]["totals"]["input_tokens"] is None
    assert '"rule": "no_extraction_tool_call"' in out and "Invented home" not in out


@pytest.mark.parametrize(
    "relative",
    [
        "src/idx_agent/enrichment/v3.py",
        "scripts/enrichment_v3_io.py",
        "src/idx_agent/enrichment/v2.py",
        "docs/ENRICHMENT_EXTRACTION_V3.md",
        "docs/ENRICHMENT_V3_FREEZE.json",
    ],
)
def test_a_mutated_implementation_or_contract_stops_before_a_token(
    private, tmp_path, capsys, monkeypatch, relative
):
    root = tmp_path / "repo"
    for name in [*driver.PINNED, driver.v3.FREEZE_FILE, driver.v3.CONTRACT_DOC]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, root / name)
    target = root / relative
    text = target.read_text()
    marker = "at most 80 characters" if relative.endswith("V3.md") else None
    target.write_text(
        text.replace(marker, "at most 81 characters") if marker else text + "\n"
    )
    monkeypatch.setattr(driver, "ROOT", root)
    fake = Fake()
    args = _paid(private, monkeypatch, fake)
    assert driver.main(args) == 1
    assert fake.calls == 0 and _last(capsys)["requests_made"] == 0
    assert token_state() == "valid"
