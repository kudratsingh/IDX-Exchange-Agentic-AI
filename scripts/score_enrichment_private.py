"""Print aggregate label scores for operator-prepared private enrichment files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from idx_agent.enrichment.private_scoring import score_private_labels

PRIVATE_DIR = Path(__file__).resolve().parents[1] / "data" / "enrichment"


def _read_private(root: Path, name: str) -> dict:
    if root.is_symlink():
        raise ValueError("invalid private directory")
    resolved_root = root.resolve(strict=True)
    target = (resolved_root / name).resolve(strict=True)
    if target.parent != resolved_root or not target.is_file():
        raise ValueError("invalid private file")
    with target.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("invalid private file")
    return value


def score_files(root: Path, split: str) -> dict:
    """Read fixed files and return only the chosen split's aggregate metrics."""
    if split not in {"dev", "test"}:
        raise ValueError("invalid split")
    sample = _read_private(root, "sample.json")
    labels = _read_private(root, "labels.json")
    predictions = _read_private(root, f"predictions-{split}.json")
    cases = sample.get("cases")
    if (
        not isinstance(cases, list)
        or sum(isinstance(case, dict) and case.get("split") == split for case in cases)
        != {"dev": 100, "test": 150}[split]
    ):
        raise ValueError("incorrect split size")
    result = score_private_labels(sample, labels, predictions, split)
    return {
        key: {
            "expected": counts.expected,
            "predicted": counts.predicted,
            "correct": counts.correct,
            "precision": counts.precision,
            "recall": counts.recall,
            "f1": counts.f1,
        }
        for key, counts in result.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    args = parser.parse_args()
    try:
        result = score_files(PRIVATE_DIR, args.split)
    except (OSError, ValueError, TypeError, KeyError):
        print(
            "Scoring failed: check the private input files and complete split labels."
        )
        return 1
    print(json.dumps({"split": args.split, "counts": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
