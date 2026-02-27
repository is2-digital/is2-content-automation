"""Tests for :mod:`ica.services.google_docs`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ica.services.google_docs import (
    SCOPES,
    GoogleDocsService,
    _extract_text,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_service_account_json(tmp_path: Path) -> Path:
    """Write a minimal service account JSON file and return its path."""
    creds = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "key-id",
        "private_key": "fake-key-for-testing",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    path = tmp_path / "creds.json"
    path.write_text(json.dumps(creds), encoding="utf-8")
    return path


@pytest.fixture
def mock_service() -> MagicMock:
    """Return a mock Google Docs API service."""
    return MagicMock(spec=["documents"])


@pytest.fixture
def svc(mock_service: MagicMock) -> GoogleDocsService:
    """Return a GoogleDocsService with a mocked API service."""
    return GoogleDocsService(service=mock_service)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_documents_mock(
    mock_service: MagicMock,
    method: str,
    return_value: dict | None = None,
) -> MagicMock:
    """Set up a mock for documents().<method>().execute()."""
    execute_mock = MagicMock(return_value=return_value or {})
    method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
    docs_mock = MagicMock(**{method: method_mock})
    mock_service.documents.return_value = docs_mock
    return method_mock


def _make_doc_response(text_parts: list[str]) -> dict:
    """Build a minimal Google Docs API response with the given text parts.

    Each text part becomes a textRun in a separate paragraph element.
    """
    content = []
    for text in text_parts:
        content.append({"paragraph": {"elements": [{"textRun": {"content": text}}]}})
    return {"body": {"content": content}}


# ===========================================================================
# GoogleDocsService.__init__
# ===========================================================================


class TestInit:
    """Tests for GoogleDocsService constructor."""

    def test_with_service(self, mock_service: MagicMock) -> None:
        svc = GoogleDocsService(service=mock_service)
        assert svc._service is mock_service

    def test_with_credentials_path(self, tmp_path: Path) -> None:
        path = _make_service_account_json(tmp_path)
        with (
            patch(
                "ica.services.google_docs.load_credentials",
                return_value=MagicMock(),
            ) as load_mock,
            patch(
                "ica.services.google_docs._build_service",
                return_value=MagicMock(),
            ) as build_mock,
            patch(
                "ica.services.google_docs._build_drive_service",
                return_value=MagicMock(),
            ) as drive_build_mock,
        ):
            svc = GoogleDocsService(credentials_path=path)
            load_mock.assert_called_once_with(path, SCOPES)
            build_mock.assert_called_once()
            drive_build_mock.assert_called_once()
            assert svc._service is build_mock.return_value
            assert svc._drive_service is drive_build_mock.return_value

    def test_no_args_raises(self) -> None:
        with pytest.raises(ValueError, match="credentials_path or service"):
            GoogleDocsService()

    def test_service_takes_precedence(self, mock_service: MagicMock) -> None:
        """When both are provided, service is used (credentials_path ignored)."""
        svc = GoogleDocsService(credentials_path="/fake/path", service=mock_service)
        assert svc._service is mock_service

    def test_credentials_path_string(self, tmp_path: Path) -> None:
        """Accepts string paths in addition to Path objects."""
        path = _make_service_account_json(tmp_path)
        with (
            patch(
                "ica.services.google_docs.load_credentials",
                return_value=MagicMock(),
            ),
            patch(
                "ica.services.google_docs._build_service",
                return_value=MagicMock(),
            ),
            patch(
                "ica.services.google_docs._build_drive_service",
                return_value=MagicMock(),
            ),
        ):
            svc = GoogleDocsService(credentials_path=str(path))
            assert svc._service is not None

    def test_drive_id_stored(self, mock_service: MagicMock) -> None:
        svc = GoogleDocsService(service=mock_service, drive_id="drive-abc")
        assert svc._drive_id == "drive-abc"

    def test_drive_id_defaults_empty(self, mock_service: MagicMock) -> None:
        svc = GoogleDocsService(service=mock_service)
        assert svc._drive_id == ""

    def test_drive_service_injection(self, mock_service: MagicMock) -> None:
        drive_mock = MagicMock()
        svc = GoogleDocsService(
            service=mock_service, drive_service=drive_mock, drive_id="d1"
        )
        assert svc._drive_service is drive_mock


# ===========================================================================
# create_document
# ===========================================================================


class TestCreateDocument:
    """Tests for GoogleDocsService.create_document()."""

    @pytest.mark.asyncio
    async def test_creates_and_returns_id(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        create_mock = _setup_documents_mock(
            mock_service,
            "create",
            return_value={"documentId": "doc-abc-123"},
        )
        doc_id = await svc.create_document("My Newsletter")

        assert doc_id == "doc-abc-123"
        create_mock.assert_called_once_with(body={"title": "My Newsletter"})

    @pytest.mark.asyncio
    async def test_title_forwarded(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        create_mock = _setup_documents_mock(
            mock_service,
            "create",
            return_value={"documentId": "id"},
        )
        await svc.create_document("Newsletter HTML")
        create_mock.assert_called_once_with(body={"title": "Newsletter HTML"})

    @pytest.mark.asyncio
    async def test_empty_title(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        create_mock = _setup_documents_mock(
            mock_service,
            "create",
            return_value={"documentId": "id"},
        )
        doc_id = await svc.create_document("")
        assert doc_id == "id"
        create_mock.assert_called_once_with(body={"title": ""})

    @pytest.mark.asyncio
    async def test_special_characters_in_title(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_documents_mock(
            mock_service,
            "create",
            return_value={"documentId": "id"},
        )
        await svc.create_document("Newsletter — Feb 2026 (Draft)")

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=Exception("API quota exceeded"))
        method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        mock_service.documents.return_value = MagicMock(create=method_mock)

        with pytest.raises(Exception, match="API quota exceeded"):
            await svc.create_document("test")

    @pytest.mark.asyncio
    async def test_return_type_is_string(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_documents_mock(
            mock_service,
            "create",
            return_value={"documentId": "doc-xyz"},
        )
        result = await svc.create_document("test")
        assert isinstance(result, str)


# ===========================================================================
# create_document — Drive API path (with drive_id)
# ===========================================================================


def _make_drive_service_mock() -> MagicMock:
    """Return a mock Google Drive API service with files().create() chain."""
    return MagicMock(spec=["files"])


def _setup_drive_create_mock(
    drive_mock: MagicMock,
    return_value: dict | None = None,
) -> MagicMock:
    """Set up a mock for files().create().execute()."""
    execute_mock = MagicMock(return_value=return_value or {})
    create_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
    drive_mock.files.return_value = MagicMock(create=create_mock)
    return create_mock


class TestCreateDocumentDrivePath:
    """Tests for create_document when drive_id is configured."""

    @pytest.fixture
    def drive_mock(self) -> MagicMock:
        return _make_drive_service_mock()

    @pytest.fixture
    def drive_svc(
        self, mock_service: MagicMock, drive_mock: MagicMock
    ) -> GoogleDocsService:
        return GoogleDocsService(
            service=mock_service,
            drive_service=drive_mock,
            drive_id="shared-drive-123",
        )

    @pytest.mark.asyncio
    async def test_creates_via_drive_api(
        self,
        drive_svc: GoogleDocsService,
        drive_mock: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        create_mock = _setup_drive_create_mock(
            drive_mock, return_value={"id": "doc-from-drive"}
        )
        doc_id = await drive_svc.create_document("My Doc")

        assert doc_id == "doc-from-drive"
        create_mock.assert_called_once_with(
            body={
                "name": "My Doc",
                "mimeType": "application/vnd.google-apps.document",
                "parents": ["shared-drive-123"],
            },
            fields="id",
            supportsAllDrives=True,
        )
        # Docs API should NOT be called
        mock_service.documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_use_docs_api(
        self,
        drive_svc: GoogleDocsService,
        drive_mock: MagicMock,
        mock_service: MagicMock,
    ) -> None:
        _setup_drive_create_mock(drive_mock, return_value={"id": "doc-xyz"})
        await drive_svc.create_document("test")
        mock_service.documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_title_forwarded(
        self,
        drive_svc: GoogleDocsService,
        drive_mock: MagicMock,
    ) -> None:
        create_mock = _setup_drive_create_mock(
            drive_mock, return_value={"id": "id"}
        )
        await drive_svc.create_document("Newsletter HTML")
        body = create_mock.call_args[1]["body"]
        assert body["name"] == "Newsletter HTML"

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        drive_svc: GoogleDocsService,
        drive_mock: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=Exception("Drive quota exceeded"))
        create_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        drive_mock.files.return_value = MagicMock(create=create_mock)

        with pytest.raises(Exception, match="Drive quota exceeded"):
            await drive_svc.create_document("test")

    @pytest.mark.asyncio
    async def test_falls_back_without_drive_id(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Without drive_id, uses the Docs API path."""
        svc = GoogleDocsService(service=mock_service)
        _setup_documents_mock(
            mock_service,
            "create",
            return_value={"documentId": "doc-fallback"},
        )
        doc_id = await svc.create_document("test")
        assert doc_id == "doc-fallback"


