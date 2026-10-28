# WO-018 held-out results

**Eligibility update, 2026-10-28:** The owner now also requires at least 10
gold examples per facet. The historical eligibility column below applies the
earlier F1-only rule; the current 20-facet list is in WO-018 Status.

2026-10-28; 150 held-out remarks, one approved run. Only aggregate data is recorded. Labels were drafted by Claude and owner-reviewed; shared-model bias is possible.

Frozen structured micro F1: 88.2%, precision 83.1%, recall 94.1%; 825 correct / 993 predicted / 877 expected. The 85% overall gate passed. Exact-span overall F1: 39.8%.

Requests: 150; retries: 0 ({}); missing tool calls: 0; remarks with validation misses: 9; diagnostics: 15.

Input: 354159 total (78759 uncached, 1836 cache creation, 273564 cache read); 2361.06 total and 525.06 uncached per remark. Output: 64068; 427.12 per remark.

A categorical facet is eligible for search and cards only when it has held-out support and F1 >= 80%. Eligibility is a threshold result, not an integration implementation. Low support gives weak evidence; counts are shown below.

| Facet or numeric field | Gold | Predicted | Correct | Precision | Recall | F1 | Facet eligible |
|---|---:|---:|---:|---:|---:|---:|---|
| facet.community_amenities.clubhouse | 17 | 16 | 16 | 100.0% | 94.1% | 97.0% | yes |
| facet.community_amenities.community_pool | 32 | 32 | 32 | 100.0% | 100.0% | 100.0% | yes |
| facet.community_amenities.fitness_center | 14 | 14 | 14 | 100.0% | 100.0% | 100.0% | yes |
| facet.community_amenities.gated_community | 16 | 20 | 16 | 80.0% | 100.0% | 88.9% | yes |
| facet.condition_sale.as_is | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% | yes |
| facet.condition_sale.back_on_market_mentioned | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% | yes |
| facet.condition_sale.motivated_seller_mentioned | 1 | 2 | 1 | 50.0% | 100.0% | 66.7% | no |
| facet.condition_sale.needs_work | 3 | 7 | 3 | 42.9% | 100.0% | 60.0% | no |
| facet.condition_sale.price_reduction_mentioned | 6 | 6 | 6 | 100.0% | 100.0% | 100.0% | yes |
| facet.condition_sale.probate_mentioned | 0 | 0 | 0 | — | — | — | no |
| facet.exterior_lot.adu | 14 | 13 | 11 | 84.6% | 78.6% | 81.5% | yes |
| facet.exterior_lot.corner_lot | 8 | 10 | 8 | 80.0% | 100.0% | 88.9% | yes |
| facet.exterior_lot.fenced_yard | 3 | 9 | 3 | 33.3% | 100.0% | 50.0% | no |
| facet.exterior_lot.garage | 70 | 75 | 68 | 90.7% | 97.1% | 93.8% | yes |
| facet.exterior_lot.large_yard | 18 | 27 | 11 | 40.7% | 61.1% | 48.9% | no |
| facet.exterior_lot.patio | 41 | 54 | 41 | 75.9% | 100.0% | 86.3% | yes |
| facet.exterior_lot.pool | 20 | 19 | 18 | 94.7% | 90.0% | 92.3% | yes |
| facet.interior_systems.central_air | 9 | 24 | 9 | 37.5% | 100.0% | 54.5% | no |
| facet.interior_systems.hardwood | 17 | 23 | 17 | 73.9% | 100.0% | 85.0% | yes |
| facet.interior_systems.luxury_vinyl_plank | 9 | 11 | 9 | 81.8% | 100.0% | 90.0% | yes |
| facet.interior_systems.solar | 21 | 18 | 18 | 100.0% | 85.7% | 92.3% | yes |
| facet.interior_systems.stainless_appliances | 26 | 29 | 25 | 86.2% | 96.2% | 90.9% | yes |
| facet.interior_systems.updated_kitchen | 18 | 32 | 18 | 56.2% | 100.0% | 72.0% | no |
| facet.interior_systems.washer_dryer | 13 | 22 | 13 | 59.1% | 100.0% | 74.3% | no |
| facet.location_views.city_view | 4 | 5 | 4 | 80.0% | 100.0% | 88.9% | yes |
| facet.location_views.mountain_view | 16 | 22 | 16 | 72.7% | 100.0% | 84.2% | yes |
| facet.location_views.near_grocery_mentioned | 13 | 11 | 11 | 100.0% | 84.6% | 91.7% | yes |
| facet.location_views.near_transit_mentioned | 13 | 14 | 13 | 92.9% | 100.0% | 96.3% | yes |
| facet.location_views.water_view | 14 | 13 | 13 | 100.0% | 92.9% | 96.3% | yes |
| facet.property_type.condominium | 18 | 18 | 17 | 94.4% | 94.4% | 94.4% | yes |
| facet.property_type.manufactured | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% | yes |
| facet.property_type.multi_unit | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% | yes |
| facet.property_type.single_family | 3 | 9 | 3 | 33.3% | 100.0% | 50.0% | no |
| facet.property_type.townhouse | 8 | 8 | 8 | 100.0% | 100.0% | 100.0% | yes |
| facet.rooms_layout.bonus_room | 19 | 18 | 18 | 100.0% | 94.7% | 97.3% | yes |
| facet.rooms_layout.office | 53 | 51 | 38 | 74.5% | 71.7% | 73.1% | no |
| facet.rooms_layout.open_plan | 38 | 46 | 37 | 80.4% | 97.4% | 88.1% | yes |
| facet.rooms_layout.single_level | 17 | 17 | 16 | 94.1% | 94.1% | 94.1% | yes |
| facet.rooms_layout.split_level | 0 | 5 | 0 | 0.0% | — | 0.0% | no |
| facet.rooms_layout.walk_in_closet | 35 | 35 | 35 | 100.0% | 100.0% | 100.0% | yes |
| facet.style.contemporary | 3 | 14 | 2 | 14.3% | 66.7% | 23.5% | no |
| facet.style.cottage | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% | yes |
| facet.style.craftsman | 0 | 0 | 0 | — | — | — | no |
| facet.style.mid_century | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% | yes |
| facet.style.ranch | 2 | 2 | 2 | 100.0% | 100.0% | 100.0% | yes |
| facet.style.spanish | 1 | 2 | 1 | 50.0% | 100.0% | 66.7% | no |
| facet.style.traditional | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% | yes |
| numeric.asking_price_usd | 1 | 1 | 1 | 100.0% | 100.0% | 100.0% | — |
| numeric.bathrooms | 89 | 88 | 85 | 96.6% | 95.5% | 96.0% | — |
| numeric.bedrooms | 95 | 94 | 92 | 97.9% | 96.8% | 97.4% | — |
| numeric.living_area_sqft | 47 | 45 | 44 | 97.8% | 93.6% | 95.7% | — |

Polarity breakdown (categorical overlap):

| Polarity | Gold | Predicted | Correct | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| polarity.affirmed | 591 | 703 | 567 | 80.7% | 95.9% | 87.6% |
| polarity.negated | 1 | 3 | 1 | 33.3% | 100.0% | 50.0% |
| polarity.uncertain | 53 | 59 | 35 | 59.3% | 66.0% | 62.5% |
