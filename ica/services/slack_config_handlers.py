"""Slack handlers for LLM config editing via the prompt editor.

Provides :func:`register_config_handlers` which wires Slack Bolt action
and view handlers to allow users to browse, inspect, and edit LLM process
configurations from within Slack.

Flow:

1. A trigger button (``ica_config_trigger``) opens a modal.
2. The modal presents a **process** dropdown (all available JSON configs)
   and an **action** dropdown (edit system, edit instruction, view summary,
   sync from doc).
3. On submission, the selected action is dispatched to the
   :class:`~ica.services.prompt_editor.PromptEditorService`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ica.logging import get_logger
from ica.services.prompt_editor import PromptEditorService

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Action / callback IDs
# ---------------------------------------------------------------------------

ACTION_CONFIG_TRIGGER = "ica_config_trigger"
VIEW_CONFIG_MODAL = "ica_config_modal"

# ---------------------------------------------------------------------------
# Action choices
# ---------------------------------------------------------------------------

ACTION_EDIT_SYSTEM = "edit_system"
ACTION_EDIT_INSTRUCTION = "edit_instruction"
ACTION_EDIT_MODEL = "edit_model"
ACTION_VIEW_SUMMARY = "view_summary"
ACTION_SYNC_FROM_DOC = "sync_from_doc"

_ACTIONS: list[tuple[str, str]] = [
    (ACTION_EDIT_SYSTEM, "Edit System Prompt"),
    (ACTION_EDIT_INSTRUCTION, "Edit Instruction Prompt"),
    (ACTION_EDIT_MODEL, "Edit Model"),
    (ACTION_VIEW_SUMMARY, "View Summary"),
    (ACTION_SYNC_FROM_DOC, "Sync from Doc"),
]


# ---------------------------------------------------------------------------
# Process discovery
# ---------------------------------------------------------------------------


def get_available_processes(configs_dir: Path | None = None) -> list[str]:
    """Return sorted list of available process names from JSON config files.

    Each ``*-llm.json`` file in the configs directory yields one process
    name (the filename stem minus the ``-llm`` suffix).

    Args:
        configs_dir: Override the default configs directory (for testing).
    """
    if configs_dir is None:
        from ica.llm_configs.loader import _CONFIGS_DIR

        configs_dir = _CONFIGS_DIR

    return sorted(
        path.stem.removesuffix("-llm")
        for path in configs_dir.glob("*-llm.json")
    )


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------


def build_config_menu_blocks() -> list[dict[str, object]]:
    """Build Block Kit blocks for the config editor trigger message."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*LLM Config Editor*\n"
                    "Manage process prompts and view configuration details."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Config Editor"},
                    "action_id": ACTION_CONFIG_TRIGGER,
                    "style": "primary",
                },
            ],
        },
    ]


