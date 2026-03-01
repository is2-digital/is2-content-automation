"""Tests for :mod:`ica.services.slack_config_handlers`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.llm_configs import loader
from ica.llm_configs.loader import _cache
from ica.services.prompt_editor import PromptEditorService
from ica.services.slack_config_handlers import (
    ACTION_CONFIG_TRIGGER,
    ACTION_EDIT_INSTRUCTION,
    ACTION_EDIT_MODEL,
    ACTION_EDIT_SYSTEM,
    ACTION_SYNC_FROM_DOC,
    ACTION_VIEW_SUMMARY,
    VIEW_CONFIG_MODAL,
    build_config_menu_blocks,
    build_config_modal,
    dispatch_config_action,
    extract_config_modal_values,
    get_available_processes,
    register_config_handlers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config_dict(process_name: str = "test-process") -> dict[str, Any]:
    """Return a minimal valid config dict."""
    return {
        "$schema": "ica-llm-config/v1",
        "processName": process_name,
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


def _write_config(
    tmp_path: Path,
    process_name: str = "test-process",
    **overrides: object,
) -> Path:
    """Write a config JSON file and return its path."""
    data = _valid_config_dict(process_name)
    data.update(overrides)
    config_file = tmp_path / f"{process_name}-llm.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    return config_file


def _make_state_values(
    process: str = "summarization",
    action: str = ACTION_VIEW_SUMMARY,
    model_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build mock Slack modal state_values dict."""
    values: dict[str, dict[str, Any]] = {
        "process_block": {
            "process_select": {
                "type": "static_select",
                "selected_option": {
                    "text": {"type": "plain_text", "text": process},
                    "value": process,
                },
            },
        },
        "action_block": {
            "action_select": {
                "type": "static_select",
                "selected_option": {
                    "text": {"type": "plain_text", "text": "View Summary"},
                    "value": action,
                },
            },
        },
        "model_block": {
            "model_input": {
                "type": "plain_text_input",
                "value": model_id,
            },
        },
    }
    return values


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches between tests."""
    _cache.clear()


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


@pytest.fixture
def mock_client() -> AsyncMock:
    """Return a mocked Slack AsyncWebClient."""
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True})
    client.views_open = AsyncMock(return_value={"ok": True})
    return client


# ---------------------------------------------------------------------------
# get_available_processes()
# ---------------------------------------------------------------------------


class TestGetAvailableProcesses:
    def test_discovers_json_files(self, tmp_path: Path) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")
        (tmp_path / "html-generation-llm.json").write_text("{}")
        (tmp_path / "not-a-config.txt").write_text("{}")

        result = get_available_processes(configs_dir=tmp_path)
        assert result == ["html-generation", "summarization"]

    def test_returns_empty_for_empty_dir(self, tmp_path: Path) -> None:
        assert get_available_processes(configs_dir=tmp_path) == []

    def test_sorted_alphabetically(self, tmp_path: Path) -> None:
        for name in ["theme-generation", "email-subject", "summarization"]:
            (tmp_path / f"{name}-llm.json").write_text("{}")

        result = get_available_processes(configs_dir=tmp_path)
        assert result == ["email-subject", "summarization", "theme-generation"]


# ---------------------------------------------------------------------------
# build_config_menu_blocks()
# ---------------------------------------------------------------------------


class TestBuildConfigMenuBlocks:
    def test_has_text_and_button(self) -> None:
        blocks = build_config_menu_blocks()
        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert blocks[1]["type"] == "actions"

    def test_button_has_correct_action_id(self) -> None:
        blocks = build_config_menu_blocks()
        button = blocks[1]["elements"][0]
        assert button["action_id"] == ACTION_CONFIG_TRIGGER

    def test_button_is_primary(self) -> None:
        blocks = build_config_menu_blocks()
        button = blocks[1]["elements"][0]
        assert button["style"] == "primary"


# ---------------------------------------------------------------------------
# build_config_modal()
# ---------------------------------------------------------------------------


class TestBuildConfigModal:
    def test_modal_structure(self, tmp_path: Path) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")

        modal = build_config_modal(configs_dir=tmp_path)
        assert modal["type"] == "modal"
        assert modal["callback_id"] == VIEW_CONFIG_MODAL

    def test_has_process_action_and_model_blocks(self, tmp_path: Path) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")

        modal = build_config_modal(configs_dir=tmp_path)
        blocks = modal["blocks"]
        assert len(blocks) == 3
        assert blocks[0]["block_id"] == "process_block"
        assert blocks[1]["block_id"] == "action_block"
        assert blocks[2]["block_id"] == "model_block"

    def test_model_block_is_optional(self, tmp_path: Path) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")

        modal = build_config_modal(configs_dir=tmp_path)
        model_block = modal["blocks"][2]
        assert model_block["optional"] is True

    def test_process_options_from_directory(self, tmp_path: Path) -> None:
        for name in ["summarization", "html-generation"]:
            (tmp_path / f"{name}-llm.json").write_text("{}")

        modal = build_config_modal(configs_dir=tmp_path)
        process_options = modal["blocks"][0]["element"]["options"]
        values = [o["value"] for o in process_options]
        assert values == ["html-generation", "summarization"]

    def test_action_options(self, tmp_path: Path) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")

        modal = build_config_modal(configs_dir=tmp_path)
        action_options = modal["blocks"][1]["element"]["options"]
        values = [o["value"] for o in action_options]
        assert ACTION_EDIT_SYSTEM in values
        assert ACTION_EDIT_INSTRUCTION in values
        assert ACTION_EDIT_MODEL in values
        assert ACTION_VIEW_SUMMARY in values
        assert ACTION_SYNC_FROM_DOC in values

    def test_title_within_slack_limit(self, tmp_path: Path) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")

        modal = build_config_modal(configs_dir=tmp_path)
        title_text = modal["title"]["text"]
        assert len(title_text) <= 24


# ---------------------------------------------------------------------------
# extract_config_modal_values()
# ---------------------------------------------------------------------------


class TestExtractConfigModalValues:
    def test_extracts_all_values(self) -> None:
        state = _make_state_values(
            "theme-generation", ACTION_EDIT_MODEL, model_id="openai/gpt-4.1"
        )
        process, action, model_id = extract_config_modal_values(state)
        assert process == "theme-generation"
        assert action == ACTION_EDIT_MODEL
        assert model_id == "openai/gpt-4.1"

    def test_extracts_without_model_id(self) -> None:
        state = _make_state_values("theme-generation", ACTION_EDIT_SYSTEM)
        process, action, model_id = extract_config_modal_values(state)
        assert process == "theme-generation"
        assert action == ACTION_EDIT_SYSTEM
        assert model_id == ""

    def test_empty_when_no_selection(self) -> None:
        process, action, model_id = extract_config_modal_values({})
        assert process == ""
        assert action == ""
        assert model_id == ""

    def test_empty_when_selected_option_is_none(self) -> None:
        state = {
            "process_block": {
                "process_select": {
                    "type": "static_select",
                    "selected_option": None,
                },
            },
            "action_block": {
                "action_select": {
                    "type": "static_select",
                    "selected_option": None,
                },
            },
        }
        process, action, model_id = extract_config_modal_values(state)
        assert process == ""
        assert action == ""
        assert model_id == ""


# ---------------------------------------------------------------------------
# dispatch_config_action()
# ---------------------------------------------------------------------------


class TestDispatchConfigAction:
    async def test_edit_system(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await dispatch_config_action(
                editor, mock_client, "#test", "test-process", ACTION_EDIT_SYSTEM
            )

        mock_client.chat_postMessage.assert_awaited_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "system prompt" in call_kwargs["text"]
        assert "shared" in call_kwargs["text"]

    async def test_edit_instruction(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await dispatch_config_action(
                editor, mock_client, "#test", "test-process", ACTION_EDIT_INSTRUCTION
            )

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "instruction prompt" in call_kwargs["text"]
        assert "doc-new-123" in call_kwargs["text"]

    async def test_view_summary(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await dispatch_config_action(
                editor, mock_client, "#test", "test-process", ACTION_VIEW_SUMMARY
            )

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "*test-process*" in call_kwargs["text"]
        assert "Version: 1" in call_kwargs["text"]

    async def test_sync_from_doc(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-abc", "lastSyncedAt": None, "version": 2},
        )
        from ica.services.prompt_editor import _build_edit_header

        header = _build_edit_header("test-process", "instruction", 2)
        mock_docs.get_content.return_value = header + "Updated content."

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await dispatch_config_action(
                editor, mock_client, "#test", "test-process", ACTION_SYNC_FROM_DOC
            )

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "Synced" in call_kwargs["text"]
        assert "v3" in call_kwargs["text"]

    async def test_edit_model(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await dispatch_config_action(
                editor,
                mock_client,
                "#test",
                "test-process",
                ACTION_EDIT_MODEL,
                model_id="openai/gpt-4.1",
            )

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "Updated" in call_kwargs["text"]
        assert "openai/gpt-4.1" in call_kwargs["text"]

    async def test_edit_model_missing_model_id(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
    ) -> None:
        await dispatch_config_action(
            editor,
            mock_client,
            "#test",
            "test-process",
            ACTION_EDIT_MODEL,
            model_id="",
        )

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "provide a Model ID" in call_kwargs["text"]

    async def test_unknown_action(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
    ) -> None:
        await dispatch_config_action(
            editor, mock_client, "#test", "test-process", "bogus_action"
        )

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "Unknown action" in call_kwargs["text"]


# ---------------------------------------------------------------------------
# register_config_handlers()
# ---------------------------------------------------------------------------


class TestRegisterConfigHandlers:
    def test_registers_action_and_view(
        self, editor: PromptEditorService
    ) -> None:
        bolt_app = MagicMock()
        bolt_app.action = MagicMock(return_value=lambda fn: fn)
        bolt_app.view = MagicMock(return_value=lambda fn: fn)

        register_config_handlers(bolt_app, editor, "#test")

        bolt_app.action.assert_called_once_with(ACTION_CONFIG_TRIGGER)
        bolt_app.view.assert_called_once_with(VIEW_CONFIG_MODAL)

    async def test_trigger_handler_opens_modal(
        self, editor: PromptEditorService, tmp_path: Path
    ) -> None:
        (tmp_path / "summarization-llm.json").write_text("{}")

        # Capture the registered handlers
        handlers: dict[str, Any] = {}
        bolt_app = MagicMock()

        def capture_action(action_id: str):
            def register(fn: Any) -> Any:
                handlers[f"action:{action_id}"] = fn
                return fn
            return register

        def capture_view(view_id: str):
            def register(fn: Any) -> Any:
                handlers[f"view:{view_id}"] = fn
                return fn
            return register

        bolt_app.action = capture_action
        bolt_app.view = capture_view

        with patch(
            "ica.services.slack_config_handlers.get_available_processes",
            return_value=["summarization"],
        ):
            register_config_handlers(bolt_app, editor, "#test")

        # Invoke the trigger handler
        ack = AsyncMock()
        client = AsyncMock()
        client.views_open = AsyncMock()
        body = {"trigger_id": "trigger-123"}

        handler = handlers[f"action:{ACTION_CONFIG_TRIGGER}"]
        await handler(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()
        call_kwargs = client.views_open.call_args[1]
        assert call_kwargs["trigger_id"] == "trigger-123"
        assert call_kwargs["view"]["callback_id"] == VIEW_CONFIG_MODAL

    async def test_modal_handler_dispatches_action(
        self,
        editor: PromptEditorService,
        tmp_path: Path,
    ) -> None:
        _write_config(tmp_path, process_name="test-process")

        handlers: dict[str, Any] = {}
        bolt_app = MagicMock()

        def capture_action(action_id: str):
            def register(fn: Any) -> Any:
                handlers[f"action:{action_id}"] = fn
                return fn
            return register

        def capture_view(view_id: str):
            def register(fn: Any) -> Any:
                handlers[f"view:{view_id}"] = fn
                return fn
            return register

        bolt_app.action = capture_action
        bolt_app.view = capture_view
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        client = AsyncMock()
        client.chat_postMessage = AsyncMock()
        body = {
            "view": {
                "state": {"values": _make_state_values("test-process", ACTION_VIEW_SUMMARY)},
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await handler(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        client.chat_postMessage.assert_awaited_once()
        call_kwargs = client.chat_postMessage.call_args[1]
        assert "*test-process*" in call_kwargs["text"]

    async def test_modal_handler_missing_selection(
        self,
        editor: PromptEditorService,
    ) -> None:
        handlers: dict[str, Any] = {}
        bolt_app = MagicMock()

        def capture_action(action_id: str):
            def register(fn: Any) -> Any:
                handlers[f"action:{action_id}"] = fn
                return fn
            return register

        def capture_view(view_id: str):
            def register(fn: Any) -> Any:
                handlers[f"view:{view_id}"] = fn
                return fn
            return register

        bolt_app.action = capture_action
        bolt_app.view = capture_view
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        client = AsyncMock()
        client.chat_postMessage = AsyncMock()
        body = {"view": {"state": {"values": {}}}}

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        await handler(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        call_kwargs = client.chat_postMessage.call_args[1]
        assert "select both" in call_kwargs["text"].lower()

    async def test_modal_handler_error_handling(
        self,
        editor: PromptEditorService,
    ) -> None:
        handlers: dict[str, Any] = {}
        bolt_app = MagicMock()

        def capture_action(action_id: str):
            def register(fn: Any) -> Any:
                handlers[f"action:{action_id}"] = fn
                return fn
            return register

        def capture_view(view_id: str):
            def register(fn: Any) -> Any:
                handlers[f"view:{view_id}"] = fn
                return fn
            return register

        bolt_app.action = capture_action
        bolt_app.view = capture_view
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        client = AsyncMock()
        client.chat_postMessage = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values(
                        "nonexistent-process", ACTION_VIEW_SUMMARY
                    ),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        await handler(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        # Should post error message (process config doesn't exist)
        call_kwargs = client.chat_postMessage.call_args[1]
        assert "failed" in call_kwargs["text"].lower()
