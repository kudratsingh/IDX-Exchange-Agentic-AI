"""WO-026 omission pilot: strata, frozen sampling, review records, aggregates.

Every key, remark and judgment here is invented.
"""

import hashlib
import json
import os
import sqlite3

import pytest
from scripts import omission_pilot as cli

from idx_agent.enrichment import omission_pilot as op
from idx_agent.enrichment.source_check import results_digest

REVIEWER = "model:test-reviewer"


def _rows():
    rows = []
    for n in range(40):
        key = f"9{n:04d}"
        if n % 4 == 0:
            rows.append(
                (key, "Bright home with a two car garage.", {"garage": "present"})
            )
        elif n % 4 == 1:
            rows.append((key, "Garage may be converted.", {"garage": "uncertain"}))
        elif n % 4 == 2:
            rows.append((key, "Detached garage and a patio.", {}))
        else:
            rows.append((key, "Quiet street, lovely trees.", {}))
    return rows


def _judgment(item, decision="correctly_absent", **extra):
    record = {
        "item_id": item["item_id"],
        "facet": item["facet"],
        "stratum": item["stratum"],
        "decision": decision,
        "existing_status_check": "correct"
        if item["stratum"] == "labeled_non_present"
        else "not_applicable",
        "reviewer": REVIEWER,
        "review_type": "model",
        "reviewed_at": "2026-11-02T12:00:00+00:00",
        "guide_version": op.GUIDE_VERSION,
        "human_review": "pending",
    }
    record.update(extra)
    return record


def test_stratum_of_excludes_present_and_splits_unknown_by_cue():
    assert op.stratum_of("garage", "present", "garage") is None
    for status in ("uncertain", "planned", "historical", "stated_absent"):
        assert op.stratum_of("garage", status, "") == "labeled_non_present"
    assert op.stratum_of("garage", "contradictory", "") == "labeled_non_present"
    assert op.stratum_of("garage", None, "Attached 2-car garage") == "cue"
    assert op.stratum_of("garage", None, "Big yard") == "no_cue"
    with pytest.raises(ValueError):
        op.stratum_of("garage", "maybe", "")


@pytest.mark.parametrize(
    ("facet", "hit", "miss"),
    [
        ("near_transit_mentioned", "steps to the light rail", "new porch railing"),
        ("near_grocery_mentioned", "near Trader Joe's", "back on the market"),
        ("single_level", "single-story living", "two story home"),
        ("stainless_appliances", "stainless steel range", "granite counters"),
        ("condominium", "top floor condo", "conditioned air"),
        ("walk_in_closet", "large walk-in closet", "walking trails"),
        ("water_view", "sweeping ocean views", "near the ocean"),
    ],
)
def test_cues_match_the_intended_words(facet, hit, miss):
    assert op.CUES[facet].search(hit)
    assert not op.CUES[facet].search(miss)


def test_every_eligible_facet_has_a_cue_and_allocation():
    assert set(op.CUES) == set(op.ELIGIBLE_FACETS)
    assert op.LIMITED_FACETS <= op.ELIGIBLE_FACETS and len(op.LIMITED_FACETS) == 6
    total = sum(sum(op.allocation(f).values()) for f in op.ELIGIBLE_FACETS)
    assert 120 <= total <= 160
    with pytest.raises(ValueError):
        op.allocation("central_air")


def test_population_excludes_keys_and_rejects_duplicates():
    pop = op.build_population(_rows(), excluded={"90002"})
    garage = {s: pop[("garage", s)] for s in op.STRATA}
    assert len(garage["labeled_non_present"]) == 10
    assert len(garage["cue"]) == 9 and "90002" not in garage["cue"]
    assert len(garage["no_cue"]) == 10
    assert garage["cue"] == sorted(garage["cue"])
    assert op.population_counts(pop)["garage"] == {
        "cue": 9,
        "labeled_non_present": 10,
        "no_cue": 10,
    }
    with pytest.raises(ValueError):
        op.build_population(_rows() + _rows()[:1], ())


