"""Google Docs service wrapping the Docs API v1 and Drive API v3.

Provides :class:`GoogleDocsService` with three operations used across
the pipeline:

* :meth:`create_document` — create a new Google Doc, return its ID
* :meth:`insert_content` — insert text into an existing document
* :meth:`get_content` — fetch the full plain-text body of a document

When a ``drive_id`` (Shared Drive) is configured, documents are created
via the Drive API inside the Shared Drive.  The service account has no
Drive storage quota of its own, so creating documents via the Docs API
directly will fail with a 403 unless a Shared Drive target is provided.

All Google API calls are synchronous under the hood
(``google-api-python-client``), so each call is wrapped in
:func:`asyncio.to_thread` to avoid blocking the event loop.

Usage::

    from ica.services.google_docs import GoogleDocsService

    svc = GoogleDocsService(
        credentials_path="/path/to/creds.json",
        drive_id="0AI2VlvBSftPwUk9PVA",
    )
    doc_id = await svc.create_document("Newsletter HTML")
    await svc.insert_content(doc_id, html_content)
    text = await svc.get_content(doc_id)
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

# Scopes required for creating/reading/writing Google Docs.
# The ``drive`` scope is needed to create documents inside Shared Drives
# via the Drive API (service accounts have no storage quota of their own).
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def _build_service(credentials: ServiceAccountCredentials) -> Resource:
    """Build a Google Docs API v1 service resource."""
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


def _build_drive_service(credentials: ServiceAccountCredentials) -> Resource:
    """Build a Google Drive API v3 service resource."""
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


class GoogleDocsService:
    """Async Google Docs client for document creation, content insertion, and retrieval.

    Args:
        credentials_path: Path to a Google service account JSON key file.
        drive_id: Shared Drive ID where documents are created.  Required
            for service accounts that have no Drive storage quota.
        service: Optional pre-built Docs API service resource (for testing).
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
    # Public API
    # ------------------------------------------------------------------

    async def create_document(self, title: str) -> str:
        """Create a new Google Doc with the given title.

        When a Shared Drive ID is configured, the document is created via
        the Drive API inside the Shared Drive (service accounts have no
        personal Drive storage quota).  Otherwise falls back to the Docs
        API directly.

        Args:
            title: The document title.

        Returns:
            The document ID of the newly created document.
        """
        logger.info("Creating document", extra={"title": title})

        if self._drive_id and self._drive_service:
            result = await asyncio.to_thread(
                self._drive_service.files()
                .create(
                    body={
                        "name": title,
                        "mimeType": "application/vnd.google-apps.document",
                        "parents": [self._drive_id],
                    },
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute,
            )
            doc_id: str = result["id"]
        else:
            result = await asyncio.to_thread(
                self._service.documents().create(body={"title": title}).execute,
            )
            doc_id = result["documentId"]

        logger.info(
            "Document created",
            extra={"document_id": doc_id, "title": title},
        )
        return doc_id

    async def insert_content(self, document_id: str, text: str) -> None:
        """Insert text content into a Google Doc.

        Inserts the text at position 1 (the beginning of the document body)
        using the ``batchUpdate`` API with an ``insertText`` request.

        Args:
            document_id: The ID of the target document.
            text: The text content to insert.
        """
        if not text:
            return

        logger.info(
            "Inserting content",
            extra={
                "document_id": document_id,
                "content_length": len(text),
            },
        )

        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": text,
                }
            }
        ]

        await asyncio.to_thread(
            self._service.documents()
            .batchUpdate(
                documentId=document_id,
                body={"requests": requests},
            )
            .execute,
        )

    async def get_content(self, document_id: str) -> str:
        """Fetch the full plain-text body of a Google Doc.

        Traverses the document's structural elements and concatenates all
        text runs into a single string.

        Args:
            document_id: The ID of the document to read.

        Returns:
            The full text content of the document.
        """
        logger.info(
            "Fetching document content",
            extra={"document_id": document_id},
        )

        result = await asyncio.to_thread(
            self._service.documents().get(documentId=document_id).execute,
        )

        return _extract_text(result)


def _extract_text(document: dict[str, Any]) -> str:
    """Extract plain text from a Google Docs API document response.

    Traverses ``body.content[].paragraph.elements[].textRun.content``
    to build the full text.
    """
    parts: list[str] = []
    body = document.get("body", {})
    for element in body.get("content", []):
        paragraph = element.get("paragraph")
        if paragraph is None:
            continue
        for text_element in paragraph.get("elements", []):
            text_run = text_element.get("textRun")
            if text_run is not None:
                parts.append(text_run.get("content", ""))
    return "".join(parts)