# ===========================================================================
# insert_content
# ===========================================================================


class TestInsertContent:
    """Tests for GoogleDocsService.insert_content()."""

    @pytest.mark.asyncio
    async def test_inserts_text(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        await svc.insert_content("doc-123", "Hello, world!")

        batch_mock.assert_called_once_with(
            documentId="doc-123",
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": "Hello, world!",
                        }
                    }
                ]
            },
        )

    @pytest.mark.asyncio
    async def test_empty_text_skips_api_call(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        await svc.insert_content("doc-123", "")
        mock_service.documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_document_id_forwarded(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        await svc.insert_content("my-special-doc-id", "content")

        call_kwargs = batch_mock.call_args[1]
        assert call_kwargs["documentId"] == "my-special-doc-id"

    @pytest.mark.asyncio
    async def test_html_content(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        html = "<html><body><h1>Newsletter</h1></body></html>"
        await svc.insert_content("doc-123", html)

        body = batch_mock.call_args[1]["body"]
        assert body["requests"][0]["insertText"]["text"] == html

    @pytest.mark.asyncio
    async def test_markdown_content(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        md = "# Title\n\nSome **bold** and *italic* text.\n\n- Bullet 1\n- Bullet 2"
        await svc.insert_content("doc-123", md)

        body = batch_mock.call_args[1]["body"]
        assert body["requests"][0]["insertText"]["text"] == md

    @pytest.mark.asyncio
    async def test_multiline_content(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        text = "Line 1\nLine 2\nLine 3"
        await svc.insert_content("doc-123", text)

        body = batch_mock.call_args[1]["body"]
        assert body["requests"][0]["insertText"]["text"] == text

    @pytest.mark.asyncio
    async def test_unicode_content(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        text = "AI \u2192 Business \u2022 \u00e9\u00e0\u00fc\u00f1"
        await svc.insert_content("doc-123", text)

        body = batch_mock.call_args[1]["body"]
        assert body["requests"][0]["insertText"]["text"] == text

    @pytest.mark.asyncio
    async def test_insert_at_index_one(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        """Content is inserted at index 1 (beginning of document body)."""
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        await svc.insert_content("doc-123", "text")

        body = batch_mock.call_args[1]["body"]
        location = body["requests"][0]["insertText"]["location"]
        assert location == {"index": 1}

    @pytest.mark.asyncio
    async def test_returns_none(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_documents_mock(mock_service, "batchUpdate")
        result = await svc.insert_content("doc-123", "text")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=RuntimeError("permission denied"))
        method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        mock_service.documents.return_value = MagicMock(batchUpdate=method_mock)

        with pytest.raises(RuntimeError, match="permission denied"):
            await svc.insert_content("doc-123", "content")

    @pytest.mark.asyncio
    async def test_large_content(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        """Handles large content without issues."""
        batch_mock = _setup_documents_mock(mock_service, "batchUpdate")
        large_text = "x" * 100_000
        await svc.insert_content("doc-123", large_text)

        body = batch_mock.call_args[1]["body"]
        assert len(body["requests"][0]["insertText"]["text"]) == 100_000


# ===========================================================================
# get_content
# ===========================================================================


class TestGetContent:
    """Tests for GoogleDocsService.get_content()."""

    @pytest.mark.asyncio
    async def test_single_paragraph(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        doc_response = _make_doc_response(["Hello, world!\n"])
        _setup_documents_mock(mock_service, "get", return_value=doc_response)

        result = await svc.get_content("doc-123")
        assert result == "Hello, world!\n"

    @pytest.mark.asyncio
    async def test_multiple_paragraphs(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        doc_response = _make_doc_response(["First paragraph\n", "Second paragraph\n"])
        _setup_documents_mock(mock_service, "get", return_value=doc_response)

        result = await svc.get_content("doc-123")
        assert result == "First paragraph\nSecond paragraph\n"

    @pytest.mark.asyncio
    async def test_empty_document(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_documents_mock(
            mock_service,
            "get",
            return_value={"body": {"content": []}},
        )
        result = await svc.get_content("doc-123")
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_body(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_documents_mock(mock_service, "get", return_value={})
        result = await svc.get_content("doc-123")
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_content_key(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_documents_mock(
            mock_service,
            "get",
            return_value={"body": {}},
        )
        result = await svc.get_content("doc-123")
        assert result == ""

    @pytest.mark.asyncio
    async def test_document_id_forwarded(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        get_mock = _setup_documents_mock(
            mock_service,
            "get",
            return_value={"body": {"content": []}},
        )
        await svc.get_content("my-doc-id-abc")
        get_mock.assert_called_once_with(documentId="my-doc-id-abc")

    @pytest.mark.asyncio
    async def test_non_paragraph_elements_skipped(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        """Elements without a 'paragraph' key are skipped."""
        doc = {
            "body": {
                "content": [
                    {"sectionBreak": {}},
                    {"paragraph": {"elements": [{"textRun": {"content": "text\n"}}]}},
                    {"table": {"rows": []}},
                ]
            }
        }
        _setup_documents_mock(mock_service, "get", return_value=doc)
        result = await svc.get_content("doc-123")
        assert result == "text\n"

    @pytest.mark.asyncio
    async def test_non_text_run_elements_skipped(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        """Elements without a 'textRun' key are skipped."""
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"inlineObjectElement": {"inlineObjectId": "img1"}},
                                {"textRun": {"content": "after image\n"}},
                            ]
                        }
                    }
                ]
            }
        }
        _setup_documents_mock(mock_service, "get", return_value=doc)
        result = await svc.get_content("doc-123")
        assert result == "after image\n"

    @pytest.mark.asyncio
    async def test_multiple_text_runs_in_paragraph(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        """Multiple text runs in a single paragraph are concatenated."""
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Hello, "}},
                                {"textRun": {"content": "world!"}},
                            ]
                        }
                    }
                ]
            }
        }
        _setup_documents_mock(mock_service, "get", return_value=doc)
        result = await svc.get_content("doc-123")
        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_html_content_preserved(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        html = "<html><body><h1>Newsletter</h1></body></html>\n"
        doc_response = _make_doc_response([html])
        _setup_documents_mock(mock_service, "get", return_value=doc_response)

        result = await svc.get_content("doc-123")
        assert result == html

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=ConnectionError("network error"))
        method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        mock_service.documents.return_value = MagicMock(get=method_mock)

        with pytest.raises(ConnectionError, match="network error"):
            await svc.get_content("doc-123")

    @pytest.mark.asyncio
    async def test_return_type_is_string(
        self,
        svc: GoogleDocsService,
        mock_service: MagicMock,
    ) -> None:
        doc_response = _make_doc_response(["text\n"])
        _setup_documents_mock(mock_service, "get", return_value=doc_response)

        result = await svc.get_content("doc-123")
        assert isinstance(result, str)


# ===========================================================================
# _extract_text (unit tests)
# ===========================================================================


class TestExtractText:
    """Tests for the _extract_text helper."""

    def test_empty_body(self) -> None:
        assert _extract_text({"body": {"content": []}}) == ""

    def test_no_body_key(self) -> None:
        assert _extract_text({}) == ""

    def test_single_text_run(self) -> None:
        doc = _make_doc_response(["Hello\n"])
        assert _extract_text(doc) == "Hello\n"

    def test_multiple_paragraphs(self) -> None:
        doc = _make_doc_response(["Line 1\n", "Line 2\n"])
        assert _extract_text(doc) == "Line 1\nLine 2\n"

    def test_text_run_missing_content(self) -> None:
        """textRun without 'content' key yields empty string."""
        doc = {"body": {"content": [{"paragraph": {"elements": [{"textRun": {}}]}}]}}
        assert _extract_text(doc) == ""

    def test_paragraph_without_elements(self) -> None:
        doc = {"body": {"content": [{"paragraph": {}}]}}
        assert _extract_text(doc) == ""

    def test_mixed_element_types(self) -> None:
        """Only textRun content is extracted; other element types are skipped."""
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "before "}},
                                {"inlineObjectElement": {"inlineObjectId": "obj1"}},
                                {"textRun": {"content": "after"}},
                            ]
                        }
                    }
                ]
            }
        }
        assert _extract_text(doc) == "before after"

    def test_unicode_text(self) -> None:
        doc = _make_doc_response(["\u2192 AI \u2022 \u00e9\u00e0\u00fc\n"])
        assert _extract_text(doc) == "\u2192 AI \u2022 \u00e9\u00e0\u00fc\n"

    def test_newlines_preserved(self) -> None:
        doc = _make_doc_response(["line1\nline2\nline3\n"])
        assert _extract_text(doc) == "line1\nline2\nline3\n"


# ===========================================================================
# Protocol satisfaction / async verification
# ===========================================================================


class TestAsyncMethods:
    """Verify that all public methods are async."""

    def test_create_document_is_async(self, svc: GoogleDocsService) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(svc.create_document)

    def test_insert_content_is_async(self, svc: GoogleDocsService) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(svc.insert_content)

    def test_get_content_is_async(self, svc: GoogleDocsService) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(svc.get_content)


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_scopes_contains_documents(self) -> None:
        assert any("documents" in s for s in SCOPES)

    def test_scopes_contains_drive(self) -> None:
        assert any("drive" in s for s in SCOPES)

    def test_scopes_is_list(self) -> None:
        assert isinstance(SCOPES, list)
