#!/usr/bin/env bash
# scripts/chart_trial_rollback.sh (WO-030, D5): the rollback that ends the one live
# WhatsApp chart trial, run at once after the trial turn completes or fails, without
# waiting for anyone's reply. Usage: scripts/chart_trial_rollback.sh pass|fail|aborted
# (the observed trial result, copied into the record).
#
# Steps, in order; each runs even when an earlier one failed, and each is reported:
#   1. .env: every IDX_ANALYSIS_TOOL and IDX_CHART_DELIVERY line is edited in place to
#      =0 (the first line for a key wins, so appending a line would not turn it off);
#      other lines, and the file mode, are kept
#   2. scripts/install.sh (removes the analysis skill-list fragment; reports charts off)
#   3. openclaw gateway restart
#   4. python -m idx_agent.analysis.delivery prune --all (our chart files only)
#   5. the launchd prune job (docs/CHART_DELIVERY.md 5b): bootout only if loaded, rm the
#      plist only if present; neither present is reported as "not installed"
#   6. verification that analysis and chart delivery are off (see the record)
# It never bootstraps, copies or loads anything. Exit 0 only when every step and every
# check passed ("ROLLBACK DONE"); else 1 ("ROLLBACK INCOMPLETE: <what>"); 2 for a bad
# argument, with nothing changed.
# Overrides: IDX_PYTHON, OPENCLAW_STATE_DIR (as install.sh).
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${IDX_PYTHON:-$REPO/.venv/bin/python}"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
LABEL=local.idx-exchange.chart-prune
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVICE="gui/$(id -u)/$LABEL"

case "${1:-}" in
  pass | fail | aborted) RESULT="$1" ;;
  *)
    echo "usage: scripts/chart_trial_rollback.sh pass|fail|aborted" >&2
    exit 2
    ;;
esac

STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
FAILED=()
RECORD=()
# note LINE: one line of the record, also printed now.
note() { RECORD+=("$1"); echo "$1"; }

# joined ITEM...: the items separated by ", ".
joined() { local out="" item; for item in "$@"; do out="${out:+$out, }$item"; done; echo "$out"; }

# 1. .env switch lines to 0, in place (dotenv_values' own line rules)
if EDITED="$("$PYTHON" - "$REPO/.env" <<'PY'
import os
import pathlib
import sys
import tempfile

path = pathlib.Path(sys.argv[1])
keys = ("IDX_ANALYSIS_TOOL", "IDX_CHART_DELIVERY")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
counts = dict.fromkeys(keys, 0)
for i, line in enumerate(lines):
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        continue
    key = text.partition("=")[0].strip().removeprefix("export ").strip()
    if key in counts:
        counts[key] += 1
        lines[i] = f"{key}=0" + ("\n" if line.endswith("\n") else "")
mode = path.stat().st_mode & 0o777
fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
with os.fdopen(fd, "w", encoding="utf-8") as out:
    out.write("".join(lines))
os.chmod(tmp, mode)
os.replace(tmp, path)
print(", ".join(f"{k} {n} line(s) set to 0" if n else f"{k} no line" for k, n in counts.items()))
PY
)"; then
  note "step .env: $EDITED"
else
  note "step .env: FAILED"
  FAILED+=(".env")
fi

# 2. install.sh (its own output shown; refusals stop only this step)
if INSTALL_OUT="$("$REPO/scripts/install.sh" 2>&1)"; then
  if grep -qE '^(Bounded analysis is on|Chart delivery is on)' <<<"$INSTALL_OUT"; then
    note "step install.sh: FAILED (it still reports analysis or charts on)"
    FAILED+=("install.sh")
  else
    note "step install.sh: ok"
  fi
else
  note "step install.sh: FAILED ($(tail -1 <<<"$INSTALL_OUT"))"
  FAILED+=("install.sh")
fi

# 3. gateway restart
if openclaw gateway restart >/dev/null 2>&1; then
  note "step gateway restart: ok"
else
  note "step gateway restart: FAILED"
  FAILED+=("gateway restart")
fi

# 4. remove every chart file of ours (the lock file stays)
if PRUNED="$(cd "$REPO" && "$PYTHON" -m idx_agent.analysis.delivery prune --all 2>&1)"; then
  note "step prune --all: $PRUNED"
else
  note "step prune --all: FAILED ($PRUNED)"
  FAILED+=("prune --all")
fi

# 5. the launchd prune job, guarded: only what is there is removed
JOB=()
if launchctl print "$SERVICE" >/dev/null 2>&1; then
  if launchctl bootout "$SERVICE" >/dev/null 2>&1; then
    JOB+=("booted out")
  else
    JOB+=("bootout FAILED")
    FAILED+=("launchd bootout")
  fi
