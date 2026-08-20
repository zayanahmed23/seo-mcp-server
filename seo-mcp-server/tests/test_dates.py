"""Date vocabulary resolution and validation."""

from datetime import date

import pytest

from seo_mcp_server.dates import (
    DateParseError,
    resolve_date,
    resolve_date_range,
)

# A fixed "today" so relative tokens are deterministic. 2026-08-21 is a Friday
# in a non-leap year, with a 31-day previous month.
TODAY = date(2026, 8, 21)


@pytest.mark.parametrize(
    "token,is_end,expected",
    [
        # explicit days
        ("2026-03-14", False, "2026-03-14"),
        ("2026-03-14", True, "2026-03-14"),
        # relative days
        ("today", False, "2026-08-21"),
        ("yesterday", False, "2026-08-20"),
        ("30daysAgo", False, "2026-07-22"),
        ("7daysAgo", False, "2026-08-14"),
        ("0daysAgo", False, "2026-08-21"),
        # separator and case tolerance
        ("30 days ago", False, "2026-07-22"),
        ("30-days-ago", False, "2026-07-22"),
        ("  TODAY  ", False, "2026-08-21"),
        ("YeStErDaY", False, "2026-08-20"),
        # windows ending today
        ("last7days", False, "2026-08-15"),
        ("last7days", True, "2026-08-21"),
        ("past 30 days", False, "2026-07-23"),
        ("last1days", False, "2026-08-21"),
        # bare months resolve by role
        ("2026-03", False, "2026-03-01"),
        ("2026-03", True, "2026-03-31"),
        ("2026-02", True, "2026-02-28"),
        ("2024-02", True, "2024-02-29"),  # leap year
        # calendar periods
        ("thisMonth", False, "2026-08-01"),
        ("thisMonth", True, "2026-08-31"),
        ("lastMonth", False, "2026-07-01"),
        ("lastMonth", True, "2026-07-31"),
        ("thisYear", False, "2026-01-01"),
        ("thisYear", True, "2026-12-31"),
        ("lastYear", False, "2025-01-01"),
        ("lastYear", True, "2025-12-31"),
    ],
)
def test_resolve_date(token, is_end, expected):
    assert resolve_date(token, is_end=is_end, today=TODAY).isoformat() == expected


def test_last_month_spans_year_boundary():
    jan = date(2026, 1, 15)
    assert resolve_date("lastMonth", is_end=False, today=jan).isoformat() == "2025-12-01"
    assert resolve_date("lastMonth", is_end=True, today=jan).isoformat() == "2025-12-31"


def test_last_month_from_a_31st_does_not_overflow():
    """A naive month subtraction from Mar 31 lands on Mar 3."""
    mar31 = date(2026, 3, 31)
    assert resolve_date("lastMonth", is_end=True, today=mar31).isoformat() == "2026-02-28"


@pytest.mark.parametrize(
    "token",
    ["garbage", "", "   ", "2026-13-01", "2026-02-30", "next week", "2026/03/14", "tomorrow"],
)
def test_uninterpretable_tokens_raise(token):
    with pytest.raises(DateParseError):
        resolve_date(token, today=TODAY)


def test_error_message_lists_accepted_formats():
    with pytest.raises(DateParseError, match="30daysAgo"):
        resolve_date("nonsense", today=TODAY)


class TestRanges:
    def test_normalizes_to_iso(self):
        r = resolve_date_range("30daysAgo", "today", today=TODAY)
        assert r["start_date"] == "2026-07-22"
        assert r["end_date"] == "2026-08-21"
        assert r["days_in_range"] == 31

    def test_period_token_on_both_ends_covers_whole_period(self):
        r = resolve_date_range("lastMonth", "lastMonth", today=TODAY)
        assert (r["start_date"], r["end_date"]) == ("2026-07-01", "2026-07-31")
        assert r["days_in_range"] == 31

    def test_single_day_range(self):
        r = resolve_date_range("today", "today", today=TODAY)
        assert r["days_in_range"] == 1

    def test_echoes_requested_input(self):
        r = resolve_date_range("lastMonth", "today", today=TODAY)
        assert r["requested_start_date"] == "lastMonth"
        assert r["requested_end_date"] == "today"

    def test_inverted_range_raises(self):
        with pytest.raises(DateParseError, match="after"):
            resolve_date_range("today", "30daysAgo", today=TODAY)

    def test_future_start_raises(self):
        with pytest.raises(DateParseError, match="future"):
            resolve_date_range("2027-01-01", "2027-02-01", today=TODAY)

    def test_future_end_is_clamped_with_a_note(self):
        r = resolve_date_range("30daysAgo", "2027-01-01", today=TODAY)
        assert r["end_date"] == "2026-08-21"
        assert any("clamped" in n for n in r["notes"])

    def test_retention_warning_when_start_is_too_old(self):
        r = resolve_date_range("2020-01-01", "today", today=TODAY, retention_months=16)
        assert any("retention" in n for n in r["notes"])
        # It warns rather than rejecting - the API still returns what it has.
        assert r["start_date"] == "2020-01-01"

    def test_no_spurious_notes_for_a_normal_range(self):
        assert resolve_date_range("30daysAgo", "today", today=TODAY,
                                  retention_months=16)["notes"] == []
