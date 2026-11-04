# WO-018 review policy v5: omission-pilot rulings (extends v4)

**This file extends v4; it does not replace it.** The approved rulings and the v2 to v4
clarifications in `docs/ENRICHMENT_REVIEW_POLICY.md` still apply. That file stays frozen
byte for byte: the private policy-audit freeze manifest pins it, and the v4 effective
store was built and validated against it. Where v5 and v4 conflict, v5 wins for any
review done under v5.

**No store has been built under v5 yet.** The serving effective store is the v4 build.
Building one under v5 is a versioned migration that belongs to the store rebuild (WO-021
Status, 2026-11-03). That migration must leave the v4 manifest unchanged.

The owner approved these rulings on 2026-11-03. They answer the WO-026 omission pilot's
open questions and keep the pilot's numbering. Each ruling names its facet and gives a
one-line rationale.

1. **Grocery retailers** (`near_grocery_mentioned`): a warehouse club counts as a named
   grocery retailer. A farmers market does not. *Rationale:* warehouse clubs sell
   groceries as a main line; a farmers market is an occasional event, not a store.
2. **Transit** (`near_transit_mentioned`): only public transit counts. A shuttle or
   transportation service run by a community for its residents does not. *Rationale:*
   the facet tells a buyer about public service in the area, not a private amenity.
3. **Stainless scope** (`stainless_appliances`): one named stainless appliance is enough,
   and stainless outdoor-kitchen appliances count. A "stainless kitchen" that names no
   appliance is uncertain, not present. *Rationale:* the facet is about appliances, so one
   named appliance proves it and a vague finish word does not.
4. **Property type** (`condominium`): property type is never inferred from comparison
   wording in a remark. The structured subtype column decides. *Rationale:* a comparison
   ("not your typical condo") is marketing, and subtype is already recorded in a column.
5. **Accessory structures** (`bonus_room`): flexible space in a detached accessory
   structure is not a bonus room. A bonus room is space inside the main home.
   *Rationale:* this applies ruling 2's scope rule to rooms, as it applies to features.
6. **Recreation centers** (`clubhouse`): a community recreation center counts when the
   remark presents it as a community amenity of the property, as with the v3 resident
   clubhouse ruling. *Rationale:* the remark offers it as a shared facility of the
   community; that is the same evidence as a resident clubhouse.
7. **Flexible-use lofts** (`bonus_room`): an existing loft offered for several uses,
   living space among them, is present. Ruling 3 (possibility is uncertain) covers things
   that may exist, not existing rooms whose use is flexible. *Rationale:* the room exists
   today; only its use is open.
8. **Unsupported uncertain labels** (the six limited facets: `condominium`, `garage`,
   `near_grocery_mentioned`, `near_transit_mentioned`, `single_level`,
   `stainless_appliances`): an `uncertain` label that nothing in the remark supports is
   removed by a documented correction overlay. Each removal is read; none is
   rule-processed. *Rationale:* such a label matches nothing today, but it records a doubt
   the remark never raised and would mislead any later use of the store.

## Scope on 2026-11-03

- Only ruling 8 has been applied, and only to a separate private overlay. The overlay's
  counts are in WO-018 Status.
- v5 has not been applied to the 471 diagnostic cases or to the dataset inventory.
  Whether to re-read under rulings 1 to 7 is an owner decision; the review-candidate
  counts are in WO-018 Status.
- Insufficient evidence still means omission, never a claim that a feature is absent.
