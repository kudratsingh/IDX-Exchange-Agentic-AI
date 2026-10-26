# ADR-0012: Deterministic card relay and the gateway privilege boundary

Status: compatibility blocked under the approved single-hook limit, 2026-10-26.
No relay extension is installed. The existing prompt mitigation is not an exact
relay guarantee and failed a subsequent email-preview check.

## Required boundary

Only rendered blocks from search_listings, find_similar_listings, recommend,
get_market_stats and draft_email are eligible. The model owns surrounding prose,
document answers and clarifications; it must not render eligible card fields.
Code must insert the original UTF-8 block without reformatting, and a regression
must demonstrate that a model rewrite cannot change a card number. Draft approval,
recipient resolution and delivery remain operator-only.

This would be the project's first TypeScript runtime component and the first
project extension executing inside the OpenClaw gateway process. It runs with
that process's privileges, not inside the model's tool sandbox. An unchanged
model tool allowlist does not sandbox plugin code. A future implementation must
import only the OpenClaw extension API, read tool results in memory, and never
read or write session files, write config, invoke a shell, add model tools or
request broader workspace permissions. Installation remains a separate operator
or coding-agent action; the loaded extension must not install or configure itself.

## Installed API compatibility review

Review target: OpenClaw 2026.9.5. Its installed hook docs, exported TypeScript
contracts and dispatcher implementation were inspected read-only; a private
receipt retains the reviewed source hashes. No vendor source is copied here.

- after_tool_call receives the original result and host run/session correlation,
  but is observation-only; its return cannot replace the final displayed answer.
- Agent tool-result middleware can replace what the model receives, not provide
  an immutable final user-visible block. Changing model input alone is insufficient.
- reply_payload_sending can replace a normalized outgoing payload, but its event
  contains the candidate payload and optional correlation/usage metadata, not the
  original tool results. One such hook cannot reconstruct trusted card bytes.
- before_agent_finalize can request another model pass or finalize; it has no
  supported replacement-text return. Retrying costs money without exactness.
- before_message_write operates on transcript persistence, not a universal
  browser/channel output replacement; using it would violate the session-write limit.
- reply_dispatch is a runtime takeover. Its input is an inbound request and
  dispatcher/lifecycle context, before tool results exist. Owning model execution,
  replay and delivery is broader than a tool-result-only card relay. Restricted
  session permission/tool overrides can also disable takeover; those restrictions
  must never be relaxed to make a relay work.

The ordinary delivery hooks also skip failed handlers rather than providing a
fail-closed relay boundary. Browser streaming must be checked independently of
WhatsApp delivery; a successful final channel substitution alone proves neither
that earlier browser text was protected nor that transcript content is consistent.

## Decision and next gate

Do not ship a single-hook extension that merely looks deterministic in a stub
containing fields the real host does not supply. Do not read transcripts to join
results, mutate session/config, add another hook silently, or weaken tool policy.
The approved implementation is blocked at compatibility, before deployment.

The smallest candidate scope exception is one extension with two narrow hooks:
a tool-result observer plus an output transform, correlated by host run identity
and holding only bounded in-memory card strings. That is a proposal, not a proven
browser solution. It still requires a synthetic host-path spike demonstrating
browser streaming/final output and WhatsApp coverage without session writes,
unchanged prose/docs/clarifications, byte identity, no cross-run leakage and no
extra provider/tool calls. If the browser path is not covered, stop again; do not
substitute a partial channel-only implementation. Alternatively wait for a host
API that joins original results with final output in one supported callback.

The user permits one paid WhatsApp preview turn only after unit tests and both
stubbed channel paths pass, under its own fresh exact-command token, to verify
the 960-sqft card. No paid turn is authorized by this ADR or performed by the spike.
