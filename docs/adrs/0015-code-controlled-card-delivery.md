# ADR-0015: Code-controlled card delivery (token relay)

**Status:** proposed, not accepted. An offline prototype only (WO-036); nothing is
installed, enabled or activated. The owner decides the exceptions below.
**Date:** 2026-11-06
**Work order:** WO-036

## Context
Phase 1 turn P1-4 failed twice because the model retyped card text: on 2026-11-05 it
changed card 2's living area, and on 2026-11-06, with Layer 2's single copy in effect,
it replaced card 3's year built with card 2's. Layer 1 detects this after the user has
seen it; Layer 2 lowers the chance. The owner's decisions of 2026-11-06 (quoted in
WO-036) ask for deterministic text delivery on WhatsApp, accept only a hook whose
failure withholds the reply, require dashboard card turns to be refused while the
dashboard stream cannot be protected, and drop the wait for the Phase 2 chart trial.
ADR-0012 found that OpenClaw 2026.9.5's reply hooks fail open and that no hook covers
the dashboard stream; it allowed at most two narrow hooks and no workspace access.

## Decision
The model never receives card values. Under `IDX_CARD_DELIVERY=1` a card tool stores
its exact `message` in an owner-only directory and returns a letters-only token
instead; data keeps positions, random integer handles and the user's own filters.
The binding that lets the server issue a token comes from a `before_tool_call` hook,
which OpenClaw runs fail-closed (a throw or timeout blocks the tool,
`dist/agent-tools.before-tool-call-ya9NNSXc.mjs:3052-3062`, sha256 `39e6ae403ad4`).
On WhatsApp only, the `reply_payload_sending` hook swaps the tokens for the stored
bytes when a pure check (`card_delivery.verify_and_substitute`, twin `verify.mjs`,
shared vectors) passes, and otherwise sends a fixed line with no digits or cancels.
Because the model holds only tokens, that hook failing open sends a token, never a
card number. The dashboard is refused in code: the hook binds "none" for anything
but a WhatsApp direct chat, and the server refuses card calls without a WhatsApp
binding. Rejected: (a) a server-drawn card image (not selectable or readable aloud,
and it rides the Phase 2 media relay); (b) the ADR-0012 two-hook spike (unawaited,
fail-open capture, the model still sees the card, no dashboard cover); (c) an own
output path or `reply_dispatch` takeover (errors fall through to the default
dispatch; far wider than a relay); a WhatsApp-channel transform (owned by the
channel plugin, so a vendor patch); an HMAC key (the threat is the model's text,
not a local process of the same user); the model-supplied `sender_id` as a channel
signal.

## Exceptions to ADR-0012 the owner must accept
1. A `before_tool_call` hook, used only to write the `idx_delivery` argument of the
   four idx card tools (it never loosens tool policy, adds tools or approves calls).
   With `reply_payload_sending` that is two hooks, but a different pair than the
   ADR-0012 spike's.
2. Read-only `node:fs` access to one fixed owner-only directory,
   `~/.openclaw/idx-cards` (outside the agent workspace that the `read` tool may open;
   critique fix), from the release hook. The server writes it; the hook never writes.
3. Release on WhatsApp only; card turns refused on the dashboard.
4. A change to what the model sees under the switch (token and handles in place of
   the card and listing keys). Schemas, descriptions and instructions are unchanged.

## Consequences
Easier: a changed or copied figure cannot reach the WhatsApp user from a card turn,
whatever the model writes, and the regression is offline and model-free. Harder: the
model cannot answer questions about card figures in free text; one payload must carry
all of a run's cards; any hook, store or correlation problem costs the card (the user
sees the fixed line, a refusal or a raw token). Out of scope and still model-relayed:
`draft_email` previews, `bounded_analysis`, `rag_answer`, and any run without a card
tool (strict mode is an owner decision). Sessions that existed before activation hold
full cards in their transcripts, so activation needs a session reset. Session digests
are unsalted hashes of keys that may hold a phone number; they sit only in 0600 files
for 300 s and could be brute-forced by someone who can read them.

## What would reverse this
OpenClaw offering a fail-closed hook on the outgoing text of every channel, the
dashboard stream included (then cards could be released there too); a read-only host
check before activation showing that `before_tool_call` does not see bundle-MCP calls
with the session key and run id the release hook sees, or that the host strips the
`idx_delivery` argument (then every card is refused and the design needs a schema
change); or a measured rate of model-invented figures in card-free replies that
needs strict mode or a code-rendered comparison.
