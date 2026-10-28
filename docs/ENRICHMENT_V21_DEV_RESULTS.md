# WO-018 Haiku v2.1 dev results

100 owner-reviewed dev remarks. Gold labels were Claude-drafted and owner-reviewed, a possible shared-model bias. This is not a held-out result.

Haiku v2.1 micro F1: 89.66%; Sonnet v2: 94.69%. Haiku was 5.03 points lower. Haiku output averaged 652.28 tokens per remark; both owner thresholds were missed. The owner decision selects Sonnet for bulk and calls for reuse of the 324 v1 records.

| Facet | Sonnet v2 F1 | Haiku v2.1 F1 |
|---|---:|---:|
| facet.community_amenities.clubhouse | 100.0% | 100.0% |
| facet.community_amenities.community_pool | 97.9% | 93.3% |
| facet.community_amenities.fitness_center | 100.0% | 95.2% |
| facet.community_amenities.gated_community | 81.8% | 84.2% |
| facet.exterior_lot.adu | 96.0% | 96.0% |
| facet.exterior_lot.garage | 100.0% | 99.0% |
| facet.exterior_lot.patio | 95.8% | 95.7% |
| facet.exterior_lot.pool | 88.9% | 82.8% |
| facet.interior_systems.hardwood | 81.1% | 82.4% |
| facet.interior_systems.solar | 100.0% | 100.0% |
| facet.interior_systems.stainless_appliances | 97.9% | 89.8% |
| facet.location_views.mountain_view | 88.2% | 87.5% |
| facet.location_views.near_grocery_mentioned | 100.0% | 50.0% |
| facet.location_views.near_transit_mentioned | 87.5% | 82.4% |
| facet.location_views.water_view | 92.3% | 100.0% |
| facet.property_type.condominium | 100.0% | 85.7% |
| facet.rooms_layout.bonus_room | 80.0% | 40.0% |
| facet.rooms_layout.open_plan | 89.6% | 72.7% |
| facet.rooms_layout.single_level | 96.6% | 93.3% |
| facet.rooms_layout.walk_in_closet | 97.1% | 95.4% |

Haiku: 100 requests; 0 retries; 0 missing tool calls; 13 remarks with validation misses. Input: 54260 uncached, 1125 cache write, 111375 cache read. Output: 65228; thinking tokens: 0. Costs come from the provider console.
