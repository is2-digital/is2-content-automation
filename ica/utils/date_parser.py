"""Relative date parser for SearchApi results.

SearchApi returns dates as relative strings (e.g., "3 days ago", "1 week ago").
This module converts them to Python date objects.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

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


def format_date_mmddyyyy(d: date) -> str:
    """Format a date as ``MM/DD/YYYY`` for Google Sheets display.

    Args:
        d: The date to format.

    Returns:
        String in ``MM/DD/YYYY`` format.
    """
    return d.strftime("%m/%d/%Y")
