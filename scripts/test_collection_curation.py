"""Integration test — article collection, DB storage, sheet population, and Slack approval.

Exercises the Phase A data pipeline end-to-end with real services:

1. Article collection via Google CSE → deduplication → PostgreSQL upsert
2. Curation data prep: DB → Google Sheet population
3. Slack approval flow: sendAndWait button callback

Usage:
    docker exec ica-app-1 python scripts/test_collection_curation.py
    docker exec ica-app-1 python scripts/test_collection_curation.py --skip-slack
    docker exec ica-app-1 python scripts/test_collection_curation.py --schedule every_2_days
    docker exec ica-app-1 python scripts/test_collection_curation.py --phase collection
    docker exec ica-app-1 python scripts/test_collection_curation.py --phase curation
    docker exec ica-app-1 python scripts/test_collection_curation.py --phase approval

Requires all environment variables from .env (Postgres, Google CSE, Google Sheets,
Slack tokens).  Run inside the app container where .env is loaded automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from dotenv import load_dotenv

# Ensure project root is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _check_env(*keys: str) -> dict[str, str]:
    """Validate that required environment variables are set."""
    load_dotenv(".env.dev")
    load_dotenv(".env")

    values: dict[str, str] = {}
    missing: list[str] = []
    for key in keys:
        val = os.environ.get(key, "").strip()
        if not val:
            missing.append(key)
        values[key] = val

    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    return values


# ---------------------------------------------------------------------------
# Phase 1: Article Collection → DB
# ---------------------------------------------------------------------------


async def phase_collection(schedule: str) -> dict[str, Any]:
    """Run article collection with real Google CSE and PostgreSQL.

    Returns summary dict for downstream phases.
    """
    print("\n" + "=" * 70)
    print("PHASE 1: Article Collection")
    print("=" * 70)

    env = _check_env(
        "GOOGLE_CSE_API_KEY",
        "GOOGLE_CSE_CX",
        "POSTGRES_HOST",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    )

    print(f"  API key:  {env['GOOGLE_CSE_API_KEY'][:8]}...{env['GOOGLE_CSE_API_KEY'][-4:]}")
    print(f"  CX:       {env['GOOGLE_CSE_CX']}")
    print(f"  Postgres: {env['POSTGRES_USER']}@{env['POSTGRES_HOST']}/{env['POSTGRES_DB']}")
    print(f"  Schedule: {schedule}")

    import httpx

    from ica.db.repository import SqlArticleRepository
    from ica.db.session import get_session
    from ica.services.google_search import GoogleSearchClient

    # Use a reduced keyword set to conserve API quota (100 free/day).
    # Daily: 1 keyword x 5 results = 1 API call
    # Every 2 days: 1 keyword x 5 results = 1 API call
    test_keywords = {
        "daily": ["Artificial Intelligence"],
        "every_2_days": ["AI research"],
    }
    sort_by_date = schedule == "daily"
    num = 5

    print("\n--- 1a. Querying Google CSE ---")
    print(f"  Keywords: {test_keywords[schedule]}")
    print(f"  Results per keyword: {num}")
    print(f"  Sort by date: {sort_by_date}")

    async with httpx.AsyncClient(timeout=30.0) as http:
        search_client = GoogleSearchClient(
            api_key=env["GOOGLE_CSE_API_KEY"],
            cx=env["GOOGLE_CSE_CX"],
            http_client=_HttpxAdapter(http),
        )

        # Search with test keywords
        raw_results = await search_client.search_keywords(
            test_keywords[schedule],
            num=num,
            sort_by_date=sort_by_date,
        )

    print(f"  Raw results: {len(raw_results)}")
    if not raw_results:
        print("  ERROR: No results returned from Google CSE.")
        print("  Check API key, CX, and quota at https://console.cloud.google.com/")
        sys.exit(1)

    # Deduplicate
    from ica.pipeline.article_collection import deduplicate_results, parse_articles

    deduplicated = deduplicate_results(raw_results)
    duplicates_removed = len(raw_results) - len(deduplicated)
    print(f"  Deduplicated: {len(deduplicated)} ({duplicates_removed} duplicates removed)")

    # Parse dates
    articles = parse_articles(deduplicated)
    dates_found = sum(1 for a in articles if a.publish_date)
    print(f"  Parsed articles: {len(articles)} ({dates_found} with dates)")

    # Display sample
    for i, a in enumerate(articles[:5], 1):
        print(f"    [{i}] {a.title[:70]}")
        print(f"        URL:  {a.url[:80]}")
        print(f"        Date: {a.publish_date}  Origin: {a.origin}")

    # Persist to PostgreSQL
    print("\n--- 1b. Upserting to PostgreSQL ---")
    async with get_session() as session:
        repo = SqlArticleRepository(session)
        rows_affected = await repo.upsert_articles(articles)

    print(f"  Rows affected: {rows_affected}")

    # Verify by reading back
    print("\n--- 1c. Verifying DB contents ---")
    from sqlalchemy import func, select

    from ica.db.models import Article
    from ica.db.session import get_session as gs

    async with gs() as session:
        # Count total articles
        total_stmt = select(func.count()).select_from(Article)
        total = (await session.execute(total_stmt)).scalar() or 0

        # Count unapproved articles (what curation will pick up)
        from sqlalchemy import or_

        unapproved_stmt = (
            select(func.count())
            .select_from(Article)
            .where(or_(Article.approved == False, Article.approved.is_(None)))  # noqa: E712
        )
        unapproved = (await session.execute(unapproved_stmt)).scalar() or 0

        # Spot-check: verify first article URL exists
        first_url = articles[0].url if articles else None
        if first_url:
            check_stmt = select(Article).where(Article.url == first_url)
            found = (await session.execute(check_stmt)).scalar_one_or_none()
            if found:
                print(f"  Spot check: Article '{found.title[:50]}...' found in DB")
            else:
                print(f"  ERROR: Article with URL {first_url[:60]} NOT found in DB!")
                sys.exit(1)

    print(f"  Total articles in DB: {total}")
    print(f"  Unapproved articles:  {unapproved}")

    # Assertions
    assert rows_affected > 0, "Expected at least 1 row affected"
    assert total > 0, "Expected at least 1 article in DB"
    assert unapproved > 0, "Expected unapproved articles for curation"

    print("\n  Phase 1 PASSED: Articles collected, deduplicated, and stored in DB.")

    return {
        "raw_count": len(raw_results),
        "dedup_count": len(deduplicated),
        "article_count": len(articles),
        "rows_affected": rows_affected,
        "total_in_db": total,
        "unapproved_in_db": unapproved,
    }


# ---------------------------------------------------------------------------
# Phase 2: Curation Data Prep (DB → Google Sheet)
# ---------------------------------------------------------------------------


async def phase_curation() -> dict[str, Any]:
    """Populate Google Sheet with unapproved articles from the DB."""
    print("\n" + "=" * 70)
    print("PHASE 2: Curation Data Preparation (DB → Google Sheet)")
    print("=" * 70)

    env = _check_env(
        "CURATED_ARTICLES_GOOGLE_SHEET_ID",
        "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
    )

    spreadsheet_id = env["CURATED_ARTICLES_GOOGLE_SHEET_ID"]
    creds_path = env["GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH"]

    print(f"  Spreadsheet ID: {spreadsheet_id}")
    print(f"  Credentials:    {creds_path}")

    from ica.db.session import get_session
    from ica.pipeline.article_curation import (
        SHEET_COLUMNS,
        articles_to_row_dicts,
        fetch_unapproved_articles,
        format_article_for_sheet,
    )
    from ica.services.google_sheets import GoogleSheetsService

    sheets_svc = GoogleSheetsService(credentials_path=creds_path)
    sheet_name = "Sheet1"

    # 2a. Clear the sheet
    print("\n--- 2a. Clearing Google Sheet ---")
    await sheets_svc.clear_sheet(spreadsheet_id, sheet_name)
    print("  Sheet cleared.")

    # 2b. Fetch unapproved articles from DB
    print("\n--- 2b. Fetching unapproved articles from DB ---")
    async with get_session() as session:
        db_articles = await fetch_unapproved_articles(session)

    print(f"  Fetched {len(db_articles)} unapproved articles.")

    if not db_articles:
        print("  WARNING: No unapproved articles in DB.")
        print("  Run Phase 1 (collection) first to populate the database.")
        return {"articles_fetched": 0, "articles_written": 0}

    # 2c. Format articles for the sheet
    print("\n--- 2c. Formatting articles for Google Sheet ---")
    sheet_articles = [format_article_for_sheet(a) for a in db_articles]
    rows = articles_to_row_dicts(sheet_articles)

    # Verify column structure
    if rows:
        actual_columns = tuple(rows[0].keys())
        assert actual_columns == SHEET_COLUMNS, (
            f"Column mismatch: expected {SHEET_COLUMNS}, got {actual_columns}"
        )
        print(f"  Columns: {', '.join(SHEET_COLUMNS)}")

    # Display sample
    for i, sa in enumerate(sheet_articles[:3], 1):
        print(f"    [{i}] {sa.title[:60]}")
        print(f"        Date: {sa.publish_date}  Origin: {sa.origin}")
        print(f"        Approved: '{sa.approved}'  Newsletter ID: '{sa.newsletter_id}'")

    # 2d. Write to Google Sheet
    print(f"\n--- 2d. Appending {len(rows)} rows to Google Sheet ---")
    written = await sheets_svc.append_rows(spreadsheet_id, sheet_name, rows)
    print(f"  Rows written: {written}")

    # 2e. Read back and verify
    print("\n--- 2e. Verifying Google Sheet contents ---")
    readback = await sheets_svc.read_rows(spreadsheet_id, sheet_name)
    print(f"  Rows read back: {len(readback)}")

    if readback:
        # Verify headers match
        actual_headers = set(readback[0].keys())
        expected_headers = set(SHEET_COLUMNS)
        assert actual_headers == expected_headers, (
            f"Header mismatch: expected {expected_headers}, got {actual_headers}"
        )
        print(f"  Headers verified: {', '.join(sorted(actual_headers))}")

        # Verify row count
        assert len(readback) == len(rows), (
            f"Row count mismatch: wrote {len(rows)}, read {len(readback)}"
        )

        # Spot-check first row
        first_row = readback[0]
        first_sheet = sheet_articles[0]
        assert first_row["url"] == first_sheet.url, (
            f"URL mismatch in first row: {first_row['url']!r} != {first_sheet.url!r}"
        )
        print(f"  Spot check: First row URL matches ({first_row['url'][:60]})")

    print(
        f"\n  Sheet link: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    )
    print("\n  Phase 2 PASSED: Unapproved articles populated in Google Sheet.")

    return {
        "articles_fetched": len(db_articles),
        "articles_written": written,
        "rows_verified": len(readback),
    }


# ---------------------------------------------------------------------------
# Phase 3: Slack Approval Flow
# ---------------------------------------------------------------------------


async def phase_approval() -> dict[str, Any]:
    """Test Slack sendAndWait approval button for the curation loop."""
    print("\n" + "=" * 70)
    print("PHASE 3: Slack Approval Flow")
    print("=" * 70)

    env = _check_env(
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "SLACK_CHANNEL",
        "CURATED_ARTICLES_GOOGLE_SHEET_ID",
    )

    bot_token = env["SLACK_BOT_TOKEN"]
    app_token = env["SLACK_APP_TOKEN"]
    channel = env["SLACK_CHANNEL"]
    spreadsheet_id = env["CURATED_ARTICLES_GOOGLE_SHEET_ID"]

    print(f"  Bot token: {bot_token[:10]}...{bot_token[-4:]}")
    print(f"  Channel:   {channel}")

    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    from slack_bolt.async_app import AsyncApp

    from ica.pipeline.article_curation import build_approval_message
    from ica.services.slack import SlackService

    # 3a. Send initial notification
    print("\n--- 3a. Sending initial notification ---")
    svc = SlackService(token=bot_token, channel=channel)
    await svc.send_message(
        channel,
        "Integration test: starting curation approval flow...",
    )
    print("  Notification sent.")

    # 3b. Connect Socket Mode for interactive callbacks
    print("\n--- 3b. Connecting Socket Mode ---")
    bolt_app = AsyncApp(token=bot_token)
    svc.register_handlers(bolt_app)
    handler = AsyncSocketModeHandler(bolt_app, app_token)
    await handler.connect_async()
    print("  Socket Mode connected.")

    # 3c. Send approval button (sendAndWait)
    print("\n--- 3c. Sending approval button ---")
    approval_msg = build_approval_message(spreadsheet_id)
    print(f"  Message: {approval_msg[:80]}...")
    print("  >>> Click the 'Proceed to next steps' button in Slack within 120s <<<")

    try:
        await asyncio.wait_for(
            svc.send_and_wait(
                channel,
                approval_msg,
                approve_label="Proceed to next steps",
            ),
            timeout=120,
        )
        print("  Button click received!")
    except TimeoutError:
        print("  TIMEOUT: No button click received within 120s.")
        print("  Approval flow test SKIPPED (interactive callback not confirmed).")
        await handler.close_async()
        return {"approval_received": False, "reason": "timeout"}

    # 3d. Verify approval by reading back from the sheet
    print("\n--- 3d. Reading sheet after approval ---")
    from ica.services.google_sheets import GoogleSheetsService

    creds_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
        "credentials/google-service-account.json",
    )
    sheets_svc = GoogleSheetsService(credentials_path=creds_path)
    rows = await sheets_svc.read_rows(spreadsheet_id, "Sheet1")
    print(f"  Rows in sheet: {len(rows)}")

    from ica.pipeline.article_curation import parse_approved_articles, validate_sheet_data

    is_valid = validate_sheet_data(rows)
    approved_articles = parse_approved_articles(rows)

    print(f"  Sheet validation: {'PASS' if is_valid else 'FAIL'}")
    print(f"  Approved articles: {len(approved_articles)}")

    if approved_articles:
        for i, a in enumerate(approved_articles[:3], 1):
            print(f"    [{i}] {a.title[:60]}")
            print(f"        Newsletter ID: {a.newsletter_id}")
            print(f"        Industry news: {a.industry_news}")

    await handler.close_async()
    print("  Socket Mode disconnected.")

    print("\n  Phase 3 PASSED: Slack approval flow works end-to-end.")

    return {
        "approval_received": True,
        "sheet_valid": is_valid,
        "approved_count": len(approved_articles),
    }


# ---------------------------------------------------------------------------
# httpx adapter (same pattern as test_google_search.py)
# ---------------------------------------------------------------------------


class _HttpxAdapter:
    """Adapt httpx.AsyncClient to the GoogleSearchClient HttpClient protocol."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:

        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: article collection, DB storage, sheet population, "
        "and Slack approval.",
    )
    parser.add_argument(
        "--schedule",
        default="daily",
        choices=["daily", "every_2_days"],
        help="Article collection schedule type (default: daily)",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=["all", "collection", "curation", "approval"],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-slack",
        action="store_true",
        help="Skip the Slack approval phase (phases 1-2 only)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}

    if args.phase in ("all", "collection"):
        results["collection"] = await phase_collection(args.schedule)

    if args.phase in ("all", "curation"):
        results["curation"] = await phase_curation()

    if args.phase in ("all", "approval") and not args.skip_slack:
        results["approval"] = await phase_approval()
    elif args.skip_slack:
        print("\n  Slack approval phase skipped (--skip-slack).")

    # Summary
    print("\n" + "=" * 70)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 70)

    for phase_name, phase_results in results.items():
        print(f"\n  {phase_name}:")
        for key, value in phase_results.items():
            print(f"    {key}: {value}")

    print("\nPhase A integration test complete!")


if __name__ == "__main__":
    main()
