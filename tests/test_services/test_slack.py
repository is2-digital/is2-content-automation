"""Tests for ica.services.slack."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.services.slack import (
    SlackService,
    _PendingInteraction,
    _PREFIX_APPROVE,
    _PREFIX_MODAL,
    _PREFIX_TRIGGER,
    _build_approval_blocks,
    _build_freetext_modal_blocks,
    _build_modal_blocks,
    _build_trigger_blocks,
    _button_block,
    _extract_modal_values,
    _text_block,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Return a mocked AsyncWebClient."""
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True})
    client.views_open = AsyncMock(return_value={"ok": True})
    return client


@pytest.fixture()
def service(mock_client: AsyncMock) -> SlackService:
    """Return a SlackService with mocked client."""
    svc = SlackService(token="xoxb-test", channel="#test-channel")
    svc._client = mock_client
    return svc


# ===========================================================================
# Block Kit helper tests
# ===========================================================================


class TestTextBlock:
    """Tests for _text_block()."""

    def test_structure(self) -> None:
        block = _text_block("Hello")
        assert block["type"] == "section"
        assert block["text"]["type"] == "mrkdwn"
        assert block["text"]["text"] == "Hello"

    def test_preserves_formatting(self) -> None:
        block = _text_block("*bold* _italic_ `code`")
        assert block["text"]["text"] == "*bold* _italic_ `code`"

    def test_multiline(self) -> None:
        block = _text_block("line1\nline2\nline3")
        assert "line1\nline2\nline3" in block["text"]["text"]


class TestButtonBlock:
    """Tests for _button_block()."""

    def test_basic_button(self) -> None:
        block = _button_block("Click Me", "action_123")
        assert block["type"] == "actions"
        assert len(block["elements"]) == 1
        btn = block["elements"][0]
        assert btn["type"] == "button"
        assert btn["text"]["text"] == "Click Me"
        assert btn["action_id"] == "action_123"
        assert btn["style"] == "primary"

    def test_no_style(self) -> None:
        block = _button_block("Click", "act", style="")
        btn = block["elements"][0]
        assert "style" not in btn

    def test_custom_style(self) -> None:
        block = _button_block("Delete", "act", style="danger")
        btn = block["elements"][0]
        assert btn["style"] == "danger"


class TestBuildApprovalBlocks:
    """Tests for _build_approval_blocks()."""

    def test_has_text_and_button(self) -> None:
        blocks = _build_approval_blocks("Ready?", "cb1", "Approve")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert blocks[1]["type"] == "actions"

    def test_button_action_id(self) -> None:
        blocks = _build_approval_blocks("msg", "abc123", "Go")
        btn = blocks[1]["elements"][0]
        assert btn["action_id"] == f"{_PREFIX_APPROVE}abc123"

    def test_button_label(self) -> None:
        blocks = _build_approval_blocks("msg", "x", "Custom Label")
        btn = blocks[1]["elements"][0]
        assert btn["text"]["text"] == "Custom Label"

    def test_text_content(self) -> None:
        blocks = _build_approval_blocks("The message", "x", "Go")
        assert blocks[0]["text"]["text"] == "The message"


class TestBuildTriggerBlocks:
    """Tests for _build_trigger_blocks()."""

    def test_has_text_and_button(self) -> None:
        blocks = _build_trigger_blocks("Click to proceed", "cb2", "Submit")
        assert len(blocks) == 2

    def test_button_action_id(self) -> None:
        blocks = _build_trigger_blocks("msg", "def456", "Btn")
        btn = blocks[1]["elements"][0]
        assert btn["action_id"] == f"{_PREFIX_TRIGGER}def456"


