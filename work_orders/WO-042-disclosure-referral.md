# WO-042 — AI disclosure and human referral in the response policy

**Driver:** agent (policy text, tests, docs); owner (approval of this PR, and separately
the install on the gateway workspace)
**Depends on:** main 7a1fe36; WO-019 (the response policy and its installer,
`config/IDX_RUNTIME.md`, `scripts/install_runtime_policy.py`); WO-037 to WO-040 (the owned
WhatsApp channel and its verifier)
**Autonomy level this moves toward:** L1: the assistant says what it is and hands
transactional matters to the licensed human, which the owner-only Cloud API test and any
later buyer use need. It adds no capability.

Owner instruction (2026-11-10), verbatim: "Use clear AI disclosure for Q5 and leave the
legal question with counsel."

## Objective
The every-turn response policy tells the model to say plainly that it is an automated AI
assistant (in the first reply of a conversation and whenever asked whether it is a bot or
a person), and to refer offers, contracts, showings and other transactional requests to
the licensed agent through the contact in the channel's profile. Neither rule adds words
to a card turn, and neither carries a digit.

## Why
`docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md` (rows "Automation and escalation" and "AI or bot
disclosure") asks for a route to the human and a disclosure, and the owner chose clear
disclosure for Q5. Before this order no file held either rule, and
`config/IDX_RUNTIME.md` told the model "Never expose credentials or agent contact
information", which also ruled out pointing a person to the licensed agent.

## Inputs (each checked against main 7a1fe36)
- `config/IDX_RUNTIME.md`: lines 8-10 make the tool's message the whole reply after one
  listing search, market figures, similar listings or a recommendation; line 41 holds the
  contact sentence above. No disclosure or referral text anywhere in it.
- `scripts/install_runtime_policy.py`: replaces only the managed block of the workspace
  `AGENTS.md` and, when the file exists, first writes its old bytes to
  `.idx-policy-backups/AGENTS-<random hex>.md` (lines 43-53).
- `evals/run.py:2733`: `routing_prompt` appends the same file to the routing prompt.
- `extensions/idx-whatsapp-channel/verifier.mjs`: R1b withholds any prose on a turn that
  called a card tool (line 178); R2 releases a reply with no figure as `no-figures`
  (line 182); R4 withholds a figure the user did not send (line 191), and the gate then
  sends `SAFE_TEXT`. A figure is any `\p{N}` run (`DIGIT_RUN_RE`, `constants.mjs`).
- `extensions/idx-whatsapp-channel/constants.mjs`: `REPLY_INSTRUCTION` (card turn: the
  token only; other turns: plain words, no figure the user did not write).
- Research note for the owner (not tracked), sections 1, 2 (A3) and 4 (options 3a and 4).
  Its repo claims were re-read against the files above before use.

## In scope
1. `config/IDX_RUNTIME.md`:
   a. a disclosure rule: first reply of a conversation, and any question whether it is a
      bot, an AI or a person, answered with one fixed digit-free sentence; the identity
      question comes first (no tool call, the sentence alone, the rest on the next turn);
   b. a fixed digit-free referral line for an offer, contract, showing or anything else
      transactional, pointing to "the licensed agent using the contact in this profile";
      no name, no number of any kind, no placeholder that would ship literally;
   c. precedence: the referral line comes before the "can't help" line; the draft decline
      keeps send, approve and change-recipient requests;
   d. the contact sentence narrowed: credentials and everyone's contact details stay
      forbidden (listing agents' included); the referral line is the one exception, and it
      writes no contact detail out;
   e. card turns, every verbatim tool message or `error.message`, and every fixed reply
      stay exactly as written; the disclosure waits for the next reply that is none of
      these, and a deferred referral is given on its own as the next reply that is neither
      a card turn nor another fixed reply.
2. `src/idx_agent/mcp_server/server.py`: the server instructions' "can't help" sentence
   leaves out transactional requests, so the two texts the model sees agree.
3. `docs/ROUTING.md`: a transactional row (no skill, no tool), tied to the new local case
   `routing-local-043` in `evals/cases/routing.yaml` (not run; it needs a paid token).
4. Tests: `tests/test_runtime_policy_disclosure.py` (new); the pinned instruction hashes in
   `tests/test_routing_contract.py`, `tests/test_phase_integration.py` and
   `tests/test_phase_integration_charts.py`; the routing case count and paid ceiling in
   `tests/test_evals_runner.py` and `evals/README.md`.
5. Docs: `docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md` (escalation rows; Q1, Q3, Q5, Q7 notes),
   `docs/EVIDENCE_LOG.md` entries (append only), this work order.

## Out of scope
- Any plugin change (`extensions/idx-whatsapp-channel`), including `REPLY_INSTRUCTION`
  and a code-enforced first-reply disclosure (research option 3b, an owner decision for
  rollout).
- License number, broker name, brokerage or display-name text (Q3 is pending with the
  broker; see the note below).
- Answers to Q2, Q4 or Q6, and any waiver of the runbook section 7 preconditions.
- Installing the policy, running `scripts/install.sh`, the installer, the openclaw CLI,
  any session reset, the local eval suite or any paid or model call. Runbook 7.5 is not
  changed.

## The added text
After the "can't help" line, in "Outside the supported roles":

```
Two kinds of request no IDX tool serves are not this case. A transactional request (an
offer, a contract, a showing or another transaction) gets the referral line in the next
section. A request to send, approve or change the recipient of a draft keeps the draft
decline below.
```

New section, after "Outside the supported roles":

```
## Disclosure and the licensed agent

You are an automated AI assistant, not a person. Say so plainly in the first reply of
a conversation, and whenever asked whether you are a bot, an AI or a person, with this
sentence:
I'm an automated AI assistant, not a person.

When a message asks whether you are a bot, an AI or a person, that question comes
first: call no tool, even if the message also asks for something else, and reply with
the sentence above alone. Handle the rest of the request on the next turn.

Tool replies and fixed replies stay as they are. A reply that copies a tool's message or
its error.message verbatim (a listing search, market figures, similar listings, a
recommendation, health, a document answer's error, an email draft, saved searches or an
analysis) gets nothing added to it, the disclosure included. On a card turn (a listing
search, market figures, similar listings or a recommendation) that message is the whole
reply. Another fixed reply in this policy also stays exactly as written. In every such
case give the disclosure in the next reply that is none of these.

For an offer, a contract, a showing or anything else transactional, call no tool and
reply with exactly this single line. It comes before the can't-help line above:
I'm an automated AI assistant and can't handle offers, contracts, showings or other transactions. Please reach the licensed agent using the contact in this profile.

The referral line is itself a fixed reply: the disclosure sentence still follows in the
next reply that is none of these. If the same request also needs a card tool, the card
turn wins: reply with the tool's message only, and give the line above, on its own, as
the next reply that is neither a card turn nor another fixed reply.
```

After the draft decline:

```
That decline, not the referral line, answers a request to send, approve or change the
recipient of a draft.
```

The old sentence "Never expose credentials or agent contact information." becomes:

```
Never expose credentials, and never write out anyone's contact details, listing agents'
included. The one exception is the transactional line above: it points to the contact
in this profile without writing any detail out.
```

The server instructions sentence (`src/idx_agent/mcp_server/server.py`) now reads: "A
message none of these tools serves (a forecast, say), other than a transactional request
(an offer, a contract, a showing), which gets the response policy's referral line to the
licensed agent instead: call no tool and reply with exactly this one line: ..." The line
itself is unchanged.

## Design notes
1. **Digit-free.** On the owned WhatsApp channel a reply with any figure the user did not
   send is withheld by R4 and becomes `SAFE_TEXT`. The disclosure and the referral line hold
   no `\p{N}` character, so on a non-card turn they release under R2 (`no-figures`). A test
   pins this with the same character class as the verifier.
2. **The profile, not a number.** The referral names "the contact in this profile" so the
   reply never carries a phone number, an email address or a license number. On the stock
   WhatsApp channel and the dashboard there is no business profile; the line still holds no
   detail, and the owner is the only dashboard user.
3. **Card turns win, so the disclosure is not guaranteed.** Lines 8-10 and R1b mean any
   prose on a card turn is withheld (owned channel) or breaks the verbatim relay (stock
   channel, dashboard). The disclosure therefore waits for the next reply that is not a card
   turn. **A conversation made only of card turns may not show the disclosure at all until
   code enforces it (research option 3b).** The one exception the policy makes: a direct
   question whether it is a bot, an AI or a person comes first. The model calls no tool and
   replies with the sentence alone (digit-free, so it releases under R2), and the rest of
   the request waits for the next turn.
4. **Tool replies and fixed replies stay exact (option (a)).** Every verbatim tool message
   or `error.message` (search, market figures, similar listings, recommend, health, a
   document answer's error, an email draft, saved searches, an analysis) and every fixed
   reply ("can't help", the draft decline, the referral line) stays exactly as written. The
   referral line is itself a fixed reply: it starts "I'm an automated AI assistant", but the
   disclosure sentence still follows in the next reply that is none of these. This keeps
   the health skill's one status line, the ROUTING.md health row, and the DEMO_RUNBOOK
   first-turn and error-path checks ("one plain sentence", the exact document-index
   message) as they are.
5. **Precedence.** No IDX tool serves an offer, contract or showing, so the "can't help"
   rule also matched. The policy now says the referral line comes before it, and the server
   instructions sentence leaves transactional requests out. A request to send, approve or
   change the recipient of a draft keeps the draft decline. A deferred referral (a request
   that also needed a card tool) is given on its own, as the next reply that is neither a
   card turn nor another fixed reply.
6. **Q3 may add identity text later.** The broker's answer on advertising identity
   (license number, responsible broker, display-name text) may require text in the first
   reply or the profile. None is added here. A license number in a reply would also trip R4
   unless the user sent it, so such text needs its own design (research option 3b or a
   verifier allowance) when Q3 is answered.

## Effect, install and restore
- **Every channel of the `idx` agent.** The policy is installed into the `idx` workspace
  `AGENTS.md`, which the host loads for every session of that agent: stock Phase 1
  WhatsApp, the owned WhatsApp channel and the dashboard.
- **New sessions only.** `AGENTS.md` is "Loaded at the start of every session" (pinned
  host `docs/concepts/agent-workspace.md:72`), so an existing session keeps the old text.
  The owner's existing WhatsApp session for the test peer may therefore keep the old policy
  for M1.
- **Install (owner-run, part of the consolidated approval).** Merging changes nothing on
  the gateway. Run `scripts/install.sh` (it calls `scripts/install_runtime_policy.py`),
  then `openclaw gateway restart` (`docs/DEMO_RUNBOOK.md`, "Runtime response policy":
  "Restart the gateway and use a fresh session after changing the policy"; install.sh
  prints the same step), then start a fresh session for the test peer.
- **A fresh session for the WhatsApp peer without a WhatsApp message (TO-CONFIRM).** The
  pinned host docs (OpenClaw 2026.9.5) describe an in-place session reset that is not a
  channel message: the Gateway's `sessions.reset` operation
  (`docs/gateway/protocol/rpc-session-control.md:38`), offered as the reset action on each
  session row of the Mac menu bar's Context submenu (`docs/platforms/mac/menu-bar.md:80`),
  and typing `/reset` in the Control UI composer of that session, which "keeps the
  Gateway's explicit in-place reset for the current session"
  (`docs/web/control-ui/chat.md:216`). `openclaw sessions archive <key>`
  (`docs/cli/sessions.md:107-134`) archives a session but the docs do not say the next
  inbound then starts a fresh one. TO-CONFIRM on the owner's build, before the smoke
  window: that the reset sends nothing to the WhatsApp peer, and that the next turn loads
  the new `AGENTS.md`. Typing `/new` in the Control UI starts a new dashboard session, not
  the peer's (`chat.md:216`). **Never send `/new` or `/reset` from WhatsApp during the
  smoke test: it is a sixth inbound message and breaks the 7.5 counts.**
- **Restore, preferred.** Reinstall the main 7a1fe36 `config/IDX_RUNTIME.md` with
  `scripts/install.sh` (it replaces only the managed block and keeps owner notes outside
  it), then `openclaw gateway restart`, then a fresh session as above.
- **Restore, alternative.** Copy back the most recent backup the installer wrote, picked
  by modification time (`ls -t <idx workspace>/.idx-policy-backups/ | head -n 1`;
  `install_runtime_policy.py:43-53` names them `AGENTS-<random hex>.md`). It replaces the
  whole `AGENTS.md`, owner notes outside the managed block included, with the bytes as they
  were before that install. Then restart the gateway and start a fresh session.

## Runbook 7.5 check (no change)
M1 ("hi") is a non-card turn. A greeting that carries the disclosure sentence holds no
figure, so it releases under R2 with `rule: "no-figures"`, one outbound `sent` line, and
the counts stay 5 in, 4 replies, 1 busy. The outbound audit line never holds the text, so
the leak pattern (which includes `agent:`) cannot match it; the new text has no `agent:`
in any case. M5 ("are you there?") is answered by `BUSY_TEXT` in code, not by the model.
`REPLY_INSTRUCTION` does not contradict the policy: it asks for the token alone on a card
turn and for plain words without unsent figures otherwise, which is what both rules do.
If the M1 session is not fresh (above), M1 may run under the old policy; it still passes
7.5, but it does not show the disclosure.

## Tests required
- `tests/test_runtime_policy_disclosure.py` (new):
  - the disclosure sentence and its two triggers; the identity question first, with the
    sentence alone and no tool call, ahead of the card-turn deferral;
  - the referral line exactly once, on its own line, and before the "can't help" line in
    precedence; the outside-roles hand-off sentence; the draft decline keeps its requests;
  - the "can't help" line and the draft decline each exactly once, as their own lines,
    with no disclosure prefix;
  - the option (a) exemption, "Another fixed reply in this policy also stays exactly as
    written.", the referral line counted as a fixed reply, and the deferred referral "on its
    own, as the next reply that is neither a card turn nor another fixed reply";
  - the new section and the contact paragraph hold no `\p{N}` character, no `[[` or `]]`,
    no `agent:`, no `@`, and no placeholder;
  - no brokerage identity wording (`licen[cs]e...`, `broker...`, `DRE`, `realty`,
    `realtor...`, once "licensed agent" is removed) in the section or the contact
    paragraph, with negative samples the scan must catch;
  - the narrowed sentence still forbids credentials and contact details, and the old
    blanket sentence is gone;
  - the referral line comes before "The one exception is the transactional line above" in
    the file, the installed managed block and the eval routing prompt.
- `tests/test_routing_contract.py`: the transactional row and its server-instructions
  clause; new pins for both instruction variants, with the reason above the pins.
- Existing: `tests/test_install_runtime_policy.py`, `tests/test_openclaw_merge_config.py`
  (both compare the installed block with the file).

## Acceptance
- The new tests fail on the earlier policy text and pass on this branch.
- `MYSQL_HOST= pytest -q`, `ruff check .`, `ruff format --check .` pass; CI green.
- No digit in the new text; no name, number or placeholder that would ship.
- No plugin, gate, guard, CI or `.gitignore` change.

## Verification commands
```bash
MYSQL_HOST= pytest -q
ruff check .
ruff format --check .
python -m evals.run --suite ci    # offline; no model or network
```

## Stop conditions
- A test outside the policy pins wording that the change would alter.
- Any eval that would need a model call: do not run it.
- The plugin would need a change for the policy to work.

## Eval status
- **Offline, run:** `python -m evals.run --suite ci` (no database configured): 251 cases,
  84 pass, 0 fail, 167 skipped (no database), 0 manual, before and after the review fixes.
  No ci case reads the response policy: `routing_prompt` is built only for the local
  suite's model router, so this run shows nothing breaks but does not exercise the new text.
- **Offline, in pytest:** the installed block and `routing_prompt` both carry the new text,
  in order (`test_runtime_policy_disclosure.py`, `test_install_runtime_policy.py`); the
  routing contract ties the new row to `routing-local-043`.
- **Paid, not run:** every case that sends the policy to a model (local suite: `routing`,
  including the new `routing-local-043`, `relay`, `description_routing`, `end_to_end` and
  the other local cases). The routing suite's ceiling is now 164 chat calls (41 cases with
  the analysis switch off). Whether the model gives the disclosure, answers the identity
  question first, keeps card turns token-only and picks the referral line over "can't
  help" can only be measured there, under a human `paid` token.

## Status
2026-11-10, ready for owner review on branch `wo-042-disclosure-referral` (from main
7a1fe36). Nothing installed, run live or sent; no paid or model call; no plugin change.
The first test version failed on main (7 of 8) and passed at ad90348.

2026-11-10, review of #189 (adversarial review, each finding kept only after a refuter):
fixed in new commits on the same branch. The identity question comes first; the referral
line takes precedence over "can't help" in the policy and the server instructions, with a
ROUTING.md row and local case `routing-local-043` (not run); the deferred referral and
the disclosure exemption (option (a)) are worded as above; design note 4 now matches the
policy; the eligibility escalation rows state the true state; the Q1, Q3 and Q7 notes
quote the owner; install and restore now include the gateway restart, a fresh session
for the peer (TO-CONFIRM) and the preferred restore. The new tests failed on the
ad90348 policy (6 of 21) and pass here.
