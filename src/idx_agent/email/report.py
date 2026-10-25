"""Pure weekly snapshot report, dated from the MLS data rather than today's date."""

from __future__ import annotations

import os
from pathlib import Path

from idx_agent.domain.models import MarketStats
from idx_agent.domain.results import AsOf
from idx_agent.email.bodies import FOOTER, check_content
from idx_agent.safety.approval import ApprovalRefused, ignored

DEFAULT_CITIES = ("Pasadena", "Glendale", "Duarte")
DEFAULT_WINDOWS = (6, 3, 1)


def render_report(cards: list[str], as_of: AsOf) -> str:
    text = (
        f"IDX weekly market report\nListings as of {as_of.active}\n"
        f"Closed sales through {as_of.sold}\n"
        "These figures change only when the data snapshot is refreshed.\n\n"
        + "\n\n".join(cards)
        + "\n\nMethod: subtype-specific closed sales, using the data's dates "
        "and exclusion rules.\n"
    )
    check_content("IDX weekly market report", text)
    return text


def collect_report(cities, result_fn, windows=DEFAULT_WINDOWS):
    cards, dates = [], None
    if not cities or len(cities) > 10 or len(set(cities)) != len(cities):
        raise ApprovalRefused("invalid_cities")
    if not windows or any(type(m) is not int or m not in {1, 3, 6} for m in windows):
        raise ApprovalRefused("invalid_windows")
    for city in cities:
        for months in windows:
            result = result_fn({"city": city, "months": months})
            if not result.ok or not isinstance(result.data, MarketStats):
                raise ApprovalRefused("report_unavailable")
            current = result.provenance.as_of
            if not current.sold or not current.active or (dates and dates != current):
                raise ApprovalRefused("inconsistent_snapshot")
            dates = current
            if months != 6 and result.data.low_sample:
                continue
            cards.append(result.message)
    return render_report(cards, dates), dates


def write_report(path: Path, text: str, *, data_root: Path, is_ignored=ignored) -> None:
    resolved = path.resolve()
    if (
        path.is_symlink()
        or not resolved.is_relative_to(data_root.resolve())
        or not is_ignored(resolved)
    ):
        raise ApprovalRefused("unsafe_report_path")
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(
            resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        raise ApprovalRefused("report_exists") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def draft_report(store, recipient: str, text: str, dates: AsOf, cities):
    import hashlib

    # Include the exact content so changed templates never return a stale draft.
    content = hashlib.sha256(text.encode()).hexdigest()[:16]
    return store.create_draft(
        recipient_label="owner",
        recipient=recipient,
        source="report",
        subject=f"IDX weekly market report, sales to {dates.sold}",
        body=text + "\n" + FOOTER,
        idempotency_key=f"report:{dates.sold}:{','.join(cities)}:{content}",
    )
