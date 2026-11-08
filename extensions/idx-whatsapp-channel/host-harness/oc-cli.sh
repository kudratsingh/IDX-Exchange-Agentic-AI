#!/bin/sh
# Runs one OpenClaw CLI command against a harness run root, with the same isolation as
# run.mjs (env -i, temporary home/state/config, sandbox denying ~/.openclaw and outbound
# network except loopback). Usage: oc-cli.sh <run-root> <openclaw args...>
set -eu
ROOT="$1"; shift
PKG="${OPENCLAW_PKG:-$HOME/.npm-global/lib/node_modules/openclaw}"
NODE="$(command -v node)"
cd "$ROOT/cwd"
exec env -i PATH="$PATH" HOME="$ROOT/home" TMPDIR="$ROOT/cwd" OPENCLAW_HOME="$ROOT/home" \
  OPENCLAW_STATE_DIR="$ROOT/state" OPENCLAW_CONFIG_PATH="$ROOT/state/openclaw.json" \
  OPENCLAW_NO_AUTO_UPDATE=1 OPENCLAW_DISABLE_BONJOUR=1 OPENCLAW_OFFLINE=1 OPENCLAW_NO_RESPAWN=1 DO_NOT_TRACK=1 \
  /usr/bin/sandbox-exec -f "$ROOT/sandbox.sb" "$NODE" "$PKG/openclaw.mjs" "$@"
