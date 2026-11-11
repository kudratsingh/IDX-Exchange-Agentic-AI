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
      bot, an AI or a person, answered with one fixed digit-free sentence;
   b. a fixed digit-free referral line for an offer, contract, showing or anything else
      transactional, pointing to "the licensed agent using the contact in this profile";
      no name, no number of any kind, no placeholder that would ship literally;
   c. the contact sentence narrowed: credentials and everyone's contact details stay
      forbidden (listing agents' included); the referral line is the one exception, and it
      writes no contact detail out;
   d. card turns unchanged, stated explicitly: no disclosure or referral words are added to
      a reply that is the tool's message, or to another fixed reply; the disclosure waits
      for the next reply that is neither.
2. Tests: `tests/test_runtime_policy_disclosure.py` (new) and the existing installer and
   eval-prompt tests, which already pin the file by content.
3. Docs: `docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md` (Q1, Q3, Q5, Q7 notes),
   `docs/EVIDENCE_LOG.md` entry, this work order.

## Out of scope
- Any plugin change (`extensions/idx-whatsapp-channel`), including `REPLY_INSTRUCTION`
  and a code-enforced first-reply disclosure (research option 3b, an owner decision for
  rollout).
- License number, broker name, brokerage or display-name text (Q3 is pending with the
  broker; see the note below).
- Answers to Q2, Q4 or Q6, and any waiver of the runbook section 7 preconditions.
- Installing the policy, running `scripts/install.sh`, the installer, the openclaw CLI or
  any paid or model call. Runbook 7.5 is not changed.

## The added text
New section, after "Outside the supported roles":

```
## Disclosure and the licensed agent

You are an automated AI assistant, not a person. Say so plainly in the first reply of
a conversation, and whenever asked whether you are a bot, an AI or a person, with this
sentence:
I'm an automated AI assistant, not a person.

Card turns stay as they are. When the tool's message is the whole reply (a listing
search, market figures, similar listings or a recommendation), add nothing to it, the
disclosure included. Another fixed reply in this policy also stays exactly as written.
In either case give the disclosure in the next reply that is neither.

For an offer, a contract, a showing or anything else transactional, call no tool and
reply with exactly this single line:
I'm an automated AI assistant and can't handle offers, contracts, showings or other transactions. Please reach the licensed agent using the contact in this profile.

If the same request also needs one of those card tools, the card turn wins: reply with
the tool's message only, and give the line above in the next reply.
```

The old line 41, "Never expose credentials or agent contact information.", becomes:

```
Never expose credentials, and never write out anyone's contact details, listing agents'
included. The one exception is the transactional line above: it points to the contact
in this profile without writing any detail out.
```

## Design notes
1. **Digit-free.** On the owned WhatsApp channel a reply with any figure the user did not
   send is withheld by R4 and becomes `SAFE_TEXT`. The disclosure and the referral line hold
   no `\p{N}` character, so on a non-card turn they release under R2 (`no-figures`). A test
   pins this with the same character class as the verifier.
2. **The profile, not a number.** The referral names "the contact in this profile" so the
   reply never carries a phone number, an email address or a license number. On the stock
   WhatsApp channel and the dashboard there is no business profile; the line still holds no
   detail, and the owner is the only dashboard user.
3. **Card turns win.** Lines 8-10 and R1b mean any prose on a card turn is withheld
   (owned channel) or breaks the verbatim relay (stock channel, dashboard). Both new rules
   therefore wait. A conversation that opens with a listing question gets the disclosure on
   its next non-card reply, not its first.
4. **Fixed replies stay exact.** The "can't help" line and the draft decline keep their
   exact wording; the disclosure does not prefix them. The referral line is itself a fixed
   reply and carries the disclosure.
5. **Q3 may add identity text later.** The broker's answer on advertising identity
   (license number, responsible broker, display-name text) may require text in the first
   reply or the profile. None is added here. A license number in a reply would also trip R4
   unless the user sent it, so such text needs its own design (research option 3b or a
   verifier allowance) when Q3 is answered.

## Effect, install and restore
- **Every channel of the `idx` agent.** The policy is installed into the `idx` workspace
  `AGENTS.md`, which the host loads for every session of that agent: stock Phase 1
  WhatsApp, the owned WhatsApp channel and the dashboard.
- **New sessions only.** `AGENTS.md` is read at session start, so an existing session keeps
  the old text until it ends. TO-CONFIRM (research note, section 4): the owner's existing
  WhatsApp session may continue into the Cloud API test, in which case the "first reply"
  rule may not fire on M1.
- **Owner-run install.** Merging changes nothing on the gateway. The owner installs with
  the existing installer path (`scripts/install.sh`, which runs
  `scripts/install_runtime_policy.py`) as part of the consolidated approval.
- **Restore.** Copy back the installer's backup from
  `<idx workspace>/.idx-policy-backups/AGENTS-<id>.md` (`install_runtime_policy.py`
  lines 43-53), or reinstall the previous `config/IDX_RUNTIME.md` (main 7a1fe36). Either
  takes effect for new sessions.

## Runbook 7.5 check (no change)
M1 ("hi") is a non-card turn. A greeting that carries the disclosure sentence holds no
figure, so it releases under R2 with `rule: "no-figures"`, one outbound `sent` line, and
the counts stay 5 in, 4 replies, 1 busy. The outbound audit line never holds the text, so
the leak pattern (which includes `agent:`) cannot match it; the new text has no `agent:`
in any case. M5 ("are you there?") is answered by `BUSY_TEXT` in code, not by the model.
`REPLY_INSTRUCTION` does not contradict the policy: it asks for the token alone on a card
turn and for plain words without unsent figures otherwise, which is what both rules do.

## Tests required
- `tests/test_runtime_policy_disclosure.py` (new):
  - the disclosure sentence, its two triggers and the referral line are present, the
    referral line exactly once and on its own line;
  - the new section and the narrowed sentence hold no `\p{N}` character, no `[[` or `]]`,
    no `agent:`, no `@`, and no bracket placeholder;
  - the card-turn rule is stated and the lines 8-10 rule is unchanged;
  - the narrowed sentence still forbids credentials and contact details, and the old
    blanket sentence is gone (fails on main 7a1fe36);
  - the installed managed block and the eval routing prompt carry the new text.
- Existing: `tests/test_install_runtime_policy.py`, `tests/test_openclaw_merge_config.py`
  (both compare the installed block with the file).

## Acceptance
- The new test fails on main 7a1fe36 and passes on this branch.
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
  84 pass, 0 fail, 167 skipped (no database), 0 manual. No ci case reads the response
  policy: `routing_prompt` is built only for the local suite's model router, so this run
  shows nothing breaks but does not exercise the new text.
- **Offline, in pytest:** the installed block and `routing_prompt` both carry the new text
  (`test_runtime_policy_disclosure.py`, `test_install_runtime_policy.py`).
- **Paid, not run:** every case that sends the policy to a model (local suite: `routing`,
  `relay`, `description_routing`, `end_to_end` and the other local cases). Whether the
  model actually gives the disclosure on a first reply, keeps card turns token-only and
  uses the referral line can only be measured there, under a human `paid` token.

## Status
2026-11-10, ready for owner review on branch `wo-042-disclosure-referral` (from main
7a1fe36). Nothing installed, run live or sent; no paid or model call; no plugin change.
The new test failed on main (7 of 8) and passes here.
