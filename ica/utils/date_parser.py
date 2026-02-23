"""Date parsing utilities for article dates.

Includes:
- Relative date parser for SearchApi results (e.g., "3 days ago")
- MM/DD/YYYY parser for Google Sheets date strings
- MM/DD/YYYY formatter for display
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_RELATIVE_DATE_RE = re.compile(
    r"(\d+)\s*(day|days|week|weeks|hour|hours|minute|minutes)\s*ago",
    re.IGNORECASE,
)


def parse_relative_date(
    date_string: str | None,
    *,
    reference: date | None = None,
) -> date:
    """Parse a relative date string into a :class:`~datetime.date`.

    Supports patterns like ``"3 days ago"``, ``"1 week ago"``,
    ``"5 hours ago"``.  Hours and minutes resolve to the reference date
    itself (no sub-day precision needed for article publish dates).

    Args:
        date_string: The relative date string from SearchApi, or ``None``.
        reference: The base date to compute from. Defaults to today.

    Returns:
        A :class:`~datetime.date` representing the parsed date.  Falls back
        to *reference* (or today) when *date_string* is ``None``, empty,
        or unparseable.
    """
    ref = reference or date.today()

    if not date_string or not isinstance(date_string, str):
        return ref

    match = _RELATIVE_DATE_RE.search(date_string)
    if not match:
        return ref

    value = int(match.group(1))
    unit = match.group(2).lower()

    if unit in ("day", "days"):
        return ref - timedelta(days=value)
    if unit in ("week", "weeks"):
        return ref - timedelta(weeks=value)
    # Hours/minutes → same day (no sub-day resolution for publish dates)
    return ref


def parse_date_mmddyyyy(date_string: str | None) -> date | None:
    """Parse a ``MM/DD/YYYY`` date string into a :class:`~datetime.date`.

    Used to convert Google Sheets date values back to Python dates for
    database insertion during the summarization data preparation step
    (PRD Section 3.2).

    Args:
        date_string: A date string in ``MM/DD/YYYY`` format, or ``None``.

    Returns:
        A :class:`~datetime.date`, or ``None`` when *date_string* is ``None``,
        empty, whitespace-only, or not in ``MM/DD/YYYY`` format.
    """
    if not date_string or not isinstance(date_string, str):
        return None

    cleaned = date_string.strip()
    if not cleaned:
        return None

    try:
        return datetime.strptime(cleaned, "%m/%d/%Y").date()
    except ValueError:
        return None


def format_date_mmddyyyy(d: date) -> str:
    """Format a date as ``MM/DD/YYYY`` for Google Sheets display.

    Args:
        d: The date to format.

    Returns:
        String in ``MM/DD/YYYY`` format.
    """
    return d.strftime("%m/%d/%Y")
