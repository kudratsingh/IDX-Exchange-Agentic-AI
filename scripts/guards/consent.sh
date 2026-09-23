#!/usr/bin/env bash
# Grant the coding agent a short window of human consent for one kind of guarded action.
#
# Run this YOURSELF. In the Claude Code prompt type it with a leading "!", which runs
# the command as you rather than as the agent:
#
#   ! scripts/guards/consent.sh delete            allow deleting files or discarding work (15 min)
#   ! scripts/guards/consent.sh paid 30           allow a paid model or API run (30 min)
#   ! scripts/guards/consent.sh gates             allow editing gates, guards, hooks, CI, .gitignore
#   ! scripts/guards/consent.sh revoke paid       end a window early
#   ! scripts/guards/consent.sh status            show what is currently granted
#
# Or run it from another terminal in the repo. The agent's own Bash tool is refused by
# scripts/guards/guard.py whenever it tries to run this script or touch .local/consent/.
# Every grant, use, and block is appended to .local/consent/audit.log.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-status}" in
  delete|paid|gates)
    exec python3 "$HERE/consent_token.py" grant "$1" "${2:-15}"
    ;;
  revoke)
    exec python3 "$HERE/consent_token.py" revoke "${2:?usage: consent.sh revoke <delete|paid|gates>}"
    ;;
  status)
    exec python3 "$HERE/consent_token.py" status
    ;;
  *)
    echo "usage: scripts/guards/consent.sh delete|paid|gates [minutes] | revoke <kind> | status" >&2
    exit 2
    ;;
esac
