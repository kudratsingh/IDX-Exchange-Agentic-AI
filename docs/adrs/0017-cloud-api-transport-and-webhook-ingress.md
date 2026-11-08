# ADR-0017: WhatsApp Cloud API transport with a signed webhook on a separate loopback listener

**Status:** proposed (drafted offline under WO-038; nothing installed). The owner settled
the ingress, config-source and lifecycle questions on 2026-11-08 (WO-038 "Decisions"); the
record stays proposed until the install PR and the separate live-setup approval.
**Date:** 2026-11-08
**Work order:** WO-038

## Context
ADR-0016 left the transport and its credentials to a later owner decision, and the
transport recommendation named Meta's Cloud API (option B) as the alternative to a
linked-device client. The owner asked for the Cloud API adapter to be prepared offline,
with credentials and the five-message live smoke test held for separate approval after
brokerage and IDX permissions and hosted-model data handling are confirmed. Cloud API
differs from everything the project runs today in two ways: it is an external paid
service (Meta's Graph API, billed per delivered message), and its inbound path is a
webhook that Meta calls over public HTTPS, so the gateway on the owner's Mac would
accept requests from the internet for the first time. ADR-0012 limits gateway-resident
project code to the extension API with no session files, config writes or shell; it says
nothing about network egress or a public route, so this needs its own record.

## Decision
Proposed, for the owner to accept or refuse. The transport is one module,
`extensions/idx-whatsapp-channel/cloud-api-transport.mjs`, that fills the existing
four-member `Transport` seam with Node built-ins and an injected `fetch`, and carries its
own webhook handler. Egress: one POST per reply to the Graph messages endpoint on a fixed
origin (`https://graph.facebook.com`, not configurable), never retried, no redirects
followed, text only with link previews off, refused locally unless the peer wrote within
the last 24 hours, and refused unless the transport is running (a start holds its
sink); a stop, an abort or a newer start aborts a request in flight. Ingress (owner
decision 2026-11-08): a separate `node:http` listener owned by the plugin, bound to
`127.0.0.1` or `::1` only, serving exactly the owner-chosen webhook path for GET and POST
and answering 404 or 405 to everything else; the owner's tunnel forwards only that path
to the listener's port, so the gateway's own port is never exposed. The listener has
header and request timeouts, a header size cap and a connection cap, starts and stops
with the account signal, and logs fixed events only. Behind it, the route adapter
refuses a POST without a well-formed `X-Hub-Signature-256` before reading its body and
caps how many bodies it reads at once, so an unauthenticated sender cannot make the
process buffer data. The handler checks the HMAC over the raw body before decoding
anything, answers fast, drops duplicates, stale retries, statuses and every non-text or
non-phone sender, and hands the rest to the channel's existing inbound path, where the
allowlist, the one-active-turn rule, the verifier and the outbound gate stay in front.
The transport decides nothing about what is sent. Credentials (access token, app secret,
verify token, phone-number id) are owner-held in one owner-only JSON file outside the
repo and outside `~/.openclaw` (mode 600, owned by the gateway's user), read once at
start by a reader that refuses symlinks, hard links, loose modes, extended ACLs (macOS),
foreign owners, extra keys and implausible values with fixed reasons only. Lifecycle:
every account start and stop begins a new ingress epoch, so a turn opened before a stop
or a reload can never send again, even if the host delivers its reply after the account
started anew. A stop raises the epoch only while it is still the one its start began,
compared on the process-wide counter, so a late stop of an older start (in any plugin
copy) cannot void a newer start's turns. The listener cancels a start that is stopped
or aborted while still binding, so a stopped account never keeps the port.
Rejected: a route on the gateway through `api.registerHttpRoute` with `auth: "plugin"`
(it would put the gateway port behind the tunnel, and the gateway dispatches
plugin-auth routes even through an untrusted proxy, so anything else reachable on that
port would depend on the tunnel's path filter alone); a hosted relay in front of the Mac
(another service to run and secure); a BSP such as Twilio (another vendor in the data
path).

## Consequences
Easier: an official, terms-compliant channel with a business identity; no third-party
npm dependency; every piece testable offline with fakes (WO-038 `cloud-api.test.mjs`).
Harder: the owner must run a public HTTPS tunnel with a valid certificate to the
listener's port, forwarding only the webhook path; the listener is a second server in
the gateway process, outside the host's route rules, and the signature check is its only
authentication. Meta retries for up to seven days, so the handler must stay idempotent
and refuse old messages. It is idempotent only within one process lifetime: the dedupe
set is in memory, so after a gateway restart a duplicate or a replayed captured request
whose Meta timestamp is still inside the inbound age limit (30 minutes) starts a second
turn and a second billed reply. The owner accepted that for the owner-only smoke test;
bounded dedupe persistence (ids only, expiring with the age limit, bounded count,
owner-only file) is a hard prerequisite before any buyer is allowlisted (WO-038
decision 8). A 2xx from the Graph API means Meta accepted the message, not that it was
delivered: errors such as 131047 can arrive only later as a `failed` status on the
webhook, so the outbound audit's "sent" means "accepted by Meta", and such failures are
logged privately to the local log only, with no notification (WO-038 decision 9). An
in-flight send aborted by a stop may still have been accepted by Meta; it is never
retried, and the voided turn cannot send again.
Per-message billing applies to every reply. The access token sits in the gateway process and is
reachable by any in-process plugin code (the same boundary ADR-0016 records for the
ingress). Because the host registers this plugin from more than one module copy, the
install must keep one transport and one listener per process, or the listener and the
channel can end up holding different instances. We now have to: pick the tunnel product
(path-restricted, to the listener port), wire the credentials file, the transport and
the listener in the install PR, build bounded dedupe persistence before any buyer is
added, add a `gates`-approved CI or runbook check if the owner wants one, and keep the
Meta conditions (opt-in, escalation path, window, no training on WhatsApp data) in the
runbook. Credentials, the number, the tunnel, the subscription, live sends and the
smoke test each need separate written approval.

## What would reverse this
The owner choosing the linked-device option or another provider; Meta changing the
webhook signature scheme or the free-form reply window; the host refusing plugin-auth
routes, or offering a fail-closed managed ingress that makes our own listener
unnecessary; or a tunnel that cannot restrict by path, in which case the listener's own
404/405 refusal becomes the only path filter and the owner decides again.
