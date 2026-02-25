"""Tests for :mod:`ica.services.google_sheets`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ica.services.google_sheets import (
    DEFAULT_RANGE,
    SCOPES,
    GoogleSheetsService,
    _load_credentials,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_service_account_json(tmp_path: Path) -> Path:
    """Write a minimal service account JSON file and return its path.

    Uses a bare-minimum structure that passes our validation checks.
    The actual credential parsing is mocked in tests that need it.
    """
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
    """Return a mock Google Sheets API service."""
    return MagicMock(spec=["spreadsheets"])


@pytest.fixture
def svc(mock_service: MagicMock) -> GoogleSheetsService:
    """Return a GoogleSheetsService with a mocked API service."""
    return GoogleSheetsService(service=mock_service)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_values_mock(
    mock_service: MagicMock,
    method: str,
    return_value: Any = None,
) -> MagicMock:
    """Set up a mock for spreadsheets().values().<method>().execute()."""
    execute_mock = MagicMock(return_value=return_value or {})
    method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
    values_mock = MagicMock(**{method: method_mock})
    mock_service.spreadsheets.return_value.values.return_value = values_mock
    return method_mock


# ===========================================================================
# _load_credentials
# ===========================================================================


class TestLoadCredentials:
    """Tests for _load_credentials()."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            _load_credentials(tmp_path / "missing.json")

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid credentials"):
            _load_credentials(path)

    def test_missing_type_field(self, tmp_path: Path) -> None:
        path = tmp_path / "no_type.json"
        path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(ValueError, match="'type' field"):
            _load_credentials(path)

    def test_unsupported_type(self, tmp_path: Path) -> None:
        path = tmp_path / "oauth.json"
        path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported credential type"):
            _load_credentials(path)

    def test_not_a_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "array.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError, match="'type' field"):
            _load_credentials(path)

    def test_valid_service_account(self, tmp_path: Path) -> None:
        path = _make_service_account_json(tmp_path)
        mock_creds = MagicMock(
            service_account_email="test@test-project.iam.gserviceaccount.com",
            scopes=SCOPES,
        )
        with patch(
            "ica.services.google_sheets.ServiceAccountCredentials.from_service_account_info",
            return_value=mock_creds,
        ) as from_info:
            creds = _load_credentials(path)
            from_info.assert_called_once()
            # Verify scopes were passed
            call_kwargs = from_info.call_args
            assert call_kwargs[1]["scopes"] == SCOPES
        assert creds is mock_creds


# ===========================================================================
# GoogleSheetsService.__init__
# ===========================================================================


class TestInit:
    """Tests for GoogleSheetsService constructor."""

    def test_with_service(self, mock_service: MagicMock) -> None:
        svc = GoogleSheetsService(service=mock_service)
        assert svc._service is mock_service

    def test_with_credentials_path(self, tmp_path: Path) -> None:
        path = _make_service_account_json(tmp_path)
        with (
            patch(
                "ica.services.google_sheets._load_credentials",
                return_value=MagicMock(),
            ) as load_mock,
            patch(
                "ica.services.google_sheets._build_service",
                return_value=MagicMock(),
            ) as build_mock,
        ):
            svc = GoogleSheetsService(credentials_path=path)
            load_mock.assert_called_once_with(path)
            build_mock.assert_called_once()
            assert svc._service is build_mock.return_value

    def test_no_args_raises(self) -> None:
        with pytest.raises(ValueError, match="credentials_path or service"):
            GoogleSheetsService()

    def test_service_takes_precedence(self, mock_service: MagicMock) -> None:
        """When both are provided, service is used (credentials_path ignored)."""
        svc = GoogleSheetsService(credentials_path="/fake/path", service=mock_service)
        assert svc._service is mock_service

    def test_credentials_path_string(self, tmp_path: Path) -> None:
        """Accepts string paths in addition to Path objects."""
        path = _make_service_account_json(tmp_path)
        with (
            patch(
                "ica.services.google_sheets._load_credentials",
                return_value=MagicMock(),
            ),
            patch(
                "ica.services.google_sheets._build_service",
                return_value=MagicMock(),
            ),
        ):
            svc = GoogleSheetsService(credentials_path=str(path))
            assert svc._service is not None


