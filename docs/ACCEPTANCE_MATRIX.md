# Acceptance matrix: Phase 1 (remarks enrichment) and Phase 2 (bounded analysis)

**Current pointer, 2026-11-10.** The original matrix and row procedures below are
historical. Use the [dated readiness update](#readiness-update-2026-11-10) for
current next actions and [STATUS.md](STATUS.md#current-checkpoint-2026-11-10) for
readiness. Installation and live attempts have occurred since the original record.

Recorded 2026-11-02 by WO-022, after PRs #134–#141 merged into main (last merge
`5432dc2`; main CI green). This is a plan of what each capability still needs before it
can be called accepted. It claims no installation, enablement or live result: **none of
the merged capabilities below is installed, enabled or live-verified on the owner's
gateway.** STATUS.md holds the current readiness ladder; this file says what moves each
row up it. When a row changes, add a dated note below the tables. Do not rewrite a row's
history.

## Terms

**State rungs** (the same as STATUS.md, post-merge section):
- **Merged:** on `main` with CI green.
- **Installed:** the serving host runs that revision. That means `git pull`,
  `.venv/bin/pip install -e ".[dev]"`, `./scripts/install.sh` and
  `openclaw gateway restart`, recorded with a probe.
- **Enabled:** the opt-in switch is on in the serving configuration, meaning the tool
  server's `.env` and, for a skill, the `idx` agent's installed `skills` list (in the
  live OpenClaw config that `./scripts/install.sh` writes). For the analyst skill, WO-027
  (open PR #146) has `install.sh` add it from the same `.env` switch; the template
  `config/openclaw.idx.json5` is not edited.
- **Live-verified:** a consented model or WhatsApp acceptance is recorded in
  `docs/EVIDENCE_LOG.md`.

**Evidence tiers:**
- **O (offline/CI):** pytest or `evals.run --suite ci`, no model, no gateway. The agent
  can run it.
- **M (owner Mac, no model):** commands on the serving host that touch private data,
  Docker or the gateway but call no model. These are human steps: the agent's hook
  refuses `openclaw` subcommands that could start the agent, and private stores live in
  the gitignored `data/`.
- **L (live, paid):** model or WhatsApp turns. Each session needs its own human `paid`
  token naming the exact command and a call ceiling. Costs come from the provider
  console.

**Owners.**
- WO-017, WO-018, WO-020 and WO-021 are on main.
- WO-023 to WO-029 are **planned (this queue)**: being built in parallel and not on main
  at this writing. Their own work orders define their scope. This file only names which
  row each one touches.
- WO-030 (chart delivery to the user) is **planned**, after the owner's decision of
  2026-11-02 that charts must actually be delivered (row P2-3).

## Summary matrix

| # | Capability | Merged state (2026-11-02) | Remaining implementation (owner) | Operator actions | Owner decisions | Acceptance evidence still required |
|---|---|---|---|---|---|---|
| P1-1 | Remark-feature search | Merged: #134 `7f10734`, #135 `c8b897c`. `features` on `search_listings`; fails closed with no store | Shared enrichment access: WO-023, planned (this queue). Activation handoff: WO-029, planned | Check (or rebuild) the store; set `IDX_ENRICHMENT_STORE`; pull, install, restart; offline verify (detail below) | Authorize activation; grant the paid token for the acceptance script | O done (A1–A12). M: store built 2026-11-02 in the main checkout (WO-021); not configured; step-4 verify on the serving gateway not run. L: §7 script steps 1–9 not run |
| P1-2 | Card badges | Merged off: #136 `411a649`. Active only when `IDX_FEATURE_BADGES=1` and the store is valid | Presentation: WO-024, planned (this queue) | After P1-1: set `IDX_FEATURE_BADGES=1`; restart | Cap of 3 and "+N more"; order; whether area facets appear; card wording and reply note | O done (`tests/test_card_badges.py`). M: one read-only local check recorded in WO-021 (process environment, not the gateway). L: no badge acceptance script on main yet |
| P1-3 | Recommendation explanations ("Also mentions: …") | Not on main. Proposed in `docs/RECOMMEND_FEATURES_DECISION.md` on unmerged branch `wo-021-recommend-design` (no PR) | Presentation: WO-024, planned (this queue) | None until built and merged; then pull, install, restart | Decision 1 (change order, or add a line only); decision 4 (which facets count) | O: tests not on main. L: none |
| P1-4 | Weighted feature rerank of `recommend` | Not on main. Scaffold and offline comparison on `wo-021-recommend-design`; `recommend` ranking unchanged | No WO assigned: blocked on the owner's decisions | None | All five decisions in the branch's decision record: order or line only; weight scheme, weight and cap; feature preferences as an argument; facets counted; eval-set re-versioning | O on branch only (offline comparison on 400 seeded subjects). Exact-order recommendation evals would need a new set version if order changes |
| P1-5 | Saved feature searches | Refused by design: `save_search` asks to save without features (`alerts/server.py`) | WO-025, planned (this queue) | After build: pull, install, restart | Semantics of a saved feature search under snapshot freshness | O: refusal tests merged; feature saving not built. L: none |
| P1-6 | Feature alerts | Refused by design: the alert query raises on a saved search with features (`alerts/query.py`) | Follows WO-025 (planned); no separate WO in this queue | Alert schedule is optional and not installed (STATUS.md) | Whether feature alerts exist at all; approval before delivery stays | O: refusal merged. M/L: none |
| P1-7 | Deal-signal alerts (as-is, back on market, price reduction) | **Intentionally ineligible.** Held-out gold support is as-is 2, back on market 2, price reduction 6, below the 10-example rule. Not built | None in this queue. Needs new, independently evaluated evidence first | None | Review of the 40 supplementary draft labels (keyword-selected, not gold, not a held-out estimate); any eligibility change | Independent evidence meeting F1 ≥ 80% **and** ≥ 10 gold per facet; then the WO-021 deliverable-4 evals. A static remark is never an event |
| P1-8 | Omission-risk audit | Not on main. Current limitation: no search for features the extractor missed (WO-021 accuracy limitations) | WO-026 pilot, planned (this queue) | Per WO-026 | Pilot scope and any wording change to the limitation line | Per WO-026; nothing recorded yet |
| P1-9 | Enrichment refresh preflight | Merged: #137 `d7df1e7`. Offline read-only script; local run recorded 2026-11-02 (`ENRICHMENT_REFRESH_PREFLIGHT.md`) | None for the preflight. A refresh itself is not built or scheduled | Rerun `python scripts/refresh_preflight.py` from the main checkout before any refresh decision | Whether and when to refresh. Re-extraction is a paid run with its own token | O done. M done once (54,885 usable, 321 never extracted, 3 ambiguous). Not a runtime feature |
| P2-1 | Bounded analyst tool (`bounded_analysis`) | Merged off: #138 `b318846`, on the Phase B service (#108–#113). Registered only when `IDX_ANALYSIS_TOOL=1`; unpinned image answers "not available" | Activation handoff: WO-029, planned (this queue) | Start Docker; build the image and pin its ID; run container tests on the Mac; set `IDX_ANALYSIS_IMAGE` and `IDX_ANALYSIS_TOOL=1`; restart | Analyst activation | O done (CI builds the image and runs the container cases). M: image not built on the Mac (Docker not running); Docker Desktop on macOS untested. L: §5 script not run |
| P2-2 | Analyst routing and skill | Skill `skills/bounded-analysis` written; **not** in the agent's `skills` list; routing row pending in `docs/ROUTING.md` | WO-027 routing/channel integration, planned (this queue) | After merge: `./scripts/install.sh`; restart; fresh session | Approve the routing row and skill wording | O: skill checks merged; routing case and contract hashes not yet updated. L: §5 steps 2–5 not run |
| P2-3 | Chart image delivery over WhatsApp | Code attaches at most one checked PNG to an `ok` result. **Image relay unproven** | WO-027 (planned, this queue): text fallback only. Delivery: WO-030, planned | As P2-1 and P2-2 | Accept the image-relay proof (one consented turn) | L: §5 step 1 (PNG arrives intact, 960×600, timing recorded). Until then images are not a WhatsApp feature |
| X-1 | Measurement (WO-020) | Merged: #139 `516764e` (56 cases, SQL truth, oracle, three scores), #140 `aed1eaa` (local-model adapter, model leg, latency) | Expansion: WO-028, planned (this queue) | Local Ollama run on the Mac against the fixture only; optional real-database latency run | Which hosted model runs, each under a paid token | O done (ci suite plus stub adapter tests). M: no local-model run yet. L: no hosted run yet |
| X-2 | Activation handoff | Release handoffs on main: `RELEASE_WO021_SEARCH.md`, `RELEASE_WO017_ANALYSIS.md` | WO-029, planned (this queue) | Consolidates the operator steps above | Order and timing of activation | Recorded install, enable and live entries in EVIDENCE_LOG.md |

## Row detail: exact operator steps and acceptance

### P1-1 Remark-feature search
Source: `docs/RELEASE_WO021_SEARCH.md` (written for #134 and #135, both now merged, so its
step 3.1 "merge the reviewed PRs" is done).

1. **M, build the store** on the serving host:
   `.venv/bin/python scripts/build_enrichment_effective_store.py`. Expect 54,888 listings
   and the status counts in the handoff. WO-021 records that the store was built and
   revalidated on 2026-11-02 in the main checkout's `data/`. If that checkout serves the
   gateway, step 2 alone confirms it. The builder refuses unless the freeze manifest,
   the results digest `46cd0a6b…9815` and the watermark `2026-09-18 06:58:44` all match.
2. **M, check the store.** `open_store` must print `StoreInfo(… listing_count=54888)`.
   Any `StoreUnavailable` means do not configure it.
3. **M, enable.** Add `IDX_ENRICHMENT_STORE=data/enrichment/full/effective-facets-v1.sqlite3`
   to the tool server's `.env`. Leave `IDX_FEATURE_BADGES` unset.
4. **M, install.**
   - `git pull` to a main at or after `5432dc2`.
   - `.venv/bin/pip install -e ".[dev]"`.
   - `./scripts/install.sh`.
   - `openclaw gateway restart`.
   - Start a fresh WhatsApp session.
5. **M, verify offline.** Run the five test files in handoff §4. The Pasadena solar probe
   must print `applied 14` on the 2026-09-18 snapshot. `stale` or `unavailable` stops
   activation.
6. **L, accept.** Handoff §7 steps 1–9 on the owner's phone under a `paid` token. Record
   each outcome and trace reference in EVIDENCE_LOG.md.

Rollback: handoff §5 disables enrichment and §6 reverts the code. Neither deletes data.

### P1-2 Card badges
1. P1-1 must be installed and enabled first. Badges read the same validated store.
2. **Owner decisions, before activation:**
   - the cap (3) and whether to say "+N more";
   - the order (requested first, then alphabetical, or a fixed priority);
   - whether `near_grocery_mentioned` and `near_transit_mentioned` appear;
   - the wording `From description:` and the reply note.
   These are placeholders today (WO-021, increment 2).
3. **M:** set `IDX_FEATURE_BADGES=1` in `.env`, then `openclaw gateway restart`.
4. **Evidence:**
   - O: done.
   - L: needs an acceptance script, which is not on main (WO-024/WO-029, planned). It
     should cover affirmed-only badges, the cap, stale-store silence, unchanged
     non-search cards and the limitation line.

### P1-3 and P1-4 Feature-aware recommendations
- Branch `wo-021-recommend-design` (commits `9339e23`, `74c98d1`; no PR) holds:
  - `src/idx_agent/enrichment/recommend_features.py` (not wired);
  - `scripts/eval_recommend_features.py`;
  - `tests/test_recommend_features.py`;
  - `docs/RECOMMEND_FEATURES_DECISION.md`.
- The decision record measures the tradeoff on 400 seeded subjects (for example 0.01 per
  feature with a 0.03 cap changed 37% of top-5 sets). No weight is approved.
- An explanation-only line (decision 1, "line only") is the lowest-risk path and belongs
  to WO-024's presentation work if the owner chooses it.
- A rerank needs decisions 2–5 and a new work order. Its acceptance would be the
  branch's listed evaluation cases on main plus a re-versioned or retained
  recommendation eval set (decision 5).

### P1-5 and P1-6 Saved feature searches and feature alerts
- Today both refuse rather than silently drop features. That is acceptance row A10 and
  the alert query's `ValueError`.
- WO-025 (planned) owns saved feature searches. Feature alerts would follow it and keep
  approval before delivery.
- The optional alert schedule stays uninstalled until its manual rehearsal (STATUS.md).

### P1-7 Deal-signal alerts
Disabled by the eligibility rule in WO-021 and WO-018 (2026-10-28 owner update).
- The 40-remark supplementary sample (keyword buckets as-is 14, back on market 13, price
  reduction 13) has draft labels: 38 annotations, unreviewed by the owner.
- Bucket membership and the drafts are not gold labels and are not a held-out estimate.
- Nothing in this queue changes eligibility.

### P1-9 Refresh preflight
- The local result is in `ENRICHMENT_REFRESH_PREFLIGHT.md`: 54,885 `unchanged` (usable),
  321 `never_extracted`, 3 `ambiguous`; `changed`, `new` and `no_longer_active` are zero.
- The local database is a frozen snapshot, so those three classes are exercised only by
  synthetic tests.
- A refresh run, schedule or approval is outside every current WO.

### P2-1 to P2-3 Bounded analyst, routing and chart delivery
Source: `docs/RELEASE_WO017_ANALYSIS.md`.

1. **M, build the image.** `open -a Docker`, then
   `docker build --tag idx-analysis-worker:local docker/analysis-worker`, then
   `docker image inspect --format '{{.Id}}' idx-analysis-worker:local`.
2. **M, prove isolation on the Mac.** Run
   `IDX_ANALYSIS_IMAGE=sha256:<id> IDX_REQUIRE_CONTAINER=1 .venv/bin/python -m pytest -m container -q tests/test_analysis_isolation.py tests/test_analysis_render.py tests/test_analysis_executor.py`.
   Every test must pass; a skip counts as a failure. If any isolation test fails, stop.
3. **M, enable.** Put `IDX_ANALYSIS_IMAGE=sha256:<id>` and `IDX_ANALYSIS_TOOL=1` in `.env`.
4. **Reviewed repository change (WO-027, open PR #146, not merged):** routing row,
   `local` routing case, skill wiring and instructions clause, all behind the same
   `IDX_ANALYSIS_TOOL` switch. With the switch on, `./scripts/install.sh` merges
   `config/openclaw.analysis.json5`, so the template's skill list is not edited by
   hand. Follow #146's `docs/RELEASE_WO017_ANALYSIS.md` sections 2–5 once it is merged,
   then `openclaw gateway restart` and a fresh session.
5. **M, verify offline.** Run handoff §4: `register_analysis_tool()` and the tool-name
   check both print `True`, then the four focused test files.
6. **L, accept.** Handoff §5 steps 1–7 under a `paid` token. Step 1 is also the image-relay
   proof that WO-017 requires.

Turning it off (after #146): remove `IDX_ANALYSIS_TOOL` from `.env`, run
`./scripts/install.sh`, restart. No code change is undone.

### X-1 Measurement
- **Done:** O. 56 cases (23 dev, 33 held-out) pass under `evals.run --suite ci` against
  the fixture, and the Ollama adapter is tested against a loopback stub.
- **Remaining human steps:**
  - the local-model run on the Mac (no token by the 2026-10-28 rule, synthetic fixture
    only; the agent's hook still treats `--suite local` as paid, so the human starts it);
  - any hosted run, under its own `paid` token;
  - optionally, a real-database `evals.latency` run.
- WO-028 (planned) expands the set. Held-out cases are never used to tune skills or
  prompts.

## Change log
- 2026-11-02 (WO-022): first version, after the #134–#141 merges. Nothing installed,
  enabled or live-verified.
- 2026-11-02 (WO-022, combined review before merge). Open PRs that will move rows when
  merged; none is merged, installed, enabled or live-verified:
  - #142 (WO-023): shared enrichment access for search and badges. Rows P1-1, P1-2.
  - #144 (WO-026): omission-risk pilot with public aggregates, human review pending.
    Row P1-8.
  - #145 (WO-028): measurement set v2, model-free. Row X-1.
  - #146 (WO-027): opt-in analyst routing, skill wiring and chart text. Rows P2-2 and
    P2-3 (text fallback only).

  Owner decisions recorded the same day:
  1. The "can't help" line stays unchanged; naming `bounded_analysis` in the enabled
     instructions is accepted (P2-2).
  2. Charts must actually be delivered; the text-only fallback stays but does not
     complete P2-3. Delivery is WO-030.

  Corrected before merge: P2 step 4 and the turn-off line had described the superseded
  hand edit of the skill list; they now point to #146's switch-and-install mechanism.

## Readiness update, 2026-11-10

This note supersedes the original rows' pending-work claims and operator sequence;
it leaves their history intact. Sources are merged code through #186, the dated
evidence log and the open PR list. It is not a new live host probe.

| Original rows / capability | Current evidence | Remaining acceptance |
|---|---|---|
| P1-1 search and effective store | v5 build and install recorded; last serving revision `0b0c48c`, store enabled. The 2026-11-06 session stopped at P1-4 on a wrong year built despite correct feature routing and one tool block (#176) | Not accepted. Complete the owned-send-path setup and smoke below, then a fresh bounded Phase 1 session from P1-0 |
| P1-2 badges, P1-3 explanation lines | Implementation merged (#149 for explanations); switches off in the last recorded state | Accept each presentation increment after the search/delivery gate. Recommendations keep their existing order |
| P1-4 reranking | Owner chose explanation lines without reranking | Experimental scaffold is not a release prerequisite; any future ranking change needs its own decision |
| P1-5 / P1-6 saved feature searches and alerts | #150 merged, conservative defaults, feature-saving switch off | Enable and test freshness, refusal and saving behavior after the prior Phase 1 gates. Approval before outbound delivery remains |
| P1-7 deal signals | No new eligibility evidence | Still ineligible; static remark labels are not event history |
| P1-8 omission pilot | #157 merged; v2 result inconclusive against the agreed threshold | Human review remains separate. Preserve the reported interval and incomplete-recall limitation |
| P1-9 refresh | Read-only preflight retained; WO-032 closed not applicable because all 321 never-extracted listings lack remarks | No missing-text extraction step. Actual refresh waits for new eligible source data and its own approval |
| P2-1 / P2-2 analysis and routing | Opt-in implementation and Mac preflight evidence exist; last recorded analysis switch off | Recheck pinned image and isolation at activation, then run separately approved live analysis acceptance after Phase 1 |
| P2-3 charts | Chart-delivery and automatic-trial-rollback code merged; last recorded chart switch off | The owned Cloud API transport is text-only. First prove compatible verified media delivery, then the one-shot live trial with automatic rollback; staying enabled needs later approval |
| X-1 measurement / extraction evaluation | Expanded tooling merged; WO-034 #163 (`ff12a71`) and stacked #164 (`8d24fc1`) merged | Key-free preparation and owner relabels can proceed alongside setup. Paid C/D runs require their gold, comparison, freeze and consent prerequisites |

### Owned send-path prerequisite

PRs #180–#186 provide the default-off owned channel, approved-server-reply release,
Cloud API transport/wiring and owner checks. The OpenClaw 2026.9.5 harness uses
synthetic data and a fake Graph API; it is not proof of a real WhatsApp delivery.
Use [the current install runbook](runbooks/WHATSAPP_CHANNEL_INSTALL.md) rather than
the original row's install commands. Complete owner permission confirmations,
credentials, number/webhook setup and tunnel validation, then the separately
approved five-message owner-only smoke test. Its smoke and rollback checks must
pass before Phase 1 acceptance is attempted.

#187 persistent dedupe merged as `7a1fe36`. The Cloud API path always uses its
persistent store, so the owner-only smoke runs with it; adding any buyer still
needs separate written owner approval. #179 remains on hold.

Owner-run manual chat checks use the bounded paid-session approval in the
activation handoff's section C5. Command-bound paid-token paths still need their
own tokens. The expired
Phase 1 session approval does not authorize another run. No new run is authorized
by this status update.
