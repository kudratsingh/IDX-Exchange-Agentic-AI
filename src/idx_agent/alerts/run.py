"""Operator-run, draft-only refresh job. No scheduler or mail transport is installed."""

from __future__ import annotations

import argparse
import json

import pymysql

from idx_agent.alerts.newsince import needs_check
from idx_agent.alerts.query import fetch_new
from idx_agent.alerts.store import configured_store
from idx_agent.alerts.template import alert_body
from idx_agent.db import asof, pool
from idx_agent.email.recipients import configured_store as configured_gate
from idx_agent.email.recipients import resolve_recipient
from idx_agent.memory.identity import key_prefix
from idx_agent.observability.logging import log_event, new_trace_id
from idx_agent.safety.approval import ApprovalRefused


def run_job(store, gate, *, reader, dates, recipient, dry_run=False, replay=None):
    """Injected reader and gate make the complete job testable without credentials."""
    summary = {"checked": 0, "drafts": 0, "skipped": 0, "failed": 0, "pending": []}
    searches = store.all_searches()
    if replay and replay not in {s.id for s in searches}:
        raise ApprovalRefused("unknown_search")
    for saved in searches:
        if replay and saved.id != replay:
            continue
        if saved.expires_at <= store.clock() or (
            not replay and not needs_check(saved.checked_as_of, dates.active)
        ):
            summary["skipped"] += 1
            continue
        try:
            checked = saved
            if replay:
                from datetime import date

                checked = saved.model_copy(
                    update={"checked_as_of": date.min, "alerted_keys": []}
                )
            count, listings = reader(checked, dates.active)
            if type(count) is not int or count < len(listings) or len(listings) > 10:
                raise ValueError("invalid match count or row cap")
            if count and not listings:
                raise ValueError("matches unavailable")
            summary["checked"] += 1
            if dry_run:
                continue
            # Serialize with deletion, confirmation and competing job processes.
            with store.transaction(write=True) as conn:
                current = next(
                    (s for s in store.rows(conn, saved.sender_key) if s.id == saved.id),
                    None,
                )
                if current is None or (
                    not replay and current.checked_as_of != saved.checked_as_of
                ):
                    continue
                prior = conn.execute(
                    "SELECT draft_id FROM alerts WHERE search_id = ? AND as_of = ?",
                    (saved.id, dates.active.isoformat()),
                ).fetchone()
                if prior:
                    continue
                keys = list(
                    dict.fromkeys(
                        [*saved.alerted_keys, *(item.listing_key for item in listings)]
                    )
                )
                if len(keys) > 500:
                    raise ApprovalRefused("alert_key_cap")
                if count:
                    subject, body = alert_body(
                        saved, count, listings, dates.to_envelope()
                    )
                    draft = gate.create_draft(
                        recipient_label="owner",
                        recipient=recipient,
                        source="listings",
                        subject=subject,
                        body=body,
                        idempotency_key=f"alert:{saved.id}:{dates.active}",
                    )
                    conn.execute(
                        "INSERT INTO alerts (search_id, as_of, draft_id) "
                        "VALUES (?, ?, ?)",
                        (saved.id, dates.active.isoformat(), draft.id),
                    )
                    summary["pending"].append(
                        {"id": draft.id, "first_alert": saved.last_alert_as_of is None}
                    )
                    summary["drafts"] += 1
                conn.execute(
                    "UPDATE searches SET checked = ?, last_alert = ?, keys = ? "
                    "WHERE id = ?",
                    (
                        dates.active.isoformat(),
                        dates.active.isoformat()
                        if count
                        else (
                            saved.last_alert_as_of.isoformat()
                            if saved.last_alert_as_of
                            else None
                        ),
                        json.dumps(keys),
                        saved.id,
                    ),
                )
            log_event(
                "alerts.check",
                trace_id=new_trace_id(),
                key_prefix=key_prefix(saved.sender_key),
                search_id=saved.id,
                matches=count,
                outcome="drafted" if count else "no_matches",
            )
        except Exception as exc:  # noqa: BLE001 - fixed codes, never source text
            summary["failed"] += 1
            reason = (
                "alert_key_cap"
                if isinstance(exc, ApprovalRefused) and exc.reason == "alert_key_cap"
                else "step_failed"
            )
            log_event(
                "alerts.check",
                trace_id=new_trace_id(),
                key_prefix=key_prefix(saved.sender_key),
                search_id=saved.id,
                outcome="failed",
                reason=reason,
            )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Operator view: private saved-search IDs, no database query",
    )
    parser.add_argument(
        "--replay",
        help="Saved-search id; one snapshot still produces at most one draft",
    )
    args = parser.parse_args(argv)
    conn = None
    try:
        store = configured_store()
        if args.list:
            if args.dry_run or args.replay:
                raise ApprovalRefused("incompatible_flags")
            searches = store.all_searches()
            print(
                json.dumps(
                    {
                        "count": len(searches),
                        "saved": [
                            {
                                "id": s.id,
                                "checked_as_of": str(s.checked_as_of),
                                "lapsed": s.expires_at <= store.clock(),
                            }
                            for s in searches
                        ],
                    },
                    sort_keys=True,
                )
            )
            return 0
        # Dry-run never opens or creates the approval journal.
        gate = None if args.dry_run else configured_gate()
        recipient = None if args.dry_run else resolve_recipient()
        conn = pool.connect()
        dates = asof.get_asof_dates(conn)
        result = run_job(
            store,
            gate,
            reader=lambda s, d: fetch_new(s, d, conn),
            dates=dates,
            recipient=recipient,
            dry_run=args.dry_run,
            replay=args.replay,
        )
        print(json.dumps(result, sort_keys=True))
        return 4 if result["failed"] else 0
    except ApprovalRefused:
        print("Alert job refused: check the private store and owner email settings.")
        return 2
    except pymysql.MySQLError:
        print("Alert job: database unavailable.")
        return 3
    except Exception:  # noqa: BLE001
        print("Alert job could not complete.")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
