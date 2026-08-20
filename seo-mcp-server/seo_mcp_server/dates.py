"""
Flexible date-range resolution for the GSC and GA4 tools.

MCP tools are filled in by an LLM from natural language ("last month",
"the past 30 days"), but the Google APIs disagree about what they accept:
the GA4 Data API understands relative forms like '30daysAgo'/'today', while
the Search Console API accepts only strict YYYY-MM-DD. This module gives
both tools one permissive input vocabulary and normalizes everything to
YYYY-MM-DD before it reaches either API.

Resolution is role-aware: a bare month like '2026-03' (or 'lastMonth')
resolves to the first of the month for a start date and the last of the
month for an end date, so a single token can express a whole period.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

# Search Console retains roughly 16 months of performance data.
GSC_RETENTION_MONTHS = 16


class DateParseError(ValueError):
    """Raised when a date string can't be interpreted."""


_ACCEPTED_HELP = (
    "Accepted formats: 'YYYY-MM-DD' (e.g. '2026-03-14'); 'YYYY-MM' for a whole "
    "month; 'today'; 'yesterday'; 'NdaysAgo' (e.g. '30daysAgo'); 'lastNdays' "
    "(e.g. 'last7days'); 'thisMonth'; 'lastMonth'; 'thisYear'; 'lastYear'."
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
# Tolerates '30daysAgo', '30 days ago', '30-days-ago'
_DAYS_AGO_RE = re.compile(r"^(\d+)[\s_-]*days?[\s_-]*ago$")
# Tolerates 'last7days', 'last 7 days', 'past 7 days'
_LAST_N_DAYS_RE = re.compile(r"^(?:last|past)[\s_-]*(\d+)[\s_-]*days?$")


def _add_months(d: date, months: int) -> date:
    """Shifts by whole months, clamping to the target month's last day."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def resolve_date(value: str, *, is_end: bool = False, today: Optional[date] = None) -> date:
    """
    Resolves one date token to a concrete date.

    Args:
        value: The token to resolve (see _ACCEPTED_HELP for the vocabulary).
        is_end: When the token names a period rather than a day (e.g. '2026-03',
            'lastMonth', 'thisYear'), return the period's last day instead of
            its first. Set this for end_date.
        today: Injectable "current day", for testing and to keep both ends of
            a range resolving against the same day.
    """
    if today is None:
        today = date.today()

    if not isinstance(value, str) or not value.strip():
        raise DateParseError(f"Date is missing or empty. {_ACCEPTED_HELP}")

    raw = value.strip()
    # Normalize case/separators for keyword matching, but keep `raw` for errors.
    token = raw.lower().replace("_", "").replace("-", "") if not _ISO_DATE_RE.match(raw) else raw

    if _ISO_DATE_RE.match(raw):
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise DateParseError(
                f"'{raw}' looks like YYYY-MM-DD but is not a real calendar date ({exc}). {_ACCEPTED_HELP}"
            ) from exc

    month_match = _ISO_MONTH_RE.match(raw)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if not 1 <= month <= 12:
            raise DateParseError(f"'{raw}' has an invalid month. {_ACCEPTED_HELP}")
        first, last = _month_bounds(year, month)
        return last if is_end else first

    if token == "today":
        return today
    if token == "yesterday":
        return today - timedelta(days=1)

    if token == "thismonth":
        first, last = _month_bounds(today.year, today.month)
        return last if is_end else first
    if token == "lastmonth":
        prev = _add_months(today.replace(day=1), -1)
        first, last = _month_bounds(prev.year, prev.month)
        return last if is_end else first

    if token == "thisyear":
        return date(today.year, 12, 31) if is_end else date(today.year, 1, 1)
    if token == "lastyear":
        return date(today.year - 1, 12, 31) if is_end else date(today.year - 1, 1, 1)

    # Match against a whitespace-preserving form so '30 days ago' works too.
    loose = re.sub(r"\s+", "", raw.lower())

    days_ago = _DAYS_AGO_RE.match(loose) or _DAYS_AGO_RE.match(raw.strip().lower())
    if days_ago:
        return today - timedelta(days=int(days_ago.group(1)))

    last_n = _LAST_N_DAYS_RE.match(loose) or _LAST_N_DAYS_RE.match(raw.strip().lower())
    if last_n:
        n = int(last_n.group(1))
        if n < 1:
            raise DateParseError(f"'{raw}' must cover at least 1 day. {_ACCEPTED_HELP}")
        # 'last7days' means the 7 days ending yesterday-inclusive of today:
        # treat it as a window ending today, so start = today - (n - 1).
        return today if is_end else today - timedelta(days=n - 1)

    raise DateParseError(f"Could not interpret date '{raw}'. {_ACCEPTED_HELP}")


def resolve_date_range(
    start_date: str,
    end_date: str,
    *,
    today: Optional[date] = None,
    retention_months: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Resolves and validates a start/end pair into API-ready YYYY-MM-DD strings.

    Returns a dict with the normalized 'start_date'/'end_date', the inputs as
    given, and any 'notes' describing adjustments (e.g. a future end date
    clamped to today) so the caller can surface them to the LLM.

    Raises:
        DateParseError: if either token is uninterpretable, or start > end.
    """
    if today is None:
        today = date.today()

    start = resolve_date(start_date, is_end=False, today=today)
    end = resolve_date(end_date, is_end=True, today=today)

    notes: list[str] = []

    # A single period token used for both ends ('lastMonth' -> 'lastMonth')
    # resolves to that period's first and last day, which is the intent.
    if start > end:
        raise DateParseError(
            f"start_date '{start_date}' resolves to {start.isoformat()}, which is after "
            f"end_date '{end_date}' ({end.isoformat()}). Swap them or widen the range."
        )

    if start > today:
        raise DateParseError(
            f"start_date '{start_date}' resolves to {start.isoformat()}, which is in the "
            f"future. Analytics data only exists up to today ({today.isoformat()})."
        )

    if end > today:
        notes.append(
            f"end_date '{end_date}' resolved to {end.isoformat()}, which is in the future; "
            f"clamped to today ({today.isoformat()})."
        )
        end = today

    if retention_months:
        cutoff = _add_months(today, -retention_months)
        if start < cutoff:
            notes.append(
                f"start_date {start.isoformat()} predates the ~{retention_months}-month "
                f"data retention window (data begins around {cutoff.isoformat()}); "
                "earlier rows will come back empty."
            )

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "days_in_range": (end - start).days + 1,
        "notes": notes,
    }
