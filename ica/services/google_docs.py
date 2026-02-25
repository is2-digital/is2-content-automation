"""Google Docs service wrapping the Docs API v1.

Provides :class:`GoogleDocsService` with three operations used across
the pipeline:

* :meth:`create_document` — create a new Google Doc, return its ID
* :meth:`insert_content` — insert text into an existing document
* :meth:`get_content` — fetch the full plain-text body of a document

All Google API calls are synchronous under the hood
(``google-api-python-client``), so each call is wrapped in
:func:`asyncio.to_thread` to avoid blocking the event loop.

Usage::

    from ica.services.google_docs import GoogleDocsService

    svc = GoogleDocsService(credentials_path="/path/to/creds.json")
    doc_id = await svc.create_document("Newsletter HTML")
    await svc.insert_content(doc_id, html_content)
    text = await svc.get_content(doc_id)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import Resource, build

from ica.logging import get_logger

logger = get_logger(__name__)

# Scopes required for creating/reading/writing Google Docs.
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


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
    """Build a Google Docs API v1 service resource."""
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


class GoogleDocsService:
    """Async Google Docs client for document creation, content insertion, and retrieval.

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
    # Public API
    # ------------------------------------------------------------------

    async def create_document(self, title: str) -> str:
        """Create a new Google Doc with the given title.

        Args:
            title: The document title.

        Returns:
            The document ID of the newly created document.
        """
        logger.info("Creating document", extra={"title": title})

        result = await asyncio.to_thread(
            self._service.documents().create(body={"title": title}).execute,
        )

        doc_id: str = result["documentId"]
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


def _extract_text(document: dict) -> str:
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
