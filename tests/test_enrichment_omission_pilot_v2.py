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


def test_weighted_rate_matches_a_hand_computed_kish_wilson_example():
    # Invented: A has N=300, 1 omission in 10; B has N=100, 0 in 10.
    # p_w = 0.75 * 0.1 + 0.25 * 0 = 0.075; n_eff = 400^2 / (300^2/10 + 100^2/10) = 16;
    # deff = 20 / 16 = 1.25. Wilson, p = 0.075, n = 16, z = 1.96, by hand:
    # centre 0.19505, spread 0.17626, denominator 1.2401 -> 0.01515 to 0.29942.
    result = op.weighted_rate({"A": (1, 10), "B": (0, 10)}, {"A": 300, "B": 100})
    assert result["estimate"] == pytest.approx(0.075)
    assert result["n"] == 20
    assert result["n_eff"] == pytest.approx(16.0)
    assert result["design_effect"] == pytest.approx(1.25)
    low, high = result["wilson95"]
    assert low == pytest.approx(0.01515, abs=1e-4)
    assert high == pytest.approx(0.29942, abs=1e-4)
    assert result["covered_population"] == 400
    assert result["uncovered_population"] == 0


def test_weighted_rate_proportional_allocation_and_uncovered_facets():
    # Items in proportion to population: n_eff equals n and p_w the pooled rate.
    result = op.weighted_rate(
        {"A": (2, 20), "B": (1, 10), "C": (0, 0)}, {"A": 200, "B": 100, "C": 50}
    )
    assert result["n_eff"] == pytest.approx(30.0)
    assert result["design_effect"] == pytest.approx(1.0)
    assert result["estimate"] == pytest.approx(0.1)
    assert result["wilson95"] == pytest.approx(list(op.wilson(3, 30)))
    # The unsampled facet is reported, never imputed.
    assert result["covered_population"] == 300
    assert result["uncovered_population"] == 50
    empty = op.weighted_rate({"A": (0, 0)}, {"A": 10})
    assert empty["estimate"] is None and empty["wilson95"] is None
    assert empty["uncovered_population"] == 10


# ---- WO-033 covered population (regression, owner-reported) -----------------------


def test_weighted_rate_reports_population_that_has_no_cell_as_uncovered():
    # Invented: D has population but no cell at all. Before the fix D vanished from
    # both the covered and the uncovered population, so coverage looked complete.
    result = op.weighted_rate({"A": (1, 10)}, {"A": 300, "D": 100})
    assert result["covered_population"] == 300
    assert result["uncovered_population"] == 100
    assert result["population"] == 400
    assert result["covered_share"] == pytest.approx(0.75)
    assert result["uncovered_facets"] == {"D": 100}


def test_weighted_rate_hand_computed_covered_only_example():
    # Invented: A N=300, 1 in 10; B N=100, 0 in 10; C N=50, cell with no items;
    # D N=150, no cell. Covered = A + B only, N_c = 400 of 600 (share 2/3).
    # p_w = (300/400)(0.1) + (100/400)(0) = 0.075;
    # n_eff = 400^2 / (300^2/10 + 100^2/10) = 160000 / 10000 = 16; deff 20/16 = 1.25.
    # Wilson, p = 0.075, n = 16 -> 0.01515 to 0.29942 (as the all-covered example).
    # Neither C nor D is imputed: not as zero, not at the covered rate.
    result = op.weighted_rate(
        {"A": (1, 10), "B": (0, 10), "C": (0, 0)},
        {"A": 300, "B": 100, "C": 50, "D": 150},
    )
    assert result["estimate"] == pytest.approx(0.075)
    assert result["n"] == 20
    assert result["n_eff"] == pytest.approx(16.0)
    assert result["design_effect"] == pytest.approx(1.25)
    low, high = result["wilson95"]
    assert low == pytest.approx(0.01515, abs=1e-4)
    assert high == pytest.approx(0.29942, abs=1e-4)
    assert result["covered_population"] == 400
    assert result["uncovered_population"] == 200
    assert result["population"] == 600
    assert result["covered_share"] == pytest.approx(2 / 3)
    assert result["covered_facets"] == 2
    assert result["uncovered_facets"] == {"C": 50, "D": 150}
    assert result["basis"] == op.COVERED_BASIS


def test_weighted_rate_all_covered_is_unchanged():
    # The pre-fix figures for a fully covered stratum, pinned exactly.
    result = op.weighted_rate({"A": (1, 10), "B": (0, 10)}, {"A": 300, "B": 100})
    assert result["estimate"] == pytest.approx(0.075)
    assert result["n_eff"] == pytest.approx(16.0)
    assert result["wilson95"] == pytest.approx(list(op.wilson(0.075 * 16, 16)))
    assert result["covered_population"] == result["population"] == 400
    assert result["uncovered_population"] == 0
    assert result["covered_share"] == 1.0
    assert result["uncovered_facets"] == {}


