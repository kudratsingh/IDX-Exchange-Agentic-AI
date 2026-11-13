# Chat-provider migration handoff

2026-10-25: the operator saved the Anthropic API key privately. IDX is now configured
for `anthropic/claude-sonnet-5-5` with `agents.entries.idx.thinkingDefault = medium`.
The installed CLI validated the route with no missing-provider or model-route
issues. A definition-preserving gateway restart succeeded and RPC was healthy.
Those initial checks were configuration acceptance. A later direct API protocol
smoke passed at 2026-10-25T21:35:56Z: 1/1, two calls, correct search route and native
medium-effort continuation. Later direct runs passed routing 40/40 twice and context
25/25. Behavior passed 36 checks; all ten original recall skips passed in a targeted
current-service run with supplied labels. All 111 local case IDs have passing
evidence at their defined scope; runtime/manual acceptance remains pending. See STATUS.md and SEMANTIC_REVIEW.md.

The pre-change config was backed up privately. Only IDX's model, model metadata
and thinkingDefault paths changed; channels, tool policy and MCP config compared
equal to the backup. Existing chat pins may remain: start a fresh session before
live checks. The migration did not change the separate embedding setting/key.
No credential value, model request, approval or email was included in the record.

The earlier offline build left live settings unchanged. Future credential changes
must continue through the private operator setup flow. Model reference checked:
[Anthropic models](https://platform.claude.com/docs/en/models/overview).

There are two separate provider dependencies:

| Component | Current dependency | Migration consequence |
|---|---|---|
| Gateway routing and reply | OpenClaw chat provider | May be changed to Anthropic; recheck routing, whole-card relay and sources |
| Semantic query embeddings | Existing OpenAI embedding space | Needs a compatible embedding key even if chat uses Anthropic |
| Recommendation ranking | Stored listing vectors | No new embedding call for a displayed listing |
| Document answers | Exact names/BM25, plus optional hybrid embeddings | Local retrieval remains available when vectors cannot be queried |
| Email previews, approval and reports | Deterministic Python plus database/local docs | No chat-provider SDK in the business logic |
| Paid local eval driver | OpenAI or Anthropic Messages adapter | Direct local checks, including judged recall, passed; runtime acceptance remains pending |

An Anthropic chat key must not be substituted into `OPENAI_API_KEY`. Existing vectors
cannot be queried by an incompatible embedding model. Retain a separate compatible
embedding key or explicitly choose a new indexing route and rebuild under consent.

The local eval driver is ready for `IDX_EVAL_PROVIDER=anthropic`, an
`ANTHROPIC_API_KEY` in its process environment or private checkout .env, and
`IDX_EVAL_MODEL` set in the process environment to the
selected Claude API model ID. OpenAI remains the default when the provider setting
is absent. No Anthropic SDK dependency is needed. It translates the internal tool
schemas, system text, calls and tool-result history to the Messages API, and normalizes
the reply for the existing route checks. Unsupported/truncated replies abort without
a retry. Temperature and OpenAI reasoning fields are omitted for Anthropic.
Explicit low/medium/high/xhigh/max effort maps to native output_config.effort and
adaptive thinking for both routing and single-tool calls. None/none leaves the native
default unchanged; it does not disable thinking. Opaque thinking blocks are retained
in memory for tool continuation and excluded from report previews. The exact-command consent
gate and call ceiling remain in force. The driver reads the Anthropic key from
the environment first, or private .env if absent there. An explicit empty env value
disables fallback; duplicate .env assignments fail closed. Only this key is read
by the eval fallback, never arbitrary settings or shell code. It does not read the
gateway profile directly. The user authorized a private copy of their existing
profile key into .env on 2026-10-25; no new key or gateway change was needed.

The adapter follows Anthropic's official [Messages reference](https://platform.claude.com/docs/en/api/messages/create)
and [tool-use schema](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).
The initial adapter tests used stubbed responses; subsequent paid evidence is
recorded in WO-019. Runtime/channel acceptance remains separate.

After configuring the new chat provider, restart through the operator workflow,
start a fresh session, and check: health; Pasadena search; condo refinement; next
page; price check; RAG sources; mixed search/market; draft preview; send/approval
decline; off-topic response; injection refusal. Then run the full rehearsal and
record actual outputs and cost. Remaining paid checks each require their own human grant.

Keep IDX_SENDER_KEY unchanged during the chat-provider switch so saved-search
bucket lookups continue to work. It is separate from either provider's API key.
The additional-capability rehearsal is in ADDITIONAL_CAPABILITIES.md; probe both
MCP servers after installation. The 40-case routing plan has a ceiling of 160 chat
requests, with a fresh run-specific grant before execution.

The user chose baseline acceptance before new capabilities: see BASELINE_ACCEPTANCE.md
and WO-019 for the frozen case counts, separate grants, human steps and resume gate.