class TestBuildModalBlocks:
    """Tests for _build_modal_blocks()."""

    def test_dropdown_field(self) -> None:
        fields = [{
            "fieldLabel": "Pick one",
            "fieldType": "dropdown",
            "fieldOptions": [{"option": "A"}, {"option": "B"}],
        }]
        blocks = _build_modal_blocks(fields)
        assert len(blocks) == 1
        block = blocks[0]
        assert block["type"] == "input"
        assert block["label"]["text"] == "Pick one"
        elem = block["element"]
        assert elem["type"] == "static_select"
        assert len(elem["options"]) == 2
        assert elem["options"][0]["value"] == "A"
        assert elem["options"][1]["value"] == "B"

    def test_textarea_field(self) -> None:
        fields = [{"fieldLabel": "Comments", "fieldType": "textarea"}]
        blocks = _build_modal_blocks(fields)
        elem = blocks[0]["element"]
        assert elem["type"] == "plain_text_input"
        assert elem["multiline"] is True

    def test_text_field(self) -> None:
        fields = [{"fieldLabel": "Name", "fieldType": "text"}]
        blocks = _build_modal_blocks(fields)
        elem = blocks[0]["element"]
        assert elem["type"] == "plain_text_input"
        assert elem["multiline"] is False

    def test_default_field_type(self) -> None:
        fields = [{"fieldLabel": "X"}]
        blocks = _build_modal_blocks(fields)
        assert blocks[0]["element"]["multiline"] is False

    def test_multiple_fields(self) -> None:
        fields = [
            {"fieldLabel": "A", "fieldType": "text"},
            {"fieldLabel": "B", "fieldType": "dropdown", "fieldOptions": [{"option": "X"}]},
            {"fieldLabel": "C", "fieldType": "textarea"},
        ]
        blocks = _build_modal_blocks(fields)
        assert len(blocks) == 3
        assert blocks[0]["block_id"] == "field_0"
        assert blocks[1]["block_id"] == "field_1"
        assert blocks[2]["block_id"] == "field_2"

    def test_optional_field(self) -> None:
        fields = [{"fieldLabel": "Optional", "requiredField": False}]
        blocks = _build_modal_blocks(fields)
        assert blocks[0]["optional"] is True

    def test_required_field_default(self) -> None:
        fields = [{"fieldLabel": "Required"}]
        blocks = _build_modal_blocks(fields)
        assert blocks[0]["optional"] is False

    def test_dropdown_empty_options(self) -> None:
        fields = [{"fieldLabel": "Empty", "fieldType": "dropdown", "fieldOptions": []}]
        blocks = _build_modal_blocks(fields)
        assert "options" not in blocks[0]["element"]

    def test_dropdown_placeholder(self) -> None:
        fields = [{"fieldLabel": "Color", "fieldType": "dropdown", "fieldOptions": [{"option": "Red"}]}]
        blocks = _build_modal_blocks(fields)
        placeholder = blocks[0]["element"]["placeholder"]
        assert placeholder["text"] == "Select Color"


class TestBuildFreetextModalBlocks:
    """Tests for _build_freetext_modal_blocks()."""

    def test_with_description(self) -> None:
        blocks = _build_freetext_modal_blocks("Please enter feedback")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert blocks[0]["text"]["text"] == "Please enter feedback"
        assert blocks[1]["type"] == "input"
        assert blocks[1]["block_id"] == "freetext_block"

    def test_without_description(self) -> None:
        blocks = _build_freetext_modal_blocks("")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "input"

    def test_textarea_element(self) -> None:
        blocks = _build_freetext_modal_blocks("")
        elem = blocks[0]["element"]
        assert elem["type"] == "plain_text_input"
        assert elem["action_id"] == "freetext_action"
        assert elem["multiline"] is True


