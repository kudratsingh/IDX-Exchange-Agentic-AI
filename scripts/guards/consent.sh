#!/usr/bin/env bash
# Human-only CLI: grant a short consent window for one kind (delete|paid|gates).
# Usage: consent.sh <kind> [minutes, default 15] | revoke <kind> | status (the default).
# Run it yourself: prefix with "!" at the CLI prompt, or use another terminal.
# guard.py refuses tool calls that run this script or touch .local/consent/.
# Wraps consent_token.py, which writes the token and .local/consent/audit.log.
set -euo pipefail

# Directory of this script, so consent_token.py resolves from any cwd.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Dispatch on the first argument; exec passes on consent_token.py's exit code.
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
