"""The data's as-of dates as a value object, and windows counted back from them.

Pure value code: no database access lives here (the db layer reads the dates).
Named AsOfDates, not AsOf, because results.AsOf is the optional-date envelope
field in Provenance; `to_envelope()` converts this one into that one.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from idx_agent.domain.results import AsOf


def _months_back(day: date, months: int) -> date:
    """Return the same day `months` calendar months earlier, clamped to month end."""
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


class AsOfDates(BaseModel):
    """Both tables' as-of dates: `sold` (california_sold) and `active` (rets_property).

    Frozen. Time windows count back from these dates, never from today.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    sold: date
    active: date

    def window(self, months: int) -> tuple[date, date]:
        """Return (start, end), inclusive, covering `months` months up to `sold`.

        End is the sold as-of date; start is the day after the same date `months`
        months earlier (6 months to 2026-09-17 starts 2026-03-18). Needs months >= 1.
        """
        if months < 1:
            raise ValueError("months must be at least 1")
        end = self.sold
        return _months_back(end, months) + timedelta(days=1), end

    def to_envelope(self) -> AsOf:
        """Return the results.AsOf used in Provenance, with both dates set."""
        return AsOf(sold=self.sold, active=self.active)