def build_config_modal(
    configs_dir: Path | None = None,
) -> dict[str, object]:
    """Build the modal view with process and action dropdowns.

    Args:
        configs_dir: Override the default configs directory (for testing).
    """
    processes = get_available_processes(configs_dir)

    process_options = [
        {
            "text": {"type": "plain_text", "text": name},
            "value": name,
        }
        for name in processes
    ]

    action_options = [
        {
            "text": {"type": "plain_text", "text": label},
            "value": value,
        }
        for value, label in _ACTIONS
    ]

    return {
        "type": "modal",
        "callback_id": VIEW_CONFIG_MODAL,
        "title": {"type": "plain_text", "text": "Config Editor"},
        "submit": {"type": "plain_text", "text": "Go"},
        "blocks": [
            {
                "type": "input",
                "block_id": "process_block",
                "label": {"type": "plain_text", "text": "Process"},
                "element": {
                    "type": "static_select",
                    "action_id": "process_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a process",
                    },
                    "options": process_options,
                },
            },
            {
                "type": "input",
                "block_id": "action_block",
                "label": {"type": "plain_text", "text": "Action"},
                "element": {
                    "type": "static_select",
                    "action_id": "action_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select an action",
                    },
                    "options": action_options,
                },
            },
            {
                "type": "input",
                "block_id": "model_block",
                "label": {"type": "plain_text", "text": "Model ID"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "model_input",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. anthropic/claude-sonnet-4.5",
                    },
                },
                "hint": {
                    "type": "plain_text",
                    "text": "Only used with Edit Model action.",
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Modal submission helpers
# ---------------------------------------------------------------------------


def extract_config_modal_values(
    state_values: dict[str, dict[str, Any]],
) -> tuple[str, str, str]:
    """Extract process name, action, and model ID from config modal state values.

    Returns:
        Tuple of ``(process_name, action_value, model_id)``.
        ``model_id`` is empty string when not provided.
    """
    process_data = state_values.get("process_block", {}).get("process_select", {})
    selected_process = process_data.get("selected_option")
    process_name = selected_process.get("value", "") if selected_process else ""

    action_data = state_values.get("action_block", {}).get("action_select", {})
    selected_action = action_data.get("selected_option")
    action_value = selected_action.get("value", "") if selected_action else ""

    model_data = state_values.get("model_block", {}).get("model_input", {})
    model_id = model_data.get("value") or ""

    return process_name, action_value, model_id


async def dispatch_config_action(
    editor: PromptEditorService,
    client: Any,
    channel: str,
    process_name: str,
    action_value: str,
    *,
    model_id: str = "",
) -> None:
    """Execute the config action and post a result message.

    Args:
        editor: The prompt editor service.
        client: Slack ``AsyncWebClient``.
        channel: Channel to post results to.
        process_name: Selected process name.
        action_value: One of the ``ACTION_*`` constants.
        model_id: New model identifier (only used with ``ACTION_EDIT_MODEL``).
    """
    if action_value == ACTION_EDIT_SYSTEM:
        url = await editor.start_edit(process_name, "system")
        await client.chat_postMessage(
            channel=channel,
            text=f"Edit *{process_name}* system prompt:\n<{url}>",
        )
    elif action_value == ACTION_EDIT_INSTRUCTION:
        url = await editor.start_edit(process_name, "instruction")
        await client.chat_postMessage(
            channel=channel,
            text=f"Edit *{process_name}* instruction prompt:\n<{url}>",
        )
    elif action_value == ACTION_EDIT_MODEL:
        if not model_id.strip():
            await client.chat_postMessage(
                channel=channel,
                text="Please provide a Model ID when using Edit Model.",
            )
            return
        config = editor.update_model(process_name, model_id)
        await client.chat_postMessage(
            channel=channel,
            text=(
                f"Updated *{process_name}* model to `{config.model}` "
                f"(v{config.metadata.version})."
            ),
        )
    elif action_value == ACTION_VIEW_SUMMARY:
        summary = editor.get_config_summary(process_name)
        await client.chat_postMessage(channel=channel, text=summary)
    elif action_value == ACTION_SYNC_FROM_DOC:
        config = await editor.sync_from_doc(process_name)
        await client.chat_postMessage(
            channel=channel,
            text=(
                f"Synced *{process_name}* from Google Doc "
                f"(v{config.metadata.version})."
            ),
        )
    else:
        await client.chat_postMessage(
            channel=channel,
            text=f"Unknown action: {action_value}",
        )


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


def register_config_handlers(
    bolt_app: Any,
    editor: PromptEditorService,
    channel: str,
) -> None:
    """Register Slack Bolt handlers for the config editing flow.

    Must be called once at app startup after the Bolt app is created.

    Args:
        bolt_app: A ``slack_bolt.async_app.AsyncApp`` instance.
        editor: A :class:`PromptEditorService` for prompt editing.
        channel: Slack channel to post result messages to.
    """

    async def _handle_config_trigger(
        ack: Any, body: dict[str, Any], client: Any
    ) -> None:
        """Open the config editor modal when the trigger button is clicked."""
        await ack()
        trigger_id = body.get("trigger_id", "")
        view = build_config_modal()
        await client.views_open(trigger_id=trigger_id, view=view)
        logger.info("Opened config editor modal")

    async def _handle_config_modal(
        ack: Any, body: dict[str, Any], client: Any
    ) -> None:
        """Handle config modal submission — dispatch the selected action."""
        await ack()

        view = body.get("view", {})
        state_values = view.get("state", {}).get("values", {})
        process_name, action_value, model_id = extract_config_modal_values(
            state_values
        )

        if not process_name or not action_value:
            await client.chat_postMessage(
                channel=channel,
                text="Please select both a process and an action.",
            )
            return

        try:
            await dispatch_config_action(
                editor, client, channel, process_name, action_value,
                model_id=model_id,
            )
        except Exception as exc:
            logger.exception(
                "Config action failed: %s %s", action_value, process_name
            )
            await client.chat_postMessage(
                channel=channel,
                text=f"Config action failed: {exc}",
            )

    bolt_app.action(ACTION_CONFIG_TRIGGER)(_handle_config_trigger)
    bolt_app.view(VIEW_CONFIG_MODAL)(_handle_config_modal)

    logger.info("Registered config editing handlers")