def test_sample_is_deterministic_bounded_and_seed_dependent():
    pop = op.build_population(_rows(), ())
    first, again = op.draw_sample(pop, "s1"), op.draw_sample(pop, "s1")
    assert first == again
    garage = [i for i in first if i["facet"] == "garage"]
    by_stratum = {s: [i for i in garage if i["stratum"] == s] for s in op.STRATA}
    assert {s: len(v) for s, v in by_stratum.items()} == op.LIMITED_ALLOCATION
    # Patio is an audited facet: no labeled stratum; the cue stratum is short here.
    patio = [i for i in first if i["facet"] == "patio"]
    assert {i["stratum"] for i in patio} == {"cue", "no_cue"}
    assert [i["item_id"] for i in first] == [
        f"op1-{n:03d}" for n in range(1, len(first) + 1)
    ]
    other = op.draw_sample(pop, "s2")
    assert [i["listing_key"] for i in other] != [i["listing_key"] for i in first]


def test_short_stratum_takes_everything():
    pop = {(f, s): [] for f in op.ELIGIBLE_FACETS for s in op.STRATA}
    pop[("garage", "cue")] = ["90001", "90002"]
    sample = op.draw_sample(pop)
    assert [i["listing_key"] for i in sample] == sorted(
        ["90001", "90002"], key=lambda k: op._rank(op.SEED, "garage", "cue", k)
    )


def test_validate_judgments_accepts_good_records_in_sample_order():
    sample = op.draw_sample(op.build_population(_rows(), ()))
    records = [_judgment(i) for i in reversed(sample)]
    checked = op.validate_judgments(records, sample, "model")
    assert [r["item_id"] for r in checked] == [i["item_id"] for i in sample]


@pytest.mark.parametrize(
    "change",
    [
        {"item_id": "op1-999"},
        {"facet": "pool"},
        {"stratum": "no_cue"},
        {"decision": "maybe"},
        {"reviewer": "someone"},
        {"reviewer": ""},
        {"review_type": "human"},
        {"guide_version": "v0"},
        {"reviewed_at": "yesterday"},
        {"human_review": "confirmed"},
        {"existing_status_check": "not_applicable"},
    ],
)
def test_validate_judgments_refuses_bad_records(change):
    sample = op.draw_sample(op.build_population(_rows(), ()))
    labeled = next(i for i in sample if i["stratum"] == "labeled_non_present")
    with pytest.raises(ValueError):
        op.validate_judgments([_judgment(labeled, **change)], sample, "model")


def test_validate_judgments_refuses_duplicates_and_status_check_on_unlabeled():
    sample = op.draw_sample(op.build_population(_rows(), ()))
    item = next(i for i in sample if i["stratum"] == "cue")
    with pytest.raises(ValueError):
        op.validate_judgments([_judgment(item), _judgment(item)], sample, "model")
    with pytest.raises(ValueError):
        op.validate_judgments(
            [_judgment(item, existing_status_check="correct")], sample, "model"
        )


def test_human_review_cannot_claim_a_model_and_overrides_the_model():
    sample = op.draw_sample(op.build_population(_rows(), ()))
    item = sample[0]
    human = _judgment(
        item,
        "omitted_present",
        reviewer="owner",
        review_type="human",
        human_review="overridden",
    )
    assert op.validate_judgments([human], sample, "human")
    with pytest.raises(ValueError):
        op.validate_judgments([dict(human, reviewer=REVIEWER)], sample, "human")
    merged = op.merge_reviews([_judgment(item)], [human])
    assert merged[item["item_id"]]["decision"] == "omitted_present"


def test_wilson_interval():
    assert op.wilson(0, 0) is None
    low, high = op.wilson(0, 10)
    assert low == 0.0 and high == pytest.approx(0.2775, abs=1e-4)
    low, high = op.wilson(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4)
    assert high == pytest.approx(0.7634, abs=1e-4)


def test_aggregate_weights_strata_and_reports_no_keys():
    pop = op.build_population(_rows(), ())
    sample = op.draw_sample(pop)
    reviews = {}
    for item in sample:
        decision = "omitted_present" if item["stratum"] == "cue" else "correctly_absent"
        reviews[item["item_id"]] = _judgment(item, decision)
    result = op.aggregate(sample, reviews, op.population_counts(pop))
    garage = result["facets"]["garage"]
    assert garage["strata"]["cue"]["omission_rate"] == 1.0
    assert garage["strata"]["no_cue"]["omission_rate"] == 0.0
    # 10 cue listings at rate 1 among 30 covered non-present listings.
    assert garage["weighted_rate_covered"] == pytest.approx(10 / 30)
    assert garage["estimated_omissions_covered"] == 10
    assert garage["uncovered_population"] == 0
    patio = result["facets"]["patio"]
    assert (
        patio["uncovered_population"]
        == patio["strata"]["labeled_non_present"]["population"]
    )
    assert result["groups"]["limited/cue"]["omitted_present"] == 7
    assert result["reviewed"] == len(sample)
    text = json.dumps(result)
    assert not any(key in text for key, _, _ in _rows())