class TestExtractModalValues:
    """Tests for _extract_modal_values()."""

    def test_dropdown_value(self) -> None:
        state = {
            "field_0": {
                "field_0_action": {
                    "type": "static_select",
                    "selected_option": {"value": "Option A"},
                },
            },
        }
        fields = [{"fieldLabel": "Pick", "fieldType": "dropdown"}]
        result = _extract_modal_values(state, fields)
        assert result == {"Pick": "Option A"}

    def test_text_value(self) -> None:
        state = {
            "field_0": {
                "field_0_action": {"type": "plain_text_input", "value": "hello"},
            },
        }
        fields = [{"fieldLabel": "Name", "fieldType": "text"}]
        result = _extract_modal_values(state, fields)
        assert result == {"Name": "hello"}

    def test_multiple_fields(self) -> None:
        state = {
            "field_0": {
                "field_0_action": {
                    "type": "static_select",
                    "selected_option": {"value": "Yes"},
                },
            },
            "field_1": {
                "field_1_action": {"type": "plain_text_input", "value": "notes"},
            },
        }
        fields = [
            {"fieldLabel": "Choice", "fieldType": "dropdown"},
            {"fieldLabel": "Notes", "fieldType": "textarea"},
        ]
        result = _extract_modal_values(state, fields)
        assert result == {"Choice": "Yes", "Notes": "notes"}

    def test_none_fields(self) -> None:
        result = _extract_modal_values({}, None)
        assert result == {}

    def test_missing_block(self) -> None:
        state = {}
        fields = [{"fieldLabel": "Missing", "fieldType": "text"}]
        result = _extract_modal_values(state, fields)
        assert result == {"Missing": ""}

    def test_dropdown_no_selection(self) -> None:
        state = {
            "field_0": {
                "field_0_action": {
                    "type": "static_select",
                    "selected_option": None,
                },
            },
        }
        fields = [{"fieldLabel": "Pick", "fieldType": "dropdown"}]
        result = _extract_modal_values(state, fields)
        assert result == {"Pick": ""}


# ===========================================================================
# SlackService constructor and properties
# ===========================================================================


class TestSlackServiceInit:
    """Tests for SlackService initialization."""

    def test_creates_client(self) -> None:
        with patch("ica.services.slack.AsyncWebClient") as mock_cls:
            svc = SlackService(token="xoxb-abc", channel="#ch")
            mock_cls.assert_called_once_with(token="xoxb-abc")
            assert svc.channel == "#ch"

    def test_pending_empty_initially(self, service: SlackService) -> None:
        assert service.pending == {}

    def test_client_property(self, service: SlackService, mock_client: AsyncMock) -> None:
        assert service.client is mock_client


# ===========================================================================
# SlackService.send_message (SlackNotifier)
# ===========================================================================


class TestSendMessage:
    """Tests for SlackService.send_message()."""

    @pytest.mark.asyncio()
    async def test_posts_to_channel(self, service: SlackService, mock_client: AsyncMock) -> None:
        await service.send_message("#general", "Hello!")
        mock_client.chat_postMessage.assert_awaited_once_with(
            channel="#general", text="Hello!"
        )

    @pytest.mark.asyncio()
    async def test_uses_explicit_channel(self, service: SlackService, mock_client: AsyncMock) -> None:
        await service.send_message("#other", "Hi")
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "#other"


# ===========================================================================
# SlackService.send_channel_message (SlackSummaryReview)
# ===========================================================================


class TestSendChannelMessage:
    """Tests for SlackService.send_channel_message()."""

    @pytest.mark.asyncio()
    async def test_uses_default_channel(self, service: SlackService, mock_client: AsyncMock) -> None:
        await service.send_channel_message("Hello!")
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "#test-channel"
        assert call_kwargs["text"] == "Hello!"

    @pytest.mark.asyncio()
    async def test_with_blocks(self, service: SlackService, mock_client: AsyncMock) -> None:
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Hi"}}]
        await service.send_channel_message("Hi", blocks=blocks)
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["blocks"] == blocks

    @pytest.mark.asyncio()
    async def test_without_blocks(self, service: SlackService, mock_client: AsyncMock) -> None:
        await service.send_channel_message("Hello")
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert "blocks" not in call_kwargs


# ===========================================================================
# SlackService.send_error (SlackErrorNotifier)
# ===========================================================================


class TestSendError:
    """Tests for SlackService.send_error()."""

    @pytest.mark.asyncio()
    async def test_posts_to_default_channel(self, service: SlackService, mock_client: AsyncMock) -> None:
        await service.send_error("Something broke")
        mock_client.chat_postMessage.assert_awaited_once_with(
            channel="#test-channel", text="Something broke"
        )


# ===========================================================================
# SlackService.send_and_wait (SlackApprovalSender)
# ===========================================================================


