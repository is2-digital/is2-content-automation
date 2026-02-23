"""Tests for ica.utils.date_parser — MM/DD/YYYY formatter and relative date parser.

Verifies date conversion handles various input formats and UTC edge cases,
matching the n8n date formatting used for Google Sheets display and the
SearchApi relative-date parsing for article publish dates.

Task: ica-dd0.1.1 — Test MM/DD/YYYY date formatter
"""

from __future__ import annotations

from datetime import date

import pytest

from ica.utils.date_parser import format_date_mmddyyyy, parse_relative_date

# Reference date for deterministic tests
REF_DATE = date(2026, 2, 22)


# ---------------------------------------------------------------------------
# format_date_mmddyyyy — basic formatting
# ---------------------------------------------------------------------------


class TestFormatBasic:
    """Core MM/DD/YYYY output format."""

    def test_standard_date(self) -> None:
        assert format_date_mmddyyyy(date(2026, 2, 22)) == "02/22/2026"

    def test_single_digit_month_is_zero_padded(self) -> None:
        assert format_date_mmddyyyy(date(2026, 1, 15)) == "01/15/2026"

    def test_single_digit_day_is_zero_padded(self) -> None:
        assert format_date_mmddyyyy(date(2026, 3, 5)) == "03/05/2026"

    def test_single_digit_month_and_day(self) -> None:
        assert format_date_mmddyyyy(date(2026, 1, 1)) == "01/01/2026"

    def test_december_31(self) -> None:
        assert format_date_mmddyyyy(date(2026, 12, 31)) == "12/31/2026"

    def test_max_day_february_non_leap(self) -> None:
        assert format_date_mmddyyyy(date(2025, 2, 28)) == "02/28/2025"

    def test_max_day_february_leap_year(self) -> None:
        assert format_date_mmddyyyy(date(2024, 2, 29)) == "02/29/2024"

    def test_year_before_1000(self) -> None:
        # Python strftime doesn't guarantee 4-digit years for years < 1000;
        # irrelevant for this project (all dates are 2024+) but documents behavior.
        result = format_date_mmddyyyy(date(999, 6, 15))
        assert result.startswith("06/15/")


# ---------------------------------------------------------------------------
# format_date_mmddyyyy — slash separators and order
# ---------------------------------------------------------------------------


class TestFormatStructure:
    """Verify MM/DD/YYYY structure — month first, slash-separated, 4-digit year."""

    def test_slash_separator(self) -> None:
        result = format_date_mmddyyyy(date(2026, 7, 4))
        parts = result.split("/")
        assert len(parts) == 3

    def test_month_is_first(self) -> None:
        result = format_date_mmddyyyy(date(2026, 3, 15))
        month, day, year = result.split("/")
        assert month == "03"
        assert day == "15"
        assert year == "2026"

    def test_four_digit_year(self) -> None:
        result = format_date_mmddyyyy(date(2026, 1, 1))
        year = result.split("/")[2]
        assert len(year) == 4

    def test_two_digit_month(self) -> None:
        result = format_date_mmddyyyy(date(2026, 11, 1))
        month = result.split("/")[0]
        assert len(month) == 2

    def test_two_digit_day(self) -> None:
        result = format_date_mmddyyyy(date(2026, 1, 30))
        day = result.split("/")[1]
        assert len(day) == 2


# ---------------------------------------------------------------------------
# format_date_mmddyyyy — boundary dates
# ---------------------------------------------------------------------------


class TestFormatBoundaries:
    """Edge-case dates: year boundaries, end-of-month, leap years."""

    def test_jan_1(self) -> None:
        assert format_date_mmddyyyy(date(2026, 1, 1)) == "01/01/2026"

    def test_dec_31(self) -> None:
        assert format_date_mmddyyyy(date(2026, 12, 31)) == "12/31/2026"

    def test_leap_day(self) -> None:
        assert format_date_mmddyyyy(date(2024, 2, 29)) == "02/29/2024"

    def test_end_of_april(self) -> None:
        assert format_date_mmddyyyy(date(2026, 4, 30)) == "04/30/2026"

    def test_end_of_march(self) -> None:
        assert format_date_mmddyyyy(date(2026, 3, 31)) == "03/31/2026"

    def test_distant_future(self) -> None:
        assert format_date_mmddyyyy(date(2099, 12, 31)) == "12/31/2099"

    def test_epoch_date(self) -> None:
        assert format_date_mmddyyyy(date(1970, 1, 1)) == "01/01/1970"


