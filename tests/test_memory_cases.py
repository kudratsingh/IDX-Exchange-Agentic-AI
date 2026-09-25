"""Checks for evals/cases/memory.yaml (WO-006): no model, no database, never skipped.

The file must load cleanly via the runner; each ci conversation then runs through it on
the real tool body and session store, invented Pasadena and Glendale listings (9 and 2
rows, as in the synthetic fixture) faking the db; a tool without sender support fails.
"""

from __future__ import annotations

import functools
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from evals import run as runner

from idx_agent.db import listings as db_listings
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import Listing, PropertySearchFilters
from idx_agent.mcp_server import server as mcp

CASES_FILE = Path(__file__).resolve().parents[1] / "evals" / "cases" / "memory.yaml"
CATEGORY = "multi_turn_memory"
ASOF = AsOfDates(sold=date(2026, 6, 30), active=date(2026, 7, 2))


def _load() -> tuple[list[runner.Case], list[runner.LoadError]]:
    """Load only memory.yaml, through the runner's own loader."""
    cases, errors = runner.load_cases(CASES_FILE.parent)
    mine = [c for c in cases if c.source == CASES_FILE.name]
    return mine, [e for e in errors if e.source == CASES_FILE.name]


CASES, LOAD_ERRORS = _load()
CI_CASES = [c for c in CASES if c.suite == "ci"]
CI_TURNS = [c for c in CI_CASES if c.check == "turns"]
LOCAL_CASES = [c for c in CASES if c.suite == "local"]


def test_file_loads_with_no_errors() -> None:
    assert LOAD_ERRORS == []
    assert CASES, "memory.yaml has no cases"


def test_case_ids_category_and_sizes() -> None:
    assert all(c.id.startswith("memory-") for c in CASES)
    assert {c.category for c in CASES} == {CATEGORY}
    # About 15 ci conversations, and the local model cases from the work order.
    assert len(CI_TURNS) >= 15
    assert len(LOCAL_CASES) >= 4
    assert all(c.check == "turns" and c.turns for c in LOCAL_CASES)
    assert all(t.input for c in LOCAL_CASES for t in c.turns)


def test_the_conversations_cover_the_work_order_list() -> None:
    modes = {
        (t.input_filters or {}).get("mode", "replace")
        for c in CI_TURNS
        for t in c.turns
    }
    assert modes == {"replace", "update", "more", "reset"}
    assert any("clear" in (t.input_filters or {}) for c in CI_TURNS for t in c.turns)
    # Two senders in one conversation, and a warning check for an update with no state.
    labels = {t.sender_id or c.sender_id for c in CI_TURNS for t in c.turns}
    assert {"sender-a", "sender-b"} <= labels
    assert any(t.warning for c in CI_TURNS for t in c.turns)
    # The photo line is checked on a refined reply and on a single search.
    assert any(c.check == "regex" for c in CI_CASES)
    assert any(
        t.check == "regex" and "photo" in t.expect["pattern"]
        for c in CI_TURNS
        for t in c.turns
    )


def _listing(key: int, city: str, postal: str, photos: int) -> Listing:
    """One invented active listing; photo counts vary so all three card forms show."""
    return Listing(
        listing_key=key,
        listing_id=f"TEST{key}",
        address=f"{key} Invented Way",
        city=city,
        postal_code=postal,
        list_price=900_000 + key * 1_000,
        bedrooms=3,
        bathrooms=2.0,
        living_area=1500,
        property_subtype="SingleFamilyResidence",
        status="Active",
        photo_count=photos,
        remarks="Invented remark about a sunny kitchen.",
    )


# Same counts as the synthetic fixture, so a paging case means the same in both.
ROWS = [_listing(k, "Pasadena", "91101", k % 3) for k in range(1, 10)] + [
    _listing(k, "Glendale", "91205", k % 3) for k in range(10, 12)
]


def _matches(filters: PropertySearchFilters) -> list[Listing]:
    """The invented rows in the filters' city or ZIP code (other filters ignored)."""
    if filters.city is not None:
        return [r for r in ROWS if r.city == filters.city]
    return [r for r in ROWS if r.postal_code == filters.postal_code]


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the db layer: search pages through the invented rows; count counts them."""

    def search(filters: PropertySearchFilters, conn: Any) -> Any:
        start = (filters.page - 1) * filters.limit
        rows = _matches(filters)[start : start + filters.limit]
        return db_listings.SearchOutcome(listings=rows)

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", lambda config=None: object())
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)
    monkeypatch.setattr(
        mcp.db_listings,
        "count_active_listings",
        lambda filters, conn: len(_matches(filters)),
        raising=False,
    )
    # The runner sets its own test key; CI=true only adds the database requirement.
    monkeypatch.delenv("IDX_SENDER_KEY", raising=False)
    monkeypatch.delenv("CI", raising=False)


@pytest.mark.parametrize("case", CI_CASES, ids=[c.id for c in CI_CASES])
def test_ci_case_passes_on_the_fake_db(case: runner.Case, fake_db: None) -> None:
    ctx = runner.RunContext(require_database=True)
    record = runner.run_case(case, ctx)
    assert record["result"] == "pass", record["detail"]


def test_ci_suite_run_is_green_and_leaks_no_sender_id(
    tmp_path: Path, fake_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every envelope the tool returns is kept, to look for the ids afterwards.
    dumps: list[str] = []
    real = mcp.search_result

    # wraps keeps the real signature, so the runner still passes sender_id as a keyword.
    @functools.wraps(real)
    def keep(raw: Any, *args: Any, **kwargs: Any) -> Any:
        env = real(raw, *args, **kwargs)
        dumps.append(json.dumps(env.model_dump(mode="json")))
        return env

    monkeypatch.setattr(mcp, "search_result", keep)
    folder = tmp_path / "cases"
    folder.mkdir()
    (folder / CASES_FILE.name).write_text(CASES_FILE.read_text("utf-8"), "utf-8")
    out = tmp_path / "report.json"
    argv = ["--cases-dir", str(folder), "--out", str(out), "--require-database"]
    code = runner.main([*argv, "--category", CATEGORY])
    report = json.loads(out.read_text("utf-8"))
    assert code == 0, [r for r in report["cases"] if r["result"] != "pass"]
    assert report["counts"]["pass"] == len(CI_CASES)
    assert report["counts"]["skipped"] == 0
    # No envelope, and not the report, carries a sender id the runner passed.
    ids = [runner.synthetic_sender_id(x) for x in ("sender-a", "sender-b")]
    text = "\n".join(dumps) + out.read_text("utf-8")
    assert dumps and not any(i in text for i in ids)
    # The runner leaves the key unset again.
    assert "IDX_SENDER_KEY" not in runner.os.environ
