# Remarks annotation pilot: proposal for review

This is a proposal, not permission to read, copy, export, or label MLS data. The
current fixtures are invented. The human must approve a permitted source and
review workflow before a real sample is selected; this file performs no selection.

## Purpose and scope

The pilot would check whether the proposed annotation instructions can be applied
consistently to a small, permissioned set of **public** listing remarks. It would
not establish population-level accuracy, authorize public examples, or enable new
search filters. Private remarks, contacts, occupants, owner details, access
instructions and other denied fields remain outside the task. The current synthetic
case marker is self-declared; it is not a way to admit or certify real data.

## Candidate pilot for the human to review

A deliberately small first pilot would use up to 30 distinct active-listing
`L_ListingID` groups from `rets_property`, with 20 groups for development and 10
for a separate test split. The only candidate text field is `L_Remarks`, which
the existing column contract treats as untrusted remarks. Its name and allowlist
status do not prove that every value is safe or licensed for this new use. The
human must first verify the feed's field definition and permitted use.

Group duplicate rows by listing key before splitting, and keep every row from one
key in the same split. Fix a seed and a deterministic selection rule before
labeling; if duplicate or unavailable rows leave fewer than 30 eligible cases,
report the smaller number rather than paging or relaxing a cap. Never fetch
more than 50 rows, including duplicates; if a group cannot be kept complete
within that limit, omit it or reduce the sample. Verify the selection query can
meet those constraints before any approved run. This is a small feasibility pilot, not a representative sample or a basis for a production accuracy
claim. No real-feed query or selection code is included or authorized here.
A synthetic-label-only split helper demonstrates the grouping rules; it cannot
select actual listings or establish the provenance of a label.

The proposed reviewer is the owner, using a local, single-user viewer that has
not yet been built. After separate approval and code review, that viewer would
read only the approved fields through the existing SELECT-only database account,
show one case at a time, and keep remarks and source identifiers in memory only.
It would not call a model, write a transcript or create a source-data copy. When
closed, it would retain only reviewed aggregate counts and generalized rule
questions without source text or identifiers. This first pilot therefore checks
the labeling instructions; it cannot support a reproducible real-data accuracy
benchmark. Any durable private label store needs a separate approved design.

A second independent review of a subset is desirable; the actual reviewer,
private display method, permitted retention and conflict-resolution process need
human selection. In particular, storing raw remarks or source identifiers is not
implicitly authorized by this proposal.

## Proposed review decisions

Before any real-data access, agree on:

1. The exact allowed source and field, the human who may view it, and whether the
   provider's terms permit the intended annotation and later evaluation.
2. A small pilot size that fits the existing query/row limits and available human
   review capacity. A pilot is for finding ambiguous rules, not for claiming a
   representative score. No bulk export or pagination around the row cap.
3. A private in-place review method and access/retention policy. Do not put remarks,
   listing identifiers, screenshots, row exports, or contact information in Git,
   reports, model prompts, telemetry, or chat. Do not create a source-data copy
   unless the human explicitly authorizes a compatible storage plan.
4. A split method that groups all versions of the same listing together, with the
   split and grouping fixed before reviewing labels. Review any time-based strategy
   against the actual available feed; do not infer history from a single snapshot.
5. How the human resolves uncertainty and disagreements, including a rule for
   independently reviewing a portion of cases. Retain decisions and aggregate
   counts without publishing source text or using model guesses as ground truth.
6. A separate real-data evaluation contract. The current synthetic-only case
   model and public examples are not a private held-out dataset and must not be
   relabeled as one. Agree on minimum support per facet/polarity and how to report
   undefined or low-sample results before looking at model scores.

The next reviewable artifact is the annotation specification in
[ENRICHMENT_ANNOTATION.md](ENRICHMENT_ANNOTATION.md), with its invented examples.
After the human approves the source and workflow, a separate work order can define
a narrowly scoped, command-bound selection and any required credentials or budget.
No new dependency, provider call, index rebuild, hard filter or notification follows
from this proposal.
