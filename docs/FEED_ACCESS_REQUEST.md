# Draft request for periodic MLS source access

Prepared for the operator to send to their coordinator. No message has been sent.
Keep endpoints, usernames, credentials and delivered files out of this public repo.

I would like permissioned access to recurring active-listing and closed-sale
snapshots for the assistant's refresh, evaluation and alert work. Could you confirm:

- Available delivery method and cadence, coverage dates and expected latency.
- Whether each delivery is a full snapshot or a delta; how deletions, status changes,
  revisions, stable identifiers and late-arriving records are represented.
- The included schemas, field definitions, time zones and any open-house dataset.
- Allowed local processing, retention, model-training and derived-artifact uses;
  display/photo rights and any restrictions on embedding or third-party processing.
- A private credential/setup channel and a small approved sample for schema checks.
- Ownership of refresh failures and changes, plus how access should be revoked.

The proposed reader remains SELECT-only. Raw records, secrets and private artifacts
will stay outside GitHub. We will validate a staged refresh, retain provenance and
keep the previous working snapshot before promoting new data. We will not assume
that receiving files grants permission for public release or external model use.
