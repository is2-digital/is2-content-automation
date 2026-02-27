"""Tests for :mod:`ica.services.prompt_editor`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.llm_configs import loader
from ica.llm_configs.loader import _cache
from ica.services.prompt_editor import (
    _HEADER_END,
    PromptEditorService,
    _build_edit_header,
    _parse_doc_content,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config_dict(**overrides: object) -> dict:
    """Return a valid config dict with optional overrides."""
    base: dict = {
        "$schema": "ica-llm-config/v1",
        "processName": "test-process",
        "description": "A test process",
        "model": "anthropic/claude-sonnet-4.5",
        "prompts": {
            "system": "You are a test system.",
            "instruction": "Follow test instructions.",
        },
        "metadata": {
            "googleDocId": None,
            "lastSyncedAt": None,
            "version": 1,
        },
    }
    base.update(overrides)
    return base


def _write_config(tmp_path: Path, process_name: str = "test-process", **overrides: object) -> Path:
    """Write a config JSON file to tmp_path and return its path."""
    data = _valid_config_dict(processName=process_name, **overrides)
    config_file = tmp_path / f"{process_name}-llm.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    return config_file


def _read_saved_config(tmp_path: Path, process_name: str = "test-process") -> dict:
    """Read and parse the config JSON file from tmp_path."""
    config_file = tmp_path / f"{process_name}-llm.json"
    return json.loads(config_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches between tests."""
    _cache.clear()
    loader._PROCESS_TO_FIELD = None


@pytest.fixture
def mock_docs() -> MagicMock:
    """Return a mock GoogleDocsService."""
    svc = MagicMock(spec=["create_document", "insert_content", "get_content"])
    svc.create_document = AsyncMock(return_value="doc-new-123")
    svc.insert_content = AsyncMock()
    svc.get_content = AsyncMock()
    return svc


@pytest.fixture
def editor(mock_docs: MagicMock) -> PromptEditorService:
    """Return a PromptEditorService with a mocked docs service."""
    return PromptEditorService(mock_docs)


# ---------------------------------------------------------------------------
# _build_edit_header()
# ---------------------------------------------------------------------------


class TestBuildEditHeader:
    def test_includes_process_and_field(self) -> None:
        header = _build_edit_header("summarization", "system", 3)
        assert "Process: summarization" in header
        assert "Field: system" in header
        assert "Version: 3" in header

    def test_ends_with_header_separator(self) -> None:
        header = _build_edit_header("test", "instruction", 1)
        assert _HEADER_END in header


# ---------------------------------------------------------------------------
# _parse_doc_content()
# ---------------------------------------------------------------------------


class TestParseDocContent:
    def test_extracts_field_and_content(self) -> None:
        content = (
            "--- ICA PROMPT EDITOR ---\n"
            "Process: summarization\n"
            "Field: system\n"
            "Version: 1\n"
            f"\n{_HEADER_END}\n\n"
            "You are a helpful assistant."
        )
        field, text = _parse_doc_content(content)
        assert field == "system"
        assert text == "You are a helpful assistant."

    def test_extracts_instruction_field(self) -> None:
        content = (
            "--- ICA PROMPT EDITOR ---\n"
            "Field: instruction\n"
            f"{_HEADER_END}\n\n"
            "Do the thing.\nWith multiple lines."
        )
        field, text = _parse_doc_content(content)
        assert field == "instruction"
        assert text == "Do the thing.\nWith multiple lines."

    def test_raises_on_missing_separator(self) -> None:
        with pytest.raises(ValueError, match="missing the header separator"):
            _parse_doc_content("Just some text without a header")

    def test_raises_on_missing_field_line(self) -> None:
        content = f"Some header\n{_HEADER_END}\nprompt text"
        with pytest.raises(ValueError, match="missing the 'Field:' line"):
            _parse_doc_content(content)

    def test_raises_on_invalid_field_name(self) -> None:
        content = f"Field: bogus\n{_HEADER_END}\nprompt text"
        with pytest.raises(ValueError, match="Unknown field"):
            _parse_doc_content(content)

    def test_roundtrip_with_build_header(self) -> None:
        """Content built with _build_edit_header parses back correctly."""
        header = _build_edit_header("theme-generation", "instruction", 5)
        prompt = "Generate {feedback_section}\n%FA_TITLE: something"
        full = header + prompt

        field, text = _parse_doc_content(full)
        assert field == "instruction"
        assert text == prompt


# ---------------------------------------------------------------------------
# PromptEditorService.start_edit()
# ---------------------------------------------------------------------------


