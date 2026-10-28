# WO-018: development overlap rescore

One prior run of 100 development remarks was rescored without provider calls. The earlier development hybrid micro F1 was 87.1%: categorical case/facet overlap ignoring polarity plus exact numeric spans. The owner subsequently froze polarity-aware facet overlap plus exact numeric value: this scores 88.5% micro F1 on dev (precision 83.8%, recall 93.7%). Exact-span micro F1 remains 47.7%. This is a development measurement, not a held-out gate result.

The table below retains the earlier polarity-agnostic overlap analysis; the frozen gate now requires polarity and ignores temporality. Numeric fields now match by exact value rather than exact span. The 150 test cases were not scored. Gold was Claude-drafted and owner-reviewed; Sonnet is in the same model family, so shared-model bias remains possible.

## Per-facet counts and F1

| Facet or numeric field | Exact gold spans | Exact predictions | Exact F1 | Overlap gold cases | Overlap predicted cases | Overlap matched cases | Overlap F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `facet.community_amenities.clubhouse` | 14 | 13 | 51.9% | 13 | 13 | 13 | 100.0% |
| `facet.community_amenities.community_pool` | 27 | 23 | 52.0% | 24 | 23 | 23 | 97.9% |
| `facet.community_amenities.fitness_center` | 11 | 11 | 100.0% | 11 | 11 | 11 | 100.0% |
| `facet.community_amenities.gated_community` | 12 | 15 | 59.3% | 9 | 14 | 9 | 78.3% |
| `facet.condition_sale.as_is` | 1 | 1 | 0.0% | 1 | 1 | 1 | 100.0% |
| `facet.condition_sale.back_on_market_mentioned` | 0 | 0 | — | 0 | 0 | 0 | — |
| `facet.condition_sale.motivated_seller_mentioned` | 1 | 2 | 66.7% | 1 | 2 | 1 | 66.7% |
| `facet.condition_sale.needs_work` | 1 | 2 | 0.0% | 1 | 2 | 1 | 66.7% |
| `facet.condition_sale.price_reduction_mentioned` | 3 | 3 | 0.0% | 3 | 3 | 3 | 100.0% |
| `facet.condition_sale.probate_mentioned` | 0 | 0 | — | 0 | 0 | 0 | — |
| `facet.exterior_lot.adu` | 22 | 10 | 12.5% | 12 | 10 | 10 | 90.9% |
| `facet.exterior_lot.corner_lot` | 8 | 9 | 82.4% | 8 | 9 | 8 | 94.1% |
| `facet.exterior_lot.fenced_yard` | 2 | 6 | 50.0% | 2 | 6 | 2 | 50.0% |
| `facet.exterior_lot.garage` | 56 | 52 | 20.4% | 52 | 52 | 52 | 100.0% |
| `facet.exterior_lot.large_yard` | 8 | 11 | 31.6% | 7 | 10 | 4 | 47.1% |
| `facet.exterior_lot.patio` | 39 | 37 | 26.3% | 34 | 37 | 34 | 95.8% |
| `facet.exterior_lot.pool` | 22 | 14 | 11.1% | 13 | 14 | 13 | 96.3% |
| `facet.interior_systems.central_air` | 12 | 19 | 64.5% | 12 | 19 | 12 | 77.4% |
| `facet.interior_systems.hardwood` | 15 | 18 | 30.3% | 15 | 18 | 15 | 90.9% |
| `facet.interior_systems.luxury_vinyl_plank` | 4 | 5 | 66.7% | 4 | 5 | 4 | 88.9% |
| `facet.interior_systems.solar` | 14 | 12 | 30.8% | 12 | 12 | 12 | 100.0% |
| `facet.interior_systems.stainless_appliances` | 23 | 26 | 85.7% | 23 | 26 | 23 | 93.9% |
| `facet.interior_systems.updated_kitchen` | 19 | 26 | 48.9% | 18 | 26 | 18 | 81.8% |
| `facet.interior_systems.washer_dryer` | 9 | 19 | 7.1% | 9 | 19 | 9 | 64.3% |
| `facet.location_views.city_view` | 4 | 5 | 0.0% | 4 | 5 | 3 | 66.7% |
| `facet.location_views.mountain_view` | 20 | 17 | 21.6% | 15 | 17 | 14 | 87.5% |
| `facet.location_views.near_grocery_mentioned` | 7 | 27 | 11.8% | 6 | 27 | 6 | 36.4% |
| `facet.location_views.near_transit_mentioned` | 9 | 11 | 10.0% | 7 | 11 | 7 | 77.8% |
| `facet.location_views.water_view` | 12 | 5 | 23.5% | 6 | 5 | 5 | 90.9% |
| `facet.property_type.condominium` | 13 | 9 | 36.4% | 10 | 9 | 9 | 94.7% |
| `facet.property_type.manufactured` | 1 | 2 | 66.7% | 1 | 2 | 1 | 66.7% |
| `facet.property_type.multi_unit` | 1 | 2 | 0.0% | 1 | 2 | 1 | 66.7% |
| `facet.property_type.single_family` | 3 | 4 | 57.1% | 3 | 4 | 3 | 85.7% |
| `facet.property_type.townhouse` | 9 | 3 | 50.0% | 5 | 3 | 3 | 75.0% |
| `facet.rooms_layout.bonus_room` | 2 | 3 | 0.0% | 2 | 3 | 2 | 80.0% |
| `facet.rooms_layout.office` | 24 | 16 | 10.0% | 22 | 16 | 14 | 73.7% |
| `facet.rooms_layout.open_plan` | 31 | 38 | 52.2% | 30 | 38 | 30 | 88.2% |
| `facet.rooms_layout.single_level` | 16 | 14 | 66.7% | 14 | 14 | 14 | 100.0% |
| `facet.rooms_layout.split_level` | 1 | 1 | 100.0% | 1 | 1 | 1 | 100.0% |
| `facet.rooms_layout.walk_in_closet` | 36 | 32 | 41.2% | 33 | 32 | 32 | 98.5% |
| `facet.style.contemporary` | 7 | 8 | 40.0% | 5 | 8 | 5 | 76.9% |
| `facet.style.cottage` | 1 | 1 | 0.0% | 1 | 1 | 1 | 100.0% |
| `facet.style.craftsman` | 0 | 0 | — | 0 | 0 | 0 | — |
| `facet.style.mid_century` | 5 | 5 | 40.0% | 5 | 5 | 5 | 100.0% |
| `facet.style.ranch` | 2 | 2 | 50.0% | 2 | 2 | 2 | 100.0% |
| `facet.style.spanish` | 1 | 1 | 0.0% | 1 | 1 | 1 | 100.0% |
| `facet.style.traditional` | 0 | 0 | — | 0 | 0 | 0 | — |
| `numeric.asking_price_usd` | 1 | 2 | 66.7% | 1 | 2 | 1 | 66.7% |
| `numeric.bathrooms` | 54 | 52 | 92.5% | 54 | 52 | 49 | 92.5% |
| `numeric.bedrooms` | 65 | 61 | 90.5% | 65 | 61 | 57 | 90.5% |
| `numeric.living_area_sqft` | 26 | 25 | 54.9% | 26 | 25 | 14 | 54.9% |

Numeric columns use exact matching in both views; em dashes mean undefined metrics.

## Dev-only wording checks

Of the 25 exact-span false-positive near-grocery predictions, 21 had generic shopping language and no grocery cue within 90 characters; one had a grocery cue only in nearby context and three included a grocery cue in their quote. Of the first group, 20 remain unmatched under overlap. This fixed-pattern context check is not proof of the model’s reasoning, and nearby words may concern a different claim.

The 22 gold ADU spans fell into these quote-wording buckets: 16 ADU/accessory dwelling, three in-law, one guest house/unit, and two other; none matched casita or second/additional unit patterns. Of 20 exact-unmatched gold spans, the respective counts were 15, three, one, and one. These are span counts, not distinct listing counts.

The 24 uncertain gold spans fell into sentence-context wording buckets: five potential/opportunity, two may/might/could, two can/verify/approval, and 15 with none of the fixed cues. These heuristics do not establish why a label was marked uncertain. Five examples for the owner are stored only in the private data directory and are not reproduced here.

No test data was used to tune the scoring amendment or facet description. No new provider calls were made.