# ---- CLI on an invented private directory ----------------------------------------


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def private_root(tmp_path, monkeypatch):
    root = tmp_path / "enrichment"
    (root / "full").mkdir(parents=True)
    rows = _rows()
    db_path = root / "full" / "active-facets-v2.sqlite3"
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE inputs "
        "(sequence INTEGER, listing_key TEXT, input_hash TEXT, remark TEXT)"
    )
    db.execute(
        "CREATE TABLE results (sequence INTEGER, listing_key TEXT, input_hash TEXT, "
        "facets TEXT, diagnostic_count INTEGER, usage TEXT)"
    )
    db.execute("CREATE TABLE result_origins (sequence INTEGER, extractor TEXT)")
    for seq, (key, remark, _) in enumerate(rows, 1):
        db.execute(
            "INSERT INTO inputs VALUES (?,?,?,?)", (seq, key, _sha(remark), remark)
        )
        db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?,?)",
            (seq, key, _sha(remark), "[]", 0, "{}"),
        )
        db.execute("INSERT INTO result_origins VALUES (?,?)", (seq, "v1"))
    db.commit()
    # The invented source stands in for the approved, frozen results.
    monkeypatch.setattr(cli, "EXPECTED_RESULTS_DIGEST", results_digest(db))
    db.close()
    db_path.chmod(0o600)
    pop = op.build_population(rows, ())
    sample = op.draw_sample(pop)
    status = {k: s for k, _, s in rows}
    for item in sample:
        item["status_at_sampling"] = status[item["listing_key"]].get(item["facet"])
    text = op.canonical_jsonl(sample)
    out = root / op.PILOT_ID
    out.mkdir()
    (out / "sample.jsonl").write_text(text)
    manifest = {
        "sample_sha256": op.sha256_text(text),
        "population_counts": op.population_counts(pop),
    }
    (out / "manifest.json").write_text(json.dumps(manifest))
    return root, sample