fi
if [ -e "$PLIST" ] || [ -L "$PLIST" ]; then
  if rm -f "$PLIST"; then
    JOB+=("plist removed")
  else
    JOB+=("plist rm FAILED")
    FAILED+=("launchd plist")
  fi
fi
if [ "${#JOB[@]}" -eq 0 ]; then
  note "step launchd prune job: not installed"
else
  note "step launchd prune job: $(joined "${JOB[@]}")"
fi

# 6. verification: what the server would decide now from this .env and this shell,
#    what OpenClaw lists, and that launchd no longer knows the job
PROBE="$(cd "$REPO" && "$PYTHON" - <<'PY' 2>/dev/null
import re

from idx_agent.analysis import delivery
from idx_agent.db.pool import dotenv_values
from idx_agent.mcp_server import server as s

ours = re.compile(r"\.?chart-[0-9a-f]{32}\.(png|tmp)")  # chart files and temp files
values = dotenv_values()
switches = ", ".join(
    f"{k} {'on' if values.get(k) == '1' else 'off'}"
    for k in ("IDX_ANALYSIS_TOOL", "IDX_CHART_DELIVERY")
)
registered = s.register_analysis_tool()
listed = "bounded_analysis" in s.tool_names()
charts = s.configure_chart_delivery()
health = s.health_result()
mentions = any(w in health.message.lower() for w in ("analysis", "chart"))
directory = delivery.chart_dir(values.get)
files = (
    sum(1 for p in directory.iterdir() if ours.fullmatch(p.name))
    if directory is not None and directory.is_dir()
    else 0
)
print(f"verify .env: {switches}")
print(
    f"verify server: bounded_analysis {'registered' if registered else 'absent'}"
    f" ({'listed' if listed else 'not listed'}), chart_state "
    f"{'on' if charts else 'off'}, problems {s.analysis_switch_problem()}"
    f" / {s.chart_delivery_problem()}"
)
print(
    f"verify health: {len(health.warnings)} warning(s), "
    f"{'mentions' if mentions else 'no'} analysis/chart line"
)
print(f"verify chart files: {files}")
PY
)" || PROBE=""
EXPECTED_PROBE="verify .env: IDX_ANALYSIS_TOOL off, IDX_CHART_DELIVERY off
verify server: bounded_analysis absent (not listed), chart_state off, problems None / None
verify health: 0 warning(s), no analysis/chart line
verify chart files: 0"
if [ "$PROBE" = "$EXPECTED_PROBE" ]; then
  while IFS= read -r line; do note "$line"; done <<<"$PROBE"
else
  while IFS= read -r line; do [ -n "$line" ] && note "$line"; done <<<"$PROBE"
  [ -n "$PROBE" ] || note "verify server: FAILED (the probe did not run)"
  FAILED+=("server probe")
fi

if DOCTOR="$(openclaw mcp doctor idx --probe 2>&1)"; then
  N="$(grep -c bounded_analysis <<<"$DOCTOR")"
  note "verify mcp doctor: bounded_analysis listed $N time(s)"
  [ "$N" = 0 ] || FAILED+=("mcp doctor")
else
  note "verify mcp doctor: FAILED (the probe did not run)"
  FAILED+=("mcp doctor")
fi
if SKILLS="$(openclaw skills list 2>&1)"; then
  N="$(grep -c bounded-analysis <<<"$SKILLS")"
  note "verify skills: bounded-analysis listed $N time(s)"
  [ "$N" = 0 ] || FAILED+=("skills")
else
  note "verify skills: FAILED (the list did not run)"
  FAILED+=("skills")
fi
if [ -e "$STATE_DIR/openclaw.analysis.json5" ]; then
  note "verify analysis fragment: PRESENT"
  FAILED+=("analysis fragment")
else
  note "verify analysis fragment: absent"
fi
if PRINTED="$(launchctl print "$SERVICE" 2>&1)"; then
  note "verify launchctl: the job is still loaded"
  FAILED+=("launchctl")
elif grep -q "Could not find service" <<<"$PRINTED"; then
  note "verify launchctl: Could not find service"
else
  note "verify launchctl: FAILED ($(head -1 <<<"$PRINTED"))"
  FAILED+=("launchctl")
fi

FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""
echo "chart trial rollback record (WO-030, D5)"
echo "  trial result: $RESULT"
echo "  rollback started: $STARTED  finished: $FINISHED"
for line in "${RECORD[@]}"; do echo "  $line"; done
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "ROLLBACK DONE: analysis off, chart delivery off"
  exit 0
fi
echo "ROLLBACK INCOMPLETE: $(joined "${FAILED[@]}")"
exit 1
