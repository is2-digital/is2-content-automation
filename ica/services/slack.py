"""Slack service wrapping Slack Bolt for interactive pipeline interactions.

Provides a single :class:`SlackService` that satisfies all Slack protocol
contracts used throughout the pipeline:

* :class:`~ica.pipeline.article_curation.SlackNotifier` — plain-text messages
* :class:`~ica.pipeline.article_curation.SlackApprovalSender` — approval buttons
* :class:`~ica.pipeline.summarization.SlackManualFallback` — free-text modals
* :class:`~ica.pipeline.summarization.SlackSummaryReview` — channel messages,
  form modals, and free-text modals
* :class:`~ica.errors.SlackErrorNotifier` — error notifications

The core primitive is :meth:`SlackService.send_and_wait`, which implements
the n8n ``sendAndWait`` blocking pattern:

1. Post a Slack message with an interactive button.
2. Register an ``asyncio.Event`` keyed by a unique callback ID.
3. When the user clicks the button, Slack Bolt routes the interaction
   payload to :meth:`_handle_action`.
4. For approval buttons, the event is resolved immediately.
5. For form/freetext buttons, a modal is opened; on submission the
   event is resolved with the form data.

Usage::

    from ica.services.slack import SlackService

    svc = SlackService(token="xoxb-...", channel="#n8n-is2")
    svc.register_handlers(bolt_app)

    await svc.send_message("#n8n-is2", "Hello!")
    await svc.send_and_wait("#n8n-is2", "Ready?", approve_label="Go")
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

from ica.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Action ID prefixes — used to route Slack interaction payloads
# ---------------------------------------------------------------------------

_PREFIX_APPROVE = "ica_approve_"
_PREFIX_TRIGGER = "ica_trigger_"
_PREFIX_MODAL = "ica_modal_"


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


@dataclass
class _PendingInteraction:
    """Tracks a single send-and-wait interaction."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    response: dict[str, str] = field(default_factory=dict)
    interaction_type: str = "approval"  # "approval" | "form" | "freetext"
    form_fields: list[dict[str, object]] | None = None
    form_title: str = ""
    form_description: str = ""


# ---------------------------------------------------------------------------
# Block Kit helpers
# ---------------------------------------------------------------------------


def _text_block(text: str) -> dict[str, object]:
    """Build a ``section`` block with mrkdwn text."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button_block(
    label: str,
    action_id: str,
    *,
    style: str = "primary",
) -> dict[str, object]:
    """Build an ``actions`` block containing a single button."""
    button: dict[str, object] = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
    }
    if style:
        button["style"] = style
    return {"type": "actions", "elements": [button]}


def _build_approval_blocks(
    text: str,
    callback_id: str,
    approve_label: str,
) -> list[dict[str, object]]:
    """Build Block Kit blocks for an approval message."""
    blocks: list[dict[str, object]] = [_text_block(text)]
    blocks.append(_button_block(approve_label, f"{_PREFIX_APPROVE}{callback_id}"))
    return blocks


def _build_trigger_blocks(
    text: str,
    callback_id: str,
    button_label: str,
) -> list[dict[str, object]]:
    """Build Block Kit blocks for a form/freetext trigger message."""
    blocks: list[dict[str, object]] = [_text_block(text)]
    blocks.append(_button_block(button_label, f"{_PREFIX_TRIGGER}{callback_id}"))
    return blocks


def _build_modal_blocks(
    form_fields: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Convert n8n-style form field definitions to Slack modal input blocks.

    Each field dict should have:
    - ``fieldLabel`` (str): label text
    - ``fieldType`` (str): ``"dropdown"`` | ``"text"`` | ``"textarea"``
    - ``fieldOptions`` (list, optional): for dropdowns — each with ``option`` key
    - ``requiredField`` (bool, optional): default True
    """
    blocks: list[dict[str, object]] = []
    for idx, f in enumerate(form_fields):
        block_id = f"field_{idx}"
        action_id = f"field_{idx}_action"
        label = str(f.get("fieldLabel", f"Field {idx}"))
        field_type = str(f.get("fieldType", "text"))
        required = bool(f.get("requiredField", True))

        if field_type == "dropdown":
            options_raw = f.get("fieldOptions", [])
            options = []
            for opt in options_raw:  # type: ignore[attr-defined]
                opt_text = str(opt.get("option", "")) if isinstance(opt, dict) else str(opt)
                options.append(
                    {
                        "text": {"type": "plain_text", "text": opt_text},
                        "value": opt_text,
                    }
                )
            element: dict[str, object] = {
                "type": "static_select",
                "action_id": action_id,
                "placeholder": {"type": "plain_text", "text": f"Select {label}"},
            }
            if options:
                element["options"] = options
            blocks.append(
                {
                    "type": "input",
                    "block_id": block_id,
                    "optional": not required,
                    "label": {"type": "plain_text", "text": label},
                    "element": element,
                }
            )
        elif field_type == "textarea":
            blocks.append(
                {
                    "type": "input",
                    "block_id": block_id,
                    "optional": not required,
                    "label": {"type": "plain_text", "text": label},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": action_id,
                        "multiline": True,
                    },
                }
            )
        else:
            # Default: single-line text input
            blocks.append(
                {
                    "type": "input",
                    "block_id": block_id,
                    "optional": not required,
                    "label": {"type": "plain_text", "text": label},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": action_id,
                        "multiline": False,
                    },
                }
            )

    return blocks


