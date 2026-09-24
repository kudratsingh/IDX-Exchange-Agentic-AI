# ADR-0005: How the sender id reaches a tool

**Status:** accepted (spike of 2026-09-24; reliability confirmed over the WO-006 manual flow)
**Date:** 2026-09-24
**Work order:** WO-006

## Context
Per-sender search memory needs a key. ADR-0003 left open how a WhatsApp sender's identity
could reach an MCP tool argument. The WO-006 spike instrumented the server (process start
time and pid in `health`; request-metadata key names and shapes on every call, never
values) and ran three live turns from the owner number through the gateway.

## Decision
The model passes the sender id. Findings, in the order the decision rule lists them:
- (a) The runtime passes nothing: every call arrived with an empty request `_meta`, and the
  MCP SDK exposes no client or session id on stdio. There is no runtime-bound identity.
- (b) The model sees the sender's number in its conversation context (OpenClaw's inbound
  envelope) and, on the first search turn, filled `sender_id` unprompted; the logged key
  prefix equals the HMAC of the owner number under the configured secret. The skill now
  instructs it explicitly. The 10-of-10 reliability check runs over the Week 4 manual
  flow: every turn's log line must carry a key prefix; one miss falls back to (c).
- (c) Fallback, not taken: carry-forward from the transcript (`previous_filters`).
- The MCP server process lives across turns (one `server_start`, then three tool calls
  over five minutes, one process alive), so the in-process store is valid.
Consequences of trusting a model-passed id: it keys search state only. Nothing that grants
an action (an email, an approval) may key off it; those wait for a runtime-bound identity.
The raw number is hashed with HMAC-SHA256 under `IDX_SENDER_KEY` at the tool boundary and
never logged, stored, or returned.

## Consequences
- The `property-search` skill tells the model to pass the sender's number as `sender_id` on
  every `search_listings` call and never to show it; the tool runs stateless with a
  warning when it is missing or does not hash.
- Two senders can only mix state if the model passes the wrong number; the store cannot
  leak by lookup. The deferred second-phone test covers this when a dedicated number exists.
- Tracing across the boundary has no join key either (WO-007 picks this up).

## What would reverse this
A turn without a key prefix in the manual flow (fall back to transcript carry-forward);
OpenClaw adding a documented sender or session field to MCP request metadata (switch to
it and drop the model-passed argument); any feature that needs identity for authorization.
