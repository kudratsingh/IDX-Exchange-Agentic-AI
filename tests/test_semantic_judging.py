"""Tests for the no-cost semantic judging-sheet scorer."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import evals.run as eval_run

from idx_agent.domain.models import SimilarResult

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "semantic_spike.py"
SPEC = importlib.util.spec_from_file_location("semantic_spike_for_tests", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
spike = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spike)


def _write_sheet(path: Path, rows: list[tuple[str, int]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relevant", "listing_key"])
        writer.writeheader()
        writer.writerows(
            {"relevant": relevant, "listing_key": listing_key}
            for relevant, listing_key in rows
        )


def _write_order(path: Path, ranked: list[int]) -> None:
    path.write_text(json.dumps({"ranked": ranked}), encoding="utf-8")


def test_score_main_writes_only_fully_marked_judgments(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    judging_dir = tmp_path / "judging"
    judging_dir.mkdir()
    good = [9123001, 9123002, 9123003, 9123004, 9123005, 9123006]
    _write_sheet(
        judging_dir / "good.csv",
        [("y", good[0]), ("n", good[1]), ("y", good[5])],
    )
    _write_order(judging_dir / "good.order.json", good)
    _write_sheet(judging_dir / "unmarked.csv", [("", 9123011)])
    _write_order(judging_dir / "unmarked.order.json", [9123011])
    _write_sheet(judging_dir / "bad-mark.csv", [("maybe", 9123021)])
    _write_order(judging_dir / "bad-mark.order.json", [9123021])

    monkeypatch.setattr(spike, "ROOT", tmp_path)
    monkeypatch.setattr(spike, "JUDGING_DIR", judging_dir)
    monkeypatch.setattr(spike, "JUDGMENTS_FILE", judging_dir / "judgments.json")
    monkeypatch.setattr(
        spike,
        "judged_queries",
        lambda: [
            {"query_id": "good", "args": {}},
            {"query_id": "unmarked", "args": {}},
            {"query_id": "bad-mark", "args": {}},
        ],
    )

    assert spike.score_main() == 0

    written = json.loads((judging_dir / "judgments.json").read_text())
    assert written == {
        "format_version": 1,
        "queries": {"good": {"judged": good, "relevant": [good[0], good[5]]}},
    }
    output = capsys.readouterr().out
    assert "unmarked | 1 row(s) not marked y or n; not scored" in output
    assert "bad-mark | 1 row(s) not marked y or n; not scored" in output


def test_runner_scores_recall_at_five_from_written_marks() -> None:
    ranked = [9123001, 9123002, 9123003, 9123004, 9123005, 9123006]
    matches = [
        SimpleNamespace(listing=SimpleNamespace(listing_key=listing_key))
        for listing_key in ranked
    ]
    result = SimilarResult.model_construct(matches=matches)
    envelope = SimpleNamespace(ok=True, data=result)
    marks = {
        "good": eval_run.Judgment(
            judged=tuple(ranked), relevant=frozenset({9123001, 9123006})
        )
    }

    outcome = eval_run._score_recall({"query_id": "good", "k": 5}, envelope, marks)

    assert outcome[0] == eval_run.PASS
    assert "recall@5 0.50" in outcome[1]
    assert "precision@5 0.20" in outcome[1]
