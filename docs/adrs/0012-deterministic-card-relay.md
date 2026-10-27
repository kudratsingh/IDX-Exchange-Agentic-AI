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


## Authorized two-hook spike: observed result

The user subsequently authorized a two-hook offline spike and autonomous work.
The candidate in extensions/idx-card-relay registers after_tool_call to capture
only eligible rendered messages and reply_payload_sending to substitute original
blocks at explicit model-produced references. It preserves the model's surrounding
sentence and does not select tools. There is no install manifest, activation,
dependency installation or live prompt/config change. The TypeScript runtime
candidate uses only an OpenClaw API type import and the passed registration API;
it has no filesystem, network, shell, config or session access code. It would
still inherit gateway privileges if installed: static checks are code-discipline
checks, not an operating-system sandbox.

Ten dependency-free Node tests passed: byte identity including Unicode/newlines,
rewritten card rejection, five allowed tool families, original result immutability,
model-owned document/clarification/excluded-tool responses, mixed prose, identity
isolation, expiry/replay rejection and real outgoing-context shape. These are
transform-level tests, not proof of full-channel acceptance.

The separate host-probe.mjs compatibility test imports inspected private host
modules only in an isolated offline process, never in the candidate extension.
It registers both handlers with the real installed host hook runner and injects
synthetic tool/model events into the actual browser live-text handler. Transport
and persistence callbacks are stubbed; its temporary config is test-owned and
no live gateway connection is made. The host is version-pinned to 2026.9.5.

Observed result: the WhatsApp sending-hook stub substituted the exact 960-sqft
block. The browser handler independently broadcast the model's synthetic
1,240-sqft rewrite with zero outgoing-hook invocations. This is a failed browser
acceptance gate; the probe deliberately asserts that counterexample, so its zero
exit status must not be reported as browser acceptance. Both hooks being present
does not protect the browser event stream. A later correct final card cannot
remove a prior visible factual error.

Decision: retain the uninstalled prototype and reproducible negative evidence.
Do not add session writes, a runtime takeover, broader tools or extra hooks to
hide this boundary. No paid WhatsApp turn is permitted yet. A supported host seam
before browser publication (also covering channel output) or a separately reviewed
architecture change is needed before implementation can satisfy the user's full
contract. Exact streaming, lifecycle/capacity handling and host hook failure policy
must also be established before calling any future implementation enforcement.

## Superseding decision: model-side checking, 2026-10-26

The human cancelled the relay and declined installation. The display boundary
belongs to OpenClaw: the stock extension API does not provide the shared browser
and WhatsApp interception point needed for deterministic relay. The proposed
host patch would have touched transcript persistence, and its multi-step rollback
was not rehearsed. The cancelled branch remains as a record; the separately staged
host, package and patch artifacts were removed. No live installation occurred.

The guarantee is narrower: code creates the stored draft and binds approval to its
exact contents. The draft tool returns the rendered preview; the email skill asks
the model to paste it unchanged. Output is checked where both the complete tool
payload and final reply are available, not enforced at the display boundary. The
numeric check reports mismatches and counts without logging the underlying values;
it is not a semantic or byte-for-byte verifier. Missing, incomplete, or ambiguous
inputs are unavailable, never passing evidence. The existing privacy-filtered live
trace does not contain both texts, so it cannot by itself verify a WhatsApp reply.

OpenClaw 2026.9.5 documents `tool_choice` for client-supplied tools on its HTTP
endpoint and a model-wide override for local-model sessions where every turn calls
a tool. Neither establishes a selective per-agent setting for the WhatsApp agent's
internal MCP calls. A blanket forced tool choice would conflict with required
clarifications, declines, and follow-up replies, so none was enabled. The card
skills instead instruct the model to call first and write nothing before the result.
The separately tokened one-turn WhatsApp check remains pending; no model-side
instruction or check guarantees what the model will display.
