# WO-018 dev3 aggregate results

2026-10-27. Development split only; owner-reviewed labels were Claude-drafted, so shared-model bias is possible. These are not held-out results.

The original prediction file contained invalid identifiers due to a runner defect. This report scores a separate file reconstructed offline from the 100 private checkpoints. No responses were regenerated.

100 requests; 0 retries; 0 missing tool calls; 7 remarks with validation misses. Input tokens 237,860 (54,260 uncached, 1,836 cache creation, 181,764 cache read), 2,378.6 per remark; output 45,036, 450.36 per remark.

Frozen categorical polarity-aware overlap plus exact numeric value: micro F1 89.3%. Exact-span overall F1 38.8%. The 85% gate is on the 150 held-out cases, not this dev result.

| Facet or numeric field | Gold | Predicted | Correct | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| facet.community_amenities.clubhouse | 13 | 13 | 13 | 100.0% | 100.0% | 100.0% |
| facet.community_amenities.community_pool | 24 | 23 | 23 | 100.0% | 95.8% | 97.9% |
| facet.community_amenities.fitness_center | 11 | 10 | 10 | 100.0% | 90.9% | 95.2% |
| facet.community_amenities.gated_community | 9 | 14 | 9 | 64.3% | 100.0% | 78.3% |
| facet.condition_sale.as_is | 1 | 2 | 1 | 50.0% | 100.0% | 66.7% |
| facet.condition_sale.back_on_market_mentioned | 0 | 0 | 0 | — | — | — |
| facet.condition_sale.motivated_seller_mentioned | 1 | 3 | 1 | 33.3% | 100.0% | 50.0% |
| facet.condition_sale.needs_work | 1 | 2 | 0 | 0.0% | 0.0% | 0.0% |
| facet.condition_sale.price_reduction_mentioned | 3 | 3 | 3 | 100.0% | 100.0% | 100.0% |
| facet.condition_sale.probate_mentioned | 0 | 0 | 0 | — | — | — |
| facet.exterior_lot.adu | 13 | 10 | 10 | 100.0% | 76.9% | 87.0% |
| facet.exterior_lot.corner_lot | 8 | 9 | 8 | 88.9% | 100.0% | 94.1% |
| facet.exterior_lot.fenced_yard | 2 | 7 | 2 | 28.6% | 100.0% | 44.4% |
| facet.exterior_lot.garage | 52 | 54 | 52 | 96.3% | 100.0% | 98.1% |
| facet.exterior_lot.large_yard | 7 | 14 | 7 | 50.0% | 100.0% | 66.7% |
| facet.exterior_lot.patio | 34 | 41 | 34 | 82.9% | 100.0% | 90.7% |
| facet.exterior_lot.pool | 13 | 14 | 12 | 85.7% | 92.3% | 88.9% |
| facet.interior_systems.central_air | 12 | 24 | 12 | 50.0% | 100.0% | 66.7% |
| facet.interior_systems.hardwood | 15 | 21 | 14 | 66.7% | 93.3% | 77.8% |
| facet.interior_systems.luxury_vinyl_plank | 4 | 6 | 4 | 66.7% | 100.0% | 80.0% |
| facet.interior_systems.solar | 12 | 12 | 12 | 100.0% | 100.0% | 100.0% |
| facet.interior_systems.stainless_appliances | 23 | 24 | 23 | 95.8% | 100.0% | 97.9% |
| facet.interior_systems.updated_kitchen | 18 | 29 | 18 | 62.1% | 100.0% | 76.6% |
| facet.interior_systems.washer_dryer | 9 | 20 | 9 | 45.0% | 100.0% | 62.1% |
| facet.location_views.city_view | 4 | 6 | 4 | 66.7% | 100.0% | 80.0% |
| facet.location_views.mountain_view | 15 | 18 | 15 | 83.3% | 100.0% | 90.9% |
| facet.location_views.near_grocery_mentioned | 6 | 5 | 5 | 100.0% | 83.3% | 90.9% |
| facet.location_views.near_transit_mentioned | 7 | 10 | 7 | 70.0% | 100.0% | 82.4% |
| facet.location_views.water_view | 6 | 6 | 5 | 83.3% | 83.3% | 83.3% |
| facet.property_type.condominium | 10 | 9 | 9 | 100.0% | 90.0% | 94.7% |
| facet.property_type.manufactured | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% |
| facet.property_type.multi_unit | 1 | 3 | 1 | 33.3% | 100.0% | 50.0% |
| facet.property_type.single_family | 3 | 4 | 3 | 75.0% | 100.0% | 85.7% |
| facet.property_type.townhouse | 5 | 5 | 5 | 100.0% | 100.0% | 100.0% |
| facet.rooms_layout.bonus_room | 2 | 4 | 2 | 50.0% | 100.0% | 66.7% |
| facet.rooms_layout.office | 23 | 21 | 16 | 76.2% | 69.6% | 72.7% |
| facet.rooms_layout.open_plan | 30 | 36 | 30 | 83.3% | 100.0% | 90.9% |
| facet.rooms_layout.single_level | 14 | 14 | 14 | 100.0% | 100.0% | 100.0% |
| facet.rooms_layout.split_level | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% |
| facet.rooms_layout.walk_in_closet | 33 | 33 | 32 | 97.0% | 97.0% | 97.0% |
| facet.style.contemporary | 5 | 8 | 5 | 62.5% | 100.0% | 76.9% |
| facet.style.cottage | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% |
| facet.style.craftsman | 0 | 0 | 0 | — | — | — |
| facet.style.mid_century | 5 | 5 | 5 | 100.0% | 100.0% | 100.0% |
| facet.style.ranch | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% |
| facet.style.spanish | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% |
| facet.style.traditional | 0 | 0 | 0 | — | — | — |
| numeric.asking_price_usd | 1 | 2 | 1 | 50.0% | 100.0% | 66.7% |
| numeric.bathrooms | 54 | 56 | 53 | 94.6% | 98.1% | 96.4% |
| numeric.bedrooms | 65 | 69 | 64 | 92.8% | 98.5% | 95.5% |
| numeric.living_area_sqft | 26 | 29 | 26 | 89.7% | 100.0% | 94.5% |

Polarity breakdown (overlap):

| Polarity | Gold | Predicted | Correct | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| polarity.affirmed | 438 | 514 | 429 | 83.5% | 97.9% | 90.1% |
| polarity.negated | 0 | 2 | 0 | 0.0% | — | 0.0% |
| polarity.uncertain | 22 | 32 | 12 | 37.5% | 54.5% | 44.4% |

Ten largest exact-span disagreements (not the overlap gate):

| Facet | False-positive spans | False-negative spans |
|---|---:|---:|
| facet.exterior_lot.garage | 50 | 52 |
| facet.exterior_lot.patio | 35 | 33 |
| facet.rooms_layout.walk_in_closet | 22 | 25 |
| facet.rooms_layout.open_plan | 24 | 19 |
| facet.rooms_layout.office | 20 | 22 |
| facet.interior_systems.updated_kitchen | 23 | 13 |
| facet.community_amenities.community_pool | 14 | 18 |
| facet.exterior_lot.pool | 12 | 20 |
| facet.interior_systems.hardwood | 19 | 13 |
| facet.exterior_lot.adu | 9 | 21 |
