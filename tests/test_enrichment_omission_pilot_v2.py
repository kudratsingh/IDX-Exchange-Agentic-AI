"""WO-033 omission pilot v2: weighted allocation, v1 exclusion, frozen provenance.

Every key, remark, label and judgment here is invented.
"""

import hashlib
import json
import sqlite3

import pytest
from scripts import omission_pilot as cli

from idx_agent.enrichment import effective_store
from idx_agent.enrichment import omission_pilot as op
from idx_agent.enrichment.source_check import results_digest

V2 = op.DESIGNS["v2"]
FACETS = sorted(op.ELIGIBLE_FACETS)


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _full_population(per_stratum=500):
    """Every (facet, stratum) with more invented keys than any target."""
    return {
        (f, s): [f"8{n:05d}" for n in range(per_stratum)]
        for f in FACETS
        for s in op.STRATA
    }


# ---- allocation ------------------------------------------------------------------


def test_v2_allocation_is_exactly_400_split_60_30_10():
    alloc = op.v2_allocation()
    totals = {s: sum(alloc[f][s] for f in FACETS) for s in op.STRATA}
    assert totals == {"no_cue": 240, "cue": 120, "labeled_non_present": 40}
    assert sum(totals.values()) == 400
    assert V2.allocation == alloc


@pytest.mark.parametrize(
    ("facet", "expected"),
    [
        # limited and an owner-named v1 omission facet: weight 3
        (
            "near_grocery_mentioned",
            {"labeled_non_present": 10, "cue": 12, "no_cue": 24},
        ),
        # limited: weight 2, labeled stratum sampled
        ("garage", {"labeled_non_present": 6, "cue": 8, "no_cue": 16}),
        ("condominium", {"labeled_non_present": 6, "cue": 8, "no_cue": 16}),
        # owner-named v1 omission facet, audited: weight 2, no labeled stratum
        ("bonus_room", {"labeled_non_present": 0, "cue": 8, "no_cue": 16}),
        ("clubhouse", {"labeled_non_present": 0, "cue": 8, "no_cue": 16}),
        ("open_plan", {"labeled_non_present": 0, "cue": 8, "no_cue": 16}),
        # neither: weight 1
        ("patio", {"labeled_non_present": 0, "cue": 4, "no_cue": 8}),
        ("solar", {"labeled_non_present": 0, "cue": 4, "no_cue": 8}),
    ],
)
def test_v2_allocation_per_facet(facet, expected):
    assert op.v2_allocation()[facet] == expected


def test_v2_weights_oversample_limited_and_v1_omission_facets():
    weights = {f: op.v2_weight(f) for f in FACETS}
    assert weights["near_grocery_mentioned"] == 3
    for facet in op.LIMITED_FACETS - {"near_grocery_mentioned"}:
        assert weights[facet] == 2
    for facet in op.V1_OMISSION_FACETS - op.LIMITED_FACETS:
        assert weights[facet] == 2
    base = set(FACETS) - op.LIMITED_FACETS - op.V1_OMISSION_FACETS
    assert len(base) == 11 and {weights[f] for f in base} == {1}
    alloc = op.v2_allocation()
    for stratum in ("cue", "no_cue"):
        for facet in FACETS:
            assert alloc[facet][stratum] == weights[facet] * alloc["patio"][stratum]
    labeled = {f for f in FACETS if alloc[f]["labeled_non_present"]}
    assert labeled == set(op.LIMITED_FACETS)
    with pytest.raises(ValueError):
        op.v2_weight("central_air")


def test_apportion_uses_largest_remainder_with_name_ties():
    assert op.apportion(10, {"a": 1, "b": 1, "c": 1}) == {"a": 4, "b": 3, "c": 3}
    assert op.apportion(7, {"x": 3, "y": 1}) == {"x": 5, "y": 2}
    assert op.apportion(0, {"a": 2}) == {"a": 0}
    parts = op.apportion(40, {f"f{n}": 2 + (n == 5) for n in range(6)})
    assert sum(parts.values()) == 40 and parts["f5"] == 10
    for bad in ({}, {"a": 0}, {"a": -1}):
        with pytest.raises(ValueError):
            op.apportion(5, bad)
    with pytest.raises(ValueError):
        op.apportion(-1, {"a": 1})


