"""Gate 4: no deletion of a tracked file without human consent (docs/AGENT_RULES.md, rule 1).

At commit (pre-commit, always_run): every staged deletion is listed with
``git diff --cached --name-status -M``. Renames pass, ``.gitkeep`` files pass, anything
else needs a valid ``delete`` consent token (``scripts/guards/consent.sh delete``).

In CI (``--range BASE...HEAD`` on pull_request): the same listing over the whole PR.
Deletions pass only with ``--approved``, which the workflow sets when the PR carries the
``deletion-approved`` label. A human applies the label; the agent's guard refuses to.
"""

import pathlib
import subprocess
import sys

from gatelib import fail

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "guards"))

import consent_token as ct  # noqa: E402

EXEMPT_NAMES = {".gitkeep"}


def parse_name_status(text):
    """Deleted paths from `git diff --name-status -M` output. Renames and .gitkeep pass."""
    deleted = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("D"):
            path = parts[1]
            if pathlib.PurePosixPath(path).name not in EXEMPT_NAMES:
                deleted.append(path)
    return deleted


def list_deletions(range_spec=None, cwd=None):
    args = ["git", "diff", "--name-status", "-M"]
    args.append(range_spec if range_spec else "--cached")
    out = subprocess.run(args, capture_output=True, text=True, check=True, cwd=cwd)
    return parse_name_status(out.stdout)


def main(argv):
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
        how = "a human adds the `deletion-approved` label to the PR and re-runs CI"
    else:
        allowed = ct.is_valid("delete")
        how = (
            "the human runs:  ! scripts/guards/consent.sh delete   (a 15-minute window)"
        )
    if allowed:
        if not range_spec:
            ct.log("use", "delete", f"gate 4: {len(deleted)} staged deletion(s)")
        print(
            f"protected_deletions: {len(deleted)} deletion(s) allowed by human consent"
        )
        for path in deleted:
            print(f"  {path}")
        return
    if not range_spec:
        ct.log("block", "delete", f"gate 4: {len(deleted)} staged deletion(s)")
    fail(
        "BLOCKED by the protected-deletions gate (docs/AGENT_RULES.md, rule 1). "
        "Deleting a tracked file needs human consent:\n"
        + "\n".join(f"  {path}" for path in deleted)
        + f"\nTo proceed, {how}. Renames and .gitkeep files pass without consent."
    )


if __name__ == "__main__":
    main(sys.argv)
