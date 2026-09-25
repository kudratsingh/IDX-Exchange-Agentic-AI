#!/usr/bin/env bash
# Human-only CLI: grant a short consent window for one kind (delete|paid|gates).
# Usage: consent.sh delete|gates [minutes, default 15]
#        consent.sh paid [minutes] --command "<argv words>" --max-calls <N>
#        consent.sh revoke <kind> | status (the default).
# A paid token covers one run of that exact command line with at most N provider
# calls; the hook admits that command once, the run spends the token when it
# starts, and a second run needs a new token. The minutes bound the run too.
# Run it yourself: prefix with "!" at the CLI prompt, or use another terminal.
# guard.py refuses tool calls that run this script or touch .local/consent/.
# Wraps consent_token.py, which writes the token and .local/consent/audit.log.
set -euo pipefail

# Directory of this script, so consent_token.py resolves from any cwd.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USAGE='usage: scripts/guards/consent.sh delete|gates [minutes] | paid [minutes] --command "<argv words>" --max-calls <N> | revoke <kind> | status'

# Dispatch on the first argument; exec passes on consent_token.py's exit code.
case "${1:-status}" in
  delete|gates)
    exec python3 "$HERE/consent_token.py" grant "$1" "${2:-15}"
    ;;
  paid)
    shift
    if [ "$#" -eq 0 ]; then
      echo "$USAGE" >&2
      exit 2
    fi
    exec python3 "$HERE/consent_token.py" grant paid "$@"
    ;;
  revoke)
    exec python3 "$HERE/consent_token.py" revoke "${2:?usage: consent.sh revoke <delete|paid|gates>}"
    ;;
  status)
    exec python3 "$HERE/consent_token.py" status
    ;;
  *)
    echo "$USAGE" >&2
    exit 2
    ;;
esac
