"""Integration tests for the full editing round-trip workflow.

Tests the end-to-end flows:

* start_edit → sync_from_doc (Google Doc round-trip)
* Plain-text preservation through Google Docs round-trip
* Concurrent edit detection and warning
* Model change via Slack form (direct, no Google Docs)
* Full Slack interaction handler flows
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.llm_configs import loader
from ica.llm_configs.loader import _cache
from ica.services.prompt_editor import (
    _HEADER_END,
    PromptEditorService,
    _build_edit_header,
)
from ica.services.slack_config_handlers import (
    ACTION_CONFIG_TRIGGER,
    ACTION_EDIT_MODEL,
    ACTION_SYNC_FROM_DOC,
    ACTION_VIEW_SUMMARY,
    VIEW_CONFIG_MODAL,
    register_config_handlers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config_dict(**overrides: object) -> dict[str, Any]:
    """Return a valid config dict with optional overrides."""
    base: dict[str, Any] = {
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


def _write_config(
    tmp_path: Path,
    process_name: str = "test-process",
    **overrides: object,
) -> Path:
    """Write a config JSON file to tmp_path and return its path."""
    data = _valid_config_dict(processName=process_name, **overrides)
    config_file = tmp_path / f"{process_name}-llm.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    return config_file


def _read_saved_config(tmp_path: Path, process_name: str = "test-process") -> dict:
    """Read and parse the config JSON file from tmp_path."""
    config_file = tmp_path / f"{process_name}-llm.json"
    return json.loads(config_file.read_text(encoding="utf-8"))


def _make_state_values(
    process: str = "test-process",
    action: str = ACTION_VIEW_SUMMARY,
    model_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build mock Slack modal state_values dict."""
    return {
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
                    "text": {"type": "plain_text", "text": action},
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


def _capture_handlers(bolt_app: MagicMock) -> dict[str, Any]:
    """Register handlers on a mock bolt app and return captured handlers."""
    handlers: dict[str, Any] = {}

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
    return handlers


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
    """Return a mock GoogleDocsService that captures inserted content."""
    svc = MagicMock(spec=["create_document", "insert_content", "get_content"])
    svc.create_document = AsyncMock(return_value="doc-rt-123")
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
# Full round-trip: start_edit → sync_from_doc
# ---------------------------------------------------------------------------


class TestEditRoundTrip:
    """Integration tests chaining start_edit and sync_from_doc."""

    async def test_system_prompt_round_trip(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """start_edit → user edits → sync_from_doc returns updated config."""
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            url = await editor.start_edit("test-process", "system")

        assert "doc-rt-123" in url

        # Capture what was written to the doc during start_edit
        inserted = mock_docs.insert_content.call_args[0][1]
        assert _HEADER_END in inserted
        assert "You are a test system." in inserted

        # Simulate user editing the prompt in Google Docs
        edited_content = inserted.replace(
            "You are a test system.",
            "You are an IMPROVED test system with new instructions.",
        )
        mock_docs.get_content.return_value = edited_content

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.prompts.system == "You are an IMPROVED test system with new instructions."
        assert config.metadata.version == 2
        assert config.metadata.last_synced_at is not None
        assert config.metadata.google_doc_id is None

    async def test_instruction_prompt_round_trip(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Round-trip for instruction field preserves edits."""
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "instruction")

        inserted = mock_docs.insert_content.call_args[0][1]
        edited = inserted.replace(
            "Follow test instructions.",
            "Follow updated instructions carefully.",
        )
        mock_docs.get_content.return_value = edited

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.prompts.instruction == "Follow updated instructions carefully."
        assert config.prompts.system == "You are a test system."  # unchanged

    async def test_version_increments_across_multiple_round_trips(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Version bumps correctly over two edit-sync cycles."""
        _write_config(tmp_path)

        # First round-trip: v1 → v2
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        inserted_1 = mock_docs.insert_content.call_args[0][1]
        mock_docs.get_content.return_value = inserted_1.replace(
            "You are a test system.", "Edit 1."
        )
        mock_docs.create_document.return_value = "doc-rt-456"

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config_1 = await editor.sync_from_doc("test-process")

        assert config_1.metadata.version == 2

        # Second round-trip: v2 → v3
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        inserted_2 = mock_docs.insert_content.call_args[0][1]
        assert "Version: 2" in inserted_2
        mock_docs.get_content.return_value = inserted_2.replace("Edit 1.", "Edit 2.")

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config_2 = await editor.sync_from_doc("test-process")

        assert config_2.metadata.version == 3
        assert config_2.prompts.system == "Edit 2."

    async def test_round_trip_persists_to_disk(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Full round-trip writes correct JSON to disk at each step."""
        _write_config(tmp_path)

        # After start_edit: doc_id saved
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        saved_mid = _read_saved_config(tmp_path)
        assert saved_mid["metadata"]["googleDocId"] == "doc-rt-123"

        # After sync: doc_id cleared, content updated
        inserted = mock_docs.insert_content.call_args[0][1]
        mock_docs.get_content.return_value = inserted.replace(
            "You are a test system.", "Final prompt."
        )

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.sync_from_doc("test-process")

        saved_final = _read_saved_config(tmp_path)
        assert saved_final["metadata"]["googleDocId"] is None
        assert saved_final["prompts"]["system"] == "Final prompt."
        assert saved_final["metadata"]["version"] == 2


# ---------------------------------------------------------------------------
# Plain-text preservation through round-trip
# ---------------------------------------------------------------------------


class TestPlainTextPreservation:
    """Verify that markdown-like syntax and template tokens survive round-trip.

    The prompt editor stores content as plain text in Google Docs.  If the
    Doc API ever converts characters (e.g., smart quotes, auto-formatting),
    prompts with markdown syntax, template variables, or marker tokens would
    silently break.  These tests catch that by verifying content is unchanged
    after start_edit → sync_from_doc.
    """

    @pytest.mark.parametrize(
        "prompt_content",
        [
            # Markdown heading and bold
            "# Section Heading\n\n**Bold text** and *italic text*.",
            # Curly-brace template variables (used in prompt interpolation)
            "Generate content for {feedback_section}.\nUse {article_count} articles.",
            # Marker tokens (%XX_ prefixes from theme generation)
            "%FA_TITLE: The Rise of AI\n%M1_SOURCE: 3\n%Q1_BLURB: Quick summary.",
            # Code blocks and backticks
            "Use `json.loads()` to parse.\n\n```python\ndef foo():\n    pass\n```",
            # HTML-like angle brackets
            "Output format: <section>\n  <title>Newsletter</title>\n</section>",
            # Special characters: pipes, brackets, parentheses
            "| Column A | Column B |\n|----------|----------|\n(see [docs](link))",
            # Mixed: real-world prompt excerpt
            (
                "You are a newsletter editor.\n\n"
                "## Rules\n"
                "1. Keep summaries under {max_chars} characters\n"
                "2. Use **active voice**\n"
                "3. Format: %FA_TITLE: <title>\n"
                "4. Escape `{braces}` when literal\n"
            ),
        ],
        ids=[
            "markdown_heading_bold",
            "curly_brace_templates",
            "marker_tokens",
            "code_blocks_backticks",
            "html_angle_brackets",
            "pipes_brackets_parens",
            "mixed_real_world",
        ],
    )
    async def test_prompt_content_survives_round_trip(
        self,
        prompt_content: str,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Prompt content with special syntax is unchanged after round-trip."""
        _write_config(
            tmp_path,
            prompts={
                "system": prompt_content,
                "instruction": "Follow test instructions.",
            },
        )
        editor = PromptEditorService(mock_docs)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        # Feed back exactly what was written (unmodified round-trip)
        inserted = mock_docs.insert_content.call_args[0][1]
        mock_docs.get_content.return_value = inserted

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.prompts.system == prompt_content

    async def test_multiline_instruction_with_markers_preserved(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Multi-line instruction prompt with marker tokens round-trips cleanly."""
        instruction = (
            "Generate themed content using these markers:\n\n"
            "%FA_TITLE: {featured_title}\n"
            "%FA_SOURCE: {featured_source}\n"
            "%M1_TITLE: Main article 1\n"
            "%M2_TITLE: Main article 2\n"
            "%Q1_BLURB: Quick highlight\n"
            "%I1_SECTION: Industry insight\n"
            "%RV_VERIFIED: Verified resource\n\n"
            "Rules:\n"
            "- Keep **all markers** on their own line\n"
            "- Do NOT modify the `%XX_` prefix format\n"
        )
        _write_config(
            tmp_path,
            prompts={
                "system": "You are a test system.",
                "instruction": instruction,
            },
        )

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "instruction")

        inserted = mock_docs.insert_content.call_args[0][1]
        mock_docs.get_content.return_value = inserted

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = await editor.sync_from_doc("test-process")

        assert config.prompts.instruction == instruction


# ---------------------------------------------------------------------------
# Concurrent edit detection
# ---------------------------------------------------------------------------


class TestConcurrentEditDetection:
    """Verify metadata tracks active edits and warns on overlap."""

    async def test_start_edit_logs_warning_when_replacing_session(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Starting a new edit while one is active logs a warning."""
        _write_config(
            tmp_path,
            metadata={"googleDocId": "old-doc-id", "lastSyncedAt": None, "version": 1},
        )

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch("ica.services.prompt_editor.logger") as mock_logger,
        ):
            url = await editor.start_edit("test-process", "system")

        assert "doc-rt-123" in url
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert "Replacing existing edit session" in call_kwargs[0][0]
        assert call_kwargs[1]["extra"]["old_doc_id"] == "old-doc-id"

    async def test_summary_shows_active_edit_after_start(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After start_edit, get_config_summary reports active edit."""
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")
            summary = editor.get_config_summary("test-process")

        assert "Active edit: Yes" in summary

    async def test_summary_shows_no_active_edit_after_sync(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After sync_from_doc, active edit is cleared."""
        _write_config(tmp_path)

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.start_edit("test-process", "system")

        inserted = mock_docs.insert_content.call_args[0][1]
        mock_docs.get_content.return_value = inserted

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await editor.sync_from_doc("test-process")
            summary = editor.get_config_summary("test-process")

        assert "Active edit: No" in summary

    async def test_no_warning_on_first_edit(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Starting an edit with no prior session does not warn."""
        _write_config(tmp_path)

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch("ica.services.prompt_editor.logger") as mock_logger,
        ):
            await editor.start_edit("test-process", "system")

        mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Model change via Slack form (direct, no Google Docs)
# ---------------------------------------------------------------------------


class TestModelChangeViaSlackForm:
    """End-to-end model editing through the Slack modal flow."""

    async def test_model_change_through_modal_submission(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Full flow: register → modal submit with edit_model → config updated."""
        _write_config(tmp_path)

        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values(
                        "test-process",
                        ACTION_EDIT_MODEL,
                        model_id="openai/gpt-4.1",
                    ),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await handler(ack=ack, body=body, client=mock_client)

        ack.assert_awaited_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "Updated" in call_kwargs["text"]
        assert "openai/gpt-4.1" in call_kwargs["text"]

        # Verify disk was updated
        saved = _read_saved_config(tmp_path)
        assert saved["model"] == "openai/gpt-4.1"
        assert saved["metadata"]["version"] == 2
        assert saved["metadata"]["lastSyncedAt"] is not None

    async def test_model_change_does_not_touch_google_doc_metadata(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Model update doesn't create or modify Google Doc references."""
        _write_config(tmp_path)

        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values(
                        "test-process",
                        ACTION_EDIT_MODEL,
                        model_id="google/gemini-2.5-flash",
                    ),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await handler(ack=ack, body=body, client=mock_client)

        saved = _read_saved_config(tmp_path)
        assert saved["metadata"]["googleDocId"] is None

    async def test_model_change_rejects_empty_model_id(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
    ) -> None:
        """Modal submission with empty model ID posts error message."""
        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values(
                        "test-process", ACTION_EDIT_MODEL, model_id=""
                    ),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        await handler(ack=ack, body=body, client=mock_client)

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "provide a Model ID" in call_kwargs["text"]


# ---------------------------------------------------------------------------
# Full Slack interaction handler flows
# ---------------------------------------------------------------------------


class TestSlackInteractionHandlers:
    """End-to-end Slack flows with mocked Slack client and Google Docs."""

    async def test_trigger_opens_modal_with_processes(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Button click opens modal listing available processes."""
        (tmp_path / "summarization-llm.json").write_text("{}")
        (tmp_path / "html-generation-llm.json").write_text("{}")

        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)

        with patch(
            "ica.services.slack_config_handlers.get_available_processes",
            return_value=["html-generation", "summarization"],
        ):
            register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {"trigger_id": "trigger-456"}
        handler = handlers[f"action:{ACTION_CONFIG_TRIGGER}"]
        await handler(ack=ack, body=body, client=mock_client)

        ack.assert_awaited_once()
        mock_client.views_open.assert_awaited_once()
        view = mock_client.views_open.call_args[1]["view"]
        assert view["type"] == "modal"
        assert view["callback_id"] == VIEW_CONFIG_MODAL

    async def test_sync_from_doc_via_slack(
        self,
        editor: PromptEditorService,
        mock_docs: MagicMock,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Full Slack flow for sync_from_doc: modal submit → config synced."""
        _write_config(
            tmp_path,
            metadata={"googleDocId": "doc-sync", "lastSyncedAt": None, "version": 3},
        )
        header = _build_edit_header("test-process", "system", 3)
        mock_docs.get_content.return_value = header + "Synced prompt from Slack."

        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values("test-process", ACTION_SYNC_FROM_DOC),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await handler(ack=ack, body=body, client=mock_client)

        ack.assert_awaited_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "Synced" in call_kwargs["text"]
        assert "v4" in call_kwargs["text"]

        saved = _read_saved_config(tmp_path)
        assert saved["prompts"]["system"] == "Synced prompt from Slack."
        assert saved["metadata"]["version"] == 4
        assert saved["metadata"]["googleDocId"] is None

    async def test_view_summary_via_slack(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Full Slack flow for view_summary: modal submit → summary posted."""
        _write_config(tmp_path)

        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values("test-process", ACTION_VIEW_SUMMARY),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            await handler(ack=ack, body=body, client=mock_client)

        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "*test-process*" in call_kwargs["text"]
        assert "anthropic/claude-sonnet-4.5" in call_kwargs["text"]
        assert "Version: 1" in call_kwargs["text"]

    async def test_error_in_action_posts_failure_message(
        self,
        editor: PromptEditorService,
        mock_client: AsyncMock,
    ) -> None:
        """Exception during dispatch posts error to Slack channel."""
        bolt_app = MagicMock()
        handlers = _capture_handlers(bolt_app)
        register_config_handlers(bolt_app, editor, "#test")

        ack = AsyncMock()
        body = {
            "view": {
                "state": {
                    "values": _make_state_values(
                        "nonexistent-process", ACTION_SYNC_FROM_DOC
                    ),
                },
            },
        }

        handler = handlers[f"view:{VIEW_CONFIG_MODAL}"]
        await handler(ack=ack, body=body, client=mock_client)

        ack.assert_awaited_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "failed" in call_kwargs["text"].lower()
