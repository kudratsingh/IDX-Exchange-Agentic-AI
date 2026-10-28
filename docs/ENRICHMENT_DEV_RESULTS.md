# WO-018: development extraction results

One dev-only run, 2026-10-27: 100 requests; 424,460 input and 43,522 output tokens; 4,244.6 input and 435.22 output tokens per remark. Zero missing tool calls; 11 diagnostics affected 10 remarks. Cost must be obtained from the provider console.

The frozen exact-span structured micro F1 is 47.7%, with precision 47.5% and recall 47.9%. The categorical micro F1 is 37.8%; numeric micro F1 is 84.6%. The supported-class macro F1 is 40.0% across 47 classes. These are development results, not a held-out test or release decision. The proposed 85% test gate has not been evaluated.

Labels were Claude-drafted and owner-reviewed. The extractor is a different model from the same family; shared-model bias may affect agreement. Exact-span matching also counts semantically equivalent but differently bounded spans as disagreements.

## Per-facet results

| Facet or field | Gold spans | Predicted spans | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| `facet.community_amenities.clubhouse` | 14 | 13 | 53.8% | 50.0% | 51.9% |
| `facet.community_amenities.community_pool` | 27 | 23 | 56.5% | 48.1% | 52.0% |
| `facet.community_amenities.fitness_center` | 11 | 11 | 100.0% | 100.0% | 100.0% |
| `facet.community_amenities.gated_community` | 12 | 15 | 53.3% | 66.7% | 59.3% |
| `facet.condition_sale.as_is` | 1 | 1 | 0.0% | 0.0% | 0.0% |
| `facet.condition_sale.back_on_market_mentioned` | 0 | 0 | — | — | — |
| `facet.condition_sale.motivated_seller_mentioned` | 1 | 2 | 50.0% | 100.0% | 66.7% |
| `facet.condition_sale.needs_work` | 1 | 2 | 0.0% | 0.0% | 0.0% |
| `facet.condition_sale.price_reduction_mentioned` | 3 | 3 | 0.0% | 0.0% | 0.0% |
| `facet.condition_sale.probate_mentioned` | 0 | 0 | — | — | — |
| `facet.exterior_lot.adu` | 22 | 10 | 20.0% | 9.1% | 12.5% |
| `facet.exterior_lot.corner_lot` | 8 | 9 | 77.8% | 87.5% | 82.4% |
| `facet.exterior_lot.fenced_yard` | 2 | 6 | 33.3% | 100.0% | 50.0% |
| `facet.exterior_lot.garage` | 56 | 52 | 21.2% | 19.6% | 20.4% |
| `facet.exterior_lot.large_yard` | 8 | 11 | 27.3% | 37.5% | 31.6% |
| `facet.exterior_lot.patio` | 39 | 37 | 27.0% | 25.6% | 26.3% |
| `facet.exterior_lot.pool` | 22 | 14 | 14.3% | 9.1% | 11.1% |
| `facet.interior_systems.central_air` | 12 | 19 | 52.6% | 83.3% | 64.5% |
| `facet.interior_systems.hardwood` | 15 | 18 | 27.8% | 33.3% | 30.3% |
| `facet.interior_systems.luxury_vinyl_plank` | 4 | 5 | 60.0% | 75.0% | 66.7% |
| `facet.interior_systems.solar` | 14 | 12 | 33.3% | 28.6% | 30.8% |
| `facet.interior_systems.stainless_appliances` | 23 | 26 | 80.8% | 91.3% | 85.7% |
| `facet.interior_systems.updated_kitchen` | 19 | 26 | 42.3% | 57.9% | 48.9% |
| `facet.interior_systems.washer_dryer` | 9 | 19 | 5.3% | 11.1% | 7.1% |
| `facet.location_views.city_view` | 4 | 5 | 0.0% | 0.0% | 0.0% |
| `facet.location_views.mountain_view` | 20 | 17 | 23.5% | 20.0% | 21.6% |
| `facet.location_views.near_grocery_mentioned` | 7 | 27 | 7.4% | 28.6% | 11.8% |
| `facet.location_views.near_transit_mentioned` | 9 | 11 | 9.1% | 11.1% | 10.0% |
| `facet.location_views.water_view` | 12 | 5 | 40.0% | 16.7% | 23.5% |
| `facet.property_type.condominium` | 13 | 9 | 44.4% | 30.8% | 36.4% |
| `facet.property_type.manufactured` | 1 | 2 | 50.0% | 100.0% | 66.7% |
| `facet.property_type.multi_unit` | 1 | 2 | 0.0% | 0.0% | 0.0% |
| `facet.property_type.single_family` | 3 | 4 | 50.0% | 66.7% | 57.1% |
| `facet.property_type.townhouse` | 9 | 3 | 100.0% | 33.3% | 50.0% |
| `facet.rooms_layout.bonus_room` | 2 | 3 | 0.0% | 0.0% | 0.0% |
| `facet.rooms_layout.office` | 24 | 16 | 12.5% | 8.3% | 10.0% |
| `facet.rooms_layout.open_plan` | 31 | 38 | 47.4% | 58.1% | 52.2% |
| `facet.rooms_layout.single_level` | 16 | 14 | 71.4% | 62.5% | 66.7% |
| `facet.rooms_layout.split_level` | 1 | 1 | 100.0% | 100.0% | 100.0% |
| `facet.rooms_layout.walk_in_closet` | 36 | 32 | 43.8% | 38.9% | 41.2% |
| `facet.style.contemporary` | 7 | 8 | 37.5% | 42.9% | 40.0% |
| `facet.style.cottage` | 1 | 1 | 0.0% | 0.0% | 0.0% |
| `facet.style.craftsman` | 0 | 0 | — | — | — |
| `facet.style.mid_century` | 5 | 5 | 40.0% | 40.0% | 40.0% |
| `facet.style.ranch` | 2 | 2 | 50.0% | 50.0% | 50.0% |
| `facet.style.spanish` | 1 | 1 | 0.0% | 0.0% | 0.0% |
| `facet.style.traditional` | 0 | 0 | — | — | — |
| `numeric.asking_price_usd` | 1 | 2 | 50.0% | 100.0% | 66.7% |
| `numeric.bathrooms` | 54 | 52 | 94.2% | 90.7% | 92.5% |
| `numeric.bedrooms` | 65 | 61 | 93.4% | 87.7% | 90.5% |
| `numeric.living_area_sqft` | 26 | 25 | 56.0% | 53.8% | 54.9% |

An em dash means the metric is undefined for its denominator.

## Polarity

| Polarity | Gold spans | Predicted spans | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| affirmed | 504 | 508 | 39.6% | 39.9% | 39.7% |
| negated | 0 | 1 | 0.0% | — | 0.0% |
| uncertain | 24 | 31 | 3.2% | 4.2% | 3.6% |

## Largest disagreement buckets

| Facet or field | False-positive spans | False-negative spans |
|---|---:|---:|
| `facet.exterior_lot.garage` | 41 | 45 |
| `facet.exterior_lot.patio` | 27 | 29 |
| `facet.rooms_layout.walk_in_closet` | 18 | 22 |
| `facet.rooms_layout.office` | 14 | 22 |
| `facet.rooms_layout.open_plan` | 20 | 13 |
| `facet.exterior_lot.pool` | 12 | 20 |
| `facet.location_views.near_grocery_mentioned` | 25 | 5 |
| `facet.location_views.mountain_view` | 13 | 16 |
| `facet.exterior_lot.adu` | 8 | 20 |
| `facet.interior_systems.washer_dryer` | 18 | 8 |

Only aggregate counts and metrics are recorded here. The remarks, labels, predictions and diagnostic response bytes remain private under `data/enrichment/`.
