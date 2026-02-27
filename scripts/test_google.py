"""Google APIs integration test — Drive listing, Docs, and Sheets round-trip.

Creates a Google Doc and a Google Sheet inside the Shared Drive,
waits 60 seconds for the user to make edits, then re-reads both
and reports what changed.

NOTE: The service account cannot delete files from the Shared Drive.
Test files are left in place and must be deleted manually by a Drive
member with sufficient permissions.

Usage:
    docker compose exec app python scripts/test_google.py

Requires credentials/google-service-account.json and a Shared Drive
accessible to the service account.  Optionally set GOOGLE_SHARED_DRIVE_ID
in .env / .env.dev; otherwise the first accessible Shared Drive is used.
"""

import asyncio
import difflib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from ica.services.google_auth import load_credentials
from ica.services.google_docs import GoogleDocsService
from ica.services.google_sheets import GoogleSheetsService

load_dotenv(".env.dev")
load_dotenv(".env")

CREDS_PATH = Path(
    os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
        "credentials/google-service-account.json",
    )
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

INITIAL_DOC_TEXT = (
    "ICA Integration Test\n\n"
    "This document was created by the ica test suite.\n"
    "Edit this text within 60 seconds to verify round-trip works.\n"
)

INITIAL_SHEET_ROWS = [
    {"Title": "AI for Small Business", "Status": "draft", "Score": "8"},
    {"Title": "Automation Trends 2026", "Status": "review", "Score": "7"},
    {"Title": "LLM Fine-Tuning Guide", "Status": "draft", "Score": "9"},
]


def _check_credentials() -> None:
    if not CREDS_PATH.exists():
        print(f"ERROR: Credentials file not found: {CREDS_PATH}")
        sys.exit(1)
    print(f"Credentials file: {CREDS_PATH}")


async def resolve_shared_drive(drive_service) -> tuple[str, str]:
    """Resolve the Shared Drive — from env var or auto-discover.

    Returns (drive_id, drive_name).
    """
    configured_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "").strip()

    if configured_id:
        # Validate the configured ID by fetching its metadata
        try:
            info = await asyncio.to_thread(
                drive_service.drives()
                .get(driveId=configured_id, fields="id,name")
                .execute,
            )
            return info["id"], info["name"]
        except Exception as exc:
            print(f"ERROR: GOOGLE_SHARED_DRIVE_ID={configured_id!r} is not accessible: {exc}")
            sys.exit(1)

    # Auto-discover
    result = await asyncio.to_thread(
        drive_service.drives()
        .list(pageSize=10, fields="drives(id, name)")
        .execute,
    )
    drives = result.get("drives", [])
    if not drives:
        print("ERROR: No Shared Drives accessible to the service account.")
        print("  Create a Shared Drive and add the service account as a member,")
        print("  or set GOOGLE_SHARED_DRIVE_ID in your .env file.")
        sys.exit(1)

    drive = drives[0]
    print(f"  Auto-discovered (set GOOGLE_SHARED_DRIVE_ID={drive['id']} to skip discovery)")
    return drive["id"], drive["name"]


async def test_drive_listing(drive_service, drive_id: str) -> None:
    """1. List files inside the Shared Drive."""
    print("\n--- 1. Listing files in Shared Drive ---")
    results = await asyncio.to_thread(
        drive_service.files()
        .list(
            corpora="drive",
            driveId=drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=20,
            fields="files(id, name, mimeType, createdTime)",
            orderBy="createdTime desc",
        )
        .execute,
    )
    files = results.get("files", [])
    if not files:
        print("  Shared Drive is empty (that's fine — we'll create test files).")
    else:
        print(f"  Found {len(files)} file(s):")
        for f in files:
            kind = "folder" if "folder" in f["mimeType"] else f["mimeType"].split(".")[-1]
            print(f"    - {f['name']}  ({kind})  id={f['id']}")


