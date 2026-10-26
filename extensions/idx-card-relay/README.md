# Offline relay candidate — not installable

This is the authorized two-hook compatibility spike, not a deployed extension.
There is deliberately no plugin install manifest, activation entry, dependency
installation or config change. Runtime code uses a type-only OpenClaw API import
and registers only after_tool_call and reply_payload_sending. It uses no filesystem,
network, shell, session-store or config API. Its in-memory cache is bounded and
expires; that is code discipline, not a sandbox against gateway privileges.

Synthetic model output contains explicit card references. The outgoing hook
inserts captured original messages without reformatting and preserves surrounding
prose. Missing, rewritten, duplicate, reordered or foreign references are cancelled.
No live prompt is changed to adopt this protocol during the compatibility spike.

Run unit and stub delivery tests without dependencies or provider calls:

    node --test extensions/idx-card-relay/relay.test.ts

These tests establish transformation behavior only. Browser live-text integration
must be proven separately against the installed host path before this can become
an installable extension or justify the single paid WhatsApp preview turn.


## Compatibility result: browser gate failed

The installed-host probe registers these two handlers with the actual host hook
runner in a separate offline process, supplies synthetic tool/model events and
stubs all channel transport. It never connects to the running gateway. Only this
test imports inspected private host modules; the runtime candidate imports no
private host implementation. The probe is pinned to OpenClaw 2026.9.5 and refuses
a different version. Its own temporary config/state fixtures are test-owned;
neither the runtime candidate nor the test writes the real gateway's sessions or
configuration.

    node extensions/idx-card-relay/host-probe.mjs --host-root /path/to/openclaw

Observed: WhatsApp stub output uses the original 960-sqft block, but the actual
browser live-text handler publishes a synthetic 1,240-sqft rewrite while invoking
the outgoing hook zero times. The probe deliberately asserts this counterexample;
a green probe process is evidence of the compatibility failure, not a passing
browser acceptance test. Even a corrected final payload cannot undo already
shown rewritten fields. No extension was installed, no live prompt was changed,
and the paid WhatsApp preview gate is not satisfied.

This remains a small transformation prototype, not production enforcement.
Capacity/expiry, partial-chunk behavior, lifecycle cancellation and host error
handling also need production design if a suitable pre-broadcast seam becomes
available. Do not activate this by adding a manifest or changing tool policy.
