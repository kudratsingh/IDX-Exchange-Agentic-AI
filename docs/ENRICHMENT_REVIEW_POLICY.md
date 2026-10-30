# WO-018 diagnostic review: approved facet clarifications

The owner approved these review-policy clarifications on 2026-10-30. They apply
to the diagnostic review overlay; they do not change frozen benchmark labels,
original model outputs, extraction evidence, or authorize integration.

The approved [annotation specification](ENRICHMENT_ANNOTATION.md) requires
explicitly supported features and separates polarity from temporality. An
omission means insufficient evidence, not an assertion of absence.

1. **ADU:** Require an explicit ADU claim or a clearly described independent
   dwelling with stated living facilities. Casita, guest suite, or second house
   alone is insufficient. Do not infer legal or permitted status.
2. **Feature scope:** Attach attributes to the structure described. Omit a
   label when the flat schema would misleadingly attribute an accessory-unit
   feature to the main home.
3. **Potential:** Possibility without stated intent is uncertain/unspecified.
   Explicit proposals are affirmed/planned; hedged plans are uncertain/planned.
   Neither establishes current presence.
4. **Patio:** Require explicit patio evidence. Do not automatically substitute
   other outdoor spaces or infer a patio from doors or covers. Exclude communal
   patios from the listing's exterior-lot patio facet.
5. **Views:** Require an explicit view claim attributable to the home. Hills or
   foothills alone do not establish mountain views. An explicit view of ocean,
   coast, or other water supports water_view; waterfront alone does not.
6. **Materials and amenities:** Require explicit hardwood or unambiguous
   solid-wood flooring evidence; generic wood or engineered wood is insufficient.
   Explicit engineered hardwood qualifies. Solar means electricity generation,
   excluding solar pool heating alone. Exclude optional external club memberships.
7. **Layout:** Accept explicit open-plan/open-concept wording or clearly
   connected living spaces. Bright or airy alone is insufficient. Do not
   automatically classify every loft or game room as a bonus room. Exclude
   storage closets and pantries from walk_in_closet.
8. **Pools and gates:** Require evidence distinguishing an on-property pool
   from a community pool; omit ambiguous mappings. A spool or spa alone is
   insufficient without explicit pool evidence. Gated buildings, parking, and
   individual property gates alone do not establish gated_community.

Apply these rulings to each case's evidence. Preserve unresolved exceptions,
the original results and all provenance. This review does not establish semantic
accuracy for remarks outside the diagnostic set.