def test_weighted_rate_with_nothing_covered_gives_an_explicit_empty_result():
    result = op.weighted_rate({"A": (0, 0)}, {"A": 10, "B": 5})
    assert result["estimate"] is None
    assert result["wilson95"] is None
    assert result["n_eff"] is None and result["design_effect"] is None
    assert result["n"] == 0
    assert result["covered_population"] == 0
    assert result["uncovered_population"] == 15
    assert result["covered_share"] == 0.0
    assert result["uncovered_facets"] == {"A": 10, "B": 5}
    assert result["basis"] == op.NO_COVERED_BASIS
    nothing = op.weighted_rate({}, {})
    assert nothing["estimate"] is None and nothing["covered_share"] is None


def test_weighted_rate_refuses_items_without_population_and_bad_counts():
    # Sampled items outside any population used to be dropped from n silently.
    with pytest.raises(ValueError, match="no population"):
        op.weighted_rate({"A": (1, 10), "B": (0, 5)}, {"A": 300})
    with pytest.raises(ValueError, match="no population"):
        op.weighted_rate({"A": (1, 10), "B": (0, 5)}, {"A": 300, "B": 0})
    with pytest.raises(ValueError, match="0 <= k <= n"):
        op.weighted_rate({"A": (12, 10)}, {"A": 300})
    with pytest.raises(ValueError, match="0 <= k <= n"):
        op.weighted_rate({"A": (-1, 10)}, {"A": 300})
    with pytest.raises(ValueError, match="negative population"):
        op.weighted_rate({"A": (0, 10)}, {"A": 300, "B": -1})


def _reviews(sample, decision="correctly_absent"):
    return {
        i["item_id"]: {
            "decision": decision,
            "review_type": "model",
            "existing_status_check": "correct",
        }
        for i in sample
    }


def test_aggregate_reports_a_facet_with_population_but_no_sampled_item():
    pop = _full_population(30)
    sample = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    dropped = "water_view"
    kept = [i for i in sample if i["facet"] != dropped]
    counts = op.population_counts(pop)
    result = op.aggregate(kept, _reviews(kept), counts, V2.pilot_id)
    no_cue = result["weighted_by_stratum"]["no_cue"]["omitted"]
    assert no_cue["uncovered_facets"] == {dropped: 30}
    assert no_cue["uncovered_population"] == 30
    assert no_cue["population"] == 30 * len(FACETS)
    assert no_cue["covered_share"] == pytest.approx(19 / 20)
    assert result["facets"][dropped]["uncovered_population"] == 90
    assert result["facets"][dropped]["weighted_rate_covered"] is None


def test_aggregate_v2_design_covers_no_cue_fully_and_reports_labeled_share():
    # The v2 design samples no-cue and cue items for all 20 facets, labeled items for
    # the six limited facets only: the other 14 facets' labeled population is
    # uncovered and must be reported as such, never folded into the estimate.
    pop = _full_population(30)
    sample = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    result = op.aggregate(
        sample, _reviews(sample), op.population_counts(pop), V2.pilot_id
    )
    weighted = result["weighted_by_stratum"]
    for stratum in ("no_cue", "cue"):
        assert weighted[stratum]["omitted"]["covered_share"] == 1.0
        assert weighted[stratum]["omitted"]["uncovered_facets"] == {}
    labeled = weighted["labeled_non_present"]["omitted"]
    assert labeled["covered_facets"] == 6
    assert set(labeled["uncovered_facets"]) == set(FACETS) - op.LIMITED_FACETS
    assert labeled["covered_share"] == pytest.approx(6 / 20)


