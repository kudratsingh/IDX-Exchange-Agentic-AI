#!/usr/bin/env bash
# scripts/chart_trial_armed.sh (WO-030, D5): arms the chart-trial rollback BEFORE
# activation. `arm` refuses unless scripts/chart_trial_rollback.sh, a private (700)
# record directory and a delete grant covering the whole armed window exist; then a
# watchdog in its own session runs the rollback exactly once, without waiting for any
# reply, on abort, on the operator's `done`, on a chart_delivery log line (+ settle),
# or at the timeout. Usage (docs/CHART_DELIVERY.md section 7):
#   scripts/chart_trial_armed.sh arm --record-dir DIR [--log FILE] [--activation-limit S]
#                                    [--timeout S] [--settle S]
#   scripts/chart_trial_armed.sh activated|abort|status RUN_DIR
#   scripts/chart_trial_armed.sh done RUN_DIR pass|fail
# Override: IDX_PYTHON (as the rollback). The logic is scripts/chart_trial_armed.py.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${IDX_PYTHON:-$REPO/.venv/bin/python}"
exec "$PYTHON" -I "$REPO/scripts/chart_trial_armed.py" "$@"