def test_v1_design_is_unchanged():
    v1 = op.DESIGNS["v1"]
    assert v1.pilot_id == op.PILOT_ID and v1.item_prefix == "op1"
    assert v1.seed == op.SEED and v1.guide_version == op.GUIDE_VERSION
    assert v1.allocation == {f: op.allocation(f) for f in FACETS}
    assert not v1.excludes_v1_items
    pop = _full_population(30)
    assert op.draw_sample(pop, v1.seed, v1.allocation, "op1") == op.draw_sample(pop)
    assert sum(sum(c.values()) for c in v1.allocation.values()) == 142


# ---- drawing ---------------------------------------------------------------------


def test_v2_draw_meets_every_target_exactly_and_is_deterministic():
    pop = _full_population()
    first = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    again = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    assert first == again and len(first) == 400
    counts = op.sample_counts(first)
    assert counts["by_stratum"] == op.V2_STRATUM_TOTALS
    for facet in FACETS:
        assert counts["by_facet"][facet] == V2.allocation[facet]
    assert [i["item_id"] for i in first] == [f"op2-{n:03d}" for n in range(1, 401)]
    other = op.draw_sample(pop, "wo033-other-seed", V2.allocation, V2.item_prefix)
    assert [i["listing_key"] for i in other] != [i["listing_key"] for i in first]
    # Within a stratum, the smallest seeded ranks are taken.
    garage_cue = [
        i["listing_key"]
        for i in first
        if (i["facet"], i["stratum"]) == ("garage", "cue")
    ]
    ranked = sorted(
        pop[("garage", "cue")], key=lambda k: op._rank(V2.seed, "garage", "cue", k)
    )
    assert garage_cue == ranked[:8]


def test_v2_short_stratum_gives_everything_and_records_the_shortfall():
    pop = _full_population()
    pop[("clubhouse", "cue")] = ["80001", "80002", "80003"]
    sample = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    counts = op.sample_counts(sample)
    assert counts["by_facet"]["clubhouse"]["cue"] == 3
    assert counts["by_stratum"]["cue"] == 120 - 5
    assert len(sample) == 395


def test_population_excludes_v1_items_only_for_their_facet():
    rows = [
        ("70001", "Detached garage and a patio.", {}),
        ("70002", "Detached garage and a patio.", {}),
        ("70003", "Quiet street.", {"garage": "uncertain"}),
    ]
    pop = op.build_population(
        rows, excluded={"70002"}, excluded_items=[("70001", "garage")]
    )
    assert pop[("garage", "cue")] == []
    assert pop[("patio", "cue")] == ["70001"]
    assert pop[("garage", "labeled_non_present")] == ["70003"]
    assert all("70002" not in keys for keys in pop.values())
    # Without the item exclusion the pair is back.
    assert op.build_population(rows, {"70002"})[("garage", "cue")] == ["70001"]


def test_sample_counts_and_aggregate_carry_the_v2_pilot_id():
    pop = _full_population(20)
    sample = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    reviews = {
        i["item_id"]: {
            "decision": "correctly_absent",
            "review_type": "model",
            "existing_status_check": "correct",
        }
        for i in sample
    }
    result = op.aggregate(sample, reviews, op.population_counts(pop), V2.pilot_id)
    assert result["pilot_id"] == "omission-pilot-v2"
    assert result["items"] == len(sample) == result["reviewed"]
    text = json.dumps(result)
    assert not any(f'"{k}"' in text for k in pop[("garage", "cue")])


