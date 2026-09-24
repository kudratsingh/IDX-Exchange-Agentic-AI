#!/usr/bin/env bash
# scripts/jaeger-local.sh (WO-007): run the local Jaeger v2 collector and trace viewer.
# Uses the binary a human unpacked under .local/tools/jaeger/ (gitignored) or IDX_JAEGER_BIN,
# with config/jaeger-local.yaml (loopback only, memory storage). Never downloads anything.
# Runs in the foreground; Ctrl-C stops it and the in-memory traces are gone.
# See docs/TRACING.md and docs/adrs/0006-local-tracing.md.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$REPO/config/jaeger-local.yaml"

# fail MESSAGE: print "jaeger-local.sh: MESSAGE" to stderr and exit 1.
fail() { echo "jaeger-local.sh: $*" >&2; exit 1; }

# find_binary DIR: print the executable jaeger binary under DIR/.local/tools/jaeger whose
# version folder (jaeger-<version>-<platform>) sorts highest by `sort -V | tail -1`, if any.
find_binary() {
  local candidate
  for candidate in "$1"/.local/tools/jaeger/jaeger-*/jaeger; do
    if [ -x "$candidate" ]; then echo "$candidate"; fi
  done | sort -V | tail -1
  return 0
}

# 1. the binary: IDX_JAEGER_BIN, else this checkout, else the main checkout (from a worktree)
BIN="${IDX_JAEGER_BIN:-}"
if [ -z "$BIN" ]; then
  BIN="$(find_binary "$REPO")"
fi
if [ -z "$BIN" ]; then
  MAIN_GIT="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  [ -n "$MAIN_GIT" ] && BIN="$(find_binary "$(dirname "$MAIN_GIT")")"
fi
[ -n "$BIN" ] && [ -x "$BIN" ] || fail "no Jaeger binary found. Download the Jaeger v2 release for this
machine from the project's GitHub releases page by hand, check its sha256, unpack it under
.local/tools/jaeger/, or set IDX_JAEGER_BIN. This script never downloads anything."
[ -f "$CONFIG" ] || fail "missing $CONFIG"

# 2. check the config, then run in the foreground
"$BIN" validate --config="file:$CONFIG" >/dev/null 2>&1 || fail "$BIN rejected $CONFIG (run: $BIN validate --config=file:$CONFIG)"
echo "Jaeger: $BIN"
echo "OTLP/HTTP in:  http://127.0.0.1:4318   (set IDX_OTLP_ENDPOINT to this in .env)"
echo "Trace UI:      http://127.0.0.1:16686"
echo "Traces are kept in memory only; Ctrl-C stops Jaeger."
exec "$BIN" --config="file:$CONFIG"