def test_aggregate_reports_the_weighted_rate_and_unclear_sensitivity():
    pop = _full_population(30)
    sample = op.draw_sample(pop, V2.seed, V2.allocation, V2.item_prefix)
    no_cue = [i for i in sample if i["stratum"] == "no_cue"]
    marked = {no_cue[0]["item_id"]: "omitted_present", no_cue[1]["item_id"]: "unclear"}
    reviews = {
        i["item_id"]: {
            "decision": marked.get(i["item_id"], "correctly_absent"),
            "review_type": "model",
            "existing_status_check": "correct",
        }
        for i in sample
    }
    counts = op.population_counts(pop)
    result = op.aggregate(sample, reviews, counts, V2.pilot_id)
    weighted = result["weighted_by_stratum"]["no_cue"]
    facet = no_cue[0]["facet"]
    share = counts[facet]["no_cue"] / sum(c["no_cue"] for c in counts.values())
    n_f = V2.allocation[facet]["no_cue"]
    assert weighted["omitted"]["estimate"] == pytest.approx(share / n_f)
    assert weighted["omitted"]["n"] == 240
    second = no_cue[1]["facet"]
    share2 = counts[second]["no_cue"] / sum(c["no_cue"] for c in counts.values())
    expected = share / n_f + share2 / V2.allocation[second]["no_cue"]
    assert weighted["unclear_as_omitted"]["estimate"] == pytest.approx(expected)


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
    assert printed["weighted_by_stratum"]["no_cue"]["omitted"]["estimate"] == 0.0
    with pytest.raises(ValueError, match="plain file name"):
        cli.main([*args, "--draft", str(good), "--kind", "model", "--name", "../x"])


# ---- WO-033 human packet ----------------------------------------------------------


def _judged(n, **overrides):
    """Invented final judgments op2-001..: correctly absent, no second read."""
    records = [
        {
            "item_id": f"op2-{i:03d}",
            "facet": "garage",
            "stratum": "cue",
            "decision": "correctly_absent",
            "existing_status_check": "not_applicable",
            "adjudicated": False,
        }
        for i in range(1, n + 1)
    ]
    for item_id, fields in overrides.items():
        next(r for r in records if r["item_id"] == item_id).update(fields)
    return records


def _second_read(record, decision=None):
    record["second_read_decision"] = decision or record["decision"]
    record["second_read_status_check"] = record["existing_status_check"]
    return record


def test_human_packet_selection_dedupes_the_union_and_draws_agreed_items():
    records = _judged(
        60,
        **{
            "op2-001": {"decision": "omitted_present", "adjudicated": True},
            "op2-002": {"decision": "omitted_present"},
            "op2-003": {"decision": "unclear"},
            "op2-004": {"decision": "correctly_absent", "adjudicated": True},
        },
    )
    for record in records[10:40]:  # 30 second-read items outside the union
        _second_read(record)
    _second_read(records[40], decision="unclear")  # disagreed, not adjudicated
    selection = op.human_packet_selection(records, seed="test-seed", random_items=20)
    reasons = selection["reasons"]
    assert reasons["op2-001"] == ["omitted_present", "adjudicated"]
    assert reasons["op2-004"] == ["adjudicated"]
    counts = selection["counts"]
    assert counts["omitted_present"] == 2
    assert counts["unclear"] == 1
    assert counts["adjudicated"] == 2
    assert counts["union"] == 4  # 2 + 1 + 2 = 5 before deduplication
    assert counts["agreed_pool"] == 30
    assert counts["random_agreed"] == 20
    assert counts["random_not_second_read"] == 0
    assert counts["packet_items"] == 24
    drawn = [i for i, w in reasons.items() if w == ["random_agreed"]]
    pool = {r["item_id"] for r in records[10:40]}
    assert len(drawn) == 20 and set(drawn) <= pool
    # The draw is the smallest sha256(seed|item_id) ranks of the pool.
    expected = sorted(pool, key=lambda i: _sha(f"test-seed|{i}"))[:20]
    assert sorted(drawn) == sorted(expected)
    again = op.human_packet_selection(records, seed="test-seed", random_items=20)
    assert again == selection
    other = op.human_packet_selection(records, seed="other-seed", random_items=20)
    assert other["reasons"] != reasons


def test_human_packet_selection_reports_a_short_agreed_pool():
    records = _judged(30, **{"op2-001": {"decision": "omitted_present"}})
    for record in records[1:6]:
        _second_read(record)
    selection = op.human_packet_selection(records, seed="s", random_items=20)
    counts = selection["counts"]
    assert counts["agreed_pool"] == 5
    assert counts["random_agreed"] == 5
    assert counts["random_not_second_read"] == 15
    assert counts["packet_items"] == 21
    with pytest.raises(ValueError, match="duplicate"):
        op.human_packet_selection([*records, records[0]])


def test_human_packet_records_carry_the_remark_model_judgment_and_blank_fields():
    records = _judged(3, **{"op2-002": {"decision": "unclear", "note": "n"}})
    sample = [
        {
            "item_id": r["item_id"],
            "facet": "garage",
            "stratum": "cue",
            "listing_key": f"9{n}",
            "status_at_sampling": None,
        }
        for n, r in enumerate(records)
    ]
    selection = op.human_packet_selection(records, random_items=0)
    remarks = {r["item_id"]: "Invented remark with a two car garage." for r in records}
    packet = op.human_packet(sample, records, remarks, selection)
    assert [p["item_id"] for p in packet] == ["op2-002"]
    record = packet[0]
    assert record["remark"] == remarks["op2-002"]
    assert record["cue_spans"]
    assert record["selection"] == ["unclear"]
    assert record["model"]["decision"] == "unclear"
    assert record["model"]["note"] == "n"
    assert all(record[f] is None for f in op.HUMAN_PACKET_BLANK_FIELDS)
    assert "listing_key" not in json.dumps(packet)