# ---------------------------------------------------------------------------
# format_date_mmddyyyy — return type
# ---------------------------------------------------------------------------


class TestFormatReturnType:
    """Ensure return value is always a string."""

    def test_returns_str(self) -> None:
        result = format_date_mmddyyyy(date(2026, 2, 22))
        assert isinstance(result, str)

    def test_length_is_10(self) -> None:
        """MM/DD/YYYY is always 10 characters."""
        result = format_date_mmddyyyy(date(2026, 2, 22))
        assert len(result) == 10


# ---------------------------------------------------------------------------
# format_date_mmddyyyy — parametrized all-months
# ---------------------------------------------------------------------------


class TestFormatAllMonths:
    """Verify every month formats correctly."""

    @pytest.mark.parametrize(
        ("month", "expected_prefix"),
        [
            (1, "01"),
            (2, "02"),
            (3, "03"),
            (4, "04"),
            (5, "05"),
            (6, "06"),
            (7, "07"),
            (8, "08"),
            (9, "09"),
            (10, "10"),
            (11, "11"),
            (12, "12"),
        ],
        ids=[f"month-{m:02d}" for m in range(1, 13)],
    )
    def test_month_prefix(self, month: int, expected_prefix: str) -> None:
        result = format_date_mmddyyyy(date(2026, month, 15))
        assert result.startswith(expected_prefix + "/")


# ---------------------------------------------------------------------------
# parse_relative_date — days
# ---------------------------------------------------------------------------


