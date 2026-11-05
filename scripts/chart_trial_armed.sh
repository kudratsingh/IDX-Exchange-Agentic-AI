#!/usr/bin/env bash
# scripts/chart_trial_armed.sh (WO-030, D5): arms the chart-trial rollback BEFORE
# activation. `arm` refuses unless scripts/chart_trial_rollback.sh, a private (700)
# record directory and a delete grant covering the whole armed window exist; it
# creates the trial's random id and key (run dir, mode 600; the key is never printed).
# Then a watchdog in its own session runs the rollback exactly once, without waiting
# for any reply, on abort, `done fail`, a missed deadline, `sent` + no-reply wait,
# SIGTERM, an unexpected error, or a chart_delivery log line the server signed with
# this trial's key (+ settle). A pass comes only from that signed line. After the
# rollback a tombstone refuses re-activation and a re-enable is rolled back again
# until the delete grant expires. Usage (docs/CHART_DELIVERY.md section 7):
#   scripts/chart_trial_armed.sh arm --record-dir DIR [--log FILE] [--activation-limit S]
#                                    [--timeout S] [--settle S] [--reply-wait S]
#                                    [--watch-after S]
#   scripts/chart_trial_armed.sh enable|activated|sent|abort|status RUN_DIR
#   scripts/chart_trial_armed.sh done RUN_DIR fail
# Override: IDX_PYTHON (as the rollback). The logic is scripts/chart_trial_armed.py.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${IDX_PYTHON:-$REPO/.venv/bin/python}"
exec "$PYTHON" -I "$REPO/scripts/chart_trial_armed.py" "$@"