class TestSendAndWait:
    """Tests for SlackService.send_and_wait()."""

    @pytest.mark.asyncio()
    async def test_posts_approval_blocks(self, service: SlackService, mock_client: AsyncMock) -> None:
        # Pre-set the event so it doesn't block
        original_post = mock_client.chat_postMessage

        async def post_and_resolve(**kwargs: Any) -> dict[str, bool]:
            result = await original_post(**kwargs)
            # Find and resolve the pending interaction
            for pending in service.pending.values():
                pending.event.set()
            return result

        mock_client.chat_postMessage = AsyncMock(side_effect=post_and_resolve)

        await service.send_and_wait("#ch", "Ready?", approve_label="Go")

        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "#ch"
        assert call_kwargs["text"] == "Ready?"
        blocks = call_kwargs["blocks"]
        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert blocks[1]["type"] == "actions"
        btn = blocks[1]["elements"][0]
        assert btn["text"]["text"] == "Go"
        assert btn["action_id"].startswith(_PREFIX_APPROVE)

    @pytest.mark.asyncio()
    async def test_blocks_until_event_set(self, service: SlackService, mock_client: AsyncMock) -> None:
        resolved = False

        async def set_after_delay() -> None:
            nonlocal resolved
            await asyncio.sleep(0.05)
            for pending in service.pending.values():
                pending.event.set()
                resolved = True

        asyncio.create_task(set_after_delay())
        await service.send_and_wait("#ch", "msg")
        assert resolved

    @pytest.mark.asyncio()
    async def test_cleans_up_pending(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve_immediately(**kwargs: Any) -> dict[str, bool]:
            for pending in service.pending.values():
                pending.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve_immediately)

        await service.send_and_wait("#ch", "msg")
        assert len(service.pending) == 0

    @pytest.mark.asyncio()
    async def test_default_approve_label(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)
        await service.send_and_wait("#ch", "msg")
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        btn = blocks[1]["elements"][0]
        assert btn["text"]["text"] == "Proceed to next steps"


# ===========================================================================
# SlackService.send_and_wait_form (SlackSummaryReview)
# ===========================================================================


class TestSendAndWaitForm:
    """Tests for SlackService.send_and_wait_form()."""

    @pytest.mark.asyncio()
    async def test_posts_trigger_blocks(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.response["Choice"] = "Yes"
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)

        fields = [{"fieldLabel": "Choice", "fieldType": "dropdown", "fieldOptions": [{"option": "Yes"}]}]
        result = await service.send_and_wait_form("Pick", form_fields=fields)

        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "#test-channel"
        blocks = call_kwargs["blocks"]
        btn = blocks[1]["elements"][0]
        assert btn["action_id"].startswith(_PREFIX_TRIGGER)
        assert result == {"Choice": "Yes"}

    @pytest.mark.asyncio()
    async def test_stores_form_metadata(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def check_and_resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                assert p.interaction_type == "form"
                assert p.form_title == "Title"
                assert p.form_description == "Desc"
                assert p.form_fields is not None
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=check_and_resolve)

        fields = [{"fieldLabel": "F"}]
        await service.send_and_wait_form(
            "msg",
            form_fields=fields,
            form_title="Title",
            form_description="Desc",
        )

    @pytest.mark.asyncio()
    async def test_cleans_up_pending(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)
        await service.send_and_wait_form("msg", form_fields=[])
        assert len(service.pending) == 0

    @pytest.mark.asyncio()
    async def test_default_button_label(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)
        await service.send_and_wait_form("msg", form_fields=[])
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        btn = blocks[1]["elements"][0]
        assert btn["text"]["text"] == "Proceed to Next Steps"


# ===========================================================================
# SlackService.send_and_wait_freetext (SlackManualFallback + SlackSummaryReview)
# ===========================================================================