def test_v2_judgments_need_the_v2_guide_version():
    sample = op.draw_sample(_full_population(5), V2.seed, V2.allocation, "op2")
    item = next(i for i in sample if i["stratum"] == "cue")
    record = {
        "item_id": item["item_id"],
        "facet": item["facet"],
        "stratum": item["stratum"],
        "decision": "correctly_absent",
        "existing_status_check": "not_applicable",
        "reviewer": "model:test-reviewer",
        "review_type": "model",
        "reviewed_at": "2026-11-03T12:00:00+00:00",
        "guide_version": op.GUIDE_VERSION_V2,
        "human_review": "pending",
    }
    assert op.validate_judgments([record], sample, "model", V2.guide_version)
    with pytest.raises(ValueError, match="guide version"):
        op.validate_judgments(
            [dict(record, guide_version=op.GUIDE_VERSION)],
            sample,
            "model",
            V2.guide_version,
        )


# ---- CLI sample on an invented private directory ---------------------------------


def _rows():
    rows = []
    for n in range(60):
        key = f"6{n:04d}"
        kind = n % 5
        if kind == 0:
            rows.append((key, "Two car garage, bonus room.", {"garage": "present"}))
        elif kind == 1:
            rows.append((key, "Garage may be converted.", {"garage": "uncertain"}))
        elif kind == 2:
            rows.append((key, "Detached garage, patio, near Trader Joe's.", {}))
        elif kind == 3:
            rows.append((key, "Quiet street, lovely trees.", {}))
        else:
            rows.append((key, "Corner lot.", {"near_grocery_mentioned": "uncertain"}))
    return rows


def _write_jsonl(path, records):
    path.write_text(op.canonical_jsonl(records))


@pytest.fixture
def v2_root(tmp_path, monkeypatch):
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
        diagnostic = 1 if key == "60059" else 0
        db.execute(
            "INSERT INTO inputs VALUES (?,?,?,?)", (seq, key, _sha(remark), remark)
        )
        db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?,?)",
            (seq, key, _sha(remark), "[]", diagnostic, "{}"),
        )
        db.execute("INSERT INTO result_origins VALUES (?,?)", (seq, "v1"))
    db.commit()
    digest = results_digest(db)
    db.close()
    db_path.chmod(0o600)
    # The invented source stands in for the approved, frozen results.
    monkeypatch.setattr(cli, "EXPECTED_RESULTS_DIGEST", digest)
    monkeypatch.setattr(effective_store, "EXPECTED_RESULTS_DIGEST", digest)
    store_path = root / "full" / "effective-facets-v1.sqlite3"
    effective_store.write_store(
        store_path,
        [(k, s) for k, _, s in rows],
        {
            "source_watermark": "2026-09-18 06:58:44",
            "policy_version": "v4",
            "rules_version": "test",
            "source_rows": str(len(rows)),
            "results_digest": digest,
            "built_from": "{}",
        },
    )
    # Exclusion files: one benchmark key, one supplement case, one spot-check key.
    (root / "splits.json").write_text(json.dumps({"splits": {"60000": "dev"}}))
    _write_jsonl(root / "sample.jsonl", [{"key": "60000"}])
    (root / "deal-signals-supplement.json").write_text(
        json.dumps({"cases": [{"id": "60005"}]})
    )
    _write_jsonl(root / "wo021-spot-check-sample.jsonl", [{"key": "60010"}])
    # A frozen v1 sample: two items whose pairs v2 must never draw.
    v1 = root / op.PILOT_ID
    v1.mkdir(mode=0o700)
    v1_sample = [
        {"facet": "garage", "stratum": "cue", "listing_key": "60002"},
        {"facet": "patio", "stratum": "cue", "listing_key": "60007"},
    ]
    for n, item in enumerate(v1_sample, 1):
        item["item_id"] = f"op1-{n:03d}"
        item["status_at_sampling"] = None
    v1_text = op.canonical_jsonl(v1_sample)
    (v1 / "sample.jsonl").write_text(v1_text)
    (v1 / "manifest.json").write_text(
        json.dumps({"pilot_id": op.PILOT_ID, "sample_sha256": _sha(v1_text)})
    )
    monkeypatch.setattr(cli, "EXPECTED_V1_SAMPLE_SHA256", _sha(v1_text))
    # A ruling 8 overlay: one removal, one kept label.
    overlay = op.canonical_jsonl(
        [
            {
                "listing_key": "60001",
                "facet": "garage",
                "status": "corrected",
                "status_after": None,
            },
            {
                "listing_key": "60006",
                "facet": "garage",
                "status": "accepted_unchanged",
                "status_after": "uncertain",
            },
        ]
    )
    (root / "v5-uncertain-cleanup-overlay.jsonl").write_text(overlay)
    (root / "v5-uncertain-cleanup-manifest.json").write_text(
        json.dumps({"overlay_sha256": _sha(overlay), "policy_version": "v5"})
    )
    return root


