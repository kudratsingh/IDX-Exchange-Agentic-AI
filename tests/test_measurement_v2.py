"""WO-028 measurement set version 2: goldens against the truth SQL, the frozen set
version 1, the new fact kinds, the fourth score (answer support) and the recorded
synthetic transcripts. No server and no model: truth runs on an SQLite copy of the
committed fixture; every transcript is hand-written and labelled synthetic."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from evals import measurement
from evals import run as runner
from evals.truth import sql as truth_sql
from evals.truth.sql import Truth

ROOT = Path(__file__).resolve().parents[1]
V1 = measurement.load_entries(measurement.CASES)
V2 = measurement.load_entries(measurement.CASES_V2)
# Recorded when each set was frozen; a change to either means a new set version.
V1_SPLIT = "d6c38c150259"
V2_SPLIT = "32621eea38c5"
TRANSCRIPTS = measurement.load_transcripts()


@pytest.fixture(scope="module")
def truth():
    return Truth(measurement.fixture_sqlite(), mark="?")


# --- versioning: set version 1 is frozen, version 2 is its own set ---


def test_set_version_one_is_unchanged():
    assert len(V1) == 56
    assert measurement.split_hash(V1).startswith(V1_SPLIT)
    assert all("set_version" not in e for e in V1)
    assert sum(e["split"] == "heldout" for e in V1) == 33


def test_set_version_two_has_its_own_split_and_hash():
    assert measurement.split_hash(V2).startswith(V2_SPLIT)
    assert all(e["set_version"] == 2 for e in V2)
    assert all(measurement.case_problem(e) is None for e in V2)
    held = sum(e["split"] == "heldout" for e in V2)
    assert len(V2) >= 40 and 0.55 <= held / len(V2) <= 0.65
    assert not {e["id"] for e in V1} & {e["id"] for e in V2}


def test_every_v2_golden_equals_the_truth_sql_over_the_committed_fixture(truth):
    assert measurement.golden_problems(V2, truth) == []


def test_v2_covers_every_new_fact_kind_and_none_that_was_stopped():
    named = {kind for e in V2 for kind in e["expect"]["facts"]}
    new = truth_sql.CARD_KINDS | truth_sql.ANALYTICS_KINDS | truth_sql.COMP_KINDS
    assert new <= named
    assert not named & set(truth_sql.STOPPED_KINDS)
    families = {e["family"] for e in V2}
    assert families == {"market", "comps"}
    verdicts = {
        e["expect"]["facts"]["comp_verdict"]
        for e in V2
        if "comp_verdict" in e["expect"]["facts"]
    }
    assert {"above", "below", "at", "insufficient"} <= verdicts


def test_the_runner_loads_v2_as_its_own_ci_category():
    cases, errors = runner.load_cases(runner.DEFAULT_CASES_DIR)
    assert errors == []
    ours = [c for c in cases if c.check == measurement.CHECK and c.set_version == 2]
    assert len(ours) == len(V2)
    assert all(c.suite == "ci" and c.category == "measurement_v2" for c in ours)
    first = [c for c in cases if c.check == measurement.CHECK and c.set_version == 1]
    assert len(first) == len(V1) and {c.category for c in first} == {"measurement"}
    comps = [c for c in ours if c.family == "comps"]
    assert comps and all(c.tool == "recommend" for c in comps)
    assert all(c.input_filters["k"] == 0 for c in comps)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"set_version": 3}, "set_version"),
        ({"category": "measurement"}, "category measurement_v2"),
        ({"id": "meas-099"}, "id must match"),
        ({"family": "search"}, "route must be"),
    ],
)
def test_malformed_v2_cases_are_refused(change, problem):
    entry = {**V2[0], **change}
    assert problem in (measurement.case_problem(entry) or "")


def test_a_v2_case_without_its_version_and_a_v1_case_with_one_are_refused():
    bare = {k: v for k, v in V2[0].items() if k != "set_version"}
    assert measurement.case_problem(bare) is not None
    assert "set_version" in measurement.case_problem({**V1[0], "set_version": 1})


def test_an_extended_figure_needs_include_extended():
    entry = next(e for e in V2 if "analytics_sold_count" in e["expect"]["facts"])
    args = {k: v for k, v in entry["expect"]["args"].items() if k != "include_extended"}
    broken = {**entry, "expect": {**entry["expect"], "args": args}}
    assert "include_extended" in measurement.case_problem(broken)


def test_v1_still_refuses_the_new_kinds():
    entry = next(e for e in V1 if e["family"] == "market")
    entry = {**entry, "expect": {**entry["expect"], "facts": {"dom_band": "low"}}}
    assert "facts for market" in measurement.case_problem(entry)


# --- the documented readings, at their boundaries (WO-008 labels) ---


@pytest.mark.parametrize(
    ("days", "band"),
    [
        (14.5, "very_low"),
        (15, "low"),
        (29.5, "low"),
        (30, "average"),
        (59.5, "average"),
        (60, "high"),
        (None, None),
    ],
)
def test_dom_band_boundaries(days, band):
    assert truth_sql.dom_band(days) == band


@pytest.mark.parametrize(
    ("ratio", "days", "lean"),
    [
        (1.0, 29.5, "seller"),
        (1.0, 30, "balanced"),
        (0.999, 10, "balanced"),
        (0.979, 10, "buyer"),
        (0.98, 59.5, "balanced"),
        (1.05, 60, "buyer"),
        (1.0, None, None),
    ],
)
def test_market_lean_order_and_boundaries(ratio, days, lean):
    assert truth_sql.market_lean(ratio, days) == lean


@pytest.mark.parametrize(
    ("ratio", "reading"),
    [
        (1.0, "at asking"),
        (1.004, "at asking"),
        (1.005, "at asking"),  # half-even: 0.5 rounds to 0
        (1.015, "2% over asking"),
        (0.975, "2% under asking"),
        (None, None),
    ],
)
def test_sale_to_list_reading(ratio, reading):
    assert truth_sql.sale_to_list_reading(ratio) == reading


def test_month_keys_cover_every_touched_month():
    from datetime import date

    assert truth_sql.month_keys(date(2026, 3, 18), date(2026, 9, 17)) == [
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert truth_sql.month_keys(date(2025, 12, 31), date(2026, 1, 1)) == [
        "2025-12",
        "2026-01",
    ]


def test_low_sample_cards_have_an_empty_trend_and_no_readings(truth):
    facts = truth.market_card({"city": "Bradbury"})
    assert facts["sample_count"] < 5 and facts["trend"] == []
    assert facts["dom_band"] is facts["market_lean"] is None
    assert facts["sale_to_list_reading"] is None


def test_extended_rows_compare_only_complete_months(truth):
    rows = truth.analytics({"city": "San Gabriel"})["analytics_months"]
    for row in rows:
        if row["partial"]:
            assert row["price_mom_pct"] is None and row["ppsf_mom_pct"] is None
    assert any(row["price_mom_pct"] is not None for row in rows)
    # The first complete month has no complete month before it.
    first = next(row for row in rows if not row["partial"])
    assert first["price_mom_pct"] is None


# --- extracting facts from real-shaped envelopes ---


def _market_envelope(facts, months):
    analytics = SimpleNamespace(
        active_count=facts["analytics_active_count"],
        sold_count=facts["analytics_sold_count"],
        mean_close_price=facts["analytics_mean_close_price"],
        mean_dom=facts["analytics_mean_dom"],
        mean_price_per_sqft=123.45,
        months=[SimpleNamespace(median_price_per_sqft=1.0, **row) for row in months],
    )
    data = SimpleNamespace(
        **{k: facts[k] for k in measurement.FAMILY_FACTS["market"]},
        dom_band=facts["dom_band"],
        market_lean=facts["market_lean"],
        sale_to_list_reading=facts["sale_to_list_reading"],
        trend=[SimpleNamespace(**row) for row in facts["trend"]],
        analytics=analytics,
    )
    return SimpleNamespace(data=data)


def test_market_envelopes_report_the_new_kinds(truth):
    place = {"city": "San Gabriel"}
    facts = {**truth.market_card(place), **truth.analytics(place)}
    envelope = _market_envelope(facts, facts["analytics_months"])
    got = measurement.envelope_facts("market", envelope)
    for kind in truth_sql.CARD_KINDS | truth_sql.ANALYTICS_KINDS:
        assert measurement.fact_matches(kind, facts[kind], got[kind]), kind
    # The stopped monthly median PPSF is never compared.
    assert "median_price_per_sqft" not in got["analytics_months"][0]


def test_a_changed_month_row_is_a_wrong_answer(truth):
    rows = truth.analytics({"city": "San Gabriel"})["analytics_months"]
    changed = [dict(row) for row in rows]
    changed[2]["price_mom_pct"] += 0.1
    assert not measurement.fact_matches("analytics_months", rows, changed)
    changed = [dict(row) for row in rows]
    changed[0]["partial"] = 1  # not a bool: refused, not coerced
    assert not measurement.fact_matches("analytics_months", rows, changed)


def test_comp_envelopes_report_the_verdict_band():
    def check(**fields):
        base = {
            "level": "postal_code",
            "sufficient": True,
            "count": 6,
            "delta_pct": 4.0,
            "median_price_per_sqft": 579,
            "range_low_price_per_sqft": 575,
            "range_high_price_per_sqft": 587,
        }
        base.update(fields)
        data = SimpleNamespace(subject_check=SimpleNamespace(**base))
        return measurement.envelope_facts("comps", SimpleNamespace(data=data))

    assert check()["comp_verdict"] == "above"
    assert check(delta_pct=-2.0)["comp_verdict"] == "below"
    assert check(delta_pct=0.0)["comp_verdict"] == "at"
    assert check(sufficient=False, delta_pct=None)["comp_verdict"] == "insufficient"
    assert check(level=None, sufficient=False)["comp_verdict"] == "not_checkable"


def test_include_extended_counts_only_when_an_extended_figure_is_expected():
    plain = {"city": "Monrovia"}
    extended = {"city": "Monrovia", "include_extended": True}
    tool = "get_market_stats"
    assert measurement._args_match(tool, plain, extended, {"median_dom": None})
    assert not measurement._args_match(
        tool, extended, plain, {"analytics_sold_count": 7}
    )
    assert measurement._args_match(
        "recommend", {"listing_key": 9130001, "k": 0}, {"listing_key": 9130001}, {}
    )
    assert not measurement._args_match(
        "recommend", {"listing_key": 9130001, "k": 0}, {"listing_key": 9130002}, {}
    )


# --- the fourth score: numeric support of a final answer ---


def test_answer_support_flags_only_unsupported_figures():
    facts = {"median_close_price": 822000, "sale_to_list_ratio": 0.998}
    calls = [("get_market_stats", {"city": "San Gabriel"}, None)]
    right = measurement.answer_support(
        "The median was $822,000 and homes sold at 99.8% of asking.", facts, calls
    )
    assert right == {
        "measured": True,
        "figures": 2,
        "unsupported": 0,
        "ungrounded": 2,
        "supported": 1,
    }
    wrong = measurement.answer_support("The median was $823,000.", facts, calls)
    assert wrong["supported"] == 0 and wrong["unsupported"] == 1
    assert measurement.answer_support(None, facts, calls) == {"measured": False}


def test_answer_support_reads_the_precision_a_figure_is_written_in():
    facts = {"analytics_mean_dom": 28.03, "comp_delta_pct": -5}
    support = measurement.answer_support(
        "About 28 days on market; listed 5% below.", facts, []
    )
    assert support["supported"] == 1
    support = measurement.answer_support("About 28.1 days on market.", facts, [])
    assert support["supported"] == 0


def test_answer_support_accepts_figures_from_the_tool_message_and_the_question():
    envelope = {"ok": True, "facts": {}, "message": "Sales to 2026-09-17: 60 sales."}
    support = measurement.answer_support(
        "There were 60 sales through 2026-09-17 in 91776.",
        {},
        [("get_market_stats", {"postal_code": "91776"}, envelope)],
        question="sales in 91776",
    )
    assert support["supported"] == 1 and support["ungrounded"] == 0


def test_the_support_tokenizer_is_the_existing_post_check():
    from idx_agent.email import verify

    assert measurement.reply_numbers is verify._numbers


# --- the recorded synthetic transcripts ---


def test_every_transcript_is_labelled_synthetic_and_covers_the_scenarios():
    assert all(t["label"] == "synthetic" for t in TRANSCRIPTS)
    scenarios = " | ".join(t["scenario"] for t in TRANSCRIPTS)
    for needed in (
        "follow-up refinement carries",
        "wrong number in the prose, right tool result",
        "right number in the prose, wrong route",
        "relayed correctly",
        "overclaimed",
        "extra call",
        "missing call",
    ):
        assert needed in scenarios, needed
    assert any(len(t["turns"]) > 1 for t in TRANSCRIPTS)


@pytest.mark.parametrize("transcript", TRANSCRIPTS, ids=lambda t: t["id"])
def test_each_recorded_turn_scores_as_written(transcript, truth):
    scored = measurement.score_conversation(transcript, truth)
    assert len(scored) == len(transcript["turns"])
    for turn, got in zip(transcript["turns"], scored, strict=True):
        assert got["scores"] == turn["want"]["scores"]
        for name, value in turn["want"]["support"].items():
            assert got["support"][name] == value, name


def test_transcripts_must_be_labelled(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text("- id: x\n  label: model\n  turns: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        measurement.load_transcripts(path)


# --- reports: one block per set, four scores kept apart ---


def test_the_summary_keeps_answer_support_apart_from_the_three_scores():
    records = [
        {
            "split": "dev",
            "family": "market",
            "scores": {"route": 1, "args": 1, "answer": 1},
            "support": {"measured": True, "supported": 0},
        },
        {
            "split": "dev",
            "family": "market",
            "scores": {"route": 1, "args": 1, "answer": 1},
        },
    ]
    block = measurement.summary(records, "model", 2)
    assert block["set_version"] == 2
    assert block["scores"]["dev"]["market"] == {
        "cases": 2,
        "route": 2,
        "args": 2,
        "answer": 2,
    }
    assert block["answer_support"]["dev"]["market"] == {"measured": 1, "supported": 0}
    assert "does not prove" in block["answer_support_note"]


def test_a_report_carries_each_set_with_its_own_version_and_split_hash():
    cases, _ = runner.load_cases(runner.DEFAULT_CASES_DIR)
    ours = [c for c in cases if c.check == measurement.CHECK]
    records = [
        {
            "id": c.id,
            "check": c.check,
            "split": c.split,
            "family": c.family,
            "set_version": c.set_version,
            "scores": {"route": 1, "args": 1, "answer": 1},
        }
        for c in ours
    ]
    blocks = runner._measurement_summary(cases, records, "ci")
    assert set(blocks) == {"measurement", "measurement_v2"}
    assert blocks["measurement"]["set_version"] == 1
    assert blocks["measurement"]["split_hash"].startswith(V1_SPLIT)
    assert blocks["measurement_v2"]["set_version"] == 2
    assert blocks["measurement_v2"]["split_hash"].startswith(V2_SPLIT)
    assert blocks["measurement_v2"]["mode"] == "oracle"
    # Oracle runs carry no prose: the fourth score is measured nowhere.
    for block in blocks.values():
        rows = [c for split in block["answer_support"].values() for c in split.values()]
        assert all(row["measured"] == 0 for row in rows)


def test_the_v1_case_file_bytes_are_frozen():
    digest = hashlib.sha256(measurement.CASES.read_bytes()).hexdigest()
    # Recomputing goldens or reformatting would change this; a v1 edit is a new set.
    assert digest == V1_FILE_SHA256


# The WO-020 file as merged (PRs #139/#140).
V1_FILE_SHA256 = "3e9025fd31250cb97b7c032e2c6075ec11dda01f2d81cdd6a9780ee80d280d9a"