class TestParseDays:
    """Relative dates with day units."""

    def test_zero_days_ago(self) -> None:
        result = parse_relative_date("0 days ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_one_day_ago(self) -> None:
        result = parse_relative_date("1 day ago", reference=REF_DATE)
        assert result == date(2026, 2, 21)

    def test_singular_day(self) -> None:
        result = parse_relative_date("1 day ago", reference=REF_DATE)
        assert result == date(2026, 2, 21)

    def test_plural_days(self) -> None:
        result = parse_relative_date("3 days ago", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_seven_days_ago(self) -> None:
        result = parse_relative_date("7 days ago", reference=REF_DATE)
        assert result == date(2026, 2, 15)

    def test_days_crossing_month_boundary(self) -> None:
        result = parse_relative_date("25 days ago", reference=REF_DATE)
        assert result == date(2026, 1, 28)

    def test_days_crossing_year_boundary(self) -> None:
        ref = date(2026, 1, 5)
        result = parse_relative_date("10 days ago", reference=ref)
        assert result == date(2025, 12, 26)

    def test_large_number_of_days(self) -> None:
        result = parse_relative_date("365 days ago", reference=REF_DATE)
        assert result == date(2025, 2, 22)


# ---------------------------------------------------------------------------
# parse_relative_date — weeks
# ---------------------------------------------------------------------------


class TestParseWeeks:
    """Relative dates with week units."""

    def test_one_week_ago(self) -> None:
        result = parse_relative_date("1 week ago", reference=REF_DATE)
        assert result == date(2026, 2, 15)

    def test_singular_week(self) -> None:
        result = parse_relative_date("1 week ago", reference=REF_DATE)
        assert result == date(2026, 2, 15)

    def test_plural_weeks(self) -> None:
        result = parse_relative_date("2 weeks ago", reference=REF_DATE)
        assert result == date(2026, 2, 8)

    def test_four_weeks_ago(self) -> None:
        result = parse_relative_date("4 weeks ago", reference=REF_DATE)
        assert result == date(2026, 1, 25)

    def test_weeks_crossing_year_boundary(self) -> None:
        ref = date(2026, 1, 10)
        result = parse_relative_date("3 weeks ago", reference=ref)
        assert result == date(2025, 12, 20)


# ---------------------------------------------------------------------------
# parse_relative_date — hours and minutes (same day)
# ---------------------------------------------------------------------------


class TestParseSubDay:
    """Hours and minutes resolve to the reference date (no sub-day precision)."""

    def test_hours_ago_returns_reference(self) -> None:
        result = parse_relative_date("5 hours ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_one_hour_ago(self) -> None:
        result = parse_relative_date("1 hour ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_many_hours_ago(self) -> None:
        result = parse_relative_date("23 hours ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_minutes_ago_returns_reference(self) -> None:
        result = parse_relative_date("30 minutes ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_one_minute_ago(self) -> None:
        result = parse_relative_date("1 minute ago", reference=REF_DATE)
        assert result == REF_DATE


# ---------------------------------------------------------------------------
# parse_relative_date — case insensitivity
# ---------------------------------------------------------------------------


class TestParseCaseInsensitive:
    """The parser should be case-insensitive per SearchApi variability."""

    def test_all_caps(self) -> None:
        result = parse_relative_date("3 DAYS AGO", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_title_case(self) -> None:
        result = parse_relative_date("3 Days Ago", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_mixed_case(self) -> None:
        result = parse_relative_date("2 Weeks ago", reference=REF_DATE)
        assert result == date(2026, 2, 8)

    def test_uppercase_hours(self) -> None:
        result = parse_relative_date("1 HOUR AGO", reference=REF_DATE)
        assert result == REF_DATE


# ---------------------------------------------------------------------------
# parse_relative_date — whitespace tolerance
# ---------------------------------------------------------------------------


class TestParseWhitespace:
    """Extra whitespace between tokens should still parse."""

    def test_extra_spaces(self) -> None:
        result = parse_relative_date("3  days  ago", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_leading_whitespace(self) -> None:
        result = parse_relative_date("  3 days ago", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_trailing_whitespace(self) -> None:
        result = parse_relative_date("3 days ago  ", reference=REF_DATE)
        assert result == date(2026, 2, 19)


# ---------------------------------------------------------------------------
# parse_relative_date — fallback / invalid input
# ---------------------------------------------------------------------------


class TestParseFallback:
    """Invalid inputs fall back to reference date."""

    def test_none_returns_reference(self) -> None:
        result = parse_relative_date(None, reference=REF_DATE)
        assert result == REF_DATE

    def test_empty_string_returns_reference(self) -> None:
        result = parse_relative_date("", reference=REF_DATE)
        assert result == REF_DATE

    def test_unparseable_string_returns_reference(self) -> None:
        result = parse_relative_date("yesterday", reference=REF_DATE)
        assert result == REF_DATE

    def test_random_text_returns_reference(self) -> None:
        result = parse_relative_date("not a date at all", reference=REF_DATE)
        assert result == REF_DATE

    def test_numeric_only_returns_reference(self) -> None:
        result = parse_relative_date("12345", reference=REF_DATE)
        assert result == REF_DATE

    def test_iso_date_format_returns_reference(self) -> None:
        """ISO dates are not handled by the relative parser."""
        result = parse_relative_date("2026-02-20", reference=REF_DATE)
        assert result == REF_DATE

    def test_non_string_int_returns_reference(self) -> None:
        result = parse_relative_date(42, reference=REF_DATE)  # type: ignore[arg-type]
        assert result == REF_DATE

    def test_non_string_float_returns_reference(self) -> None:
        result = parse_relative_date(3.14, reference=REF_DATE)  # type: ignore[arg-type]
        assert result == REF_DATE

    def test_unsupported_unit_months(self) -> None:
        """'months ago' is not supported."""
        result = parse_relative_date("2 months ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_unsupported_unit_years(self) -> None:
        """'years ago' is not supported."""
        result = parse_relative_date("1 year ago", reference=REF_DATE)
        assert result == REF_DATE


# ---------------------------------------------------------------------------
# parse_relative_date — default reference (today)
# ---------------------------------------------------------------------------


class TestParseDefaultReference:
    """When no reference is provided, defaults to date.today()."""

    def test_zero_days_no_reference(self) -> None:
        result = parse_relative_date("0 days ago")
        assert result == date.today()

    def test_none_no_reference(self) -> None:
        result = parse_relative_date(None)
        assert result == date.today()


# ---------------------------------------------------------------------------
# parse_relative_date — UTC edge cases
# ---------------------------------------------------------------------------


class TestParseUtcEdgeCases:
    """Date calculations near UTC midnight / timezone boundaries.

    Since parse_relative_date works with date objects (not datetimes),
    UTC edge cases are handled by the caller choosing the correct reference
    date. These tests verify that the function works correctly with dates
    at boundary points.
    """

    def test_reference_at_year_start(self) -> None:
        """Reference date is Jan 1 — subtracting should cross to prior year."""
        ref = date(2026, 1, 1)
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2025, 12, 31)

    def test_reference_at_feb_28_non_leap(self) -> None:
        """Feb 28 in a non-leap year — 1 day forward from Feb 27."""
        ref = date(2025, 2, 28)
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2025, 2, 27)

    def test_reference_at_feb_29_leap_year(self) -> None:
        """Feb 29 in leap year."""
        ref = date(2024, 2, 29)
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2024, 2, 28)

    def test_reference_at_march_1_non_leap(self) -> None:
        """March 1 minus 1 day in non-leap year → Feb 28."""
        ref = date(2025, 3, 1)
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2025, 2, 28)

    def test_reference_at_march_1_leap_year(self) -> None:
        """March 1 minus 1 day in leap year → Feb 29."""
        ref = date(2024, 3, 1)
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2024, 2, 29)

    def test_dst_spring_forward_date(self) -> None:
        """Date around DST spring-forward (no impact since we use date, not datetime)."""
        ref = date(2026, 3, 8)  # US DST spring forward
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2026, 3, 7)

    def test_dst_fall_back_date(self) -> None:
        """Date around DST fall-back (no impact since we use date, not datetime)."""
        ref = date(2025, 11, 2)  # US DST fall back
        result = parse_relative_date("1 day ago", reference=ref)
        assert result == date(2025, 11, 1)


# ---------------------------------------------------------------------------
# parse_relative_date — return type
# ---------------------------------------------------------------------------


class TestParseReturnType:
    """Always returns a date object, not datetime."""

    def test_returns_date_type(self) -> None:
        result = parse_relative_date("3 days ago", reference=REF_DATE)
        assert type(result) is date

    def test_fallback_returns_date_type(self) -> None:
        result = parse_relative_date(None, reference=REF_DATE)
        assert type(result) is date

    def test_sub_day_returns_date_type(self) -> None:
        result = parse_relative_date("5 hours ago", reference=REF_DATE)
        assert type(result) is date


# ---------------------------------------------------------------------------
# Parametrized integration — format(parse()) round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Verify parse → format produces correct MM/DD/YYYY strings."""

    @pytest.mark.parametrize(
        ("relative", "expected"),
        [
            ("0 days ago", "02/22/2026"),
            ("1 day ago", "02/21/2026"),
            ("3 days ago", "02/19/2026"),
            ("7 days ago", "02/15/2026"),
            ("1 week ago", "02/15/2026"),
            ("2 weeks ago", "02/08/2026"),
            ("5 hours ago", "02/22/2026"),
            ("30 minutes ago", "02/22/2026"),
        ],
        ids=[
            "0-days",
            "1-day",
            "3-days",
            "7-days",
            "1-week",
            "2-weeks",
            "5-hours",
            "30-minutes",
        ],
    )
    def test_parse_then_format(self, relative: str, expected: str) -> None:
        parsed = parse_relative_date(relative, reference=REF_DATE)
        assert format_date_mmddyyyy(parsed) == expected