def _record_v2(v2_root, tmp_path, marks):
    cli.main(["--data-root", str(v2_root), "--pilot", "v2", "sample"])
    out = v2_root / "omission-pilot-v2"
    sample = cli.read_jsonl(out / "sample.jsonl")
    records = []
    for n, item in enumerate(sample):
        record = {
            "item_id": item["item_id"],
            "facet": item["facet"],
            "stratum": item["stratum"],
            "decision": marks.get(n, "correctly_absent"),
            "existing_status_check": "correct"
            if item["stratum"] == "labeled_non_present"
            else "not_applicable",
            "reviewer": "model:test-reviewer",
            "review_type": "model",
            "reviewed_at": "2026-11-03T12:00:00+00:00",
            "guide_version": op.GUIDE_VERSION_V2,
            "human_review": "pending",
            "adjudicated": n == 2,
        }
        if n % 2:
            _second_read(record)
        records.append(record)
    draft = tmp_path / "draft.jsonl"
    _write_jsonl(draft, records)
    cli.main(
        ["--data-root", str(v2_root), "--pilot", "v2", "record"]
        + ["--draft", str(draft), "--kind", "model"]
    )
    return out, sample


def test_cli_human_packet_writes_a_new_private_file_under_human(
    v2_root, tmp_path, capsys
):
    out, sample = _record_v2(v2_root, tmp_path, {0: "omitted_present", 1: "unclear"})
    judgments_before = (out / "judgments.jsonl").read_bytes()
    capsys.readouterr()
    args = ["--data-root", str(v2_root), "--pilot", "v2", "human-packet"]
    cli.main([*args, "--random", "2"])
    printed = capsys.readouterr().out
    summary = json.loads(printed)
    assert summary["union"] == 3  # items 0, 1 and the adjudicated item 2
    assert summary["random_agreed"] == 2
    assert summary["packet_items"] == 5
    assert summary["seed"] == op.HUMAN_PACKET_SEED
    human = out / "human"
    assert human.stat().st_mode & 0o077 == 0
    path = human / "human-packet-r1.jsonl"
    assert path.stat().st_mode & 0o077 == 0
    packet = cli.read_jsonl(path)
    assert summary["packet_sha256"] == op.sha256_text(path.read_text())
    assert len(packet) == 5
    assert all(p["remark"] and p["human_decision"] is None for p in packet)
    # Counts and hashes only on stdout: no key and no remark text.
    assert not any(i["listing_key"] in printed for i in sample)
    assert not any(p["remark"] in printed for p in packet)
    assert (out / "judgments.jsonl").read_bytes() == judgments_before
    # Never replaces a file, never leaves the subdirectory.
    with pytest.raises(FileExistsError):
        cli.main(args)
    with pytest.raises(ValueError, match="plain file name"):
        cli.main([*args, "--name", "../escape.jsonl"])
    with pytest.raises(ValueError, match="plain file name"):
        cli.main([*args, "--name", str(tmp_path / "abs.jsonl")])
    assert not (out / "escape.jsonl").exists()
    assert not (tmp_path / "abs.jsonl").exists()


def test_cli_human_packet_refuses_a_linked_human_directory(v2_root, tmp_path):
    out, _ = _record_v2(v2_root, tmp_path, {0: "omitted_present"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (out / "human").symlink_to(elsewhere)
    with pytest.raises(ValueError, match="real owner-only directory"):
        cli.main(["--data-root", str(v2_root), "--pilot", "v2", "human-packet"])
    assert list(elsewhere.iterdir()) == []


def test_cli_human_packet_refuses_incomplete_judgments(v2_root, tmp_path):
    out, _ = _record_v2(v2_root, tmp_path, {0: "omitted_present"})
    records = cli.read_jsonl(out / "judgments.jsonl")
    _write_jsonl(out / "judgments-partial.jsonl", records[:-1])
    with pytest.raises(ValueError, match="every sampled item"):
        cli.main(
            ["--data-root", str(v2_root), "--pilot", "v2", "human-packet"]
            + ["--judgments", "judgments-partial.jsonl"]
        )
    assert not (out / "human").exists()