class TestSendAndWaitFreetext:
    """Tests for SlackService.send_and_wait_freetext()."""

    @pytest.mark.asyncio()
    async def test_posts_trigger_blocks(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.response["text"] = "User feedback here"
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)

        result = await service.send_and_wait_freetext("Give feedback")
        assert result == "User feedback here"

    @pytest.mark.asyncio()
    async def test_stores_freetext_metadata(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def check_and_resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                assert p.interaction_type == "freetext"
                assert p.form_title == "My Title"
                assert p.form_description == "My Desc"
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=check_and_resolve)

        await service.send_and_wait_freetext(
            "msg",
            form_title="My Title",
            form_description="My Desc",
        )

    @pytest.mark.asyncio()
    async def test_returns_empty_string_when_no_text(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)
        result = await service.send_and_wait_freetext("msg")
        assert result == ""

    @pytest.mark.asyncio()
    async def test_cleans_up_pending(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)
        await service.send_and_wait_freetext("msg")
        assert len(service.pending) == 0

    @pytest.mark.asyncio()
    async def test_default_button_label(self, service: SlackService, mock_client: AsyncMock) -> None:
        async def resolve(**kwargs: Any) -> dict[str, bool]:
            for p in service.pending.values():
                p.event.set()
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=resolve)
        await service.send_and_wait_freetext("msg")
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        btn = blocks[1]["elements"][0]
        assert btn["text"]["text"] == "Add feedback"


# ===========================================================================
# Handler: _handle_approve
# ===========================================================================


class TestHandleApprove:
    """Tests for SlackService._handle_approve()."""

    @pytest.mark.asyncio()
    async def test_resolves_pending_event(self, service: SlackService) -> None:
        pending = _PendingInteraction(interaction_type="approval")
        service._pending["abc"] = pending

        ack = AsyncMock()
        body = {"actions": [{"action_id": f"{_PREFIX_APPROVE}abc"}]}
        await service._handle_approve(ack, body)

        ack.assert_awaited_once()
        assert pending.event.is_set()

    @pytest.mark.asyncio()
    async def test_ignores_unknown_callback(self, service: SlackService) -> None:
        ack = AsyncMock()
        body = {"actions": [{"action_id": f"{_PREFIX_APPROVE}unknown"}]}
        await service._handle_approve(ack, body)
        ack.assert_awaited_once()
        # No error raised

    @pytest.mark.asyncio()
    async def test_empty_actions(self, service: SlackService) -> None:
        ack = AsyncMock()
        body = {"actions": [{}]}
        await service._handle_approve(ack, body)
        ack.assert_awaited_once()


# ===========================================================================
# Handler: _handle_trigger
# ===========================================================================