def _tree(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_cli_v2_sample_freezes_provenance_and_honors_exclusions(v2_root, capsys):
    before = _tree(v2_root)
    cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    printed = json.loads(capsys.readouterr().out)
    out = v2_root / "omission-pilot-v2"
    assert sorted(p.name for p in out.iterdir()) == ["manifest.json", "sample.jsonl"]
    assert out.stat().st_mode & 0o077 == 0
    assert all(p.stat().st_mode & 0o077 == 0 for p in out.iterdir())
    # Nothing outside the new directory was written or changed.
    after = {
        k: v for k, v in _tree(v2_root).items() if not k.startswith("omission-pilot-v2")
    }
    assert after == before

    text = (out / "sample.jsonl").read_text()
    manifest_text = (out / "manifest.json").read_text()
    manifest = json.loads(manifest_text)
    sample = [json.loads(line) for line in text.splitlines()]
    assert printed == {
        "items": len(sample),
        "sample_sha256": _sha(text),
        "manifest_sha256": _sha(manifest_text),
    }
    assert manifest["sample_sha256"] == _sha(text)
    assert manifest["seed"] == "wo033-omission-20261103"
    assert manifest["pilot_id"] == "omission-pilot-v2"
    assert manifest["work_order"] == "WO-033"
    assert manifest["guide_version"] == op.GUIDE_VERSION_V2
    assert manifest["allocation"] == op.v2_allocation()
    assert manifest["design"]["stratum_totals"] == op.V2_STRATUM_TOTALS
    assert manifest["design"]["weights"]["near_grocery_mentioned"] == 3
    assert manifest["sample_counts"] == op.sample_counts(sample)
    assert manifest["store"]["policy_version"] == "v4"
    assert "not applied" in manifest["strata_source"]
    assert manifest["excluded_v1_items"]["items"] == 2
    assert (
        manifest["excluded_v1_items"]["sample_sha256"] == cli.EXPECTED_V1_SAMPLE_SHA256
    )
    assert manifest["excluded_by_source"]["diagnostic_471"] == 1

    pairs = {(i["listing_key"], i["facet"]) for i in sample}
    assert ("60002", "garage") not in pairs and ("60007", "patio") not in pairs
    # A v1 item leaves only its own facet's population: 12 invented cue listings each.
    counts = manifest["population_counts"]
    assert counts["garage"]["cue"] == 11 and counts["patio"]["cue"] == 11
    assert counts["near_grocery_mentioned"]["cue"] == 12
    keys = {i["listing_key"] for i in sample}
    assert not keys & {"60000", "60005", "60010", "60059"}
    assert all(i["item_id"].startswith("op2-") for i in sample)

    ruling8 = manifest["ruling8_overlay"]
    assert ruling8["applied_to_strata"] is False
    assert ruling8["removals"] == 1
    assert ruling8["removals_in_labeled_population"] == 1
    removed_sampled = ("60001", "garage") in pairs
    assert ruling8["sampled_items_removed_by_overlay"] == int(removed_sampled)
    # The removed label stays in the labeled stratum: the overlay is not applied.
    assert counts["garage"]["labeled_non_present"] == 12
    for item in sample:
        if (item["listing_key"], item["facet"]) == ("60001", "garage"):
            assert item["stratum"] == "labeled_non_present"
            assert item["status_at_sampling"] == "uncertain"
    # No key or remark reaches the manifest.
    for key, remark, _ in _rows():
        assert f'"{key}"' not in manifest_text and remark not in manifest_text


def test_cli_v2_sample_is_reproducible_from_the_seed(v2_root, tmp_path, capsys):
    cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    first = (v2_root / "omission-pilot-v2" / "sample.jsonl").read_text()
    (v2_root / "omission-pilot-v2").rename(tmp_path / "first-draw")
    cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    assert (v2_root / "omission-pilot-v2" / "sample.jsonl").read_text() == first
    (v2_root / "omission-pilot-v2").rename(tmp_path / "second-draw")
    cli.main(
        ["--data-root", str(v2_root), "--pilot", "v2", "sample", "--seed", "other"]
    )
    third = (v2_root / "omission-pilot-v2" / "sample.jsonl").read_text()
    assert (
        json.loads((v2_root / "omission-pilot-v2" / "manifest.json").read_text())[
            "seed"
        ]
        == "other"
    )
    assert third != first


def test_cli_v2_sample_refuses_an_existing_v2_directory(v2_root):
    (v2_root / "omission-pilot-v2").mkdir()
    with pytest.raises(FileExistsError):
        cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    assert list((v2_root / "omission-pilot-v2").iterdir()) == []


def test_cli_v2_refuses_a_v1_sample_other_than_the_frozen_one(v2_root, monkeypatch):
    monkeypatch.setattr(cli, "EXPECTED_V1_SAMPLE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="frozen WO-026 sample"):
        cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    assert not (v2_root / "omission-pilot-v2").exists()


def test_cli_v2_refuses_a_changed_v1_sample(v2_root):
    with (v2_root / op.PILOT_ID / "sample.jsonl").open("a") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="manifest"):
        cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    assert not (v2_root / "omission-pilot-v2").exists()


def test_cli_v2_refuses_an_overlay_that_differs_from_its_manifest(v2_root):
    with (v2_root / "v5-uncertain-cleanup-overlay.jsonl").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="ruling 8 overlay"):
        cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    assert not (v2_root / "omission-pilot-v2").exists()


