"""Gate 4: no deletion of a tracked file without human consent (docs/AGENT_RULES.md, rule 1).

Pre-commit (always_run): staged deletions need a `delete` token; exit 1 blocks.
CI (--range HEAD^1...HEAD on a PR): needs --approved, set by the `deletion-approved`
label, which any repo-token holder can add; main's ruleset and review are the boundary.
"""

import pathlib
import subprocess
import sys

from gatelib import fail

HERE = pathlib.Path(__file__).resolve().parent
# consent_token lives in scripts/guards/; make it importable from here.
sys.path.insert(0, str(HERE.parent / "guards"))

import consent_token as ct  # noqa: E402

# File names whose deletion never needs consent.
EXEMPT_NAMES = {".gitkeep"}


def parse_name_status(text):
    """Return deleted paths from `git diff --name-status -M` output.

    Only lines with a D status count; renames (R), edits and adds are ignored,
    and paths named .gitkeep are dropped.
    """
    deleted = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("D"):
            path = parts[1]
            if pathlib.PurePosixPath(path).name not in EXEMPT_NAMES:
                deleted.append(path)
    return deleted


def list_deletions(range_spec=None, cwd=None):
    """Return non-exempt deleted paths from git diff with rename detection.

    Input: range_spec (CI, e.g. HEAD^1...HEAD) or None for the staged index.
    """
    args = ["git", "diff", "--name-status", "-M"]
    args.append(range_spec if range_spec else "--cached")
    out = subprocess.run(args, capture_output=True, text=True, check=True, cwd=cwd)
    return parse_name_status(out.stdout)


# Decision steps, in execution order:
# 1. List deletions (staged index, or the --range diff in CI).
# 2. Exempt renames and .gitkeep files; if nothing is left, print ok and return.
# 3. Pre-commit: read the delete token from the checkout that owns the git common dir,
#    ignoring env vars, so a prefix on `git commit` cannot point it at a fake token.
#    CI: the only approval is the --approved flag.
# 4. Allow (log "use", print the paths) or fail (log "block", exit 1).
def main(argv):
    """Parse --range/--approved from argv and apply the decision steps above."""
    range_spec = None
    approved = False
    args = iter(argv[1:])
    for arg in args:
        if arg == "--range":
            range_spec = next(args, None)
        elif arg == "--approved":
            approved = True
    deleted = list_deletions(range_spec)
    if not deleted:
        print("protected_deletions: ok (no deletions)")
        return
    if range_spec:
        allowed = approved
        how = "a human adds the `deletion-approved` label to the PR (CI re-runs on it)"
    else:
        allowed = ct.is_valid("delete", ignore_env=True)
        how = (
            "the human runs:  ! scripts/guards/consent.sh delete   (a 15-minute window)"
        )
    if allowed:
        if not range_spec:
            ct.log("use", "delete", f"gate 4: {len(deleted)} staged deletion(s)", True)
        print(
            f"protected_deletions: {len(deleted)} deletion(s) allowed by human consent"
        )
        for path in deleted:
            print(f"  {path}")
        return
    if not range_spec:
        ct.log("block", "delete", f"gate 4: {len(deleted)} staged deletion(s)", True)
    fail(
        "BLOCKED by the protected-deletions gate (docs/AGENT_RULES.md, rule 1). "
        "Deleting a tracked file needs human consent:\n"
        + "\n".join(f"  {path}" for path in deleted)
        + f"\nTo proceed, {how}. Renames and .gitkeep files pass without consent."
    )


if __name__ == "__main__":
    main(sys.argv)
