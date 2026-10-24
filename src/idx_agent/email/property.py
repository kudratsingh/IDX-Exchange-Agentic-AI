"""Fresh property summaries and recommendation digests using the existing comp math."""

from idx_agent.channels.format import format_listing_card
from idx_agent.db import asof, pool
from idx_agent.domain.models import RecommendationResult
from idx_agent.email.bodies import check_content, dates_footer
from idx_agent.email.photos import fetch_photos
from idx_agent.safety.approval import ApprovalRefused


def property_body(result, photos, dates, *, digest=False):
    def card(listing, evidence):
        lines = [format_listing_card(listing, dates.active)]
        if evidence:
            lines.append("Price check: " + evidence.sentence)
            if evidence.range_sentence:
                lines.append(evidence.range_sentence)
        urls = photos.get(listing.listing_key, [])
        lines.extend(f"Photo {i}: {url}" for i, url in enumerate(urls, 1))
        if not urls:
            lines.append(
                "Photo links unavailable; the listing card shows "
                "the feed's photo count."
            )
        return "\n".join(lines)

    title = "IDX recommendation digest" if digest else "IDX property summary"
    sections = [
        title,
        "Subject property\n" + card(result.subject, result.subject_check),
    ]
    if digest:
        for i, rec in enumerate(result.recommendations, 1):
            sections.append(
                f"Recommendation {i}\n" + card(rec.listing, rec.comp_evidence)
            )
        if not result.recommendations:
            sections.append("No similar active listings were available.")
        if result.index_as_of and result.index_as_of != dates.active:
            sections.append(
                f"Similarity index as of {result.index_as_of}; "
                "current listings were rechecked."
            )
    sections.append(dates_footer(dates))
    body = "\n\n".join(sections)
    subject = f"{title}, listings as of {dates.active}"
    check_content(subject, body, allow_photos=True)
    return subject, body


def build_property(request, server):
    digest = request.source == "recommendations"
    result = server.recommend_result(
        {"listing_key": request.listing_keys[0], "k": 5 if digest else 0}
    )
    if not result.ok or not isinstance(result.data, RecommendationResult):
        return result, None
    data = result.data
    keys = [
        data.subject.listing_key,
        *(r.listing.listing_key for r in data.recommendations),
    ]
    conn = pool.connect()
    try:
        dates = asof.get_asof_dates(conn).to_envelope()
        if dates != result.provenance.as_of:
            raise ApprovalRefused("snapshot_changed")
        photos = fetch_photos(keys, conn)
    finally:
        conn.close()
    return result, property_body(data, photos, dates, digest=digest)
