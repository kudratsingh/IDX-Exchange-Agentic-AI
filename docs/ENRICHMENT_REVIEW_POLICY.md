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

## Versioned clarifications

These owner-approved clarifications narrow the numbered rulings above. Later
versions override earlier ones where they conflict.

**v2 (2026-11-01), species flooring.** Keep `hardwood` for explicitly named
qualifying wood-species flooring, including white oak and Brazilian walnut. Exclude
laminate, vinyl, imitation, and "wood-look" descriptions. Species names describing
cabinets, trim, or furniture do not qualify. Generic engineered wood or engineered
oak alone stays excluded; explicit engineered hardwood still qualifies. The
`hardwood` label does not prove solid-wood construction.

**v3 (2026-11-01), remaining questions.**

- **Species list:** qualifying species are oak, walnut, maple, hickory, cherry,
  mahogany, teak, acacia, pecan, ash, birch, ipe and tigerwood. Exclude bamboo, pine,
  fir, cedar, cork, and unspecified parquet unless other explicit qualifying evidence
  exists. Parquet with a named qualifying species counts. The engineered-flooring
  exclusions above remain.
- **Real or natural wood:** those descriptions alone are insufficient. Require
  explicit hardwood, solid hardwood, or qualifying species evidence. "Real"
  establishes neither species nor hardness.
- **Clubhouse:** accept a resident clubroom or community center explicitly described
  as a physical communal facility available to residents. A named club, social
  organization, activities program, or membership alone does not establish a
  clubhouse. Exclude nearby facilities and optional external memberships.
- **ADU:** an explicit ADU claim remains sufficient. Otherwise require a clearly
  separate or self-contained dwelling with stated sleeping space, bathroom, and
  kitchen or kitchenette. Bedroom plus bathroom alone is insufficient. Attached units
  can qualify; detachment is not required. Do not infer legal or permitted status.
- **Open plan:** omit "open flow," "open feel," "open interiors," and "open gathering
  spaces" when they give no concrete layout evidence. Keep `open_plan` for explicit
  open-plan, open-concept, open-layout, or open-floor-plan wording, and for clearly
  connected living spaces, such as a kitchen that flows into the dining and family
  rooms. "Open kitchen," "open living area," "great room," or "open main level" alone
  do not automatically qualify: read the surrounding text for evidence of a connected
  layout. Openness within one room does not establish an open-plan home.

**v4 (2026-11-02), scope and amenity questions.**

- **Gated street:** count an explicitly gated residential street or lane serving
  multiple homes. A gate serving one property, or a shared driveway without clear
  multi-home scope, is insufficient.
- **Gated access:** count a physical gate explicitly controlling access to the
  residential community or complex; the literal phrase "gated community" is not
  required. Security alone does not establish a gate. Building-only, parking-only and
  unit gates remain excluded. Omit when the scope is unclear.
- **Bonus room:** accept explicit bonus rooms and indoor flex rooms or spaces described
  for flexible living use. Also accept lofts, game rooms or media rooms explicitly
  described as additional flexible living space; their names alone are insufficient.
  Generic spare space, storage and outdoor areas do not qualify.
- **HOA club amenities:** count explicitly identified physical pools, fitness centers
  and clubhouses when resident access is included automatically through HOA dues. Club
  membership alone establishes none of those facilities. Exclude optional memberships,
  proximity-only claims, and access requiring a separate membership purchase. An
  offsite location alone does not disqualify guaranteed HOA-included access.
- **Solid wood flooring:** keep `hardwood` for an explicit "solid wood floors" or
  "solid wood flooring" claim, even without a named species. An explicitly excluded
  material or species, such as solid pine, overrides this. Generic "real wood" or
  "natural wood" alone remains insufficient. This resolves the conflict between ruling
  6 and the v3 real-wood clarification.

Apply these versions consistently across the full candidate inventory and the
original 471 cases, revisiting both retained labels and prior removals. Original
extraction evidence and the correction history are preserved. Insufficient evidence
means omission, never a claim that a feature is absent or a layout is closed.

Apply these rulings to each case's evidence. Preserve unresolved exceptions,
the original results and all provenance. This review does not establish semantic
accuracy for remarks outside the diagnostic set.
