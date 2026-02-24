"""Tests for HTML generation pipeline step (Step 5).

Tests cover:
- HtmlGenerationResult dataclass
- SlackHtmlReview protocol
- GoogleDocsService protocol
- aggregate_feedback: notes → bullet-point string
- call_html_llm: HTML generation LLM call
- call_html_regeneration: scoped HTML regeneration LLM call
- extract_html_learning_data: learning data extraction with JSON parsing
- build_next_steps_form: dropdown form definition
- parse_next_steps_response: dropdown value → UserChoice
- store_html_feedback: notes table insertion
- create_html_doc: Google Doc creation
- run_html_generation: full orchestrated pipeline step
- Constants: Slack field labels, messages, markers
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.html_generation import (
    APPROVAL_MESSAGE,
    FEEDBACK_BUTTON_LABEL,
    FEEDBACK_FORM_DESCRIPTION,
    FEEDBACK_FORM_TITLE,
    FEEDBACK_MESSAGE,
    GOOGLE_DOC_TITLE,
    HTML_VALID_MARKER,
    NEXT_STEPS_BUTTON_LABEL,
    NEXT_STEPS_FIELD_LABEL,
    NEXT_STEPS_FORM_DESCRIPTION,
    NEXT_STEPS_FORM_TITLE,
    NEXT_STEPS_MESSAGE,
    NEXT_STEPS_OPTIONS,
    HtmlGenerationResult,
    aggregate_feedback,
    build_next_steps_form,
    call_html_llm,
    call_html_regeneration,
    create_html_doc,
    extract_html_learning_data,
    parse_next_steps_response,
    run_html_generation,
    store_html_feedback,
)
from ica.utils.output_router import UserChoice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """# *INTRODUCTION*

This week's newsletter explores AI governance.

# *QUICK HIGHLIGHTS*

• Bullet one about featured article with bold terms.
• Bullet two about main article one content here.
• Bullet three about main article two details here.

# *FOOTER*

Alright, that's a wrap for the week!

Thoughts?
"""

SAMPLE_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Artificially Intelligent, Actually Useful. - [INSERT DATE]</title>
</head>
<body>
    <table class="nl-wrapper">
        <td class="nl-date"></td>
        <td class="nl-content nl-intro"></td>
        <td class="nl-quick-highlights"></td>
        <td class="nl-footer"></td>
    </table>
</body>
</html>
"""

SAMPLE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Artificially Intelligent, Actually Useful. - February 23, 2026</title>
</head>
<body>
    <table class="nl-wrapper">
        <td class="nl-date">February 23, 2026</td>
        <td class="nl-content nl-intro"><p>This week's newsletter...</p></td>
        <td class="nl-quick-highlights"><tr><td>Bullet one</td></tr></td>
        <td class="nl-footer"><p>Alright, that's a wrap!</p></td>
    </table>
</body>
</html>
"""

SAMPLE_DATE = "February 23, 2026"


def _mock_llm_response(content: str) -> MagicMock:
    """Create a mock litellm.acompletion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


def _make_note(feedback_text: str | None) -> MagicMock:
    """Create a mock Note row."""
    note = MagicMock()
    note.feedback_text = feedback_text
    return note


def _make_slack_mock() -> AsyncMock:
    """Create a mock Slack handler implementing SlackHtmlReview."""
    slack = AsyncMock()
    slack.send_channel_message = AsyncMock()
    slack.send_and_wait_form = AsyncMock()
    slack.send_and_wait_freetext = AsyncMock()
    return slack


def _make_docs_mock(doc_id: str = "doc-html-123") -> AsyncMock:
    """Create a mock Google Docs service implementing GoogleDocsService."""
    docs = AsyncMock()
    docs.create_document = AsyncMock(return_value=doc_id)
    docs.insert_content = AsyncMock()
    docs.get_content = AsyncMock(return_value=SAMPLE_MARKDOWN)
    return docs


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------