class TestHandleTrigger:
    """Tests for SlackService._handle_trigger()."""

    @pytest.mark.asyncio()
    async def test_opens_form_modal(self, service: SlackService, mock_client: AsyncMock) -> None:
        fields = [{"fieldLabel": "X", "fieldType": "text"}]
        pending = _PendingInteraction(
            interaction_type="form",
            form_fields=fields,
            form_title="Form Title",
        )
        service._pending["def"] = pending

        ack = AsyncMock()
        body = {
            "actions": [{"action_id": f"{_PREFIX_TRIGGER}def"}],
            "trigger_id": "trig123",
        }
        await service._handle_trigger(ack, body)

        ack.assert_awaited_once()
        mock_client.views_open.assert_awaited_once()
        view = mock_client.views_open.call_args.kwargs["view"]
        assert view["type"] == "modal"
        assert view["callback_id"] == f"{_PREFIX_MODAL}def"
        assert view["private_metadata"] == "def"
        assert view["title"]["text"] == "Form Title"
        # Should have form field blocks
        assert len(view["blocks"]) == 1

    @pytest.mark.asyncio()
    async def test_opens_freetext_modal(self, service: SlackService, mock_client: AsyncMock) -> None:
        pending = _PendingInteraction(
            interaction_type="freetext",
            form_title="Feedback",
            form_description="Enter feedback",
        )
        service._pending["ghi"] = pending

        ack = AsyncMock()
        body = {
            "actions": [{"action_id": f"{_PREFIX_TRIGGER}ghi"}],
            "trigger_id": "trig456",
        }
        await service._handle_trigger(ack, body)

        view = mock_client.views_open.call_args.kwargs["view"]
        assert view["title"]["text"] == "Feedback"
        # Description block + input block
        assert len(view["blocks"]) == 2
        assert view["blocks"][0]["type"] == "section"
        assert view["blocks"][1]["block_id"] == "freetext_block"

    @pytest.mark.asyncio()
    async def test_truncates_long_title(self, service: SlackService, mock_client: AsyncMock) -> None:
        pending = _PendingInteraction(
            interaction_type="freetext",
            form_title="A" * 50,
        )
        service._pending["jkl"] = pending

        ack = AsyncMock()
        body = {
            "actions": [{"action_id": f"{_PREFIX_TRIGGER}jkl"}],
            "trigger_id": "trig789",
        }
        await service._handle_trigger(ack, body)

        view = mock_client.views_open.call_args.kwargs["view"]
        assert len(view["title"]["text"]) <= 24

    @pytest.mark.asyncio()
    async def test_ignores_unknown_callback(self, service: SlackService, mock_client: AsyncMock) -> None:
        ack = AsyncMock()
        body = {
            "actions": [{"action_id": f"{_PREFIX_TRIGGER}unknown"}],
            "trigger_id": "trig",
        }
        await service._handle_trigger(ack, body)
        ack.assert_awaited_once()
        mock_client.views_open.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_freetext_without_description(self, service: SlackService, mock_client: AsyncMock) -> None:
        pending = _PendingInteraction(
            interaction_type="freetext",
            form_title="Title",
            form_description="",
        )
        service._pending["mno"] = pending

        ack = AsyncMock()
        body = {
            "actions": [{"action_id": f"{_PREFIX_TRIGGER}mno"}],
            "trigger_id": "trig",
        }
        await service._handle_trigger(ack, body)

        view = mock_client.views_open.call_args.kwargs["view"]
        # Only input block, no description
        assert len(view["blocks"]) == 1
        assert view["blocks"][0]["type"] == "input"

    @pytest.mark.asyncio()
    async def test_default_title(self, service: SlackService, mock_client: AsyncMock) -> None:
        pending = _PendingInteraction(interaction_type="freetext", form_title="")
        service._pending["pqr"] = pending

        ack = AsyncMock()
        body = {
            "actions": [{"action_id": f"{_PREFIX_TRIGGER}pqr"}],
            "trigger_id": "trig",
        }
        await service._handle_trigger(ack, body)

        view = mock_client.views_open.call_args.kwargs["view"]
        assert view["title"]["text"] == "Submit Response"


# ===========================================================================
# Handler: _handle_view_submission
# ===========================================================================


class TestHandleViewSubmission:
    """Tests for SlackService._handle_view_submission()."""

    @pytest.mark.asyncio()
    async def test_freetext_submission(self, service: SlackService) -> None:
        pending = _PendingInteraction(interaction_type="freetext")
        service._pending["stu"] = pending

        ack = AsyncMock()
        body = {
            "view": {
                "private_metadata": "stu",
                "state": {
                    "values": {
                        "freetext_block": {
                            "freetext_action": {"value": "My feedback"},
                        },
                    },
                },
            },
        }
        await service._handle_view_submission(ack, body)

        ack.assert_awaited_once()
        assert pending.response["text"] == "My feedback"
        assert pending.event.is_set()

    @pytest.mark.asyncio()
    async def test_form_submission(self, service: SlackService) -> None:
        fields = [
            {"fieldLabel": "Choice", "fieldType": "dropdown"},
            {"fieldLabel": "Notes", "fieldType": "text"},
        ]
        pending = _PendingInteraction(
            interaction_type="form",
            form_fields=fields,
        )
        service._pending["vwx"] = pending

        ack = AsyncMock()
        body = {
            "view": {
                "private_metadata": "vwx",
                "state": {
                    "values": {
                        "field_0": {
                            "field_0_action": {
                                "type": "static_select",
                                "selected_option": {"value": "Option A"},
                            },
                        },
                        "field_1": {
                            "field_1_action": {
                                "type": "plain_text_input",
                                "value": "Some notes",
                            },
                        },
                    },
                },
            },
        }
        await service._handle_view_submission(ack, body)

        assert pending.response == {"Choice": "Option A", "Notes": "Some notes"}
        assert pending.event.is_set()

    @pytest.mark.asyncio()
    async def test_ignores_unknown_callback(self, service: SlackService) -> None:
        ack = AsyncMock()
        body = {
            "view": {
                "private_metadata": "unknown",
                "state": {"values": {}},
            },
        }
        await service._handle_view_submission(ack, body)
        ack.assert_awaited_once()
        # No error raised

    @pytest.mark.asyncio()
    async def test_freetext_empty_value(self, service: SlackService) -> None:
        pending = _PendingInteraction(interaction_type="freetext")
        service._pending["xyz"] = pending

        ack = AsyncMock()
        body = {
            "view": {
                "private_metadata": "xyz",
                "state": {
                    "values": {
                        "freetext_block": {
                            "freetext_action": {"value": ""},
                        },
                    },
                },
            },
        }
        await service._handle_view_submission(ack, body)

        assert pending.response["text"] == ""
        assert pending.event.is_set()


