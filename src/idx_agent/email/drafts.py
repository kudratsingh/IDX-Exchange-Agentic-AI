"""Build and store email previews from fresh tool data; no delivery imports."""

from __future__ import annotations

import pymysql

from idx_agent.db import asof, listings, pool
from idx_agent.domain.email import DraftEmailRequest
from idx_agent.domain.models import (
    Clarification,
    MarketStats,
    PropertySearchFilters,
    RagAnswer,
)
from idx_agent.domain.results import AgentResult, EmailDraftView, Provenance, ToolError
from idx_agent.email import bodies
from idx_agent.email.recipients import configured_store, resolve_recipient
from idx_agent.memory.identity import memory_key
from idx_agent.observability.logging import new_trace_id
from idx_agent.observability.tracing import span
from idx_agent.safety.approval import ApprovalRefused, view

APPROVAL_NOTICE = (
    "Nothing has been sent. The owner approves this draft outside this chat "
    "before it can go out."
)


def _draft_error(trace_id, provenance, category, message):
    return AgentResult(
        ok=False,
        provenance=provenance,
        error=ToolError(
            category=category,
            message=message,
            trace_id=trace_id,
        ),
    )


def draft_result(raw, trace_id=None, log_fields=None):
    """Validate, re-fetch a known source and persist a deterministic preview."""
    from idx_agent.mcp_server import server

    trace_id = trace_id or new_trace_id()
    provenance = Provenance(tool="draft_email", trace_id=trace_id)
    with span("idx.draft.validate"):
        checked = DraftEmailRequest.from_input(raw)
    if isinstance(checked, Clarification):
        return AgentResult(
            ok=True, data=checked, message=checked.question, provenance=provenance
        )
    try:
        recipient = resolve_recipient(checked.to)
        if checked.source in {"property", "recommendations"}:
            from idx_agent.email.property import build_property

            result, content = build_property(checked, server)
            provenance = result.provenance.model_copy(
                update={"tool": "draft_email", "trace_id": trace_id}
            )
            if content is None:
                return result.model_copy(update={"provenance": provenance})
            subject, body = content
        elif checked.source == "listings":
            keys = checked.listing_keys
            if keys is None:
                key = memory_key(checked.sender_id)
                session = server._get_store().get(key) if key else None
                keys = session.last_result_keys[:10] if session else []
            if not keys:
                return AgentResult(
                    ok=True,
                    message="Which displayed listings should I draft?",
                    provenance=provenance,
                )
            if not pool.database_configured():
                raise ApprovalRefused("db")
            conn = pool.connect()
            try:
                dates = asof.get_asof_dates(conn).to_envelope()
                found = listings.fetch_candidates(PropertySearchFilters(), keys, conn)
            finally:
                conn.close()
            if not found.listings:
                return AgentResult(
                    ok=True,
                    message="Those listings are no longer available.",
                    provenance=provenance,
                )
            subject, body = bodies.listing_body(
                found.listings, dates, len(keys) - len(found.listings)
            )
            provenance = provenance.model_copy(
                update={"tables": ["rets_property"], "as_of": dates}
            )
        else:
            params = checked.model_dump(
                exclude_none=True,
                include={
                    "city",
                    "postal_code",
                    "property_subtype",
                    "months",
                    "question",
                    "include_extended",
                },
            )
            # Reference-note email uses lexical retrieval, with no provider call.
            result = (
                server.market_result(params)
                if checked.source == "market"
                else server.rag_result(params, lexical_only=True)
            )
            provenance = result.provenance.model_copy(
                update={"tool": "draft_email", "trace_id": trace_id}
            )
            if not result.ok or isinstance(result.data, Clarification):
                return result.model_copy(update={"provenance": provenance})
            if checked.source == "market":
                if not isinstance(result.data, MarketStats) or result.data.low_sample:
                    return AgentResult(
                        ok=True, message=result.message, provenance=provenance
                    )
                subject, body = bodies.market_body(result.message, provenance.as_of)
            else:
                if not isinstance(result.data, RagAnswer) or not result.data.found:
                    return AgentResult(
                        ok=True,
                        message="There are no reference notes to draft.",
                        provenance=provenance,
                    )
                subject, body = bodies.document_body(result.data.chunks)
        with span("idx.draft.store"):
            record = configured_store().create_draft(
                recipient_label="owner",
                recipient=recipient,
                source=checked.source,
                subject=subject,
                body=body,
            )
        preview = view(record)
        if log_fields is not None:
            log_fields.update(
                draft_id=record.id, source=checked.source, state="pending"
            )
        message = (
            f"Draft {record.id} for owner\nSubject: {subject}\n\n{body}\n\n"
            f"Expires: {preview.expires_at.isoformat()}\n"
            f"Digest: {preview.digest_prefix}\n{APPROVAL_NOTICE}"
        )
        return AgentResult[EmailDraftView](
            ok=True,
            data=preview,
            pending_action=preview,
            message=message,
            provenance=provenance,
        )
    except ApprovalRefused as exc:
        if log_fields is not None:
            log_fields["reason"] = exc.reason
        if exc.reason == "no_shareable_answer":
            return AgentResult(
                ok=True,
                provenance=provenance,
                message="There are no project-authored reference notes to draft.",
            )
        if exc.reason == "db":
            return _draft_error(
                trace_id,
                provenance,
                "db",
                "The email source is unavailable; try again later.",
            )
        if exc.reason == "safety_refusal":
            return _draft_error(
                trace_id,
                provenance,
                "safety_refusal",
                "The email preview contains restricted information and was refused.",
            )
        return _draft_error(
            trace_id,
            provenance,
            "not_found",
            "The email draft is unavailable; check the email settings.",
        )
    except pymysql.MySQLError:
        return _draft_error(
            trace_id,
            provenance,
            "db",
            "The email source is unavailable; try again later.",
        )
    except Exception:  # noqa: BLE001 - no private details across MCP
        return AgentResult(
            ok=False,
            provenance=provenance,
            error=ToolError(
                category="internal",
                message="The email draft could not be prepared; try again later.",
                trace_id=trace_id,
            ),
        )
