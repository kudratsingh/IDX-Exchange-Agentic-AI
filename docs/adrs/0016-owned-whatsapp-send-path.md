# ADR-0016: Project-owned WhatsApp send path with the verifier at the channel boundary

**Status:** proposed
**Date:** 2026-11-06
**Work order:** WO-037

## Context
The model relays card values and has rewritten them (Phase 1 r6, a year copied from
another card). The plugin hooks a gateway extension can register (`reply_payload_sending`,
`message_sending`, `before_agent_run`) fail open: a hook error does not stop a delivery,
and the browser live-text path bypassed the outgoing hook entirely (WO-019). In OpenClaw
2026.9.5 the only awaited send boundary a plugin owns is its channel's inbound `deliver`
callback and its outbound `sendText`; the reply dispatcher awaits `deliver`, records a
throw as a failed delivery, and has no other route out. Every other sender (message tool,
cron, heartbeat, CLI) resolves the channel's outbound adapter from the registry by
channel id. Numbering: 0015 is taken on PR #179's branch, so this is 0016.

## Decision
Path A: a small project-owned channel plugin claims channel id `whatsapp` for DMs, with
the stock `@openclaw/whatsapp` plugin blocked by `plugins.deny: ["whatsapp"]` (checked
before every other enablement rule) and our manifest preferring over it. The plugin owns
ingress, so it knows the user's inbound text per turn, and its outbound gate runs the
verifier under a deadline and sends only a released verdict or one fixed safe text; a
thrown, late or malformed verdict, a non-text payload, an unknown card token or a
missing inbound record withholds. The plugin refuses to register unless the host config
denies the stock plugin. The skeleton ships on a fake transport first; the real transport
and its credentials are a later, owner-approved decision. Rejected: Path B, an external
adapter in front of the stock plugin (no awaited boundary inside the host; a second
process to secure); Path C, the hook prototype of WO-019 (fails open, bypassed by the
live-text path).

## Consequences
Easier: a single code path for every outbound text, testable offline; a verifier policy
that keeps greetings and clarifications working while refusing invented figures; a card
resolver seam for the #179 token check. Harder: the project owns a channel plugin that
runs with gateway privileges (ADR-0012's boundary applies: extension API only, no
session files, no config writes, no shell); the stock plugin's features (groups, media,
polls, QR login, reconnect) are gone until re-implemented or accepted as out of scope;
ingress is process memory, so cross-process and post-restart sends are withheld; an
operator who removes the deny brings the stock plugin back. We now have to: choose the
transport and credentials, wire the route resolver and inbound runner, decide the
withheld-reply default and the chunker, and write the runbook.

Turn binding revision (2026-11-06): three rules tighten the gate. A send is bound to a
turn only by the frozen handle the ingress minted when it recorded that turn, held in
the channel's own `deliver` closure and never given to the host runner; a turn id string
or a look-alike object is untrusted and the send is withheld with nothing sent. A turn on
which a card tool ran (`cardToolCalled`, monotonic, set through the `beforeToolCall` seam
or per session) may release only fully resolved card tokens, while ordinary turns keep
greetings and clarifications. The gate accepts only a release that names one of the
three rules and is consistent with the input and the record, so an incomplete verdict is
withheld as malformed. Consequences: a reply bound to a turn that has since been evicted
is lost rather than re-bound; the card-turn rule is only as good as the source of the
mark (a missed mark leaves that turn on the ordinary rules, never looser than before);
and the verifier and the gate now have to agree on the rule vocabulary, so a verifier
change that adds a rule must land with the gate's check. The same revision's review made
the destination part of the binding: the gate reads `to` once, refuses anything but a
non-empty string, and hands the transport the canonical peer it verified against, with a
linked id kept apart from the phone-number peer; the transport PR owns the mapping from
that canonical id to its own address format.

Decisions 16 and 17 (2026-11-06): the handle is required, so the gate has one binding
path and no fallback to the peer's newest turn; a send without the channel-minted handle
is withheld with nothing sent, which means no proactive send (tool, cron, heartbeat, CLI,
alert delivery) leaves this channel until a handle-bearing path for such sends exists.
The card-turn mark is applied from the host's before-tool-call event, before the tool
executes, so a card call that fails still leaves its turn on the card-only rule; the
model and the card store are never the source of the mark. The tool name in that event
is matched in the host's spelling (`idx__<tool>`, ADR-0003) as well as the server's, so a
namespace prefix cannot skip the mark; over-marking a turn is accepted, under-marking is
not.

## What would reverse this
The install PR finding that the host does not route every send through the registered
outbound adapter (a sender that bypasses `sendText`), or that the stock plugin cannot be
kept off reliably by `plugins.deny`; a measured rate of withheld legitimate replies that
makes the assistant unusable on DMs; or the host gaining a fail-closed pre-send hook that
makes an owned channel unnecessary.
