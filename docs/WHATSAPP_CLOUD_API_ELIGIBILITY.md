# WhatsApp Cloud API eligibility for this deployment

**Status:** RESEARCH for the owner. Not legal advice; nothing was signed up for, created or sent.
**Date:** 2026-11-08 (all sources retrieved this day). **Work order:** WO-037.
**Related:** `docs/WHATSAPP_TRANSPORT_RECOMMENDATION.md` (option B), ADR-0016, `docs/AUTONOMY_LADDER.md`.

Deployment assessed: one California licensed real-estate professional (`<OWNER_NAME>`, under
`<BROKERAGE_NAME>`), an AI buyer's-agent assistant answering a small allowlist of known buyers
who message first, over WhatsApp DMs, text only, reply-only (no templates, no marketing),
listing search, market stats and similar listings from IDX feed tables, running on the
owner's Mac through OpenClaw, with a hand-off to the licensed human for anything
transactional and a human approval gate on email.

## 1. Verdict: qualifies with conditions

Nothing in Meta's current terms or policies excludes this use, and the reply-only, low-volume
shape avoids most of the platform's friction (templates, messaging limits, display-name
review). It is a business serving its own customers, which is what the platform is for; the
AI Providers clause (section 3) targets AI vendors whose product is the assistant itself.
Conditions, all on the owner's side: a Meta business portfolio in the name of the business
that actually serves the buyers; a dedicated number; an opt-in that names the business;
a visible route to the human; a published privacy policy; no training of any shared model on
WhatsApp data; a model-vendor arrangement the owner is satisfied fits Meta's data-sharing
clause; and brokerage and MLS sign-off (section 4). Two limits on certainty: Meta reserves
"sole discretion" over who is an AI Provider, and the help-center pages on accepted
verification documents and display-name rules could not be read (they render only in a
browser), so those rows rest on secondary sources.

## 2. Requirement by requirement

