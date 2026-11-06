# Card delivery gateway hooks — offline prototype, not installable

WO-036 Layer 3 prototype (ADR-0015, proposed). Not installed, enabled or activated.
There is deliberately no `openclaw.plugin.json`, `package.json`, dependency or config
entry, and the module never installs or configures itself. If an operator installed
it, it would run with the gateway's privileges; the limits below are code discipline,
not a sandbox.

It supersedes the two-hook spike in `../idx-card-relay/` (kept unchanged as the
ADR-0012 record): that spike captured cards in a fail-open, unawaited
`after_tool_call` and let the model see every card value.

## What it does

- `before_tool_call` (fail-closed in OpenClaw 2026.9.5: a throw or a timeout blocks
  the tool) writes one argument, `idx_delivery`, into the four idx card tools'
  arguments, replacing anything the model sent. The binding is `wa` only for agent
  `idx` in a WhatsApp direct chat (`agent:idx:whatsapp:direct:<peer>`) whose turn
  targets the chat itself; otherwise `none`, which the server refuses. It holds a
  session digest, the run id and the tool-call id, never the peer or the session key.
  Each `wa` call is also recorded in an in-memory per-run ledger, and every tool call
  in a WhatsApp direct chat registers its run there (session digest and run id, 30
  minutes), so the release side knows every run it may release for.
- `reply_payload_sending` (FAIL-OPEN: skipped on a throw or a 15 s timeout) acts on
  WhatsApp only. A payload with no run id, or a run not registered for its session
  (never registered, another session, expired), is withheld with the fixed line
  whatever its text, plain replies included; a registered run with no card call
  passes its text unless strict mode is on. It reads the referenced records from `~/.openclaw/idx-cards`
  read-only (that directory only: the server's `IDX_CARD_DIR` test override is not
  followed, so any other value there withholds every card) and calls
  `verifyAndSubstitute`: the stored cards replace the tokens only
  when every check passes and the tokens cover every card call the ledger holds for
  the run. Otherwise the reply becomes a fixed line with no digits, or is cancelled.
  A throw inside the handler cancels the payload.

## What it does not guarantee (architectural blocker)

Within OpenClaw 2026.9.5 this prototype withholds only while the release handler
runs. `reply_payload_sending` is fail-open by host design: if the plugin is absent,
the handler times out, fails outside its own catch, or returns a shape the host does
not accept, OpenClaw sends the model's text unchanged, and some sends (heartbeat,
cron, exec-completion turns, message-tool sends) skip the hook. An invented figure, a
malformed reply or an unmatched run's reply then reaches the user. Token redaction
and prompt instructions reduce this; they cannot remove it. See WO-036 "Architectural
blocker" and "Delivery boundary: feasibility and recommendation" (an owned WhatsApp
send path, pending the owner). The host-emulation tests `test_host_blocker_*` and
"host blocker:" assert today's outcome.

What does hold: with the plugin loaded the model never receives card values, so a
retyped card carries no tool figure:

- `IDX_CARD_DELIVERY=1`: the server returns a token, or a refusal without a WhatsApp
  binding (so with the plugin absent, nothing is bound and no token is issued);
- switch off: the server refuses any card call that carries `idx_delivery`, so a
  loaded plugin never meets a full card it would have to correlate.

Only with the plugin absent and the switch off does the model receive the card, which
is today's behaviour and carries no guarantee.

## Files

| File | Imports | Role |
|---|---|---|
| `verify.mjs` | `node:crypto` | pure twin of `src/idx_agent/channels/card_delivery.py` |
| `store.mjs` | `node:fs`, `node:path` | read-only record reader; never writes |
| `plugin.mjs` | `node:os`, `node:path`, the two above | the two hook handlers and the ledger |
| `delivery.test.mjs` | node built-ins | shared vectors, static checks, stub hook tests, host-emulation blocker tests |

Plain ESM with JSDoc types, so no compiler is needed and Node 18 or later runs it.

## Run the tests (offline, no host, gateway or network)

    node --test extensions/idx-card-delivery/delivery.test.mjs

`tests/test_card_delivery_js.py` runs the same from pytest. The shared cases live in
`tests/fixtures/card_delivery_vectors.json`; the Python core runs every one of them
too (`tests/test_card_delivery.py`).
