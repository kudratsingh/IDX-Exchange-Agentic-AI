# ADR-0017: WhatsApp Cloud API transport with a signed webhook route on the gateway

**Status:** proposed (drafted offline under WO-038; owner decision required, nothing installed)
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
the last 24 hours. Ingress: one route registered with `api.registerHttpRoute` and
`auth: "plugin"` on an owner-chosen path. The route refuses a POST without a
well-formed `X-Hub-Signature-256` before reading its body and caps how many bodies it
reads at once, so an unauthenticated sender cannot make the gateway buffer data. The
handler checks the HMAC over the raw body before decoding anything, answers fast, drops
duplicates, stale retries, statuses and every non-text or non-phone sender, and hands
the rest to the
channel's existing inbound path, where the allowlist, the one-active-turn rule, the
verifier and the outbound gate stay in front. The transport decides nothing about what
is sent. Credentials (access token, app secret, verify token, phone-number id) are
owner-held, outside the repo, and reach the module only as an injected config object.
Rejected for now: a separate loopback listener owned by the plugin (smaller exposed
surface, but a second server inside the gateway process and outside the host's route
rules; kept as the fallback if path-restricted tunnelling is not available); a hosted
relay in front of the Mac (another service to run and secure); a BSP such as Twilio
(another vendor in the data path).

## Consequences
Easier: an official, terms-compliant channel with a business identity; no third-party
npm dependency; every piece testable offline with fakes (WO-038 `cloud-api.test.mjs`).
Harder: the owner must run a public HTTPS tunnel to the gateway port with a valid
certificate, ideally forwarding only the webhook path; anything reachable through that
tunnel is internet-facing, and the gateway accepts plugin-auth routes even through an
unattributed proxy, so the signature check is the route's only gate. Meta retries for up
to seven days, so the handler must stay idempotent and refuse old messages. It is
idempotent only within one process lifetime: the dedupe set is in memory, so after a
gateway restart a duplicate or a replayed captured request whose Meta timestamp is
still inside the inbound age limit (30 minutes) starts a second turn and a second billed
reply (residual risk, WO-038 decision 8). A 2xx from the Graph API means Meta accepted
the message, not that it was delivered: errors such as 131047 can arrive only later as
a `failed` status on the webhook, so the outbound audit's "sent" means "accepted by
Meta", and for now the webhook only logs such a failure (WO-038 decision 9).
Per-message billing applies to every reply. The access token sits in the gateway process and is
reachable by any in-process plugin code (the same boundary ADR-0016 records for the
ingress). Because the host registers this plugin from more than one module copy, the
install must keep one transport instance per process, or the route and the channel can
end up holding different instances. We now have to: choose the config source and the
tunnel, register the route in the install PR, add a `gates`-approved CI or runbook check
if the owner wants one, and keep the Meta conditions (opt-in, escalation path, window,
no training on WhatsApp data) in the runbook.

## What would reverse this
The owner choosing the linked-device option or another provider; Meta changing the
webhook signature scheme or the free-form reply window; the host refusing plugin-auth
routes through a tunnel, or offering a fail-closed managed ingress that makes our own
route unnecessary; or a security review finding that exposing the gateway port, even
path-restricted, is unacceptable, in which case the separate listener above replaces the
route.
