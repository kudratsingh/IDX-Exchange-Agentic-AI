# WhatsApp transport for the owned send path: recommendation and live smoke test

**Status:** PROPOSAL for owner approval. Nothing here is installed, linked or sent.
**Date:** 2026-11-07. **Work order:** WO-037 (gate G3 of `docs/runbooks/WHATSAPP_CHANNEL_INSTALL.md`).
**Decision record:** ADR-0016 (transport deferred to "a later, owner-approved decision").
**Note 2026-11-11** (this proposal stays as written): the A/B choice is no longer open in
practice. The Cloud API (option B) is the working transport for the owner-only smoke test
(WO-038 to WO-043); ADR-0017 stays proposed, with no acceptance recorded. See
[STATUS.md conflict X3](../STATUS.md#known-conflicts-in-other-docs), AG-C28.

Deployment assumed: one licensed real-estate professional (the owner), one bot number, a
small allowlist of buyer contacts, DMs only, text only, reply-only (proactive sends stay
withheld `no-turn-handle`, item 18), gateway on the owner's Mac (OpenClaw 2026.9.5).
The owner holds every credential and sends every live message. The agent never reads
`~/.openclaw` or any `.env`, never handles a credential, never links a device, never sends.

The seam every option must fill (`extensions/idx-whatsapp-channel/transport.mjs`):
`start({accountId, signal, onInbound})` stays pending until `signal` aborts;
`sendText({accountId, to, text, signal}) -> {messageId}`; `stop()`; `isConfigured()`.
Inbound is `{accountId, peerId, text, messageId, receivedAt}`. The gate hands `sendText` a
canonical peer (`+<digits>` or `<digits>@lid`); the transport maps it to its own address.

## 1. Options compared

| | A. WhatsApp Web linked device (Baileys) | B. WhatsApp Cloud API (Meta) | C. Twilio WhatsApp (BSP over Cloud API) | D. Reuse the stock `@openclaw/whatsapp` session |
|---|---|---|---|---|
| Official status / ToS risk | Unofficial. Baileys states it is not affiliated with or endorsed by WhatsApp and discourages automated messaging [1]. WhatsApp's terms bar access "through automated or other means" and auto-messaging [2]; WhatsApp is reported to be testing a warning for unofficial web clients [3]. Risk: the linked number is restricted or banned. | Official. Business Solution terms since 2026-01-15 bar general-purpose AI assistants whose chatbot is the product; business-specific assistants (service, sales, bookings) remain allowed [4]. Owner should read the terms; our assistant is business-specific. | Official (Twilio is a Meta BSP). Same Meta terms as B, plus Twilio's. | Same library and risk as A (the stock plugin runs on Baileys [5]). |
| Setup, owner only | Get a dedicated number with WhatsApp on a phone; run one owner-only link step (QR or pairing code) from that phone's Linked devices screen. Minutes. | Meta developer account, business portfolio, app with the WhatsApp use case, register a number (one already on WhatsApp must be deleted first [6]), system-user token [7], webhook URL plus verify token, tunnel. Business verification lifts the starting limits [6]. Hours to days. | Twilio account, self sign-up through a Meta pop-up, Meta business verification before production [8], webhook URL. | Install and log in the stock plugin, which ADR-0016 excludes. |
| Credentials, where | Baileys auth folder (long-lived Signal keys; never commit [9]) in an owner-created dir outside the repo and outside `~/.openclaw`, mode 700. | System-user token, app secret, verify token, phone-number id: owner-held, outside the repo, read by the gateway at start. | Account SID and auth token (plus Meta assets), same rule. | `~/.openclaw/credentials/whatsapp/<accountId>/` [5], host-owned. |
| Inbound mechanism | Outbound WebSocket from the Mac. No public endpoint, no tunnel. | Webhook: Meta POSTs to a public HTTPS URL with a valid, non-self-signed certificate, signed `X-Hub-Signature-256` with the app secret [10]. Needs a tunnel to the Mac and a route (`api.registerHttpRoute`, `auth: "plugin"`) or a separate listener. | Webhook from Twilio to a public HTTPS URL; same tunnel need. | Socket owned by the stock plugin, not by us. |
| 24 h window / templates vs reply-only | Not applicable. | Free-form replies only inside 24 h of the user's last message; outside it, templates to opted-in users only [11]. Our replies follow an inbound by seconds (ingress TTL 30 min), so the window always holds. Proactive alerts (item 18) would need approved templates later. | Same as B. | Not applicable. |
| Cost model | No provider billing. | Per delivered message since 2025-07-01; service replies chargeable from 2026-10-01 beyond a monthly free tier per number [11]. See the Meta pricing page; costs from the console only. | Twilio per-message fee plus Meta's charges [12]. See the Twilio pricing page. | As A. |
| Fit with our seam | Direct: socket lifetime = pending `start`; `sendMessage` = `sendText`. Adds one npm dependency (breaks "Node built-ins only"). | `sendText` = one `fetch` POST (built-ins only). `start` registers the webhook route and waits on `signal`. Adds an internet-facing ingress to the gateway host. | Like B, through Twilio's REST API. | Poor: no exported transport API; ADR-0012 forbids touching host session files; two sockets on one linked identity displace each other (not confirmed on this host); allowing the stock plugin reopens the fail-open path ADR-0016 closes. |
| Rollback | Fast rollback (runbook 4). Owner may also remove the linked device from the phone and keep or delete the auth dir (owner's own data). | Fast rollback, stop the tunnel, revoke the token, unsubscribe the webhook. | As B, in the Twilio console. | n/a |

## 2. Recommendation

**Option A, Baileys linked device on a dedicated bot number**, behind our gate, with B as
the named fallback. Reasons:
- No inbound internet exposure. The gateway stays loopback-only; B and C need a public
  HTTPS ingress into a privileged process on the owner's Mac, which is new infrastructure
  and a new attack surface.
- It is the mechanism the host itself ships as production-ready for WhatsApp [5], so its
  linking, reconnect and relink behaviour is documented on this host version.
- Shortest path to G3: one owner link step, no Meta onboarding or template review, no
  metered billing, and nothing to buy for the smoke test.
- The seam keeps the choice reversible: B is a second file implementing the same four
  members, and the gate, verifier and ingress do not change.

Risks it accepts (the owner's to accept or refuse):
- Unofficial client against WhatsApp's terms: the bot number can be restricted or banned
  without notice. Mitigation: a dedicated number, never the owner's personal or brokerage
  number; reply-only; small allowlist; no bulk sends.
- A third-party dependency inside the gateway process (Baileys and its transitive tree),
  pinned to an exact version with a lockfile; protocol changes on WhatsApp's side can
  break it until upgraded.
- Long-lived keys on disk in the auth dir; anyone with that dir can act as the bot number.
- Linked-device rules: secondary sources say up to four linked devices and sign-out after
  about 14 days without the primary phone (not confirmed against WhatsApp's own FAQ).
- Not a business identity: buyers see an ordinary WhatsApp account, not a verified
  business profile. If the owner's brokerage requires an official business channel, or
  the allowlist grows, move to B.

**Owner decision requested:** (1) accept A's terms and ban risk on a dedicated number, or
require B (accepting a tunnel, Meta onboarding and metered billing); (2) supply the bot
number and choose the auth-dir path (owner-held; the agent never sees either); (3) approve
the new npm dependency and the ADR-0012 scope exception below; (4) item 22 (operator
interrupt), which the live install needs regardless of transport.

## 3. Adapter plan (transport PR)

New file `extensions/idx-whatsapp-channel/baileys-transport.mjs` exporting
`createBaileysTransport({ authDir, makeSocket, loadAuthState, now, log })`. The defaults
load Baileys by dynamic `import()` inside `start`, so every offline test injects fakes and
runs without the package installed. `index.mjs` builds it only when an `authDir` is
configured; otherwise `unavailableTransport` stays the default.
- `isConfigured()`: true only when `authDir` is an absolute path outside the repo, exists,
  is mode 700 and holds a linked credential file (existence only, no read). Otherwise
  false, so the host skips the account instead of entering a restart loop.
- `start()`: load the auth state, open the socket (no presence, no read receipts, no
  history sync), and return a promise that resolves only when `signal` aborts (then end
  the socket). On close, reconnect with capped backoff; on logged-out, stop reconnecting,
  log `logged-out` and keep the promise pending until abort (the owner relinks).
- Inbound filter, a pure exported function: keep only `notify` upserts that are not
  `fromMe`, whose chat is a DM (`@s.whatsapp.net` or `@lid`; drop `@g.us`, broadcast,
  status, newsletter), whose body is plain text (`conversation` or extended text; any
  media, reaction or poll is dropped), and whose timestamp is not older than the socket's
  open time (no replies to an offline backlog). Map to `{accountId, peerId: <jid>, text,
  messageId: key.id, receivedAt: ms}` and `await onInbound` one message at a time.
- `sendText()`: map `+<digits>` to `<digits>@s.whatsapp.net`, keep `<digits>@lid`, reject
  anything else; reject at once when not connected; send `{ text }` only; return
  `{ messageId: key.id }`. No queue, no retry (the gate never retries either).
- `stop()`: idempotent socket end.
- Logging: Baileys' logger gets a silent or redacting sink; Baileys can log JIDs and
  payloads at debug level, and runbook S6 must find no peer number or text.
- Owner-only link script, `extensions/idx-whatsapp-channel/tools/link.mjs --auth-dir <dir>`:
  prints a QR or pairing code in the owner's terminal. The agent never runs it.
- Credentials and state: the auth dir lives outside the repo (for example
  `$HOME/.idx-whatsapp/auth/default`, owner-created, mode 700) and outside `~/.openclaw`,
  so it never shares keys with the stock plugin. The transport refuses an `authDir` inside
  the repo. `.gitignore` already has `whatsapp-auth/` and `*.session` but not
  `node_modules/`; adding that needs a `gates` token, so until then the dependency installs
  only in the link-installed copy and the PR checks `git status` is clean.
- Paperwork in the same PR: a work-order note for the dependency; an ADR (or ADR-0016
  amendment) scoping ADR-0012's boundary so the transport alone may open a network socket
  to WhatsApp and read and write its own auth dir (never OpenClaw session files or config);
  a config key for `authDir` (the manifest `configSchema` is empty and strict today).

Offline tests (`node --test`, no network, no package): inbound filter over synthetic
upserts (DM text kept; group, broadcast, `fromMe`, media, stale and empty dropped); peer
mapping both ways, including `@lid` kept apart; `start` pending until abort and resolving
after it; reconnect and logged-out policy with a fake socket factory; `sendText` rejects
when disconnected or for a bad address, returns the fake receipt otherwise, never
retries; `isConfigured` false for a missing, in-repo or loose-mode dir; a source test that
only this file imports Baileys and only `transmit` calls `sendText`; a log-capture test
that no line carries a synthetic number such as `+1 555 0100` or the message text.
Host harness: run `host-harness/run.mjs` with the transport built on the fake socket
factory to prove the real host's `startAccount` lifecycle (pending start, abort on gateway
stop, no restart loop) and that A/B/C checks still pass. Not testable offline: real
linking, WhatsApp's protocol, ban behaviour, `@lid` delivery in practice, real reconnects.

## 4. Shortest live smoke test (for approval; the owner sends, the agent never sends)

Preconditions, all required: (P1) owner approval in writing lifting "installation
paused"; (P2) the transport PR and the install PR merged on `main` with green CI; (P3) the
production package link-installed from the main checkout (never `host-harness/plugin/`);
(P4) the inbound allowlist (code item C3, landed with the owned-channel install PR)
configured to admit only `<OWNER_TEST_NUMBER>`, with an unmapped `@lid` peer dropped;
(P5) item 22's host-level control in place for any dashboard user other than the owner
(runbook 3.6b); (P6) the owned card resolver (owned-channel install PR, confirmed on the
real host by the harness) plus the card-turn skill text (runbook C10), or M3 runs its
fallback; #179 stays on hold; (P7) runbook section 2
backup taken; (P8) the owner has linked `<BOT_NUMBER>` and kept `openclaw logs --follow`
open. Synthetic content only. Wait for each reply before the next message, except M4-M5.

| # | Owner sends from `<OWNER_TEST_NUMBER>` | Expected | Abort and roll back if |
|---|---|---|---|
| M1 | "hi" | One greeting within about a minute; audit `outcome: "sent"`, `rule: "no-figures"`, `boundToTurn: true`. | No reply, `SAFE_TEXT` (`unbound-turn`), two replies, or a stock-style reply. |
| M2 | "What did homes in `<TEST_CITY>` sell for last quarter?" | A market card whose bytes equal the renderer's card for the tool's result (`rule: "card"`), or `SAFE_TEXT`, or a digit-free clarification. | Any released figure that is neither the owner's nor in a resolved card. |
| M3 | With P6: "Show me three-bedroom listings under nine hundred thousand". Without P6: "Is 3 or 4 bedrooms better for a family?" | With P6: card bytes identical to the tool's card (`rule: "card"`). Without: only 3 and 4 appear, else `SAFE_TEXT`. | Card bytes differ, or any other figure is released. |
| M4 | A slow request (for example M3's text again) | Its own reply, usually after M5's busy reply. | M4 lost, or replied twice. |
| M5 | "are you there?" within two seconds of M4 | Exactly `BUSY_TEXT`; one `outcome: "busy"` line. | M5 handled as a turn, or no `BUSY_TEXT`. |

Then, with no message: the runbook's S6 log grep returns `clean`. Abort at any step also
on: a reply to any number other than `<OWNER_TEST_NUMBER>`, any message the owner did not
trigger, plugin status `error`, a log line with message text, a peer number, a session key
or a run id, or a `logged-out` from the transport. Abort means, at once:
```bash
openclaw plugins disable idx-whatsapp-channel && openclaw gateway restart
```
then the full rollback (runbook 4) and a formats-only entry in `docs/EVIDENCE_LOG.md`.
Not in this smoke: the dashboard replay (harness only, G2) and buyer contacts (added to the
allowlist only after a pass).

## Sources (checked 2026-11-07)
[1] Baileys README, https://github.com/WhiskeySockets/Baileys
[2] WhatsApp Terms of Service, https://www.whatsapp.com/legal/terms-of-service
[3] WABetaInfo, https://wabetainfo.com/whatsapp-is-testing-a-safety-warning-for-unofficial-web-clients/
[4] TechCrunch, https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform/
[5] OpenClaw 2026.9.5 bundled docs, `docs/channels/whatsapp.md` (global npm install)
[6] Meta, business phone numbers, https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers
[7] Meta, Cloud API get started, https://developers.facebook.com/docs/whatsapp/cloud-api/get-started
[8] Twilio, WhatsApp self sign-up, https://www.twilio.com/docs/whatsapp/self-sign-up
[9] Baileys docs, session management, https://baileys.wiki/authentication/session-management.md
[10] Meta, webhooks getting started, https://developers.facebook.com/docs/graph-api/webhooks/getting-started
[11] Meta, WhatsApp pricing, https://developers.facebook.com/docs/whatsapp/pricing
[12] Twilio, WhatsApp pricing, https://www.twilio.com/en-us/whatsapp/pricing