def test_cli_v2_record_uses_the_v2_directory_and_guide(v2_root, tmp_path, capsys):
    cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    out = v2_root / "omission-pilot-v2"
    sample = cli.read_jsonl(out / "sample.jsonl")
    draft = tmp_path / "draft.jsonl"

    def judgment(item, guide):
        return {
            "item_id": item["item_id"],
            "facet": item["facet"],
            "stratum": item["stratum"],
            "decision": "correctly_absent",
            "existing_status_check": "correct"
            if item["stratum"] == "labeled_non_present"
            else "not_applicable",
            "reviewer": "model:test-reviewer",
            "review_type": "model",
            "reviewed_at": "2026-11-03T12:00:00+00:00",
            "guide_version": guide,
            "human_review": "pending",
        }

    _write_jsonl(draft, [judgment(i, op.GUIDE_VERSION) for i in sample])
    args = ["--data-root", str(v2_root), "--pilot", "v2", "record"]
    with pytest.raises(ValueError, match="guide version"):
        cli.main([*args, "--draft", str(draft), "--kind", "model"])
    good = tmp_path / "good.jsonl"
    _write_jsonl(good, [judgment(i, op.GUIDE_VERSION_V2) for i in sample])
    cli.main([*args, "--draft", str(good), "--kind", "model"])
    assert len(cli.read_jsonl(out / "judgments.jsonl")) == len(sample)
    assert not (v2_root / op.PILOT_ID / "judgments.jsonl").exists()
    capsys.readouterr()
    cli.main(["--data-root", str(v2_root), "--pilot", "v2", "aggregate"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["pilot_id"] == "omission-pilot-v2"
    with pytest.raises(ValueError, match="plain file name"):
        cli.main([*args, "--draft", str(good), "--kind", "model", "--name", "../x"])