def test_cli_packet_record_aggregate(private_root, tmp_path, capsys):
    root, sample = private_root
    cli.main(["--data-root", str(root), "packet"])
    packet = cli.read_jsonl(root / op.PILOT_ID / "packet.jsonl")
    assert [p["item_id"] for p in packet] == [i["item_id"] for i in sample]
    assert all("listing_key" not in p for p in packet)
    garage_cue = next(p for p in packet if p["facet"] == "garage" and p["cue_spans"])
    start, end = garage_cue["cue_spans"][0]
    assert garage_cue["remark"][start:end].lower() == "garage"
    assert (root / op.PILOT_ID / "packet.jsonl").stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        cli.main(["--data-root", str(root), "packet"])

    draft = tmp_path / "draft.jsonl"
    draft.write_text(op.canonical_jsonl(_judgment(i) for i in sample))
    cli.main(
        ["--data-root", str(root), "record", "--draft", str(draft), "--kind", "model"]
    )
    recorded = cli.read_jsonl(root / op.PILOT_ID / "judgments.jsonl")
    assert len(recorded) == len(sample)
    assert {r["human_review"] for r in recorded} == {"pending"}
    capsys.readouterr()
    cli.main(["--data-root", str(root), "aggregate", "--name", "aggregates.json"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["overall"]["correctly_absent"] == len(sample)
    assert printed["reviewed_by"] == {"model": len(sample)}
    assert not any(key in json.dumps(printed) for key, _, _ in _rows())


def test_cli_refuses_a_changed_sample_or_foreign_judgments(private_root, tmp_path):
    root, sample = private_root
    out = root / op.PILOT_ID
    draft = tmp_path / "draft.jsonl"
    draft.write_text(op.canonical_jsonl(_judgment(i) for i in sample))
    cli.main(
        ["--data-root", str(root), "record", "--draft", str(draft), "--kind", "model"]
    )
    forged = [
        dict(r, sample_sha256="0" * 64) for r in cli.read_jsonl(out / "judgments.jsonl")
    ]
    (out / "forged.jsonl").write_text(op.canonical_jsonl(forged))
    with pytest.raises(ValueError):
        cli.main(["--data-root", str(root), "aggregate", "--judgments", "forged.jsonl"])
    with (out / "sample.jsonl").open("a") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError):
        cli.main(["--data-root", str(root), "packet"])


def test_cli_sample_refuses_an_existing_pilot_directory(private_root):
    root, _ = private_root
    with pytest.raises(FileExistsError):
        cli.main(["--data-root", str(root), "sample"])


def test_readonly_refuses_shared_files_and_write_new_never_replaces(tmp_path):
    shared = tmp_path / "shared.sqlite3"
    sqlite3.connect(shared).close()
    shared.chmod(0o644)
    with pytest.raises(ValueError):
        cli.readonly(shared)
    target = tmp_path / "new.txt"
    cli.write_new(target, "a")
    with pytest.raises(FileExistsError):
        cli.write_new(target, "b")
    assert target.read_text() == "a"


def test_excluded_keys_union_benchmark_files_and_diagnostics(tmp_path):
    (tmp_path / "splits.json").write_text(json.dumps({"splits": {"91000": "dev"}}))
    (tmp_path / "sample.jsonl").write_text(json.dumps({"key": "91000"}) + "\n")
    (tmp_path / "deal-signals-supplement.json").write_text(
        json.dumps({"cases": [{"id": "91001"}]})
    )
    (tmp_path / "wo021-spot-check-sample.jsonl").write_text(
        json.dumps({"key": "91002"}) + "\n"
    )
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE results (listing_key TEXT, diagnostic_count INTEGER)")
    db.executemany("INSERT INTO results VALUES (?,?)", [("91003", 1), ("91004", 0)])
    keys, counts = cli.excluded_keys(tmp_path, db)
    assert keys == {"91000", "91001", "91002", "91003"}
    assert counts["diagnostic_471"] == 1 and counts["splits.json"] == 1
    (tmp_path / "splits.json").rename(tmp_path / "moved.json")
    with pytest.raises(FileNotFoundError):
        cli.excluded_keys(tmp_path, db)


# ---- WO-026 review fixes: output confinement and frozen source-text hashes -------


def _listing(directory):
    return sorted(p.name for p in directory.iterdir())


def _packet(root, *extra):
    cli.main(["--data-root", str(root), "packet", *extra])


def test_packet_refuses_an_absolute_output_name(private_root, tmp_path):
    root, _ = private_root
    outside = tmp_path / "outside.jsonl"
    with pytest.raises(ValueError, match="plain file name"):
        _packet(root, "--name", str(outside))
    assert not outside.exists()


@pytest.mark.parametrize("name", ["../escape.jsonl", "../../escape.jsonl", ".."])
def test_packet_refuses_parent_traversal(private_root, tmp_path, name):
    root, _ = private_root
    before = {p for p in tmp_path.rglob("*")}
    with pytest.raises(ValueError, match="plain file name"):
        _packet(root, "--name", name)
    assert {p for p in tmp_path.rglob("*")} == before


@pytest.mark.parametrize("command", ["record", "aggregate"])
def test_record_and_aggregate_refuse_escaping_output_names(
    private_root, tmp_path, command
):
    root, sample = private_root
    draft = tmp_path / "draft.jsonl"
    draft.write_text(op.canonical_jsonl(_judgment(i) for i in sample))
    record = ["--data-root", str(root), "record", "--draft", str(draft)]
    if command == "aggregate":
        cli.main([*record, "--kind", "model"])
    args = {
        "record": [*record, "--kind", "model"],
        "aggregate": ["--data-root", str(root), "aggregate"],
    }[command]
    for name in (str(tmp_path / "abs.jsonl"), "../up.jsonl"):
        with pytest.raises(ValueError, match="plain file name"):
            cli.main([*args, "--name", name])
    assert not (tmp_path / "abs.jsonl").exists()
    assert not (root / "up.jsonl").exists()


def test_packet_refuses_a_symlinked_pilot_directory(private_root, tmp_path):
    root, _ = private_root
    real = root / op.PILOT_ID
    outside = tmp_path / "elsewhere"
    real.rename(outside)
    (root / op.PILOT_ID).symlink_to(outside, target_is_directory=True)
    before = _listing(outside)
    with pytest.raises(ValueError, match="real directory"):
        _packet(root)
    assert _listing(outside) == before


def test_packet_refuses_a_symlinked_intermediate_directory(private_root, tmp_path):
    root, _ = private_root
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / op.PILOT_ID / "sub").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="plain file name"):
        _packet(root, "--name", "sub/packet.jsonl")
    assert _listing(outside) == []