def _build_freetext_modal_blocks(
    description: str,
) -> list[dict[str, object]]:
    """Build modal blocks for a single free-text input."""
    blocks: list[dict[str, object]] = []
    if description:
        blocks.append(_text_block(description))
    blocks.append(
        {
            "type": "input",
            "block_id": "freetext_block",
            "label": {"type": "plain_text", "text": "Your response"},
            "element": {
                "type": "plain_text_input",
                "action_id": "freetext_action",
                "multiline": True,
            },
        }
    )
    return blocks


def _extract_modal_values(
    state_values: dict[str, dict[str, Any]],
    form_fields: list[dict[str, object]] | None,
) -> dict[str, str]:
    """Extract form values from a Slack modal submission.

    Maps each field's label to the submitted value.
    """
    result: dict[str, str] = {}
    if form_fields is None:
        return result

    for idx, f in enumerate(form_fields):
        block_id = f"field_{idx}"
        action_id = f"field_{idx}_action"
        label = str(f.get("fieldLabel", f"Field {idx}"))

        block_data = state_values.get(block_id, {})
        action_data = block_data.get(action_id, {})
        action_type = action_data.get("type", "")

        if action_type == "static_select":
            selected = action_data.get("selected_option")
            result[label] = selected["value"] if selected else ""
        else:
            result[label] = action_data.get("value", "")

    return result


# ---------------------------------------------------------------------------
# SlackService
# ---------------------------------------------------------------------------


