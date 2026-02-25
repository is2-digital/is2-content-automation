"""Google Sheets service wrapping the Sheets API v4.

Provides :class:`GoogleSheetsService` that satisfies the Sheet protocol
contracts used in the pipeline:

* :class:`~ica.pipeline.article_curation.SheetWriter` — clear and append
* :class:`~ica.pipeline.article_curation.SheetReader` — read rows
* :class:`~ica.pipeline.summarization.SheetReader` — read rows

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
import json
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build, Resource

from ica.logging import get_logger

logger = get_logger(__name__)

# Scopes required for read/write access to Google Sheets.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Default range covering all columns (A through Z) to capture any data.
DEFAULT_RANGE = "A:Z"


def _load_credentials(credentials_path: Path) -> ServiceAccountCredentials:
    """Load Google service account credentials from a JSON key file.

    Args:
        credentials_path: Path to the service account JSON key file.

    Returns:
        Scoped credentials ready for API use.

    Raises:
        FileNotFoundError: If the credentials file does not exist.
        ValueError: If the file is not valid JSON or not a service account key.
    """
    path = Path(credentials_path)
    if not path.exists():
        raise FileNotFoundError(f"Credentials file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid credentials file: {exc}") from exc

    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("Credentials file must be a JSON object with a 'type' field")

    if data["type"] != "service_account":
        raise ValueError(
            f"Unsupported credential type: {data['type']!r}. Only 'service_account' is supported."
        )

    return ServiceAccountCredentials.from_service_account_info(
        data,
        scopes=SCOPES,
    )


def _build_service(credentials: ServiceAccountCredentials) -> Resource:
    """Build a Google Sheets API v4 service resource."""
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


class GoogleSheetsService:
    """Async Google Sheets client satisfying pipeline SheetWriter/SheetReader.

    Args:
        credentials_path: Path to a Google service account JSON key file.
        service: Optional pre-built API service resource (for testing).
    """

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        *,
        service: Resource | None = None,
    ) -> None:
        if service is not None:
            self._service = service
        elif credentials_path is not None:
            creds = _load_credentials(Path(credentials_path))
            self._service = _build_service(creds)
        else:
            raise ValueError("Either credentials_path or service must be provided")

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
