"""Tests for :mod:`ica.services.google_auth`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ica.services.google_auth import load_credentials

SAMPLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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


class TestLoadCredentials:
    """Tests for load_credentials()."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            load_credentials(tmp_path / "missing.json", SAMPLE_SCOPES)

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid credentials"):
            load_credentials(path, SAMPLE_SCOPES)

    def test_missing_type_field(self, tmp_path: Path) -> None:
        path = tmp_path / "no_type.json"
        path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(ValueError, match="'type' field"):
            load_credentials(path, SAMPLE_SCOPES)

    def test_unsupported_type(self, tmp_path: Path) -> None:
        path = tmp_path / "oauth.json"
        path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported credential type"):
            load_credentials(path, SAMPLE_SCOPES)

    def test_not_a_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "array.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError, match="'type' field"):
            load_credentials(path, SAMPLE_SCOPES)

    def test_valid_service_account(self, tmp_path: Path) -> None:
        path = _make_service_account_json(tmp_path)
        mock_creds = MagicMock(
            service_account_email="test@test-project.iam.gserviceaccount.com",
        )
        with patch(
            "ica.services.google_auth.ServiceAccountCredentials.from_service_account_info",
            return_value=mock_creds,
        ) as from_info:
            creds = load_credentials(path, SAMPLE_SCOPES)
            from_info.assert_called_once()
            call_kwargs = from_info.call_args
            assert call_kwargs[1]["scopes"] == SAMPLE_SCOPES
        assert creds is mock_creds

    def test_scopes_forwarded(self, tmp_path: Path) -> None:
        """Different scopes are forwarded to from_service_account_info."""
        path = _make_service_account_json(tmp_path)
        custom_scopes = [
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive.file",
        ]
        with patch(
            "ica.services.google_auth.ServiceAccountCredentials.from_service_account_info",
            return_value=MagicMock(),
        ) as from_info:
            load_credentials(path, custom_scopes)
            assert from_info.call_args[1]["scopes"] == custom_scopes

    def test_binary_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "binary.json"
        path.write_bytes(b"\x80\x81\x82")
        with pytest.raises(ValueError, match="Invalid credentials"):
            load_credentials(path, SAMPLE_SCOPES)