# ===========================================================================
# Handler registration
# ===========================================================================


class TestRegisterHandlers:
    """Tests for SlackService.register_handlers()."""

    def test_registers_three_handlers(self, service: SlackService) -> None:
        bolt_app = MagicMock()
        # Make action() and view() return decorators
        bolt_app.action.return_value = lambda f: f
        bolt_app.view.return_value = lambda f: f

        service.register_handlers(bolt_app)

        assert bolt_app.action.call_count == 2  # approve + trigger
        assert bolt_app.view.call_count == 1  # modal submission

    def test_action_patterns(self, service: SlackService) -> None:
        bolt_app = MagicMock()
        bolt_app.action.return_value = lambda f: f
        bolt_app.view.return_value = lambda f: f

        service.register_handlers(bolt_app)

        # Check that patterns match our prefixes
        action_calls = bolt_app.action.call_args_list
        patterns = [str(call.args[0].pattern) for call in action_calls]
        assert any(_PREFIX_APPROVE.replace("_", r"\_").rstrip("\\") in p or _PREFIX_APPROVE in p for p in patterns)
        assert any(_PREFIX_TRIGGER.replace("_", r"\_").rstrip("\\") in p or _PREFIX_TRIGGER in p for p in patterns)


# ===========================================================================
# Protocol satisfaction
# ===========================================================================


class TestProtocolSatisfaction:
    """Verify SlackService satisfies all pipeline protocols."""

    def test_slack_notifier(self, service: SlackService) -> None:
        """SlackNotifier requires send_message(channel, text)."""
        assert callable(getattr(service, "send_message", None))

    def test_slack_approval_sender(self, service: SlackService) -> None:
        """SlackApprovalSender requires send_and_wait(channel, text, approve_label)."""
        assert callable(getattr(service, "send_and_wait", None))

    def test_slack_manual_fallback(self, service: SlackService) -> None:
        """SlackManualFallback requires send_and_wait_freetext(message, ...)."""
        assert callable(getattr(service, "send_and_wait_freetext", None))

    def test_slack_summary_review(self, service: SlackService) -> None:
        """SlackSummaryReview requires send_channel_message, send_and_wait_form, send_and_wait_freetext."""
        assert callable(getattr(service, "send_channel_message", None))
        assert callable(getattr(service, "send_and_wait_form", None))
        assert callable(getattr(service, "send_and_wait_freetext", None))

    def test_slack_error_notifier(self, service: SlackService) -> None:
        """SlackErrorNotifier requires send_error(message)."""
        assert callable(getattr(service, "send_error", None))


# ===========================================================================
# End-to-end: approval flow
# ===========================================================================


class TestApprovalE2E:
    """End-to-end test for the approval send-and-wait flow."""

    @pytest.mark.asyncio()
    async def test_full_approval_flow(self, service: SlackService, mock_client: AsyncMock) -> None:
        """Post approval, simulate button click, verify unblocked."""
        callback_id_holder: list[str] = []

        async def capture_and_schedule_click(**kwargs: Any) -> dict[str, bool]:
            blocks = kwargs.get("blocks", [])
            for block in blocks:
                if block.get("type") == "actions":
                    action_id = block["elements"][0]["action_id"]
                    cb_id = action_id.removeprefix(_PREFIX_APPROVE)
                    callback_id_holder.append(cb_id)
                    # Schedule the approval handler to fire after a tick
                    async def _click() -> None:
                        await asyncio.sleep(0.01)
                        ack = AsyncMock()
                        body = {"actions": [{"action_id": action_id}]}
                        await service._handle_approve(ack, body)
                    asyncio.create_task(_click())
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=capture_and_schedule_click)

        # This should not hang — the simulated click resolves it
        await asyncio.wait_for(
            service.send_and_wait("#ch", "Approve?", approve_label="Yes"),
            timeout=2.0,
        )
        assert len(callback_id_holder) == 1
        assert len(service.pending) == 0


