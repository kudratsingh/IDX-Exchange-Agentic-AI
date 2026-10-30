# WO-018 diagnostic review: proposed facet clarifications

These proposals are for the private diagnostic review. They are not approved
facet definitions, changes to the frozen benchmark, or permission to integrate.
Original labels, model outputs and extraction evidence remain unchanged. Case
counts below refer to the 110 unresolved cases at this review checkpoint; a
case can involve multiple questions, so counts must not be added together.

The approved [annotation specification](ENRICHMENT_ANNOTATION.md) already
requires an explicitly supported facet, separates polarity and temporality,
and treats unmentioned features as unknown. A proposal is an affirmed planned
mention; uncertain and planned can coexist when the text supports both. Generic
shopping is not a grocery claim. Numeric counts have separate rules and do not
define the scope of categorical facets.

Questions requiring owner rulings, with conservative recommendations:

1. **ADUs (32 cases):** Require an explicit ADU label or an independent living
   unit with stated living facilities; do not equate every guest room, casita,
   suite or second house with an ADU solely from its name.
2. **Accessory-unit features (6):** Keep the structure attribution; do not
   represent a feature on an accessory unit as a primary-home feature. The
   current flat schema cannot express that attribution, so omit the ambiguous
   flat label unless property-wide meaning is approved.
3. **Future possibilities (22):** For mere room or potential, use uncertain
   polarity and unspecified time unless there is evidence of a plan. Keep
   explicit proposals as affirmed/planned, as the specification already says.
4. **Outdoor spaces (21):** Reserve patio for explicit patios; do not map
   balconies, decks, porches, terraces, courtyards, patio doors or covers to a
   patio without an explicit definition. Decide shared patios separately.
5. **Views (9):** Do not equate hills with mountains or community views with a
   view from the listed home; treat coastline wording as case-specific. The
   existing rule already disallows inferring a view from frontage alone.
6. **Materials and amenities (10):** Do not infer hardwood from generic wood or
   engineered wood. Decide separately whether solar pool heating counts as
   solar and whether optional external clubs are community amenities.
7. **Layout (15):** Require an explicit open-plan claim or clear connection
   between living spaces. Decide whether lofts and dedicated game rooms count
   as bonus rooms and whether storage closets count as walk-in closets.
8. **Pools and gates (7):** Do not assume a pool is private or communal when
   scope is unstated; decide how to label a spool and a gated building. Existing
   rules do not establish a gated community from a private gate or a garage
   from gated parking alone.

Each case remains private and must be applied individually after a ruling.
Unresolved changes remain unapplied; this review does not establish semantic
accuracy for remarks outside the diagnostic set.
