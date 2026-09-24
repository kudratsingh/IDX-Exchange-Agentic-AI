#!/usr/bin/env bash
# scripts/install.sh v0 (WO-001): point OpenClaw at this repo's skills and MCP server.
# Inputs: .env (IDX_OWNER_E164), the venv python, config/openclaw.idx.json5.
# Outputs: ~/.openclaw/openclaw.idx.json5 (mode 600); openclaw.json installed or merged.
# Overrides: IDX_PYTHON, OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_PATH.
# Nothing under ~/.openclaw is ever committed.
#
# Steps, numbered as in the body:
#   1. openclaw present; Node major 24 or 26 (warns otherwise; needs 24.16+ or 26.1+)
#   2. venv python imports idx_agent and mcp   3. IDX_OWNER_E164 read from .env
#   4. template rendered with absolute paths and the owner number into the state dir
#      (it also turns off agents.defaults.compaction.memoryFlush.enabled and
#      plugins.entries.memory-core.config.dreaming.enabled)
#   5. installed as openclaw.json, or deep-merged into it with a .pre-idx.bak backup
#   6. MCP server 'idx' also registered through the CLI (idempotent on the same name)
#
# Manual steps (WO-001): install OpenClaw, `openclaw onboard`, link WhatsApp with
# `openclaw channels login --channel whatsapp`, start the gateway, send test messages.
set -euo pipefail

# Paths: repo root from this script's location; the rest default under ~/.openclaw.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${IDX_PYTHON:-$REPO/.venv/bin/python}"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
CONFIG="${OPENCLAW_CONFIG_PATH:-$STATE_DIR/openclaw.json}"
RENDERED="$STATE_DIR/openclaw.idx.json5"
TEMPLATE="$REPO/config/openclaw.idx.json5"

# fail MESSAGE: print "install.sh: MESSAGE" to stderr and exit 1.
fail() { echo "install.sh: $*" >&2; exit 1; }

# 1. openclaw and node (an unsupported Node major warns but does not stop the install)
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

# 4. render: fill __REPO__, __PYTHON__, __OWNER_E164__; mode 600 (it holds the number)
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

# Print the manual follow-up commands; nothing below runs automatically.
cat <<'EOF'

Next, by hand:
  openclaw config validate
  openclaw config get agents.defaults.compaction.memoryFlush.enabled                 # expects false
  openclaw config get plugins.entries.memory-core.config.dreaming.enabled            # expects false
  openclaw mcp doctor idx --probe          # expects idx__health and idx__search_listings
  openclaw skills list                     # expects: health, property-search
  openclaw channels login --channel whatsapp   # QR from the dedicated number
  openclaw gateway restart                 # or: openclaw gateway install (LaunchAgent)
  openclaw logs --follow                   # then send "health check" from the owner number
EOF