class TestStartEdit:
    async def test_creates_doc_and_returns_url(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            url = await editor.start_edit("test-process", "system")

        assert url == "https://docs.google.com/document/d/doc-new-123/edit"
        mock_docs.create_document.assert_awaited_once()
        mock_docs.insert_content.assert_awaited_once()

    async def test_populates_doc_with_system_prompt(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        content = mock_docs.insert_content.call_args[0][1]
        assert "You are a test system." in content
        assert _HEADER_END in content
        assert "Field: system" in content

    async def test_populates_doc_with_instruction_prompt(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "instruction")

        content = mock_docs.insert_content.call_args[0][1]
        assert "Follow test instructions." in content
        assert "Field: instruction" in content

    async def test_saves_doc_id_to_metadata(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        saved = _read_saved_config(tmp_path)
        assert saved["metadata"]["googleDocId"] == "doc-new-123"

    async def test_warns_when_replacing_existing_session(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "old-doc", "lastSyncedAt": None, "version": 1},
        )

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            url = await editor.start_edit("test-process", "system")

        assert "doc-new-123" in url
        saved = _read_saved_config(tmp_path)
        assert saved["metadata"]["googleDocId"] == "doc-new-123"

    async def test_invalid_field_raises(self, editor: PromptEditorService) -> None:
        with pytest.raises(ValueError, match="Invalid field"):
            await editor.start_edit("test-process", "bogus")


# ---------------------------------------------------------------------------
# PromptEditorService.sync_from_doc()
# ---------------------------------------------------------------------------


class TestSyncFromDoc:
    async def test_syncs_system_prompt(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-abc", "lastSyncedAt": None, "version": 2},
        )
        header = _build_edit_header("test-process", "system", 2)
        mock_docs.get_content.return_value = header + "Updated system prompt."

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.prompts.system == "Updated system prompt."
        assert config.metadata.version == 3

    async def test_syncs_instruction_prompt(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-abc", "lastSyncedAt": None, "version": 1},
        )
        header = _build_edit_header("test-process", "instruction", 1)
        mock_docs.get_content.return_value = header + "New instruction content."

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.prompts.instruction == "New instruction content."

    async def test_bumps_version_and_sets_timestamp(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-abc", "lastSyncedAt": None, "version": 5},
        )
        header = _build_edit_header("test-process", "system", 5)
        mock_docs.get_content.return_value = header + "Content."

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.metadata.version == 6
        assert config.metadata.last_synced_at is not None

    async def test_clears_google_doc_id(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-abc", "lastSyncedAt": None, "version": 1},
        )
        header = _build_edit_header("test-process", "system", 1)
        mock_docs.get_content.return_value = header + "Content."

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.metadata.google_doc_id is None
        saved = _read_saved_config(tmp_path)
        assert saved["metadata"]["googleDocId"] is None

    async def test_writes_config_to_disk(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-abc", "lastSyncedAt": None, "version": 1},
        )
        header = _build_edit_header("test-process", "system", 1)
        mock_docs.get_content.return_value = header + "Persisted prompt."

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.sync_from_doc("test-process")

        saved = _read_saved_config(tmp_path)
        assert saved["prompts"]["system"] == "Persisted prompt."
        assert saved["metadata"]["version"] == 2

    async def test_raises_when_no_doc_linked(
        self,
        editor: PromptEditorService,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="No Google Doc linked"),
        ):
            await editor.sync_from_doc("test-process")


# ---------------------------------------------------------------------------
# PromptEditorService.update_model()
# ---------------------------------------------------------------------------


class TestUpdateModel:
    def test_updates_model(
        self, editor: PromptEditorService, tmp_path: Path
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = editor.update_model("test-process", "openai/gpt-4.1")

        assert config.model == "openai/gpt-4.1"

    def test_bumps_version(
        self, editor: PromptEditorService, tmp_path: Path
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = editor.update_model("test-process", "openai/gpt-4.1")

        assert config.metadata.version == 2

    def test_sets_timestamp(
        self, editor: PromptEditorService, tmp_path: Path
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = editor.update_model("test-process", "openai/gpt-4.1")

        assert config.metadata.last_synced_at is not None

    def test_writes_to_disk(
        self, editor: PromptEditorService, tmp_path: Path
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            editor.update_model("test-process", "openai/gpt-4.1")

        saved = _read_saved_config(tmp_path)
        assert saved["model"] == "openai/gpt-4.1"
        assert saved["metadata"]["version"] == 2

    def test_strips_whitespace(
        self, editor: PromptEditorService, tmp_path: Path
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = editor.update_model("test-process", "  openai/gpt-4.1  ")

        assert config.model == "openai/gpt-4.1"

    def test_raises_on_empty_model(self, editor: PromptEditorService) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            editor.update_model("test-process", "")

    def test_raises_on_whitespace_only_model(
        self, editor: PromptEditorService
    ) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            editor.update_model("test-process", "   ")


# ---------------------------------------------------------------------------
# PromptEditorService.get_config_summary()
# ---------------------------------------------------------------------------


class TestGetConfigSummary:
    def test_formats_summary(self, editor: PromptEditorService, tmp_path: Path) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            summary = editor.get_config_summary("test-process")

        assert "*test-process*" in summary
        assert "anthropic/claude-sonnet-4.5" in summary
        assert "Version: 1" in summary
        assert "Last synced: Never" in summary
        assert "Active edit: No" in summary

    def test_shows_active_edit(self, editor: PromptEditorService, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-123", "lastSyncedAt": None, "version": 1},
        )

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            summary = editor.get_config_summary("test-process")

        assert "Active edit: Yes" in summary

    def test_shows_last_synced_time(
        self,
        editor: PromptEditorService,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={
                "googleDocId": None,
                "lastSyncedAt": "2026-02-24T12:00:00+00:00",
                "version": 3,
            },
        )

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            summary = editor.get_config_summary("test-process")

        assert "2026-02-24T12:00:00+00:00" in summary
        assert "Version: 3" in summary

    def test_shows_prompt_lengths(self, editor: PromptEditorService, tmp_path: Path) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            summary = editor.get_config_summary("test-process")

        assert "System prompt:" in summary
        assert "Instruction prompt:" in summary
        assert "chars" in summary
