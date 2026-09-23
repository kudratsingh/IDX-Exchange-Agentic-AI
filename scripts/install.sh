#!/usr/bin/env bash
# scripts/install.sh v0 (WO-001): point OpenClaw at this repo's skills and register the MCP server.
#
# What it does, in order:
#   1. Checks openclaw is installed and Node is a supported major (24.16+ or 26.1+).
#   2. Checks the venv python can import idx_agent (pip install -e . into it first).
#   3. Reads IDX_OWNER_E164 from .env (the one WhatsApp number allowed to talk to the bot).
#   4. Renders config/openclaw.idx.json5 with absolute paths into ~/.openclaw/openclaw.idx.json5.
#   5. If ~/.openclaw/openclaw.json does not exist, installs the rendered file as the config.
#      If it exists, prints the rendered path and stops: merge by hand, then run
#      `openclaw config validate` (nothing here overwrites an existing config).
#   6. Registers the MCP server through the CLI as well, so `openclaw mcp doctor idx --probe` works.
#
# Human steps that stay manual (see WO-001): install OpenClaw, `openclaw onboard`, link WhatsApp
# with `openclaw channels login --channel whatsapp`, start the gateway, send the test messages.
# Nothing under ~/.openclaw is ever committed.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${IDX_PYTHON:-$REPO/.venv/bin/python}"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
CONFIG="${OPENCLAW_CONFIG_PATH:-$STATE_DIR/openclaw.json}"
RENDERED="$STATE_DIR/openclaw.idx.json5"
TEMPLATE="$REPO/config/openclaw.idx.json5"

fail() { echo "install.sh: $*" >&2; exit 1; }

# 1. openclaw and node
command -v openclaw >/dev/null || fail "openclaw is not installed. See docs/adrs/0003-routing-and-tool-route.md (Install)."
NODE_VERSION="$(node --version 2>/dev/null | sed 's/^v//')" || fail "node is not installed"
NODE_MAJOR="${NODE_VERSION%%.*}"
case "$NODE_MAJOR" in
  24|26) ;;
  *) echo "install.sh: node $NODE_VERSION is not supported by OpenClaw (needs 24.16+ or 26.1+); the OpenClaw installer can add Node 26" >&2 ;;
esac
echo "openclaw $(openclaw --version 2>/dev/null | head -1), node $NODE_VERSION"

# 2. the package in the venv (the MCP server runs from it; PYTHONPATH is not passed to servers)
[ -x "$PYTHON" ] || fail "no python at $PYTHON; create the venv and run: pip install -e ."
"$PYTHON" -c "import idx_agent, mcp" 2>/dev/null || fail "idx_agent or mcp not importable by $PYTHON; run: $PYTHON -m pip install -e ."

# 3. the owner's number, never committed
[ -f "$REPO/.env" ] || fail ".env is missing; copy .env.example and set IDX_OWNER_E164"
OWNER="$(grep -E '^IDX_OWNER_E164=' "$REPO/.env" | tail -1 | cut -d= -f2- | tr -d '[:space:]"')"
[[ "$OWNER" =~ ^\+[1-9][0-9]{7,14}$ ]] || fail "IDX_OWNER_E164 in .env must be an E.164 number like +14155550100"

# 4. render
mkdir -p "$STATE_DIR"
sed -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$PYTHON|g" -e "s|__OWNER_E164__|$OWNER|g" "$TEMPLATE" > "$RENDERED"
chmod 600 "$RENDERED"
echo "rendered $RENDERED"

# 5. install, or deep-merge into the existing config (a backup is kept beside it)
if [ ! -f "$CONFIG" ]; then
  cp "$RENDERED" "$CONFIG"
  chmod 600 "$CONFIG"
  echo "installed $CONFIG"
else
  "$PYTHON" "$REPO/scripts/openclaw_merge_config.py" "$RENDERED" "$CONFIG"
fi

# 6. register the MCP server through the CLI too (idempotent on the same name)
openclaw mcp add idx --command "$PYTHON" --arg -m --arg idx_agent.mcp_server.server --cwd "$REPO" >/dev/null 2>&1 \
  && echo "registered MCP server 'idx' (probe: openclaw mcp doctor idx --probe)" \
  || echo "openclaw mcp add did not succeed; the rendered config carries the same server definition"

cat <<'EOF'

Next, by hand:
  openclaw config validate
  openclaw mcp doctor idx --probe          # expects the tool idx__health
  openclaw skills list                     # expects: health
  openclaw channels login --channel whatsapp   # QR from the dedicated number
  openclaw gateway restart                 # or: openclaw gateway install (LaunchAgent)
  openclaw logs --follow                   # then send "health check" from the owner number
EOF