| Requirement | What the primary source says | This deployment | Owner must do or confirm |
|---|---|---|---|
| Business use only | Platform services are "solely for your business or commercial use", not personal use [S2 s1, s3]; you need a Meta business portfolio and accurate account details [S1 s2.2]. | A licensed agent serving buyers is a commercial use. | Decide whose business it is: the owner's own (sole proprietor or entity) or the brokerage's (Q1). |
| AI Providers rule | Vendors of LLMs, gen-AI platforms or "general-purpose artificial intelligence assistants" may not use the platform where that technology is the "primary (rather than incidental or ancillary)" functionality, as Meta decides [S1 s4.7]. In force since the 2026-01-15 terms update; the paid exception covers named EU, Brazil and Turkiye markets, not the US [S5]. | Not barred; see section 3. | Keep the assistant scoped to the owner's real-estate service; do not offer it as a general chatbot. |
| No AI training on platform data | Platform data, including derived forms, may not be used to "create, develop, train, or improve" AI models, except fine-tuning a model "for your exclusive use" [S1 s4.7]. | The self-improvement program (distillation, RL, refresh) could pull in chat text. | Exclude WhatsApp message content from every shared training or eval set; confirm the model vendor does not train on API inputs. |
| Data sharing and profiling | No profiling of WhatsApp users from platform data, "with the exception of the content of your message threads" [S1 s4.1(a)]; no sharing with third parties "except to a Solution Provider" [S1 s4.1(b)], defined as a party using the APIs on the business's behalf [S1 s1.1]. Data may be used only as "reasonably necessary to support messaging with that person" [S3 s3]. | Inbound text goes to a hosted LLM to draft the reply. The terms do not say whether such a vendor counts as a third party under 4.1(b). An L2 buyer profile built from thread content falls inside the exception. | Confirm with counsel that the LLM vendor's processing fits 4.1(b) (cannot determine from the text). Never enrich profiles from WhatsApp metadata beyond the thread. |
| Opt-in | Contact people only if they gave you their number and you "received opt-in permission"; the opt-in must say it is from the business and name it; SMS, web, phone or paper all work [S3 s1; S6]. | Buyers message first, but Meta's pages do not say an inbound message alone is opt-in. | Collect a simple opt-in at intake naming `<BUSINESS_NAME>` and keep a record. Honor opt-outs [S2 s4]. |
| 24-hour window | Free-form replies only inside 24 h of the user's last message; outside it, approved templates only [S3 s2; S10]. | Replies follow the inbound by seconds (ingress TTL 30 min); no proactive sends (ADR-0016, decisions 16-17). | Nothing now. Proactive alerts (item 18) later need templates and opt-in. |
| Automation and escalation | Automation is allowed inside the window, but the business "must also have available prompt, clear, and direct escalation paths" (human in chat, phone, email, web, in person) [S3 s2]. | Before WO-042 no hand-off existed: no file told the assistant to refer anyone to the licensed human. WO-042 adds one fixed, digit-free referral line to the response policy (`config/IDX_RUNTIME.md`) for offers, contracts, showings and other transactions, and for a request to talk to or reach a person, a human or the agent. It is a prompt instruction, not code, and is not installed yet. | Put the human's contact route in the business profile; the hand-off line only points to "the contact in this profile" and carries no contact detail itself. Install the policy (owner-run) and staff the route. |
| AI or bot disclosure | Messaging Policy has no AI-disclosure rule [S3]. Meta's Business Agents terms bar presenting output "as human-generated" but cover Meta's own agents [S15]. | Not required by Meta for a self-built assistant. | Disclose anyway; California bot-disclosure law may apply (Q5). |
| Real estate and commerce | No real-estate restriction in the Messaging Policy, its prohibited list or the enforcement violation list [S3 s4-5; S17]. Commerce Policies apply to catalogs and shops and name housing only under discrimination [S4]. Wrongful discrimination is barred [S3 s4]. | Allowed category; no catalog or payments used. | Keep fair-housing rules on replies; no catalog listings without reading [S4]. |
| Business verification | Not stated as a precondition for Cloud API. It raises the number cap from 2 to 20 and is one path to the 2,000 limit [S7; S9]. Limits count only messages outside the service window [S9]. | Reply-only, one number: workable unverified. | Verify only if wanted for profile trust or a brokerage rule. Accepted documents and sole-proprietor eligibility unconfirmed (Q1). |
| Phone number | Owned by you, can take SMS or voice, no short codes; a number already on WhatsApp must be deleted first; two-step PIN at registration [S7]. | Plan already calls for a dedicated `<BOT_NUMBER>`. | Use a new number, never the personal or brokerage line. |
| Display name | Required at registration; review happens automatically at higher messaging limits; shown in chats only once approved [S8]. Naming rules are in a help article not readable here [S8 link]. | Low volume, so review may never trigger; name shows in the profile. | Choose a name matching the business record; brokerage name rules may apply (Q3). |
| Profile and privacy policy | Keep a profile with support contacts, accurate and current; maintain a "published privacy policy" [S3 s1, s3]; give users required notices [S2 s4]. | None exists yet for this channel. | Publish a privacy policy covering WhatsApp, the model vendor and retention. |
| Meta's data role | For Cloud API, Meta is processor (Meta Platforms, Inc. in the US) and uses data only "to provide Cloud API", plus controller for safety and integrity [S12 Exh. A, s2.2, s2.7]. Message data kept at most 30 days; messages are not used automatically for ads [S11]. No regulated data and no HIPAA [S1 s4.2]; no full card numbers [S3 s3]. | Text only. Transactional matters are meant for the human: once the WO-042 policy is installed, the assistant gives a referral line to the profile contact (a prompt instruction). | Tell buyers not to send IDs, account or card numbers. |
| Pricing | Per delivered message; service replies charged again since 2026-10-01 beyond a monthly free allowance per number [S10]. | Each reply is a service message. | Check current rates on [S10] and the console; no amounts here. |
| Webhook | Public HTTPS with a valid, non-self-signed certificate; GET verify-token handshake; `X-Hub-Signature-256` HMAC-SHA256 of the raw body with the app secret [S13]; retries up to 7 days, duplicates possible; mTLS optional [S14]. | The gateway is loopback-only today. | See section 5. |

