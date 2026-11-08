/**
 * The synthetic card-tool result the fake `idx` server returns (harness data only). It has
 * the real server's shape for `search_listings`: one text content block holding the JSON
 * envelope `{ ok, data: { listings }, provenance }` (ONE_COPY_TOOLS). The channel's own
 * renderer (`../card-render.mjs`) turns it into the card bytes the peer must receive.
 */
export function listingEnvelopeFor(ref) {
  return {
    ok: true,
    data: {
      listings: [
        {
          listing_id: ref,
          city: "Irvine",
          postal_code: "92618",
          list_price: 612000,
          bedrooms: 3,
          bathrooms: 2,
          living_area: 1640,
          property_subtype: "SingleFamilyResidence",
          status: "Active",
        },
      ],
    },
    provenance: { as_of: { active: "2026-10-31" } },
  };
}

/** The host-shaped tool result for that envelope. */
export function listingResultFor(ref) {
  return { content: [{ type: "text", text: JSON.stringify(listingEnvelopeFor(ref), null, 2) }] };
}
