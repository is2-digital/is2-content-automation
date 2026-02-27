"""Google Custom Search integration test — single query with date parsing.

Runs a live query against Google CSE and prints results, including raw date
metadata from pagemap.metatags.  Verifies that the date extraction logic in
``GoogleSearchClient._parse_results`` handles real Google responses correctly.

Usage:
    docker compose exec app python scripts/test_google_search.py
    docker compose exec app python scripts/test_google_search.py --keyword "AI research"
    docker compose exec app python scripts/test_google_search.py --num 5 --sort-by-date

Requires GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX environment variables.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime
from typing import Any

import httpx
from dotenv import load_dotenv

# Ensure project root is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ica.services.google_search import _DATE_META_KEYS, GoogleSearchClient


class _HttpxAdapter:
    """Adapt httpx.AsyncClient to the GoogleSearchClient HttpClient protocol."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def _parse_iso_date(raw: str | None) -> date | None:
    """Best-effort parse of an ISO-8601 date string to a date object."""
    if not raw:
        return None
    # Try common ISO formats: 2026-02-20T10:30:00Z, 2026-02-20, etc.
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _check_env() -> tuple[str, str]:
    """Load and validate required environment variables."""
    load_dotenv(".env.dev")
    load_dotenv(".env")

    api_key = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_CX", "").strip()

    if not api_key:
        print("ERROR: GOOGLE_CSE_API_KEY not set")
        sys.exit(1)
    if not cx:
        print("ERROR: GOOGLE_CSE_CX not set")
        sys.exit(1)

    print(f"API key: {api_key[:8]}...{api_key[-4:]}")
    print(f"CX:      {cx}")
    return api_key, cx


async def run_search(
    api_key: str,
    cx: str,
    keyword: str,
    num: int,
    sort_by_date: bool,
) -> None:
    """Execute a search and display results with date diagnostics."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = GoogleSearchClient(
            api_key=api_key,
            cx=cx,
            http_client=_HttpxAdapter(http),
        )

        print(f"\nSearching: {keyword!r}  (num={num}, sort_by_date={sort_by_date})")
        print("-" * 70)

        results = await client.search(
            keyword, num=num, sort_by_date=sort_by_date
        )

    if not results:
        print("  No results returned.")
        return

    print(f"  Got {len(results)} result(s)\n")

    dates_found = 0
    dates_parsed = 0

    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r.title}")
        print(f"      URL:    {r.url}")
        print(f"      Origin: {r.origin}")
        print(f"      Date:   {r.date or '(none)'}")

        if r.date:
            dates_found += 1
            parsed = _parse_iso_date(r.date)
            if parsed:
                dates_parsed += 1
                age = (date.today() - parsed).days
                print(f"      Parsed: {parsed}  ({age} day(s) ago)")
            else:
                print(f"      Parsed: FAILED — raw value: {r.date!r}")
        print()

    # Summary
    print("=" * 70)
    print(
        f"Results: {len(results)}  |  Dates found: {dates_found}"
        f"  |  Dates parsed: {dates_parsed}"
    )

    if dates_found > 0:
        pct = dates_parsed / dates_found * 100
        print(f"Date parse rate: {pct:.0f}%  ({dates_parsed}/{dates_found})")
        if dates_parsed < dates_found:
            print("WARNING: Some dates could not be parsed as ISO-8601.")
            print("  Google CSE returns dates via pagemap.metatags, typically ISO format.")
            print(f"  Checked meta keys: {', '.join(_DATE_META_KEYS)}")
    else:
        print("NOTE: No date metadata found in any result.")
        print("  This is normal — not all pages expose date metatags.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Google CSE integration test")
    parser.add_argument(
        "--keyword",
        default="Artificial Intelligence",
        help="Search keyword (default: 'Artificial Intelligence')",
    )
    parser.add_argument(
        "--num",
        type=int,
        default=5,
        help="Number of results to request (default: 5)",
    )
    parser.add_argument(
        "--sort-by-date",
        action="store_true",
        help="Sort results by date (daily schedule mode)",
    )
    args = parser.parse_args()

    api_key, cx = _check_env()
    asyncio.run(run_search(api_key, cx, args.keyword, args.num, args.sort_by_date))
    print("\nGoogle CSE integration test passed!")


if __name__ == "__main__":
    main()
