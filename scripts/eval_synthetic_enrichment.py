"""Evaluate the provisional extractor on the committed invented development cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idx_agent.domain.enrichment import SyntheticAnnotationCase  # noqa: E402
from idx_agent.enrichment.annotation_scoring import Counts, score_dataset  # noqa: E402
from idx_agent.enrichment.synthetic_extractor import extract_synthetic  # noqa: E402


def _counts(value: Counts) -> dict[str, int | float | None]:
    return {
        "expected": value.expected,
        "predicted": value.predicted,
        "correct": value.correct,
        "precision": value.precision,
        "recall": value.recall,
    }


def main() -> int:
    """Use the fixed invented dev fixture; print counts only and never real text."""
    if len(sys.argv) != 1:
        print("This synthetic development check accepts no arguments.", file=sys.stderr)
        return 2
    path = ROOT / "tests" / "fixtures" / "enrichment" / "dev.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = [SyntheticAnnotationCase.model_validate(item) for item in raw]
    if any(case.split != "dev" or case.source != "synthetic" for case in expected):
        raise ValueError("expected invented development cases")
    score = score_dataset(expected, [extract_synthetic(case) for case in expected])
    print(
        json.dumps(
            {
                "scope": "invented_development_only_not_a_real_data_benchmark",
                "cases": score.cases,
                "overall": _counts(score.overall),
                "by_facet": {
                    key: _counts(value) for key, value in score.by_facet.items()
                },
                "by_polarity": {
                    key: _counts(value) for key, value in score.by_polarity.items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
