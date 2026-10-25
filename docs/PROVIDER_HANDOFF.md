# Chat-provider migration handoff

2026-10-25: the operator saved the Anthropic API key privately. IDX is now configured
for `anthropic/claude-sonnet-5-5` with `agents.entries.idx.thinkingDefault = medium`.
The installed CLI validated the route with no missing-provider or model-route
issues. A definition-preserving gateway restart succeeded and RPC was healthy.
This is configuration acceptance, not a successful live provider/evaluation run.

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
| Paid local eval driver | OpenAI or Anthropic Messages adapter | Offline-tested schema/history translation; real provider acceptance remains pending |

An Anthropic chat key must not be substituted into `OPENAI_API_KEY`. Existing vectors
cannot be queried by an incompatible embedding model. Retain a separate compatible
embedding key or explicitly choose a new indexing route and rebuild under consent.

The local eval driver is ready for `IDX_EVAL_PROVIDER=anthropic`, an
`ANTHROPIC_API_KEY` in the operator's environment, and `IDX_EVAL_MODEL` set to the
selected Claude API model ID. OpenAI remains the default when the provider setting
is absent. No Anthropic SDK dependency is needed. It translates the internal tool
schemas, system text, calls and tool-result history to the Messages API, and normalizes
the reply for the existing route checks. Unsupported/truncated replies abort without
a retry. Temperature and OpenAI reasoning fields are omitted for Anthropic; non-none
reasoning-effort flags are refused before a run starts. The exact-command consent
gate and call ceiling remain in force. The driver reads the Anthropic key only from
the environment, not the repo `.env` or OpenClaw's private credentials.

The adapter follows Anthropic's official [Messages reference](https://platform.claude.com/docs/en/api/messages/create)
and [tool-use schema](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).
Only stubbed responses were used to test it; no live provider request was sent.

After configuring the new chat provider, restart through the operator workflow,
start a fresh session, and check: health; Pasadena search; condo refinement; next
page; price check; RAG sources; mixed search/market; draft preview; send/approval
decline; off-topic response; injection refusal. Then run the full rehearsal and
record actual outputs and cost. Paid tests are intentionally deferred.

Keep IDX_SENDER_KEY unchanged during the chat-provider switch so saved-search
bucket lookups continue to work. It is separate from either provider's API key.
The additional-capability rehearsal is in ADDITIONAL_CAPABILITIES.md; probe both
MCP servers after installation. The 40-case routing plan has a ceiling of 160 chat
requests, with a fresh run-specific grant before execution.