class TestHtmlGenerationResult:
    def test_creation(self):
        result = HtmlGenerationResult(
            html="<html>test</html>",
            html_doc_id="doc-123",
            doc_url="https://docs.google.com/document/d/doc-123/edit",
            model="anthropic/claude-sonnet-4.5",
        )
        assert result.html == "<html>test</html>"
        assert result.html_doc_id == "doc-123"
        assert result.doc_url == "https://docs.google.com/document/d/doc-123/edit"
        assert result.model == "anthropic/claude-sonnet-4.5"

    def test_frozen(self):
        result = HtmlGenerationResult(
            html="x", html_doc_id="y", doc_url="z", model="m",
        )
        with pytest.raises(AttributeError):
            result.html = "new"  # type: ignore[misc]

    def test_fields(self):
        result = HtmlGenerationResult(
            html="h", html_doc_id="d", doc_url="u", model="m",
        )
        assert hasattr(result, "html")
        assert hasattr(result, "html_doc_id")
        assert hasattr(result, "doc_url")
        assert hasattr(result, "model")


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_next_steps_options(self):
        assert NEXT_STEPS_OPTIONS == ["Yes", "Provide Feedback"]

    def test_field_label(self):
        assert NEXT_STEPS_FIELD_LABEL == "Ready to proceed to next step ?"

    def test_html_valid_marker(self):
        assert HTML_VALID_MARKER == "<!DOCTYPE html>"

    def test_google_doc_title(self):
        assert GOOGLE_DOC_TITLE == "Newsletter HTML"

    def test_approval_message(self):
        assert "Approved" in APPROVAL_MESSAGE

    def test_feedback_message(self):
        assert "feedback" in FEEDBACK_MESSAGE.lower()

    def test_next_steps_message(self):
        assert "generated" in NEXT_STEPS_MESSAGE.lower()


# ---------------------------------------------------------------------------
# aggregate_feedback tests
# ---------------------------------------------------------------------------


class TestAggregateFeedback:
    def test_empty_notes(self):
        assert aggregate_feedback([]) is None

    def test_none_feedback(self):
        note = _make_note(None)
        assert aggregate_feedback([note]) is None

    def test_single_note(self):
        note = _make_note("Improve the intro section")
        result = aggregate_feedback([note])
        assert result == "\u2022 Improve the intro section"

    def test_multiple_notes(self):
        notes = [_make_note("Note 1"), _make_note("Note 2")]
        result = aggregate_feedback(notes)
        assert result == "\u2022 Note 1\n\u2022 Note 2"

    def test_skips_empty_feedback(self):
        notes = [_make_note("Good"), _make_note(""), _make_note("Better")]
        result = aggregate_feedback(notes)
        assert result == "\u2022 Good\n\u2022 Better"

    def test_all_empty_feedback(self):
        notes = [_make_note(""), _make_note("")]
        assert aggregate_feedback(notes) is None


# ---------------------------------------------------------------------------
# call_html_llm tests
# ---------------------------------------------------------------------------