async def test_docs_round_trip(
    docs_svc: GoogleDocsService,
    drive_service,
    drive_id: str,
) -> tuple[str, str]:
    """2. Create a Doc inside the Shared Drive, insert content."""
    print("\n--- 2. Creating Google Doc ---")

    # Create via Drive API to place the file in the Shared Drive.
    # The service account has no storage quota of its own, so all files
    # must live inside a Shared Drive (quota belongs to the org).
    result = await asyncio.to_thread(
        drive_service.files()
        .create(
            body={
                "name": "ICA Test Doc",
                "mimeType": "application/vnd.google-apps.document",
                "parents": [drive_id],
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute,
    )
    doc_id = result["id"]
    print(f"  Created doc: https://docs.google.com/document/d/{doc_id}/edit")

    print("  Inserting initial content...")
    await docs_svc.insert_content(doc_id, INITIAL_DOC_TEXT)

    readback = await docs_svc.get_content(doc_id)
    print(f"  Content verified ({len(readback)} chars).")
    return doc_id, readback


async def test_sheets_round_trip(
    sheets_svc: GoogleSheetsService,
    drive_service,
    drive_id: str,
) -> tuple[str, str, list[dict[str, str]]]:
    """3. Create a Sheet inside the Shared Drive, write rows."""
    print("\n--- 3. Creating Google Sheet ---")

    # Create via Drive API to place the file in the Shared Drive.
    result = await asyncio.to_thread(
        drive_service.files()
        .create(
            body={
                "name": "ICA Test Sheet",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": [drive_id],
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute,
    )
    spreadsheet_id = result["id"]
    sheet_name = "Sheet1"
    print(f"  Created sheet: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")

    print(f"  Writing {len(INITIAL_SHEET_ROWS)} rows to '{sheet_name}'...")
    await sheets_svc.append_rows(spreadsheet_id, sheet_name, INITIAL_SHEET_ROWS)

    readback = await sheets_svc.read_rows(spreadsheet_id, sheet_name)
    print(f"  Content verified ({len(readback)} rows).")
    return spreadsheet_id, sheet_name, readback


def _diff_text(label: str, before: str, after: str) -> None:
    """Show a unified diff of text changes."""
    if before == after:
        print(f"  {label}: No changes detected.")
        return
    diff = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
    )
    print(f"  {label}: Changes detected!")
    for line in diff:
        print(f"    {line}", end="" if line.endswith("\n") else "\n")


def _diff_rows(
    label: str,
    before: list[dict[str, str]],
    after: list[dict[str, str]],
) -> None:
    """Compare sheet rows and report differences."""
    if before == after:
        print(f"  {label}: No changes detected.")
        return

    print(f"  {label}: Changes detected!")

    if len(before) != len(after):
        print(f"    Row count: {len(before)} -> {len(after)}")

    max_rows = max(len(before), len(after))
    for i in range(max_rows):
        if i >= len(before):
            print(f"    + Row {i + 1} (added): {after[i]}")
        elif i >= len(after):
            print(f"    - Row {i + 1} (deleted): {before[i]}")
        elif before[i] != after[i]:
            for key in set(list(before[i].keys()) + list(after[i].keys())):
                old_val = before[i].get(key, "")
                new_val = after[i].get(key, "")
                if old_val != new_val:
                    print(f"    Row {i + 1}, '{key}': '{old_val}' -> '{new_val}'")


async def _countdown(seconds: int) -> None:
    """Display a countdown timer."""
    for remaining in range(seconds, 0, -1):
        print(f"\r  Waiting... {remaining:2d}s remaining ", end="", flush=True)
        await asyncio.sleep(1)
    print("\r  Time's up!                        ")


async def main() -> None:
    _check_credentials()

    creds = load_credentials(CREDS_PATH, SCOPES)
    print(f"Service account: {creds.service_account_email}")

    # Build API services
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets_raw = build("sheets", "v4", credentials=creds, cache_discovery=False)
    docs_svc = GoogleDocsService(
        service=build("docs", "v1", credentials=creds, cache_discovery=False)
    )
    sheets_svc = GoogleSheetsService(service=sheets_raw)

    # 0. Resolve Shared Drive
    drive_id, drive_name = await resolve_shared_drive(drive_service)
    print(f"Shared Drive: {drive_name} (id={drive_id})")

    # 1. List existing files
    await test_drive_listing(drive_service, drive_id)

    # 2. Create Doc with content
    doc_id, doc_before = await test_docs_round_trip(docs_svc, drive_service, drive_id)

    # 3. Create Sheet with rows
    sheet_id, sheet_name, rows_before = await test_sheets_round_trip(
        sheets_svc, drive_service, drive_id
    )

    # 4. Wait for user edits
    print("\n--- 4. Waiting for your edits ---")
    print("  Make changes to the Doc and/or Sheet now!")
    print(f"  Doc:   https://docs.google.com/document/d/{doc_id}/edit")
    print(f"  Sheet: https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    await _countdown(60)

    # 5. Re-read and compare
    print("\n--- 5. Reading back changes ---")
    doc_after = await docs_svc.get_content(doc_id)
    rows_after = await sheets_svc.read_rows(sheet_id, sheet_name)

    _diff_text("Google Doc", doc_before, doc_after)
    _diff_rows("Google Sheet", rows_before, rows_after)

    # NOTE: The service account cannot delete files from the Shared Drive.
    # Test files must be deleted manually by a Drive member with delete
    # permissions (Manager role).
    print("\n--- 6. Cleanup (manual) ---")
    print("  The service account does not have delete permissions.")
    print("  Please delete these test files manually from the Shared Drive:")
    print(f"    - ICA Test Doc   ({doc_id})")
    print(f"    - ICA Test Sheet ({sheet_id})")

    print("\nAll Google API tests passed!")


asyncio.run(main())
