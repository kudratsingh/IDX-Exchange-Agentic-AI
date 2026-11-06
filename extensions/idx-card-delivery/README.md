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
  Each `wa` call is also recorded in an in-memory per-run ledger.
- `reply_payload_sending` (fail-open: skipped on a throw or a 15 s timeout) acts on
  WhatsApp only. It reads the referenced records from `~/.openclaw/idx-cards`
  read-only and calls `verifyAndSubstitute`: the stored cards replace the tokens only
  when every check passes and the tokens cover every card call the ledger holds for
  the run. Otherwise the reply becomes a fixed line with no digits, or is cancelled.
  A throw inside the handler cancels the payload.

If either hook is skipped, the user can see a token (letters only, starting "Listing
details not shown. Please ask again.") or a refusal, never the model's card text: the
model never received card values.

## Files

| File | Imports | Role |
|---|---|---|
| `verify.mjs` | `node:crypto` | pure twin of `src/idx_agent/channels/card_delivery.py` |
| `store.mjs` | `node:fs`, `node:path` | read-only record reader; never writes |
| `plugin.mjs` | `node:os`, `node:path`, the two above | the two hook handlers and the ledger |
| `delivery.test.mjs` | node built-ins | shared vectors, static checks, stub hook tests |

Plain ESM with JSDoc types, so no compiler is needed and Node 18 or later runs it.

## Run the tests (offline, no host, gateway or network)

    node --test extensions/idx-card-delivery/delivery.test.mjs

`tests/test_card_delivery_js.py` runs the same from pytest. The shared cases live in
`tests/fixtures/card_delivery_vectors.json`; the Python core runs every one of them
too (`tests/test_card_delivery.py`).
