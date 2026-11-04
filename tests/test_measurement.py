"""WO-020 measurement set: goldens against the independent truth SQL, case shape, the
truth module's independence, and the three separate scores on synthetic transcripts.

No server: the truth SQL runs on an SQLite copy of the committed fixture rows. The ci
suite runs the same comparison, plus the tools, on the MySQL fixture."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from evals import measurement
from evals import run as runner
from evals.truth.sql import Truth

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = measurement.load_entries()


@pytest.fixture(scope="module")
def truth():
    return Truth(measurement.fixture_sqlite(), mark="?")


def test_every_golden_equals_the_truth_sql_over_the_committed_fixture(truth):
    assert measurement.golden_problems(ENTRIES, truth) == []


def test_the_set_meets_the_work_order_floor():
    assert len(ENTRIES) >= 50
    assert sum(e["split"] == "heldout" for e in ENTRIES) >= 30
    assert all(measurement.case_problem(e) is None for e in ENTRIES)
    assert all(e["expect"]["facts"] and e["expect"]["args"] for e in ENTRIES)
    assert {e["family"] for e in ENTRIES} == {"search", "market"}
    # Figures beyond counts are exercised, not only sample sizes.
    full = [e for e in ENTRIES if e["expect"]["facts"].get("median_dom") is not None]
    assert len(full) >= 5


def test_the_runner_loads_them_as_ci_cases_in_their_own_category():
    cases, errors = runner.load_cases(runner.DEFAULT_CASES_DIR)
    assert errors == []
    ours = [c for c in cases if c.check == measurement.CHECK and c.set_version == 1]
    assert len(ours) == len(ENTRIES)
    assert all(c.suite == "ci" and c.category == "measurement" for c in ours)
    assert all(c.input_filters == dict(c.expect["args"]) for c in ours)
    assert {c.split for c in ours} == {"dev", "heldout"}


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"split": "tuning"}, "split"),
        ({"suite": "local"}, "suite ci"),
        ({"family": "market"}, "route must be"),
        ({"database": "any"}, "fixture"),
        ({"expect": {"route": ["search_listings"], "args": {}, "facts": {}}}, "args"),
    ],
)
def test_malformed_cases_are_refused(change, problem):
    entry = {**ENTRIES[0], **change}
    assert problem in (measurement.case_problem(entry) or "")


def test_a_fact_the_family_does_not_report_is_refused():
    entry = dict(ENTRIES[0])
    entry["expect"] = {**entry["expect"], "facts": {"median_dom": 1.0}}
    assert "facts for search" in measurement.case_problem(entry)


def test_the_truth_module_imports_only_the_pool_and_the_column_allowlist():
    allowed = {"idx_agent.db.pool", "idx_agent.safety.columns"}
    for path in (ROOT / "evals" / "truth").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                if name.startswith("idx_agent"):
                    assert name in allowed, f"{path.name} imports {name}"
                assert not name.startswith("evals"), f"{path.name} imports {name}"


def test_truth_statements_refuse_more_than_fifty_rows():
    class Rows:
        description = [("n",)]

        def fetchall(self):
            return [(i,) for i in range(51)]

    class Conn:
        def execute(self, sql, params):
            return Rows()

    with pytest.raises(ValueError, match="more than 50"):
        Truth(Conn(), mark="?")._rows("SELECT 1", ())


def test_the_split_hash_is_over_sorted_id_and_split_pairs():
    shuffled = list(reversed(ENTRIES))
    assert measurement.split_hash(shuffled) == measurement.split_hash(ENTRIES)
    flipped = [
        dict(ENTRIES[0], split="dev" if ENTRIES[0]["split"] != "dev" else "heldout")
    ]
    assert measurement.split_hash(flipped + ENTRIES[1:]) != measurement.split_hash(
        ENTRIES
    )


# --- the three scores on recorded synthetic transcripts ---


def _envelope(**facts):
    return SimpleNamespace(data=SimpleNamespace(**facts))


SEARCH = next(e for e in ENTRIES if e["family"] == "search")
MARKET = next(
    e
    for e in ENTRIES
    if e["family"] == "market" and e["expect"]["facts"].get("median_dom") is not None
)


def _right(entry):
    tool = entry["expect"]["route"][0]
    return (tool, dict(entry["expect"]["args"]), _envelope(**entry["expect"]["facts"]))


def test_a_right_transcript_scores_one_on_each_part():
    for entry in (SEARCH, MARKET):
        assert measurement.score_transcript(entry, [_right(entry)]) == {
            "route": 1,
            "args": 1,
            "answer": 1,
        }


def test_a_wrong_route_scores_zero_on_everything():
    tool, args, envelope = _right(SEARCH)
    wrong = [("get_market_stats", {"city": args.get("city", "Pasadena")}, envelope)]
    assert measurement.score_transcript(SEARCH, wrong) == {
        "route": 0,
        "args": 0,
        "answer": 0,
    }


def test_an_extra_call_is_a_wrong_route():
    assert measurement.score_transcript(SEARCH, [_right(SEARCH), _right(SEARCH)]) == {
        "route": 0,
        "args": 0,
        "answer": 0,
    }


def test_a_wrong_argument_keeps_the_route_and_loses_the_args():
    tool, args, envelope = _right(MARKET)
    other = dict(args, months=args.get("months", 6) % 6 + 1)
    assert measurement.score_transcript(MARKET, [(tool, other, envelope)]) == {
        "route": 1,
        "args": 0,
        "answer": 1,
    }


def test_a_wrong_number_loses_only_the_answer():
    tool, args, _ = _right(MARKET)
    facts = dict(MARKET["expect"]["facts"])
    facts["median_close_price"] += 1
    assert measurement.score_transcript(MARKET, [(tool, args, _envelope(**facts))]) == {
        "route": 1,
        "args": 1,
        "answer": 0,
    }
    facts = dict(MARKET["expect"]["facts"], sale_to_list_ratio=None)
    scored = measurement.score_transcript(MARKET, [(tool, args, _envelope(**facts))])
    assert scored["answer"] == 0


def test_the_ratio_tolerance_is_half_a_thousandth():
    assert measurement.fact_matches("sale_to_list_ratio", 0.998, 0.9984)
    assert not measurement.fact_matches("sale_to_list_ratio", 0.998, 0.999)
    assert not measurement.fact_matches("total_matches", 3, 4)
    assert measurement.fact_matches("median_dom", None, None)


def test_the_report_keeps_the_three_scores_apart_per_split_and_family():
    records = []
    for entry, transcript in (
        (SEARCH, [_right(SEARCH)]),
        (MARKET, [("search_listings", {"city": "Pasadena"}, _envelope())]),
    ):
        records.append(
            {
                "split": entry["split"],
                "family": entry["family"],
                "scores": measurement.score_transcript(entry, transcript),
            }
        )
    block = measurement.summary(records, "model")
    assert block["set_version"] == measurement.SET_VERSION
    search = block["scores"][SEARCH["split"]]["search"]
    market = block["scores"][MARKET["split"]]["market"]
    assert search == {"cases": 1, "route": 1, "args": 1, "answer": 1}
    assert market == {"cases": 1, "route": 0, "args": 0, "answer": 0}


# --- oracle mode against the MySQL fixture (CI's db step) ---


@pytest.mark.db
def test_oracle_mode_passes_on_the_fixture_database(tmp_path):
    cases, _ = runner.load_cases(runner.DEFAULT_CASES_DIR)
    ours = [c for c in cases if c.check == measurement.CHECK]
    ctx = runner.RunContext(require_database=True)
    try:
        records = [runner.run_case(c, ctx) for c in ours]
    finally:
        ctx.close()
    failed = [(r["id"], r["detail"]) for r in records if r["result"] != runner.PASS]
    assert failed == []


def test_presentation_arguments_do_not_cost_the_args_score():
    tool, args, envelope = _right(SEARCH)
    shown = dict(args, limit=10, page=1)
    assert measurement.score_transcript(SEARCH, [(tool, shown, envelope)])["args"] == 1