## 3. Does the AI Providers rule bar this use?

No, on the current text, subject to Meta's discretion. Section 4.7 [S1] prohibits AI vendors
from using the platform "for the purposes of providing, delivering, offering, selling, or
otherwise making available such technologies" when they are "the primary (rather than
incidental or ancillary) functionality being made available". Three points decide it here:
- **Who is restricted.** "AI Providers" are "providers and developers" of AI technologies.
  The owner is a real-estate licensee using AI, not an AI vendor. Even if the project's
  developers counted as one, the same section says "you may retain an AI Provider as your
  Solution Provider", subject to the no-training rule.
- **What is made available.** The buyer gets the owner's real-estate service: listings,
  market figures and comparables from the owner's IDX feed, with a hand-off to a licensed
  human. The AI is how that service is delivered, which is "incidental or ancillary" to it,
  not a general-purpose assistant offered for its own sake. Meta's pricing page frames AI
  Providers as those offering "general-purpose AI assistants" [S5], and Meta told the press
  at announcement that businesses using AI to serve their customers are not affected
  (TechCrunch, 2025-10-18; secondary).
- **Where it could go wrong.** An assistant that will write essays, code or anything else
  on request starts to look general-purpose. The tool set is already narrow (IDX search,
  market stats, similar listings, cards); a system-prompt rule to decline unrelated
  requests and refer to the human keeps it plainly business-specific.

## 4. Open questions only the owner, brokerage or MLS can answer

- **Q1 Business entity.** Does the portfolio belong to the owner (sole proprietor, DBA or
  entity, and which registration documents exist) or to `<BROKERAGE_NAME>`? Meta's
  accepted-document list [S16] could not be read; vendor guides say a registered sole
  proprietor can verify with a government registration or official tax document.
  *2026-11-10, owner:* "Fold Q1 business ownership, Q3 identity text and Q7 retention
  into the brokerage confirmation." The request draft is held outside the repo and the
  owner sends it. Still OPEN; no answer is recorded here.
- **Q2 Brokerage policy.** Does the broker allow a salesperson-run AI channel, and must
  it use a brokerage-owned number, account or archive? Who supervises it?
- **Q3 Advertising identity.** California rules on licensee advertising (license number,
  responsible broker, team names) may govern the display name, profile and first reply.
  Not checked here; the owner's broker or counsel should confirm.
  *2026-11-10, owner:* "Fold Q1 business ownership, Q3 identity text and Q7 retention
  into the brokerage confirmation." The request draft is held outside the repo and the
  owner sends it. Still OPEN; no answer is recorded here.
  The response policy adds no license, broker or display-name text until this is answered.
- **Q4 MLS and IDX display rules.** Does the MLS's IDX policy permit showing listing data
  in a third-party messaging channel, and which attribution (listing broker, disclaimers,
  data-currency notice) must each card carry? Do sold and market stats fall under IDX or a
  separate VOW or data licence?
- **Q5 Bot disclosure.** Does California's bot-disclosure statute (SB 1001, Bus. and Prof.
  Code s17940 onward) apply to this assistant? The statute text could not be fetched.
  *2026-11-10, owner:* "Use clear AI disclosure for Q5 and leave the legal question with
  counsel." The response policy `config/IDX_RUNTIME.md` (WO-042) instructs the assistant to
  say plainly that it is an automated AI assistant. It is not installed and its effect
  has not been measured. Whether the statute applies is not answered here; that
  question stays with counsel.
  Limit: the disclosure is a prompt instruction, not code. A card reply (listings, market
  figures, similar listings, a recommendation) must stay exactly the tool's message, so a
  conversation made only of card turns may not show the disclosure until code enforces
  it (research option 3b). Owner gates of 2026-11-11, requirements not yet met:
  code-enforced disclosure is required before any buyer is added, and the paid routing
  eval that would measure the policy needs its own separate approval. Neither delays the
  owner-only smoke test. Under the policy, a direct "are you a bot?" question is to be
  answered first, on its own turn, and an offer, contract or showing request is to get
  the referral line at once.
