"""Offline re-judgment of a saved local-suite report's description-routing failures.

Model-free and key-free: it reads one saved report (never writes it), checks the
report's sha256 against the one given, and re-judges each `description_routing`
failure against its case's original `expect` with the corrected checker of
`evals.run` (the tuple-versus-list fix). It verifies a failure only when the
saved record proves the call: the same route, one step, the only differing
argument `features`, every expected argument key among those sent, and the
reconstructed call passing the corrected checker while the raw comparison
reproduces the original failure. Anything else stays unverified.

    python -m evals.rejudge --report evals/runs/relay-measure-01.json \\
        --sha256 <64 hex> --fix-commit <sha> --out evals/runs/<new>.json

The output is a new file (never an overwrite) holding counts, case ids, the
hashes and commits it relied on, and per attempt a verdict with its reasons.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals import run as runner

CATEGORY = "description_routing"
CASES_FILE = "evals/cases/description_routing.yaml"
_DETAIL = re.compile(r"^step (\d+) ([a-z_]+): differs on (\{.*\})$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=runner.ROOT, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {done.stderr.strip()[:200]}")
    return done.stdout.strip()


def judge_failure(case: Any, entry: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """(verified, reasons) for one saved failure of `case` (see the module notes)."""
    reasons: list[str] = []
    routes = runner.route_options(case.expect)
    if len(routes) != 1 or len(routes[0][0]) != 1:
        return False, ["the case does not pin one single-step route"]
    (want_route, subsets) = routes[0]
    subset = dict(subsets[0])
    calls = entry.get("calls") or []
    got_route = [c.get("name") for c in calls]
    if got_route != want_route:
        return False, [f"route {got_route} is not {want_route}"]
    reasons.append(f"route {got_route} as expected")
    match = _DETAIL.match(str(entry.get("detail") or ""))
    if match is None or match.group(1) != "1" or match.group(2) != want_route[0]:
        return False, [*reasons, "the detail is not one step-1 argument difference"]
    try:
        wrong = ast.literal_eval(match.group(3))
    except (ValueError, SyntaxError):
        return False, [*reasons, "the detail's differing arguments do not parse"]
    if not isinstance(wrong, dict) or set(wrong) != {"features"}:
        return False, [
            *reasons,
            f"differing arguments {sorted(wrong)} are not features",
        ]
    sent = wrong["features"]
    if not isinstance(sent, tuple) or not all(isinstance(f, str) for f in sent):
        return False, [*reasons, "the recorded features are not a validated tuple"]
    reasons.append("only features differed; every other expected argument matched")
    keys = set(calls[0].get("argument_keys") or [])
    if not set(subset) <= keys:
        return False, [*reasons, f"expected keys {sorted(set(subset) - keys)} unsent"]
    reasons.append(f"argument keys sent {sorted(keys)}")
    expected = subset["features"]
    if sent == expected:
        return False, [*reasons, "the raw comparison would not have failed"]
    reasons.append("raw comparison reproduces the failure (tuple against list)")
    # The other expected keys matched the validated call, so they hold the case's
    # values; `features` is what the validator stored for the sent call.
    arguments = {**subset, "features": list(sent)}
    result, detail = runner.check_route_exact(
        case, [runner.ToolCall(want_route[0], arguments)]
    )
    if result != runner.PASS:
        return False, [*reasons, f"corrected checker: {detail}"]
    reasons.append(f"corrected checker passes: {detail}")
    return True, reasons


def rejudge(
    report: Mapping[str, Any], cases: Sequence[Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Per-attempt verdicts for every description_routing entry, and the counts."""
    by_id = {c.id: c for c in cases}
    rows: list[dict[str, Any]] = []
    for entry in report.get("cases") or []:
        if entry.get("category") != CATEGORY:
            continue
        raw = entry.get("result")
        row = {"id": entry.get("id"), "run": entry.get("run"), "raw": raw}
        if raw == runner.PASS:
            row |= {"corrected": "pass", "reasons": ["raw pass, kept"]}
        elif raw == runner.FAIL and entry.get("id") in by_id:
            ok, reasons = judge_failure(by_id[entry["id"]], entry)
            row |= {"corrected": "pass" if ok else "unverified", "reasons": reasons}
        else:
            row |= {"corrected": "unverified", "reasons": [f"raw {raw}, not judged"]}
        rows.append(row)
    counts = {
        "attempts": len(rows),
        "raw_pass": sum(r["raw"] == "pass" for r in rows),
        "raw_fail": sum(r["raw"] == "fail" for r in rows),
        "verified_failures": sum(
            r["raw"] == "fail" and r["corrected"] == "pass" for r in rows
        ),
        "corrected_pass": sum(r["corrected"] == "pass" for r in rows),
        "unverified": sum(r["corrected"] == "unverified" for r in rows),
    }
    return rows, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--fix-commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    data = args.report.read_bytes()
    digest = _sha256(data)
    if digest != args.sha256.lower():
        print(f"refused: the report's sha256 is {digest}, not the one given")
        return 2
    if args.out.exists() or args.out.resolve() == args.report.resolve():
        print("refused: --out exists or is the report; nothing is overwritten")
        return 2
    report = json.loads(data)
    head = _git("rev-parse", "HEAD")
    fix = _git("rev-parse", args.fix_commit)
    _git("merge-base", "--is-ancestor", fix, head)  # raises unless fix is in HEAD
    run_commit = str(report.get("git_commit") or "")
    then = _git("rev-parse", f"{run_commit}:{CASES_FILE}")
    now = _git("hash-object", CASES_FILE)
    if then != now:
        print("refused: the case file changed since the report's commit")
        return 2
    cases, errors = runner.load_cases(runner.DEFAULT_CASES_DIR)
    if errors:
        print(f"refused: {len(errors)} case files fail to load")
        return 2
    rows, counts = rejudge(report, [c for c in cases if c.category == CATEGORY])
    record = {
        "kind": "offline description_routing re-judgment",
        "defect": "evals.run _match_subset compared the validator's sorted features "
        "tuple with the case file's list, so a correct call outside mode: update "
        "always failed (fixed in --fix-commit)",
        "report": str(args.report),
        "report_sha256": digest,
        "report_git_commit": run_commit,
        "report_run_at": report.get("run_at"),
        "checker_fix_commit": fix,
        "rejudged_at_commit": head,
        "cases_file_blob": now,
        "counts": counts,
        "attempts": rows,
        "all_failures_verified": counts["verified_failures"] == counts["raw_fail"],
    }
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("report_sha256", "counts")}, indent=2))
    print(f"all failures verified: {record['all_failures_verified']}; wrote {args.out}")
    return 0 if record["all_failures_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
