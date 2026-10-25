"""Versioned candidate vocabulary, not extracted or verified listing facts."""

from types import MappingProxyType

VOCABULARY_VERSION = "remarks-facets-v1"
FACETS = MappingProxyType(
    {
        "property_type": frozenset(
            {"single_family", "condominium", "townhouse", "manufactured", "multi_unit"}
        ),
        "style": frozenset(
            {
                "craftsman",
                "mid_century",
                "traditional",
                "contemporary",
                "spanish",
                "ranch",
                "cottage",
            }
        ),
        "rooms_layout": frozenset(
            {
                "open_plan",
                "single_level",
                "split_level",
                "bonus_room",
                "office",
                "walk_in_closet",
            }
        ),
        "interior_systems": frozenset(
            {
                "central_air",
                "washer_dryer",
                "stainless_appliances",
                "hardwood",
                "luxury_vinyl_plank",
                "solar",
                "updated_kitchen",
            }
        ),
        "exterior_lot": frozenset(
            {
                "adu",
                "corner_lot",
                "large_yard",
                "fenced_yard",
                "pool",
                "garage",
                "patio",
            }
        ),
        "community_amenities": frozenset(
            {"community_pool", "clubhouse", "fitness_center", "gated_community"}
        ),
        "location_views": frozenset(
            {
                "mountain_view",
                "city_view",
                "water_view",
                "near_transit_mentioned",
                "near_grocery_mentioned",
            }
        ),
        "condition_sale": frozenset(
            {
                "needs_work",
                "as_is",
                "probate_mentioned",
                "price_reduction_mentioned",
                "back_on_market_mentioned",
                "motivated_seller_mentioned",
            }
        ),
    }
)
