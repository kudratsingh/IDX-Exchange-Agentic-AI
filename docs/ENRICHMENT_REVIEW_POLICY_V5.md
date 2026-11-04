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

## Rulings 9 to 15 (added 2026-11-04)

The owner approved rulings 9 to 15 on 2026-11-04. They answer the definitional questions
raised by the WO-033 model review of the frozen v2 omission sample (PR #157). Rulings 9 to
14 answer that review's questions 1 to 6 in order, and ruling 15 is the owner's companion
ruling on grocery wording. They continue the numbering above and are cited as v5 rulings
9 to 15. Each names its facet and gives a one-line rationale.

9. **Markets** (`near_grocery_mentioned`): a market counts as a grocery retailer only when
   the remark says food or groceries are sold there. A bare "market", or a "market hall",
   stays unknown. Reviewer doubt alone never creates an `uncertain` label. *Rationale:*
   "market" names many kinds of place, and an `uncertain` label must record a doubt the
   remark raises, not one the reader brings (ruling 8).
   *Owner clarification, 2026-11-04:* a named grocery chain counts whatever words its name contains, "Market" and "Farmers Market" included; the market rules above apply only to an unnamed or unknown place.
10. **Ferries** (`near_transit_mentioned`): a scheduled public ferry is public transit.
    *Rationale:* it is a public service on a timetable, which is what ruling 2 keeps; only
    private, residents-only services are excluded.
11. **Shared garages** (`garage`): an assigned space in a shared garage counts as a garage.
    *Rationale:* the unit has its own parking space inside a garage, which is what a buyer
    reads the facet to mean.
12. **Entry stairs** (`single_level`): a unit with all its living space on one floor is
    single level even when an entry stair leads up to it. *Rationale:* the facet describes
    the layout inside the home, not how the home is reached.
13. **Outdoor barbecue inserts** (`stainless_appliances`): a stainless insert in a built-in
    outdoor barbecue is a stainless appliance. *Rationale:* it is a named appliance, and
    ruling 3 already counts stainless outdoor-kitchen appliances.
14. **Utility rooms** (`bonus_room`): a utility room is a bonus room only when the remark
    presents it as existing, usable living space. Wording that it could be converted is
    uncertain. *Rationale:* as in ruling 7, an existing room counts; as in v4 ruling 3, a
    possibility is uncertain.
15. **"Groceries"** (`near_grocery_mentioned`): the word counts when the remark establishes
    nearby access to grocery shopping. Food inside the home and grocery deliveries do not
    count. *Rationale:* the facet is about nearby grocery access, not about food or
    services in the home.

## Scope on 2026-11-04

- Rulings 9 to 15 were added to this file on 2026-11-04.
- No store has been built under v5. The serving effective store is still the v4 build.
- No stored label has had rulings 9 to 15 applied. Only ruling 8 has been applied, and
  only to its separate private overlay (Scope on 2026-11-03, above).
- The WO-033 v2 model judgments predate rulings 9 to 15 and are not re-read under them
  here.
- The proposed v5 manifest (WO-035) hashes this file, so it must be recomputed from this
  version before the owner freezes it. The v4 file and the v4 manifest are unchanged.