class TestCallHtmlLlm:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            result = await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                model="test-model",
            )
            assert "<!DOCTYPE html>" in result
            mock_call.assert_called_once()
            call_args = mock_call.call_args
            assert call_args.kwargs["model"] == "test-model"
            msgs = call_args.kwargs["messages"]
            assert len(msgs) == 2
            assert msgs[0]["role"] == "system"
            assert msgs[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_passes_markdown_content(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                model="test-model",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert SAMPLE_MARKDOWN in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_passes_html_template(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                model="test-model",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert SAMPLE_HTML_TEMPLATE in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_passes_newsletter_date(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                model="test-model",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert SAMPLE_DATE in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_with_feedback(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                aggregated_feedback="\u2022 feedback note",
                model="test-model",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert "feedback note" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_without_feedback(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                model="test-model",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert "Editorial Improvement Context" not in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_default_model(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call, \
             patch("ica.pipeline.html_generation.get_model", return_value="anthropic/claude-sonnet-4.5"):
            await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
            )
            assert mock_call.call_args.kwargs["model"] == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        mock_resp = _mock_llm_response("")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                await call_html_llm(
                    SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                    model="m",
                )

    @pytest.mark.asyncio
    async def test_whitespace_only_response_raises(self):
        mock_resp = _mock_llm_response("   \n  ")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                await call_html_llm(
                    SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                    model="m",
                )

    @pytest.mark.asyncio
    async def test_none_response_raises(self):
        mock_resp = _mock_llm_response(None)  # type: ignore[arg-type]
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                await call_html_llm(
                    SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                    model="m",
                )

    @pytest.mark.asyncio
    async def test_strips_response(self):
        mock_resp = _mock_llm_response(f"  {SAMPLE_HTML}  \n")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            result = await call_html_llm(
                SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
                model="m",
            )
            assert result == SAMPLE_HTML.strip()


# ---------------------------------------------------------------------------
# call_html_regeneration tests
# ---------------------------------------------------------------------------


class TestCallHtmlRegeneration:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            result = await call_html_regeneration(
                previous_html=SAMPLE_HTML,
                markdown_content=SAMPLE_MARKDOWN,
                html_template=SAMPLE_HTML_TEMPLATE,
                user_feedback="Fix the intro section",
                newsletter_date=SAMPLE_DATE,
                model="test-model",
            )
            assert "<!DOCTYPE html>" in result
            mock_call.assert_called_once()
            msgs = mock_call.call_args.kwargs["messages"]
            assert len(msgs) == 2
            assert msgs[0]["role"] == "system"
            assert msgs[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_passes_previous_html(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_regeneration(
                previous_html="<html>OLD</html>",
                markdown_content=SAMPLE_MARKDOWN,
                html_template=SAMPLE_HTML_TEMPLATE,
                user_feedback="Fix it",
                newsletter_date=SAMPLE_DATE,
                model="m",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert "<html>OLD</html>" in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_passes_user_feedback(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_regeneration(
                previous_html=SAMPLE_HTML,
                markdown_content=SAMPLE_MARKDOWN,
                html_template=SAMPLE_HTML_TEMPLATE,
                user_feedback="Make the footer italic",
                newsletter_date=SAMPLE_DATE,
                model="m",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert "Make the footer italic" in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_scoped_update_system_prompt(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await call_html_regeneration(
                previous_html=SAMPLE_HTML,
                markdown_content=SAMPLE_MARKDOWN,
                html_template=SAMPLE_HTML_TEMPLATE,
                user_feedback="Fix intro",
                newsletter_date=SAMPLE_DATE,
                model="m",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert "scoped update mode" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_default_model(self):
        mock_resp = _mock_llm_response(SAMPLE_HTML)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call, \
             patch("ica.pipeline.html_generation.get_model", return_value="anthropic/claude-sonnet-4.5"):
            await call_html_regeneration(
                previous_html=SAMPLE_HTML,
                markdown_content=SAMPLE_MARKDOWN,
                html_template=SAMPLE_HTML_TEMPLATE,
                user_feedback="Fix it",
                newsletter_date=SAMPLE_DATE,
            )
            assert mock_call.call_args.kwargs["model"] == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        mock_resp = _mock_llm_response("")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                await call_html_regeneration(
                    previous_html=SAMPLE_HTML,
                    markdown_content=SAMPLE_MARKDOWN,
                    html_template=SAMPLE_HTML_TEMPLATE,
                    user_feedback="Fix it",
                    newsletter_date=SAMPLE_DATE,
                    model="m",
                )

    @pytest.mark.asyncio
    async def test_strips_response(self):
        mock_resp = _mock_llm_response(f"  {SAMPLE_HTML}  \n")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            result = await call_html_regeneration(
                previous_html=SAMPLE_HTML,
                markdown_content=SAMPLE_MARKDOWN,
                html_template=SAMPLE_HTML_TEMPLATE,
                user_feedback="Fix it",
                newsletter_date=SAMPLE_DATE,
                model="m",
            )
            assert result == SAMPLE_HTML.strip()


# ---------------------------------------------------------------------------
# extract_html_learning_data tests
# ---------------------------------------------------------------------------


class TestExtractHtmlLearningData:
    @pytest.mark.asyncio
    async def test_json_extraction(self):
        learning_json = json.dumps({
            "learning_feedback": "Improve header styling in future.",
        })
        mock_resp = _mock_llm_response(learning_json)
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            result = await extract_html_learning_data(
                feedback="Fix the header",
                input_text=SAMPLE_HTML,
                model_output="<html>regen</html>",
                model="m",
            )
            assert result == "Improve header styling in future."

    @pytest.mark.asyncio
    async def test_plain_text_fallback(self):
        mock_resp = _mock_llm_response("Plain text learning note.")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            result = await extract_html_learning_data(
                feedback="Fix it",
                input_text=SAMPLE_HTML,
                model_output="<html>regen</html>",
                model="m",
            )
            assert result == "Plain text learning note."

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        mock_resp = _mock_llm_response("")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                await extract_html_learning_data(
                    feedback="Fix",
                    input_text="in",
                    model_output="out",
                    model="m",
                )

    @pytest.mark.asyncio
    async def test_json_without_learning_feedback_key(self):
        mock_resp = _mock_llm_response('{"other_key": "value"}')
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            result = await extract_html_learning_data(
                feedback="f",
                input_text="i",
                model_output="o",
                model="m",
            )
            assert result == '{"other_key": "value"}'

    @pytest.mark.asyncio
    async def test_default_model(self):
        mock_resp = _mock_llm_response("note")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call, \
             patch("ica.pipeline.html_generation.get_model", return_value="anthropic/claude-sonnet-4.5"):
            await extract_html_learning_data(
                feedback="f",
                input_text="i",
                model_output="o",
            )
            assert mock_call.call_args.kwargs["model"] == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_passes_correct_prompts(self):
        mock_resp = _mock_llm_response("note")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp) as mock_call:
            await extract_html_learning_data(
                feedback="user feedback text",
                input_text="the input",
                model_output="the output",
                model="m",
            )
            msgs = mock_call.call_args.kwargs["messages"]
            assert "user feedback text" in msgs[1]["content"]
            assert "the input" in msgs[1]["content"]
            assert "the output" in msgs[1]["content"]

    @pytest.mark.asyncio
    async def test_strips_response(self):
        mock_resp = _mock_llm_response("  learning note  \n")
        with patch("ica.pipeline.html_generation.litellm.acompletion", return_value=mock_resp):
            result = await extract_html_learning_data(
                feedback="f", input_text="i", model_output="o", model="m",
            )
            assert result == "learning note"


# ---------------------------------------------------------------------------
# build_next_steps_form tests
# ---------------------------------------------------------------------------


class TestBuildNextStepsForm:
    def test_returns_list(self):
        form = build_next_steps_form()
        assert isinstance(form, list)
        assert len(form) == 1

    def test_field_structure(self):
        form = build_next_steps_form()
        field = form[0]
        assert field["fieldLabel"] == NEXT_STEPS_FIELD_LABEL
        assert field["fieldType"] == "dropdown"
        assert field["requiredField"] is True

    def test_field_options(self):
        form = build_next_steps_form()
        field = form[0]
        options = field["fieldOptions"]
        assert isinstance(options, dict)
        values = options["values"]
        assert len(values) == 2
        assert values[0]["option"] == "Yes"
        assert values[1]["option"] == "Provide Feedback"


# ---------------------------------------------------------------------------
# parse_next_steps_response tests
# ---------------------------------------------------------------------------


class TestParseNextStepsResponse:
    def test_yes(self):
        response = {NEXT_STEPS_FIELD_LABEL: "Yes"}
        assert parse_next_steps_response(response) == UserChoice.YES

    def test_provide_feedback(self):
        response = {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"}
        assert parse_next_steps_response(response) == UserChoice.PROVIDE_FEEDBACK

    def test_case_insensitive(self):
        response = {NEXT_STEPS_FIELD_LABEL: "yes"}
        assert parse_next_steps_response(response) == UserChoice.YES

    def test_unknown_value(self):
        response = {NEXT_STEPS_FIELD_LABEL: "unknown"}
        assert parse_next_steps_response(response) is None

    def test_empty_response(self):
        assert parse_next_steps_response({}) is None

    def test_missing_field(self):
        response = {"Other Field": "Yes"}
        assert parse_next_steps_response(response) is None


# ---------------------------------------------------------------------------
# store_html_feedback tests
# ---------------------------------------------------------------------------


class TestStoreHtmlFeedback:
    @pytest.mark.asyncio
    async def test_stores_feedback(self):
        with patch("ica.pipeline.html_generation.add_note", new_callable=AsyncMock) as mock_add:
            session = AsyncMock()
            await store_html_feedback(session, "learning text")
            mock_add.assert_called_once_with(
                session,
                "user_htmlgenerator",
                "learning text",
                newsletter_id=None,
            )

    @pytest.mark.asyncio
    async def test_stores_with_newsletter_id(self):
        with patch("ica.pipeline.html_generation.add_note", new_callable=AsyncMock) as mock_add:
            session = AsyncMock()
            await store_html_feedback(
                session, "text", newsletter_id="nl-42",
            )
            mock_add.assert_called_once_with(
                session,
                "user_htmlgenerator",
                "text",
                newsletter_id="nl-42",
            )


# ---------------------------------------------------------------------------
# create_html_doc tests
# ---------------------------------------------------------------------------


class TestCreateHtmlDoc:
    @pytest.mark.asyncio
    async def test_creates_and_inserts(self):
        docs = _make_docs_mock("html-doc-456")
        doc_id, doc_url = await create_html_doc(docs, "<html>content</html>")
        assert doc_id == "html-doc-456"
        assert "html-doc-456" in doc_url
        assert doc_url == "https://docs.google.com/document/d/html-doc-456/edit"
        docs.create_document.assert_called_once_with(GOOGLE_DOC_TITLE)
        docs.insert_content.assert_called_once_with("html-doc-456", "<html>content</html>")

    @pytest.mark.asyncio
    async def test_custom_title(self):
        docs = _make_docs_mock("doc-789")
        await create_html_doc(docs, "<html>x</html>", title="Custom Title")
        docs.create_document.assert_called_once_with("Custom Title")

    @pytest.mark.asyncio
    async def test_returns_tuple(self):
        docs = _make_docs_mock("doc-abc")
        result = await create_html_doc(docs, "<html>test</html>")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# run_html_generation tests — Yes approval
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationYes:
    @pytest.mark.asyncio
    async def test_yes_returns_result(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }
        docs = _make_docs_mock("html-doc-yes")

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="anthropic/claude-sonnet-4.5"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                docs=docs,
                session=AsyncMock(),
            )

        assert isinstance(result, HtmlGenerationResult)
        assert result.html_doc_id == "html-doc-yes"
        assert "html-doc-yes" in result.doc_url
        assert result.model == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_yes_sends_approval_message(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="test-model"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        # Check that approval message was sent
        calls = slack.send_channel_message.call_args_list
        approval_calls = [c for c in calls if APPROVAL_MESSAGE in str(c)]
        assert len(approval_calls) >= 1

    @pytest.mark.asyncio
    async def test_yes_creates_google_doc(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }
        docs = _make_docs_mock("html-doc-abc")

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="test-model"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                docs=docs,
                session=AsyncMock(),
            )

        docs.create_document.assert_called_once()
        docs.insert_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_yes_without_docs(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="test-model"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        assert result.html_doc_id == ""
        assert result.doc_url == ""


# ---------------------------------------------------------------------------
# run_html_generation tests — Feedback loop
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationFeedback:
    @pytest.mark.asyncio
    async def test_feedback_then_yes(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "Fix the intro section"
        docs = _make_docs_mock("html-doc-fb")

        regen_html = SAMPLE_HTML.replace("This week's", "Updated this week's")
        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)  # initial generation
            if call_count == 2:
                return _mock_llm_response(regen_html)  # regeneration
            return _mock_llm_response('{"learning_feedback": "note"}')  # learning

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="test-model"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock) as mock_add_note:
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                docs=docs,
                session=AsyncMock(),
            )

        assert isinstance(result, HtmlGenerationResult)
        # Feedback form should have been invoked
        slack.send_and_wait_freetext.assert_called_once()
        # Learning data should have been stored
        mock_add_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_feedback_collects_freetext(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "Make it more colorful"

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)
            if call_count == 2:
                return _mock_llm_response(SAMPLE_HTML)
            return _mock_llm_response('{"learning_feedback": "x"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        slack.send_and_wait_freetext.assert_called_once_with(
            FEEDBACK_MESSAGE,
            button_label=FEEDBACK_BUTTON_LABEL,
            form_title=FEEDBACK_FORM_TITLE,
            form_description=FEEDBACK_FORM_DESCRIPTION,
        )

    @pytest.mark.asyncio
    async def test_feedback_stores_learning_data(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback text"

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)
            if call_count == 2:
                return _mock_llm_response(SAMPLE_HTML)
            return _mock_llm_response(
                '{"learning_feedback": "stored learning note"}'
            )

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock) as mock_add_note:
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        mock_add_note.assert_called_once()
        call_args = mock_add_note.call_args
        assert call_args.args[1] == "user_htmlgenerator"
        assert call_args.args[2] == "stored learning note"

    @pytest.mark.asyncio
    async def test_feedback_updates_google_doc(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "Fix it"
        docs = _make_docs_mock("html-doc-update")

        regen_html = "<!DOCTYPE html><html>UPDATED</html>"
        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)
            if call_count == 2:
                return _mock_llm_response(regen_html)
            return _mock_llm_response('{"learning_feedback": "x"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                docs=docs,
                session=AsyncMock(),
            )

        # Doc should have been updated with regenerated HTML
        insert_calls = docs.insert_content.call_args_list
        assert len(insert_calls) >= 2  # initial + regen
        # Last insert before approval should contain regenerated HTML
        regen_insert = insert_calls[-1]
        assert regen_insert.args[1] == regen_html

    @pytest.mark.asyncio
    async def test_multiple_feedback_rounds(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.side_effect = [
            "First feedback",
            "Second feedback",
        ]

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return _mock_llm_response(SAMPLE_HTML)  # initial gen
            if call_count <= 3:
                return _mock_llm_response(SAMPLE_HTML)  # regen 1 + learning 1
            if call_count <= 5:
                return _mock_llm_response(SAMPLE_HTML)  # regen 2 + learning 2
            return _mock_llm_response('{"learning_feedback": "x"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock) as mock_add_note:
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        assert isinstance(result, HtmlGenerationResult)
        assert slack.send_and_wait_freetext.call_count == 2
        assert mock_add_note.call_count == 2

    @pytest.mark.asyncio
    async def test_feedback_without_session_skips_storage(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)
            if call_count == 2:
                return _mock_llm_response(SAMPLE_HTML)
            return _mock_llm_response('{"learning_feedback": "x"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock) as mock_add_note:
            # No session passed
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
            )

        assert isinstance(result, HtmlGenerationResult)
        mock_add_note.assert_not_called()


# ---------------------------------------------------------------------------
# run_html_generation tests — Learning data aggregation
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationLearningData:
    @pytest.mark.asyncio
    async def test_fetches_learning_data(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        notes = [_make_note("Prior note 1"), _make_note("Prior note 2")]

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)) as mock_call, \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=notes):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        # The LLM call should include the aggregated feedback
        msgs = mock_call.call_args.kwargs["messages"]
        assert "Prior note 1" in msgs[0]["content"]
        assert "Prior note 2" in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_no_learning_data_available(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)) as mock_call, \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        msgs = mock_call.call_args.kwargs["messages"]
        assert "Editorial Improvement Context" not in msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_without_session_skips_learning_data_fetch(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock) as mock_notes:
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                # No session
            )

        mock_notes.assert_not_called()


# ---------------------------------------------------------------------------
# run_html_generation tests — Unknown choice
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationUnknownChoice:
    @pytest.mark.asyncio
    async def test_unknown_choice_loops_back(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Something Unknown"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        assert isinstance(result, HtmlGenerationResult)
        assert slack.send_and_wait_form.call_count == 2


# ---------------------------------------------------------------------------
# run_html_generation tests — Slack message content
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationSlackMessages:
    @pytest.mark.asyncio
    async def test_shares_doc_link_in_message(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }
        docs = _make_docs_mock("html-doc-link")

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                docs=docs,
                session=AsyncMock(),
            )

        # First channel message should include doc URL
        first_msg_call = slack.send_channel_message.call_args_list[0]
        msg_text = first_msg_call.args[0]
        assert "html-doc-link" in msg_text

    @pytest.mark.asyncio
    async def test_sends_form_with_correct_params(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    return_value=_mock_llm_response(SAMPLE_HTML)), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]):
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        form_call = slack.send_and_wait_form.call_args
        assert form_call.kwargs["button_label"] == NEXT_STEPS_BUTTON_LABEL
        assert form_call.kwargs["form_title"] == NEXT_STEPS_FORM_TITLE
        assert form_call.kwargs["form_description"] == NEXT_STEPS_FORM_DESCRIPTION


# ---------------------------------------------------------------------------
# run_html_generation tests — Content validity
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationContentValidity:
    @pytest.mark.asyncio
    async def test_invalid_regen_falls_back_to_original(self):
        """When regenerated HTML doesn't contain DOCTYPE, router falls back."""
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "Fix it"

        invalid_regen = "<html>missing doctype</html>"
        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)  # initial
            if call_count == 2:
                return _mock_llm_response(invalid_regen)  # regen (invalid)
            return _mock_llm_response('{"learning_feedback": "x"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock):
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        # Result should contain original HTML (fallback due to invalid regen)
        assert "<!DOCTYPE html>" in result.html

    @pytest.mark.asyncio
    async def test_valid_regen_uses_regenerated(self):
        """When regenerated HTML contains DOCTYPE, router uses it."""
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "Fix the intro"

        regen_html = "<!DOCTYPE html><html>REGEN VERSION</html>"
        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)
            if call_count == 2:
                return _mock_llm_response(regen_html)
            return _mock_llm_response('{"learning_feedback": "x"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock):
            result = await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
            )

        assert "REGEN VERSION" in result.html


# ---------------------------------------------------------------------------
# run_html_generation tests — Newsletter ID propagation
# ---------------------------------------------------------------------------


class TestRunHtmlGenerationNewsletterId:
    @pytest.mark.asyncio
    async def test_passes_newsletter_id_to_feedback(self):
        slack = _make_slack_mock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(SAMPLE_HTML)
            if call_count == 2:
                return _mock_llm_response(SAMPLE_HTML)
            return _mock_llm_response('{"learning_feedback": "note"}')

        with patch("ica.pipeline.html_generation.litellm.acompletion",
                    side_effect=mock_acompletion), \
             patch("ica.pipeline.html_generation.get_model",
                    return_value="m"), \
             patch("ica.pipeline.html_generation.get_recent_notes",
                    new_callable=AsyncMock, return_value=[]), \
             patch("ica.pipeline.html_generation.add_note",
                    new_callable=AsyncMock) as mock_add_note:
            await run_html_generation(
                SAMPLE_MARKDOWN,
                SAMPLE_HTML_TEMPLATE,
                SAMPLE_DATE,
                slack=slack,
                session=AsyncMock(),
                newsletter_id="nl-99",
            )

        mock_add_note.assert_called_once()
        assert mock_add_note.call_args.kwargs["newsletter_id"] == "nl-99"
