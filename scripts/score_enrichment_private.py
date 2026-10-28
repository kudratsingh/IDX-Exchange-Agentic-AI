"""Print aggregate label scores for operator-prepared private enrichment files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from idx_agent.enrichment.private_scoring import score_private_labels

PRIVATE_DIR = Path.cwd() / "data" / "enrichment"


def _private_path(root: Path, name: str) -> Path:
    if root.is_symlink():
        raise ValueError("invalid private directory")
    resolved_root = root.resolve(strict=True)
    target = (resolved_root / name).resolve(strict=True)
    if target.parent != resolved_root or not target.is_file():
        raise ValueError("invalid private file")
    return target


def _read_private(root: Path, name: str) -> dict:
    with _private_path(root, name).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("invalid private file")
    return value


def _sample_jsonl(root: Path, split: str) -> dict:
    """Parse only requested-split remarks; retain other split keys as placeholders."""
    manifest = _read_private(root, "splits.json")
    splits = manifest.get("splits")
    if (
        manifest.get("version") != 1
        or not isinstance(splits, dict)
        or len(splits) != 250
    ):
        raise ValueError("invalid private sample")
    cases, seen = [], set()
    pattern = re.compile(r'^\s*\{\s*"key"\s*:\s*"([0-9]+)"')
    with _private_path(root, "sample.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            match = pattern.match(line)
            if not match:
                raise ValueError("invalid private sample")
            key = match.group(1)
            if key not in splits or key in seen or splits[key] not in {"dev", "test"}:
                raise ValueError("invalid private sample")
            seen.add(key)
            text = ""
            if splits[key] == split:
                row = json.loads(line)
                if (
                    not isinstance(row, dict)
                    or set(row) != {"key", "subtype", "remark"}
                    or row["key"] != key
                    or not isinstance(row["subtype"], str)
                    or not isinstance(row["remark"], str)
                ):
                    raise ValueError("invalid private sample")
                text = row["remark"]
            cases.append({"id": key, "split": splits[key], "text": text})
    if seen != set(splits):
        raise ValueError("invalid private sample")
    return {"version": 1, "dataset_id": manifest.get("dataset_id"), "cases": cases}


def score_files(root: Path, split: str) -> dict:
    """Read fixed files and return only the chosen split's aggregate metrics."""
    if split not in {"dev", "test"}:
        raise ValueError("invalid split")
    if (root / "sample.jsonl").exists():
        sample = _sample_jsonl(root, split)
    else:
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
    overlap = score_private_labels(
        sample, labels, predictions, split, categorical_overlap=True
    )
    counts = {
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
    included = [
        value.f1
        for key, value in result.items()
        if key.startswith(("facet.", "numeric.")) and value.expected > 0
    ]
    disagreements = [
        {
            "facet": key,
            "false_positive_spans": value.predicted - value.correct,
            "false_negative_spans": value.expected - value.correct,
        }
        for key, value in result.items()
        if key.startswith(("facet.", "numeric."))
        and value.expected + value.predicted > 2 * value.correct
    ]
    disagreements.sort(
        key=lambda item: (
            -(item["false_positive_spans"] + item["false_negative_spans"]),
            item["facet"],
        )
    )
    overlap_counts = {
        key: {
            "expected": value.expected,
            "predicted": value.predicted,
            "correct": value.correct,
            "precision": value.precision,
            "recall": value.recall,
            "f1": value.f1,
        }
        for key, value in overlap.items()
        if not key.startswith("polarity.")
    }
    return {
        "overlap_counts": overlap_counts,
        "worst_disagreements": disagreements[:10],
        "counts": counts,
        "macro_f1": sum(included) / len(included) if included else None,
        "macro_supported_classes": len(included),
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
    print(json.dumps({"split": args.split, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