# ===========================================================================
# End-to-end: form flow
# ===========================================================================


class TestFormE2E:
    """End-to-end test for the form send-and-wait flow."""

    @pytest.mark.asyncio()
    async def test_full_form_flow(self, service: SlackService, mock_client: AsyncMock) -> None:
        """Post form trigger, simulate button click + modal open + submit."""
        callback_id_holder: list[str] = []

        async def capture_trigger(**kwargs: Any) -> dict[str, bool]:
            blocks = kwargs.get("blocks", [])
            for block in blocks:
                if block.get("type") == "actions":
                    action_id = block["elements"][0]["action_id"]
                    cb_id = action_id.removeprefix(_PREFIX_TRIGGER)
                    callback_id_holder.append(cb_id)

                    async def _simulate_click() -> None:
                        await asyncio.sleep(0.01)
                        # Simulate button click → opens modal
                        ack = AsyncMock()
                        body = {
                            "actions": [{"action_id": action_id}],
                            "trigger_id": "trig_test",
                        }
                        await service._handle_trigger(ack, body)

                        # Now simulate modal submission
                        await asyncio.sleep(0.01)
                        submit_ack = AsyncMock()
                        submit_body = {
                            "view": {
                                "private_metadata": cb_id,
                                "state": {
                                    "values": {
                                        "field_0": {
                                            "field_0_action": {
                                                "type": "static_select",
                                                "selected_option": {"value": "Yes"},
                                            },
                                        },
                                    },
                                },
                            },
                        }
                        await service._handle_view_submission(submit_ack, submit_body)

                    asyncio.create_task(_simulate_click())
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=capture_trigger)

        fields = [{"fieldLabel": "Choice", "fieldType": "dropdown", "fieldOptions": [{"option": "Yes"}]}]
        result = await asyncio.wait_for(
            service.send_and_wait_form("Pick one", form_fields=fields),
            timeout=2.0,
        )

        assert result == {"Choice": "Yes"}
        assert len(service.pending) == 0
        # Verify modal was opened
        mock_client.views_open.assert_awaited_once()


# ===========================================================================
# End-to-end: freetext flow
# ===========================================================================


class TestFreetextE2E:
    """End-to-end test for the freetext send-and-wait flow."""

    @pytest.mark.asyncio()
    async def test_full_freetext_flow(self, service: SlackService, mock_client: AsyncMock) -> None:
        """Post freetext trigger, simulate button click + modal + submit."""
        async def capture_trigger(**kwargs: Any) -> dict[str, bool]:
            blocks = kwargs.get("blocks", [])
            for block in blocks:
                if block.get("type") == "actions":
                    action_id = block["elements"][0]["action_id"]
                    cb_id = action_id.removeprefix(_PREFIX_TRIGGER)

                    async def _simulate() -> None:
                        await asyncio.sleep(0.01)
                        # Button click
                        await service._handle_trigger(
                            AsyncMock(),
                            {"actions": [{"action_id": action_id}], "trigger_id": "t"},
                        )
                        # Modal submit
                        await asyncio.sleep(0.01)
                        await service._handle_view_submission(
                            AsyncMock(),
                            {
                                "view": {
                                    "private_metadata": cb_id,
                                    "state": {
                                        "values": {
                                            "freetext_block": {
                                                "freetext_action": {"value": "My text"},
                                            },
                                        },
                                    },
                                },
                            },
                        )

                    asyncio.create_task(_simulate())
            return {"ok": True}

        mock_client.chat_postMessage = AsyncMock(side_effect=capture_trigger)

        result = await asyncio.wait_for(
            service.send_and_wait_freetext("Feedback please"),
            timeout=2.0,
        )

        assert result == "My text"
        assert len(service.pending) == 0