class SlackService:
    """Unified Slack service for all pipeline interactions.

    Wraps ``slack_sdk.AsyncWebClient`` and provides methods matching every
    Slack protocol used by the pipeline steps.

    Args:
        token: Slack Bot OAuth token (``xoxb-...``).
        channel: Default channel for messages (e.g. ``"#n8n-is2"``).
    """

    def __init__(self, *, token: str, channel: str) -> None:
        self._client = AsyncWebClient(token=token)
        self._channel = channel
        self._pending: dict[str, _PendingInteraction] = {}

    @property
    def client(self) -> AsyncWebClient:
        """The underlying ``AsyncWebClient`` (exposed for testing)."""
        return self._client

    @property
    def channel(self) -> str:
        """The default Slack channel."""
        return self._channel

    @property
    def pending(self) -> dict[str, _PendingInteraction]:
        """Pending interactions (exposed for testing)."""
        return self._pending

    # ------------------------------------------------------------------
    # Protocol: SlackNotifier
    # ------------------------------------------------------------------

    async def send_message(self, channel: str, text: str) -> None:
        """Post a plain-text message to *channel*.

        Satisfies :class:`~ica.pipeline.article_curation.SlackNotifier`.
        """
        await self._client.chat_postMessage(channel=channel, text=text)
        logger.info("Sent message to %s", channel)

    # ------------------------------------------------------------------
    # Protocol: SlackSummaryReview.send_channel_message
    # ------------------------------------------------------------------

    async def send_channel_message(
        self,
        text: str,
        *,
        blocks: list[dict[str, object]] | None = None,
    ) -> None:
        """Post a message (with optional Block Kit blocks) to the default channel.

        Satisfies :meth:`~ica.pipeline.summarization.SlackSummaryReview.send_channel_message`.
        """
        kwargs: dict[str, Any] = {"channel": self._channel, "text": text}
        if blocks is not None:
            kwargs["blocks"] = blocks
        await self._client.chat_postMessage(**kwargs)
        logger.info("Sent channel message to %s", self._channel)

    # ------------------------------------------------------------------
    # Protocol: SlackErrorNotifier
    # ------------------------------------------------------------------

    async def send_error(self, message: str) -> None:
        """Post an error notification to the default channel.

        Satisfies :class:`~ica.errors.SlackErrorNotifier`.
        """
        await self._client.chat_postMessage(channel=self._channel, text=message)
        logger.info("Sent error notification to %s", self._channel)

    # ------------------------------------------------------------------
    # Protocol: SlackApprovalSender
    # ------------------------------------------------------------------

    async def send_and_wait(
        self,
        channel: str,
        text: str,
        *,
        approve_label: str = "Proceed to next steps",
    ) -> None:
        """Post an approval button and block until the user clicks it.

        Satisfies :class:`~ica.pipeline.article_curation.SlackApprovalSender`.

        Args:
            channel: Target Slack channel.
            text: Message text displayed above the button.
            approve_label: Button label text.
        """
        callback_id = uuid.uuid4().hex[:12]
        pending = _PendingInteraction(interaction_type="approval")
        self._pending[callback_id] = pending

        blocks = _build_approval_blocks(text, callback_id, approve_label)
        await self._client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=blocks,
        )
        logger.info("Sent approval request to %s (callback=%s)", channel, callback_id)

        try:
            await pending.event.wait()
        finally:
            self._pending.pop(callback_id, None)

    # ------------------------------------------------------------------
    # Protocol: SlackSummaryReview.send_and_wait_form
    # ------------------------------------------------------------------

    async def send_and_wait_form(
        self,
        message: str,
        *,
        form_fields: list[dict[str, object]],
        button_label: str = "Proceed to Next Steps",
        form_title: str = "Proceed to next step",
        form_description: str = "",
    ) -> dict[str, str]:
        """Post a form trigger button and block until the user submits the modal.

        Satisfies :meth:`~ica.pipeline.summarization.SlackSummaryReview.send_and_wait_form`.

        Args:
            message: Message text displayed above the button.
            form_fields: n8n-style form field definitions.
            button_label: Trigger button label.
            form_title: Modal title.
            form_description: Optional description in the modal.

        Returns:
            Dict mapping field labels to submitted values.
        """
        callback_id = uuid.uuid4().hex[:12]
        pending = _PendingInteraction(
            interaction_type="form",
            form_fields=form_fields,
            form_title=form_title,
            form_description=form_description,
        )
        self._pending[callback_id] = pending

        blocks = _build_trigger_blocks(message, callback_id, button_label)
        await self._client.chat_postMessage(
            channel=self._channel,
            text=message,
            blocks=blocks,
        )
        logger.info("Sent form trigger to %s (callback=%s)", self._channel, callback_id)

        try:
            await pending.event.wait()
            return dict(pending.response)
        finally:
            self._pending.pop(callback_id, None)

    # ------------------------------------------------------------------
    # Protocol: SlackManualFallback + SlackSummaryReview.send_and_wait_freetext
    # ------------------------------------------------------------------

    async def send_and_wait_freetext(
        self,
        message: str,
        *,
        button_label: str = "Add feedback",
        form_title: str = "Feedback Form",
        form_description: str = "",
    ) -> str:
        """Post a freetext trigger button and block until the user submits text.

        Satisfies both :class:`~ica.pipeline.summarization.SlackManualFallback`
        and :meth:`~ica.pipeline.summarization.SlackSummaryReview.send_and_wait_freetext`.

        Args:
            message: Message text displayed above the button.
            button_label: Trigger button label.
            form_title: Modal title.
            form_description: Optional description in the modal.

        Returns:
            The text entered by the user.
        """
        callback_id = uuid.uuid4().hex[:12]
        pending = _PendingInteraction(
            interaction_type="freetext",
            form_title=form_title,
            form_description=form_description,
        )
        self._pending[callback_id] = pending

        blocks = _build_trigger_blocks(message, callback_id, button_label)
        await self._client.chat_postMessage(
            channel=self._channel,
            text=message,
            blocks=blocks,
        )
        logger.info("Sent freetext trigger to %s (callback=%s)", self._channel, callback_id)

        try:
            await pending.event.wait()
            return pending.response.get("text", "")
        finally:
            self._pending.pop(callback_id, None)

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handlers(self, bolt_app: Any) -> None:
        """Register Slack Bolt action and view handlers.

        Must be called once after creating the Bolt app so that button
        clicks and modal submissions are routed to this service.

        Args:
            bolt_app: A ``slack_bolt.async_app.AsyncApp`` instance.
        """
        import re

        # Handle approval button clicks
        bolt_app.action(re.compile(f"^{re.escape(_PREFIX_APPROVE)}"))(self._handle_approve)

        # Handle form/freetext trigger button clicks
        bolt_app.action(re.compile(f"^{re.escape(_PREFIX_TRIGGER)}"))(self._handle_trigger)

        # Handle modal submissions
        bolt_app.view(re.compile(f"^{re.escape(_PREFIX_MODAL)}"))(self._handle_view_submission)

        logger.info("Registered Slack interaction handlers")

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _handle_approve(self, ack: Any, body: dict[str, Any]) -> None:
        """Handle an approval button click — resolve the pending event."""
        await ack()

        action = body.get("actions", [{}])[0]
        action_id: str = action.get("action_id", "")
        callback_id = action_id.removeprefix(_PREFIX_APPROVE)

        pending = self._pending.get(callback_id)
        if pending is None:
            logger.warning("No pending interaction for callback_id=%s", callback_id)
            return

        logger.info("Approval received (callback=%s)", callback_id)
        pending.event.set()

    async def _handle_trigger(self, ack: Any, body: dict[str, Any]) -> None:
        """Handle a form/freetext trigger button — open a modal."""
        await ack()

        action = body.get("actions", [{}])[0]
        action_id: str = action.get("action_id", "")
        callback_id = action_id.removeprefix(_PREFIX_TRIGGER)
        trigger_id = body.get("trigger_id", "")

        pending = self._pending.get(callback_id)
        if pending is None:
            logger.warning("No pending interaction for callback_id=%s", callback_id)
            return

        # Build modal view
        modal_callback_id = f"{_PREFIX_MODAL}{callback_id}"
        title_text = pending.form_title or "Submit Response"
        # Slack modal titles are limited to 24 characters
        if len(title_text) > 24:
            title_text = title_text[:24]

        if pending.interaction_type == "form" and pending.form_fields:
            modal_blocks = _build_modal_blocks(pending.form_fields)
        else:
            modal_blocks = _build_freetext_modal_blocks(pending.form_description)

        view: dict[str, object] = {
            "type": "modal",
            "callback_id": modal_callback_id,
            "private_metadata": callback_id,
            "title": {"type": "plain_text", "text": title_text},
            "submit": {"type": "plain_text", "text": "Submit"},
            "blocks": modal_blocks,
        }

        await self._client.views_open(trigger_id=trigger_id, view=view)
        logger.info(
            "Opened modal for callback=%s (type=%s)", callback_id, pending.interaction_type
        )

    async def _handle_view_submission(self, ack: Any, body: dict[str, Any]) -> None:
        """Handle a modal form submission — extract values and resolve event."""
        await ack()

        view = body.get("view", {})
        callback_id = view.get("private_metadata", "")
        state_values = view.get("state", {}).get("values", {})

        pending = self._pending.get(callback_id)
        if pending is None:
            logger.warning("No pending interaction for callback_id=%s", callback_id)
            return

        if pending.interaction_type == "freetext":
            # Extract the single freetext value
            freetext_block = state_values.get("freetext_block", {})
            freetext_action = freetext_block.get("freetext_action", {})
            pending.response["text"] = freetext_action.get("value", "")
        else:
            # Extract form field values
            pending.response.update(_extract_modal_values(state_values, pending.form_fields))

        logger.info(
            "Modal submitted (callback=%s, type=%s, fields=%d)",
            callback_id,
            pending.interaction_type,
            len(pending.response),
        )
        pending.event.set()