- **Q6 Model vendor.** Which LLM vendor and terms (no training, retention, sub-processors),
  and does counsel accept that arrangement under [S1 s4.1(b)]?
- **Q7 Recordkeeping.** Must buyer chats be retained under brokerage or DRE record rules,
  given Meta keeps message data at most 30 days [S11]?
  *2026-11-10, owner:* "Fold Q1 business ownership, Q3 identity text and Q7 retention
  into the brokerage confirmation." The request draft is held outside the repo and the
  owner sends it. Still OPEN; no answer is recorded here.

## 5. What changes in our design if Cloud API is chosen

- **Ingress.** A public HTTPS callback URL with a valid certificate, reached by an
  owner-run tunnel to the Mac (new internet-facing surface on a privileged process). The
  plugin registers one route (`api.registerHttpRoute`, `auth: "plugin"`) or runs a separate
  listener; it answers the verify-token GET, checks `X-Hub-Signature-256` over the raw body
  before parsing, returns 200 fast, and dedupes by message id (Meta retries for days).
  Stale-backlog drop and the 30-minute ingress TTL stay as they are.
- **Egress.** `sendText` becomes one `fetch` POST to the Graph API messages endpoint
  (built-ins only). No templates; the gate and verifier do not change.
- **Credentials, owner-held, outside the repo and `~/.openclaw`:** system-user access token,
  app secret, verify token, phone-number id, WhatsApp business account id and two-step PIN.
  The agent never sees or handles any of them.
- **Rollback.** Stop the tunnel, unsubscribe the webhook, revoke the token, then runbook 4.

**On hold:** the Baileys transport, any credential setup, number registration or linking,
and the five-message live smoke test (recommendation section 4) stay paused. Each needs
separate written owner approval; this research approves none of them and does not change
the recommendation's open owner decision between options A and B.

## Sources (all retrieved 2026-11-08)
- [S1] Meta Terms for WhatsApp Business Platform, last modified 2026-09-23. https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform (the old Business Solution Terms URL, https://www.whatsapp.com/legal/business-solution-terms, redirects here)
- [S2] WhatsApp Terms for WhatsApp Business Platform, effective 2026-09-23. https://www.whatsapp.com/legal/WhatsApp-Terms-for-WhatsApp-Business-Platform
- [S3] WhatsApp Business Messaging Policy, updated 2026-09-23. https://whatsappbusiness.com/policy/ (redirect from https://www.whatsapp.com/legal/business-policy)
- [S4] Meta Commerce Policies. https://www.facebook.com/policies_center/commerce
- [S5] AI Providers (pricing). https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers
- [S6] Get opt-in for WhatsApp. https://developers.facebook.com/docs/whatsapp/overview/getting-opt-in
- [S7] Business phone numbers. https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers
- [S8] Display names. https://developers.facebook.com/documentation/business-messaging/whatsapp/display-names (guidelines: https://www.facebook.com/business/help/757569725593362, not readable)
- [S9] Messaging limits. https://developers.facebook.com/docs/whatsapp/messaging-limits
- [S10] Pricing. https://developers.facebook.com/docs/whatsapp/pricing
- [S11] Cloud API data privacy and security. https://developers.facebook.com/docs/whatsapp/cloud-api/overview/data-privacy-and-security
- [S12] WhatsApp Business Platform Cloud API Terms, updated 2026-09-23. https://www.facebook.com/legal/Meta-Hosting-Terms-Cloud-API
- [S13] Create a webhook endpoint. https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint
- [S14] Webhooks overview. https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks
- [S15] Meta Business Agents and Platform Terms of Service, updated 2026-07-16. https://www.facebook.com/legal/3774714022740775
- [S16] Business verification: https://developers.facebook.com/docs/development/release/business-verification ; accepted documents (not readable): https://www.facebook.com/business/help/159334372093366
- [S17] Policy enforcement violations. https://developers.facebook.com/documentation/business-messaging/whatsapp/policy-enforcement-violations
- Secondary: TechCrunch, 2025-10-18, https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform/