@pytest.mark.parametrize("existing", [False, True])
def test_packet_refuses_a_destination_symlink_pointing_outside(
    private_root, tmp_path, existing
):
    root, _ = private_root
    target = tmp_path / "target.jsonl"
    if existing:
        target.write_text("kept\n")
    (root / op.PILOT_ID / "packet.jsonl").symlink_to(target)
    with pytest.raises((ValueError, FileExistsError)):
        _packet(root)
    assert target.exists() == existing
    if existing:
        assert target.read_text() == "kept\n"


def test_write_new_does_not_follow_a_final_symlink(tmp_path):
    target = tmp_path / "target.txt"
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        cli.write_new(link, "x")
    assert not target.exists()


def test_a_legitimate_output_name_still_works(private_root):
    root, sample = private_root
    _packet(root, "--name", "packet-human.jsonl")
    path = root / op.PILOT_ID / "packet-human.jsonl"
    assert len(cli.read_jsonl(path)) == len(sample)
    assert not path.is_symlink() and path.stat().st_mode & 0o077 == 0


def _source(root):
    return sqlite3.connect(root / "full" / "active-facets-v2.sqlite3")


def test_packet_refuses_changed_source_text_and_writes_nothing(private_root, capsys):
    root, sample = private_root
    item = sample[2]
    db = _source(root)
    db.execute(
        "UPDATE inputs SET remark = 'Invented replacement text.' WHERE listing_key = ?",
        (item["listing_key"],),
    )
    db.commit()
    db.close()
    before = _listing(root / op.PILOT_ID)
    with pytest.raises(ValueError, match="source text") as refused:
        _packet(root)
    assert item["item_id"] in str(refused.value)
    assert "Invented replacement" not in str(refused.value)
    assert item["listing_key"] not in str(refused.value)
    assert _listing(root / op.PILOT_ID) == before
    assert capsys.readouterr().out == ""


def test_packet_refuses_missing_source_text_and_writes_nothing(private_root):
    root, sample = private_root
    item = sample[0]
    db = _source(root)
    db.execute("DELETE FROM inputs WHERE listing_key = ?", (item["listing_key"],))
    db.commit()
    db.close()
    before = _listing(root / op.PILOT_ID)
    with pytest.raises(ValueError, match="source text") as refused:
        _packet(root)
    assert item["item_id"] in str(refused.value)
    assert _listing(root / op.PILOT_ID) == before


def test_packet_refuses_rehashed_source_text_against_the_frozen_digest(private_root):
    root, sample = private_root
    item = sample[1]
    changed = "Invented rewritten text with matching hashes."
    db = _source(root)
    for table in ("inputs", "results"):
        db.execute(
            f"UPDATE {table} SET input_hash = ? WHERE listing_key = ?",
            (_sha(changed), item["listing_key"]),
        )
    db.execute(
        "UPDATE inputs SET remark = ? WHERE listing_key = ?",
        (changed, item["listing_key"]),
    )
    db.commit()
    db.close()
    before = _listing(root / op.PILOT_ID)
    with pytest.raises(ValueError, match="approved digest"):
        _packet(root)
    assert _listing(root / op.PILOT_ID) == before


def test_packet_with_unchanged_source_text_matches_the_frozen_hashes(private_root):
    root, sample = private_root
    _packet(root)
    packet = cli.read_jsonl(root / op.PILOT_ID / "packet.jsonl")
    remarks = {k: r for k, r, _ in _rows()}
    assert [p["remark"] for p in packet] == [remarks[i["listing_key"]] for i in sample]
    assert os.stat(root / op.PILOT_ID / "packet.jsonl").st_mode & 0o077 == 0
