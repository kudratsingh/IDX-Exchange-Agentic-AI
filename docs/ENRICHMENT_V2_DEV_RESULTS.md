# WO-018 v2 dev comparison

2026-10-28. 100 owner-reviewed dev remarks per model; Claude-drafted labels create possible shared-model bias. No held-out evaluation was performed.

Frozen polarity-aware overlap across the 20 v2 facets: Sonnet 94.69% micro F1; Haiku 93.85%. Haiku is 0.84 percentage points lower and meets the three-point dev rule.

| Facet | Sonnet F1 | Haiku F1 |
|---|---:|---:|
| facet.community_amenities.clubhouse | 100.0% | 100.0% |
| facet.community_amenities.community_pool | 97.9% | 95.7% |
| facet.community_amenities.fitness_center | 100.0% | 100.0% |
| facet.community_amenities.gated_community | 81.8% | 85.7% |
| facet.exterior_lot.adu | 96.0% | 96.0% |
| facet.exterior_lot.garage | 100.0% | 100.0% |
| facet.exterior_lot.patio | 95.8% | 100.0% |
| facet.exterior_lot.pool | 88.9% | 88.9% |
| facet.interior_systems.hardwood | 81.1% | 85.7% |
| facet.interior_systems.solar | 100.0% | 100.0% |
| facet.interior_systems.stainless_appliances | 97.9% | 97.9% |
| facet.location_views.mountain_view | 88.2% | 100.0% |
| facet.location_views.near_grocery_mentioned | 100.0% | 80.0% |
| facet.location_views.near_transit_mentioned | 87.5% | 82.4% |
| facet.location_views.water_view | 92.3% | 100.0% |
| facet.property_type.condominium | 100.0% | 95.2% |
| facet.rooms_layout.bonus_room | 80.0% | 57.1% |
| facet.rooms_layout.open_plan | 89.6% | 81.1% |
| facet.rooms_layout.single_level | 96.6% | 82.4% |
| facet.rooms_layout.walk_in_closet | 97.1% | 100.0% |

| Model | Requests | Uncached input | Cache write | Cache read | Output | Validation-miss remarks | Missing tool calls | Retries |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| sonnet | 100 | 54260 | 1101 | 108999 | 28189 | 0 | 0 | 0 |
| haiku | 100 | 54260 | 1101 | 108999 | 87174 | 1 | 0 | 0 |

Costs must be read from the provider console. Haiku requires a separate authorized held-out confirmation; no integration eligibility changes from this dev run.
