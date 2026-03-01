"""Google Sheets service wrapping the Sheets API v4 and Drive API v3.

Provides :class:`GoogleSheetsService` that satisfies the Sheet protocol
contracts used in the pipeline:

* :class:`~ica.pipeline.article_curation.SheetWriter` — clear and append
* :class:`~ica.pipeline.article_curation.SheetReader` — read rows
* :class:`~ica.pipeline.summarization.SheetReader` — read rows

Also provides spreadsheet lifecycle management:

* :meth:`create_spreadsheet` — create a new spreadsheet in a Shared Drive
* :meth:`ensure_spreadsheet` — return existing or create new spreadsheet
* :meth:`ensure_tab` — create a sheet tab if it doesn't exist

All Google API calls are synchronous under the hood
(``google-api-python-client``), so each call is wrapped in
:func:`asyncio.to_thread` to avoid blocking the event loop.

Usage::

    from ica.services.google_sheets import GoogleSheetsService

    svc = GoogleSheetsService(credentials_path="/path/to/creds.json")
    rows = await svc.read_rows(spreadsheet_id, "Sheet1")
    await svc.clear_sheet(spreadsheet_id, "Sheet1")
    count = await svc.append_rows(spreadsheet_id, "Sheet1", rows)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from ica.logging import get_logger
from ica.services.google_auth import load_credentials

logger = get_logger(__name__)

# Scopes required for read/write access to Google Sheets and Drive
# (creating spreadsheets in Shared Drives requires the Drive scope).
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Default range covering all columns (A through Z) to capture any data.
DEFAULT_RANGE = "A:Z"


def _build_service(credentials: ServiceAccountCredentials) -> Resource:
    """Build a Google Sheets API v4 service resource."""
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _build_drive_service(credentials: ServiceAccountCredentials) -> Resource:
    """Build a Google Drive API v3 service resource."""
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


class GoogleSheetsService:
    """Async Google Sheets client satisfying pipeline SheetWriter/SheetReader.

    Args:
        credentials_path: Path to a Google service account JSON key file.
        drive_id: Shared Drive ID where new spreadsheets are created.
            Required for service accounts that have no Drive storage quota.
        service: Optional pre-built API service resource (for testing).
        drive_service: Optional pre-built Drive API service resource (for testing).
    """

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        *,
        drive_id: str = "",
        service: Resource | None = None,
        drive_service: Resource | None = None,
    ) -> None:
        if service is not None:
            self._service = service
            self._drive_service = drive_service
        elif credentials_path is not None:
            creds = load_credentials(Path(credentials_path), SCOPES)
            self._service = _build_service(creds)
            self._drive_service = _build_drive_service(creds)
        else:
            raise ValueError("Either credentials_path or service must be provided")
        self._drive_id = drive_id

    # ------------------------------------------------------------------
    # Public API — spreadsheet lifecycle
    # ------------------------------------------------------------------

    async def create_spreadsheet(self, title: str) -> str:
        """Create a new Google Sheets spreadsheet and return its ID.

        When a Shared Drive ID is configured, the spreadsheet is created
        via the Drive API inside the Shared Drive (service accounts have
        no personal Drive storage quota).  Otherwise falls back to the
        Sheets API directly.

        Args:
            title: The spreadsheet title.

        Returns:
            The spreadsheet ID of the newly created spreadsheet.
        """
        logger.info("Creating spreadsheet", extra={"title": title})

        if self._drive_id and self._drive_service:
            result = await asyncio.to_thread(
                self._drive_service.files()
                .create(
                    body={
                        "name": title,
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                        "parents": [self._drive_id],
                    },
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute,
            )
            spreadsheet_id: str = result["id"]
        else:
            result = await asyncio.to_thread(
                self._service.spreadsheets()
                .create(
                    body={"properties": {"title": title}},
                    fields="spreadsheetId",
                )
                .execute,
            )
            spreadsheet_id = result["spreadsheetId"]

        logger.info(
            "Spreadsheet created",
            extra={"spreadsheet_id": spreadsheet_id, "title": title},
        )
        return spreadsheet_id

    async def ensure_spreadsheet(self, spreadsheet_id: str, title: str) -> str:
        """Return the existing spreadsheet ID, or create a new spreadsheet.

        Validates that the given ``spreadsheet_id`` points to an accessible
        spreadsheet.  If the ID is empty or the spreadsheet cannot be found,
        a new spreadsheet is created with the given ``title``.

        Args:
            spreadsheet_id: The spreadsheet ID to check (may be empty).
            title: Title for the new spreadsheet if one must be created.

        Returns:
            A valid spreadsheet ID (existing or newly created).
        """
        if spreadsheet_id:
            try:
                await asyncio.to_thread(
                    self._service.spreadsheets()
                    .get(
                        spreadsheetId=spreadsheet_id,
                        fields="spreadsheetId",
                    )
                    .execute,
                )
                return spreadsheet_id
            except Exception:
                logger.warning(
                    "Spreadsheet %s not accessible, creating a new one",
                    spreadsheet_id,
                )

        new_id = await self.create_spreadsheet(title)
        logger.warning(
            "Set CURATED_ARTICLES_GOOGLE_SHEET_ID=%s in your .env file",
            new_id,
        )
        return new_id

    async def ensure_tab(self, spreadsheet_id: str, tab_name: str) -> None:
        """Create a sheet tab if it doesn't already exist.

        Fetches the spreadsheet metadata to check for existing tabs,
        then creates the tab via ``batchUpdate`` if missing.

        Args:
            spreadsheet_id: The spreadsheet to check.
            tab_name: The tab/sheet name to ensure exists.
        """
        result = await asyncio.to_thread(
            self._service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets.properties.title",
            )
            .execute,
        )

        existing_tabs = [
            sheet["properties"]["title"] for sheet in result.get("sheets", [])
        ]

        if tab_name in existing_tabs:
            return

        logger.info(
            "Creating tab",
            extra={"spreadsheet_id": spreadsheet_id, "tab_name": tab_name},
        )

        await asyncio.to_thread(
            self._service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {"addSheet": {"properties": {"title": tab_name}}}
                    ]
                },
            )
            .execute,
        )

    # ------------------------------------------------------------------
    # Public API — matches pipeline protocol contracts
    # ------------------------------------------------------------------

    async def clear_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> None:
        """Clear all values from the specified sheet.

        Matches :class:`~ica.pipeline.article_curation.SheetWriter.clear_sheet`.

        Uses the Sheets API ``values.clear`` method to remove all cell values
        while preserving the sheet structure and formatting.
        """
        range_notation = f"{sheet_name}!{DEFAULT_RANGE}"
        logger.info(
            "Clearing sheet",
            extra={"spreadsheet_id": spreadsheet_id, "range": range_notation},
        )

        await asyncio.to_thread(
            self._service.spreadsheets()
            .values()
            .clear(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                body={},
            )
            .execute,
        )

    async def append_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Append rows to the specified sheet.

        Matches :class:`~ica.pipeline.article_curation.SheetWriter.append_rows`.

        The first call writes headers (dict keys from the first row), then all
        data rows.  Returns the number of rows appended (excluding header).

        Args:
            spreadsheet_id: Google Sheets document ID.
            sheet_name: Sheet/tab name within the spreadsheet.
            rows: List of dicts where keys are column headers.

        Returns:
            Number of data rows appended.
        """
        if not rows:
            return 0

        headers = list(rows[0].keys())
        values: list[list[str]] = [headers]
        for row in rows:
            values.append([str(row.get(h, "")) for h in headers])

        range_notation = f"{sheet_name}!{DEFAULT_RANGE}"
        logger.info(
            "Appending rows",
            extra={
                "spreadsheet_id": spreadsheet_id,
                "range": range_notation,
                "row_count": len(rows),
            },
        )

        await asyncio.to_thread(
            self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption="RAW",
                body={"values": values},
            )
            .execute,
        )

        return len(rows)

    async def read_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> list[dict[str, str]]:
        """Read all rows from the specified sheet.

        Matches :class:`~ica.pipeline.article_curation.SheetReader.read_rows`
        and :class:`~ica.pipeline.summarization.SheetReader.read_rows`.

        The first row is treated as headers; subsequent rows become dicts
        keyed by those headers.  Missing trailing cells are filled with
        empty strings.

        Returns:
            List of dicts, one per data row.  Empty list if the sheet has
            no data or only a header row.
        """
        range_notation = f"{sheet_name}!{DEFAULT_RANGE}"
        logger.info(
            "Reading rows",
            extra={"spreadsheet_id": spreadsheet_id, "range": range_notation},
        )

        result = await asyncio.to_thread(
            self._service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
            )
            .execute,
        )

        all_values: list[list[str]] = result.get("values", [])
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        output: list[dict[str, str]] = []
        for data_row in all_values[1:]:
            row_dict: dict[str, str] = {}
            for i, header in enumerate(headers):
                row_dict[header] = data_row[i] if i < len(data_row) else ""
            output.append(row_dict)

        return output