# ===========================================================================
# clear_sheet
# ===========================================================================


class TestClearSheet:
    """Tests for GoogleSheetsService.clear_sheet()."""

    @pytest.mark.asyncio
    async def test_calls_api(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        clear_mock = _setup_values_mock(mock_service, "clear")
        await svc.clear_sheet("sheet-id-123", "Sheet1")

        clear_mock.assert_called_once_with(
            spreadsheetId="sheet-id-123",
            range=f"Sheet1!{DEFAULT_RANGE}",
            body={},
        )

    @pytest.mark.asyncio
    async def test_custom_sheet_name(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        clear_mock = _setup_values_mock(mock_service, "clear")
        await svc.clear_sheet("abc", "Articles")

        clear_mock.assert_called_once_with(
            spreadsheetId="abc",
            range=f"Articles!{DEFAULT_RANGE}",
            body={},
        )

    @pytest.mark.asyncio
    async def test_returns_none(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(mock_service, "clear")
        result = await svc.clear_sheet("id", "Sheet1")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=Exception("API error"))
        method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        values_mock = MagicMock(clear=method_mock)
        mock_service.spreadsheets.return_value.values.return_value = values_mock

        with pytest.raises(Exception, match="API error"):
            await svc.clear_sheet("id", "Sheet1")


# ===========================================================================
# append_rows
# ===========================================================================


class TestAppendRows:
    """Tests for GoogleSheetsService.append_rows()."""

    @pytest.mark.asyncio
    async def test_empty_rows_returns_zero(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        result = await svc.append_rows("id", "Sheet1", [])
        assert result == 0
        # Should not call API
        mock_service.spreadsheets.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_row(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [{"url": "https://example.com", "title": "Test"}]
        count = await svc.append_rows("sheet-id", "Sheet1", rows)

        assert count == 1
        update_mock.assert_called_once()
        call_kwargs = update_mock.call_args[1]
        assert call_kwargs["spreadsheetId"] == "sheet-id"
        assert call_kwargs["range"] == f"Sheet1!{DEFAULT_RANGE}"
        assert call_kwargs["valueInputOption"] == "RAW"

        body = call_kwargs["body"]
        assert body["values"][0] == ["url", "title"]  # headers
        assert body["values"][1] == ["https://example.com", "Test"]  # data

    @pytest.mark.asyncio
    async def test_multiple_rows(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [
            {"a": "1", "b": "2"},
            {"a": "3", "b": "4"},
            {"a": "5", "b": "6"},
        ]
        count = await svc.append_rows("id", "Sheet1", rows)

        assert count == 3
        body = update_mock.call_args[1]["body"]
        assert len(body["values"]) == 4  # 1 header + 3 data rows

    @pytest.mark.asyncio
    async def test_headers_from_first_row(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [
            {"url": "u1", "title": "t1", "origin": "o1"},
            {"url": "u2", "title": "t2", "origin": "o2"},
        ]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][0] == ["url", "title", "origin"]

    @pytest.mark.asyncio
    async def test_missing_key_defaults_to_empty(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [
            {"a": "1", "b": "2"},
            {"a": "3"},  # missing "b"
        ]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][2] == ["3", ""]

    @pytest.mark.asyncio
    async def test_non_string_values_converted(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [{"count": 42, "active": True, "ratio": 3.14}]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][1] == ["42", "True", "3.14"]

    @pytest.mark.asyncio
    async def test_custom_sheet_name(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        await svc.append_rows("id", "Articles", [{"x": "1"}])

        call_kwargs = update_mock.call_args[1]
        assert call_kwargs["range"] == f"Articles!{DEFAULT_RANGE}"

    @pytest.mark.asyncio
    async def test_return_count_matches_data_rows(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(mock_service, "update")

        rows = [{"k": str(i)} for i in range(7)]
        count = await svc.append_rows("id", "Sheet1", rows)
        assert count == 7

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=RuntimeError("quota exceeded"))
        method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        values_mock = MagicMock(update=method_mock)
        mock_service.spreadsheets.return_value.values.return_value = values_mock

        with pytest.raises(RuntimeError, match="quota exceeded"):
            await svc.append_rows("id", "Sheet1", [{"a": "1"}])


# ===========================================================================
# read_rows
# ===========================================================================


class TestReadRows:
    """Tests for GoogleSheetsService.read_rows()."""

    @pytest.mark.asyncio
    async def test_empty_sheet(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(mock_service, "get", return_value={"values": []})
        result = await svc.read_rows("id", "Sheet1")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_values_key(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(mock_service, "get", return_value={})
        result = await svc.read_rows("id", "Sheet1")
        assert result == []

    @pytest.mark.asyncio
    async def test_only_header_row(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(
            mock_service,
            "get",
            return_value={"values": [["url", "title"]]},
        )
        result = await svc.read_rows("id", "Sheet1")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_data_row(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    ["url", "title"],
                    ["https://example.com", "Test Article"],
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        assert result == [{"url": "https://example.com", "title": "Test Article"}]

    @pytest.mark.asyncio
    async def test_multiple_data_rows(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    ["a", "b"],
                    ["1", "2"],
                    ["3", "4"],
                    ["5", "6"],
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        assert len(result) == 3
        assert result[0] == {"a": "1", "b": "2"}
        assert result[1] == {"a": "3", "b": "4"}
        assert result[2] == {"a": "5", "b": "6"}

    @pytest.mark.asyncio
    async def test_short_row_fills_empty(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """Rows shorter than headers get empty strings for missing cells."""
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    ["a", "b", "c"],
                    ["1"],  # missing b and c
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        assert result == [{"a": "1", "b": "", "c": ""}]

    @pytest.mark.asyncio
    async def test_seven_column_sheet(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """Full curated-articles sheet columns."""
        headers = [
            "url",
            "title",
            "publish_date",
            "origin",
            "approved",
            "newsletter_id",
            "industry_news",
        ]
        row1 = [
            "https://example.com/1",
            "Article 1",
            "02/22/2026",
            "google_news",
            "yes",
            "NL-001",
            "",
        ]
        row2 = [
            "https://example.com/2",
            "Article 2",
            "02/21/2026",
            "searchapi",
            "",
            "",
            "yes",
        ]
        _setup_values_mock(
            mock_service,
            "get",
            return_value={"values": [headers, row1, row2]},
        )
        result = await svc.read_rows("id", "Sheet1")

        assert len(result) == 2
        assert result[0]["url"] == "https://example.com/1"
        assert result[0]["approved"] == "yes"
        assert result[0]["newsletter_id"] == "NL-001"
        assert result[1]["industry_news"] == "yes"
        assert result[1]["approved"] == ""

    @pytest.mark.asyncio
    async def test_custom_sheet_name(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        get_mock = _setup_values_mock(
            mock_service,
            "get",
            return_value={"values": []},
        )
        await svc.read_rows("id", "MySheet")

        get_mock.assert_called_once()
        assert get_mock.call_args[1]["range"] == f"MySheet!{DEFAULT_RANGE}"

    @pytest.mark.asyncio
    async def test_api_error_propagates(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        execute_mock = MagicMock(side_effect=ConnectionError("network"))
        method_mock = MagicMock(return_value=MagicMock(execute=execute_mock))
        values_mock = MagicMock(get=method_mock)
        mock_service.spreadsheets.return_value.values.return_value = values_mock

        with pytest.raises(ConnectionError, match="network"):
            await svc.read_rows("id", "Sheet1")


# ===========================================================================
# Protocol satisfaction
# ===========================================================================


class TestProtocolSatisfaction:
    """Verify that GoogleSheetsService matches pipeline protocols."""

    def test_has_clear_sheet(self) -> None:
        assert hasattr(GoogleSheetsService, "clear_sheet")

    def test_has_append_rows(self) -> None:
        assert hasattr(GoogleSheetsService, "append_rows")

    def test_has_read_rows(self) -> None:
        assert hasattr(GoogleSheetsService, "read_rows")

    def test_clear_sheet_is_async(self, svc: GoogleSheetsService) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(svc.clear_sheet)

    def test_append_rows_is_async(self, svc: GoogleSheetsService) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(svc.append_rows)

    def test_read_rows_is_async(self, svc: GoogleSheetsService) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(svc.read_rows)


# ===========================================================================
# Column ordering and data integrity
# ===========================================================================


class TestDataIntegrity:
    """Tests for data integrity in append_rows and read_rows."""

    @pytest.mark.asyncio
    async def test_column_order_preserved(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """Headers come from dict key order of the first row."""
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [{"z": "1", "a": "2", "m": "3"}]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][0] == ["z", "a", "m"]
        assert body["values"][1] == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_special_characters_preserved(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [{"text": "Hello\nWorld\t!"}]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][1] == ["Hello\nWorld\t!"]

    @pytest.mark.asyncio
    async def test_unicode_preserved(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [{"title": "AI \u2192 Business"}]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][1] == ["AI \u2192 Business"]

    @pytest.mark.asyncio
    async def test_empty_string_values(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        update_mock = _setup_values_mock(mock_service, "update")

        rows = [{"a": "", "b": "x", "c": ""}]
        await svc.append_rows("id", "Sheet1", rows)

        body = update_mock.call_args[1]["body"]
        assert body["values"][1] == ["", "x", ""]


# ===========================================================================
# Edge cases for read_rows
# ===========================================================================


class TestReadRowsEdgeCases:
    """Additional edge cases for read_rows."""

    @pytest.mark.asyncio
    async def test_extra_data_beyond_headers_ignored(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """Data cells beyond the header count are silently ignored."""
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    ["a", "b"],
                    ["1", "2", "extra"],
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        # Only headers "a" and "b" are used
        assert result == [{"a": "1", "b": "2"}]

    @pytest.mark.asyncio
    async def test_completely_empty_row(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """An empty data row (no cells at all) gets all empty strings."""
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    ["a", "b"],
                    [],
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        assert result == [{"a": "", "b": ""}]

    @pytest.mark.asyncio
    async def test_whitespace_header_names(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """Headers with whitespace are used as-is (no trimming)."""
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    [" url ", "title"],
                    ["http://x", "Y"],
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        assert " url " in result[0]
        assert result[0][" url "] == "http://x"

    @pytest.mark.asyncio
    async def test_duplicate_headers(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        """When headers are duplicated, last value wins in the dict."""
        _setup_values_mock(
            mock_service,
            "get",
            return_value={
                "values": [
                    ["a", "a"],
                    ["first", "second"],
                ],
            },
        )
        result = await svc.read_rows("id", "Sheet1")
        assert result[0]["a"] == "second"

    @pytest.mark.asyncio
    async def test_read_rows_spreadsheet_id_forwarded(
        self,
        svc: GoogleSheetsService,
        mock_service: MagicMock,
    ) -> None:
        get_mock = _setup_values_mock(
            mock_service,
            "get",
            return_value={"values": []},
        )
        await svc.read_rows("my-spreadsheet-id", "Sheet1")

        call_kwargs = get_mock.call_args[1]
        assert call_kwargs["spreadsheetId"] == "my-spreadsheet-id"


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_default_range(self) -> None:
        assert DEFAULT_RANGE == "A:Z"

    def test_scopes_contains_spreadsheets(self) -> None:
        assert any("spreadsheets" in s for s in SCOPES)
