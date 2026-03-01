"""Tests for ica.guided.google_settings — guided-mode Google validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ica.guided.google_settings import (
    STEPS_REQUIRING_DOCS,
    STEPS_REQUIRING_GOOGLE,
    STEPS_REQUIRING_SHEETS,
    GuidedGoogleSettingsError,
    validate_google_settings,
)
from ica.pipeline.orchestrator import StepName

# ---------------------------------------------------------------------------
# Step → service mapping constants
# ---------------------------------------------------------------------------


class TestStepMappings:
    """Step-to-Google-service mapping is correct and consistent."""

    def test_sheets_steps(self) -> None:
        assert frozenset({
            StepName.CURATION,
            StepName.SUMMARIZATION,
        }) == STEPS_REQUIRING_SHEETS

    def test_docs_steps(self) -> None:
        assert frozenset({
            StepName.MARKDOWN_GENERATION,
            StepName.HTML_GENERATION,
            StepName.EMAIL_SUBJECT,
            StepName.SOCIAL_MEDIA,
            StepName.LINKEDIN_CAROUSEL,
        }) == STEPS_REQUIRING_DOCS

    def test_combined_google_set(self) -> None:
        assert STEPS_REQUIRING_GOOGLE == STEPS_REQUIRING_SHEETS | STEPS_REQUIRING_DOCS

    def test_theme_generation_does_not_need_google(self) -> None:
        assert StepName.THEME_GENERATION not in STEPS_REQUIRING_GOOGLE

    def test_alternates_html_does_not_need_google(self) -> None:
        assert StepName.ALTERNATES_HTML not in STEPS_REQUIRING_GOOGLE


# ---------------------------------------------------------------------------
# validate_google_settings
# ---------------------------------------------------------------------------


def _mock_settings(
    *,
    spreadsheet_id: str = "",
    drive_folder_id: str = "",
) -> MagicMock:
    """Create a mock Settings with guided test target fields."""
    s = MagicMock()
    s.guided_test_spreadsheet_id = spreadsheet_id
    s.guided_test_drive_folder_id = drive_folder_id
    return s


class TestValidateGoogleSettings:
    """validate_google_settings fails fast when test targets are missing."""

    @patch("ica.config.settings.get_settings")
    def test_no_google_steps_passes(self, mock_get: MagicMock) -> None:
        """Steps with no Google dependency skip validation entirely."""
        mock_get.return_value = _mock_settings()
        # theme_generation and alternates_html need no Google services
        validate_google_settings([StepName.THEME_GENERATION, StepName.ALTERNATES_HTML])

    @patch("ica.config.settings.get_settings")
    def test_sheets_step_missing_id_raises(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings()
        with pytest.raises(GuidedGoogleSettingsError, match="GUIDED_TEST_SPREADSHEET_ID"):
            validate_google_settings([StepName.CURATION])

    @patch("ica.config.settings.get_settings")
    def test_docs_step_missing_id_raises(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings()
        with pytest.raises(GuidedGoogleSettingsError, match="GUIDED_TEST_DRIVE_FOLDER_ID"):
            validate_google_settings([StepName.MARKDOWN_GENERATION])

    @patch("ica.config.settings.get_settings")
    def test_both_missing_reports_both(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings()
        with pytest.raises(GuidedGoogleSettingsError) as exc_info:
            validate_google_settings([StepName.CURATION, StepName.HTML_GENERATION])
        msg = str(exc_info.value)
        assert "GUIDED_TEST_SPREADSHEET_ID" in msg
        assert "GUIDED_TEST_DRIVE_FOLDER_ID" in msg

    @patch("ica.config.settings.get_settings")
    def test_sheets_configured_passes(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings(spreadsheet_id="abc123")
        # Only sheets steps — no docs step, so drive folder not needed
        validate_google_settings([StepName.CURATION, StepName.SUMMARIZATION])

    @patch("ica.config.settings.get_settings")
    def test_docs_configured_passes(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings(drive_folder_id="folder789")
        validate_google_settings([StepName.HTML_GENERATION, StepName.EMAIL_SUBJECT])

    @patch("ica.config.settings.get_settings")
    def test_both_configured_passes(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings(
            spreadsheet_id="abc123",
            drive_folder_id="folder789",
        )
        validate_google_settings([
            StepName.CURATION,
            StepName.SUMMARIZATION,
            StepName.MARKDOWN_GENERATION,
            StepName.HTML_GENERATION,
        ])

    @patch("ica.config.settings.get_settings")
    def test_error_lists_affected_steps(self, mock_get: MagicMock) -> None:
        """Error message names the steps that need the missing setting."""
        mock_get.return_value = _mock_settings()
        with pytest.raises(GuidedGoogleSettingsError) as exc_info:
            validate_google_settings([StepName.CURATION, StepName.SUMMARIZATION])
        msg = str(exc_info.value)
        assert "curation" in msg
        assert "summarization" in msg

    @patch("ica.config.settings.get_settings")
    def test_error_includes_setup_instructions(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_settings()
        with pytest.raises(GuidedGoogleSettingsError) as exc_info:
            validate_google_settings([StepName.CURATION])
        msg = str(exc_info.value)
        assert ".env" in msg
        assert "service account" in msg.lower() or "edit access" in msg.lower()

    @patch("ica.config.settings.get_settings")
    def test_empty_run_steps_passes(self, mock_get: MagicMock) -> None:
        """An empty step list (e.g. resumed completed run) skips validation."""
        mock_get.return_value = _mock_settings()
        validate_google_settings([])
