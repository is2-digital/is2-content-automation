"""Tests for the LinkedIn carousel generator pipeline step.

Covers:
- SlideError data class and serialization
- Character validation (validate_slide_bodies)
- Form builder (build_next_steps_form)
- LLM call wrappers (carousel generation, regeneration)
- Generation with validation retry loop
- Google Doc creation
- Full orchestration (run_linkedin_carousel_generation)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.linkedin_carousel import (
    APPROVAL_MESSAGE,
    FEEDBACK_BUTTON_LABEL,
    FEEDBACK_FORM_DESCRIPTION,
    FEEDBACK_FORM_TITLE,
    FEEDBACK_MESSAGE,
    GOOGLE_DOC_TITLE,
    MAX_CHARS,
    MAX_VALIDATION_ATTEMPTS,
    MIN_CHARS,
    NEXT_STEPS_BUTTON_LABEL,
    NEXT_STEPS_FIELD,
    NEXT_STEPS_FORM_DESCRIPTION,
    NEXT_STEPS_FORM_TITLE,
    NEXT_STEPS_MESSAGE,
    NEXT_STEPS_OPTIONS,
    SLACK_CHANNEL,
    LinkedInCarouselResult,
    SlideError,
    ValidationResult,
    build_next_steps_form,
    call_carousel_llm,
    call_regeneration_llm,
    create_carousel_doc,
    generate_with_validation,
    run_linkedin_carousel_generation,
    validate_slide_bodies,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_FORMATTED_THEME: dict[str, object] = {
    "THEME": "THEME: AI Automation in Business",
    "FEATURED ARTICLE": {
        "Title": "Featured Article Title",
        "Source": "1",
        "URL": "https://example.com/featured",
    },
    "MAIN ARTICLE 1": {
        "Title": "Main Article 1 Title",
        "Source": "2",
        "URL": "https://example.com/main1",
    },
    "MAIN ARTICLE 2": {
        "Title": "Main Article 2 Title",
        "Source": "3",
        "URL": "https://example.com/main2",
    },
    "QUICK HIT 1": {
        "Title": "Quick Hit 1 Title",
        "Source": "4",
        "URL": "https://example.com/qh1",
    },
    "QUICK HIT 2": {
        "Title": "Quick Hit 2 Title",
        "Source": "5",
        "URL": "https://example.com/qh2",
    },
    "QUICK HIT 3": {
        "Title": "Quick Hit 3 Title",
        "Source": "6",
        "URL": "https://example.com/qh3",
    },
    "INDUSTRY DEVELOPMENT 1": {
        "Title": "Industry Dev 1 Title",
        "Source": "7",
        "URL": "https://example.com/id1",
    },
    "INDUSTRY DEVELOPMENT 2": {
        "Title": "Industry Dev 2 Title",
        "Source": "8",
        "URL": "https://example.com/id2",
    },
}


def _make_body(char_count: int, *, offset: int = 4) -> str:
    """Create a body text that yields exactly ``char_count`` after the -4 offset.

    The validator trims trailing whitespace and subtracts 4 from the length.
    So we produce a string of ``char_count + offset`` non-whitespace characters.
    """
    total = char_count + offset
    return "x" * total


def _make_slide_output(*bodies: str) -> str:
    """Build a minimal LLM output string with ``*Body:*`` sections."""
    parts: list[str] = []
    for i, body in enumerate(bodies, start=3):
        parts.append(f"*Slide {i}: Title {i}*\n*Title:* Title {i}\n\n*Body:*\n{body}")
    return "\n\n---\n\n".join(parts)


def _make_valid_body() -> str:
    """Return a body that passes validation (290 chars after -4 offset)."""
    return _make_body(290)


def _make_short_body() -> str:
    """Return a body that fails validation — too short (200 chars)."""
    return _make_body(200)


def _make_long_body() -> str:
    """Return a body that fails validation — too long (400 chars)."""
    return _make_body(400)


def _mock_llm_response(text: str) -> MagicMock:
    """Build a mock litellm.acompletion response."""
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# SlideError
# ═══════════════════════════════════════════════════════════════════════════


class TestSlideError:
    """Tests for the SlideError dataclass."""

    def test_frozen(self) -> None:
        err = SlideError(slide_body="test", actual_characters=100)
        with pytest.raises(AttributeError):
            err.slide_body = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        err = SlideError(slide_body="body", actual_characters=250)
        assert err.required_range == "265-315"
        assert err.error_type == "CHARACTER_LIMIT_VIOLATION"
        assert err.severity == "ERROR"
        assert "265-315" in err.instruction

    def test_to_dict_keys(self) -> None:
        err = SlideError(slide_body="body text", actual_characters=250)
        d = err.to_dict()
        assert d["slide_body"] == "body text"
        assert d["type"] == "CHARACTER_LIMIT_VIOLATION"
        assert d["severity"] == "ERROR"
        assert d["actualCharacters"] == 250
        assert d["requiredRange"] == "265-315"
        assert "instruction" in d

    def test_to_dict_serializable(self) -> None:
        err = SlideError(slide_body="test", actual_characters=300)
        # Must be JSON-serializable
        json.dumps(err.to_dict())


# ═══════════════════════════════════════════════════════════════════════════
# validate_slide_bodies
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateSlidesBodies:
    """Tests for slide body character validation."""

    def test_no_body_markers(self) -> None:
        result = validate_slide_bodies("No body markers here")
        assert result.errors == []
        assert result.annotated_output == "No body markers here"

    def test_single_valid_body(self) -> None:
        body = _make_valid_body()
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert result.errors == []
        assert "*Character count:* 290 characters" in result.annotated_output

    def test_single_short_body(self) -> None:
        body = _make_short_body()
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert len(result.errors) == 1
        assert result.errors[0].actual_characters == 200
        assert result.errors[0].error_type == "CHARACTER_LIMIT_VIOLATION"

    def test_single_long_body(self) -> None:
        body = _make_long_body()
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert len(result.errors) == 1
        assert result.errors[0].actual_characters == 400

    def test_multiple_bodies_all_valid(self) -> None:
        raw = _make_slide_output(
            _make_valid_body(),
            _make_valid_body(),
            _make_valid_body(),
        )
        result = validate_slide_bodies(raw)
        assert result.errors == []
        assert result.annotated_output.count("*Character count:*") == 3

    def test_multiple_bodies_mixed(self) -> None:
        raw = _make_slide_output(
            _make_valid_body(),
            _make_short_body(),
            _make_valid_body(),
        )
        result = validate_slide_bodies(raw)
        assert len(result.errors) == 1
        assert result.errors[0].actual_characters == 200

    def test_errors_in_slide_order(self) -> None:
        raw = _make_slide_output(
            _make_short_body(),
            _make_long_body(),
        )
        result = validate_slide_bodies(raw)
        assert len(result.errors) == 2
        # First error should be for the short body
        assert result.errors[0].actual_characters == 200
        # Second error for the long body
        assert result.errors[1].actual_characters == 400

    def test_boundary_min_exactly(self) -> None:
        body = _make_body(MIN_CHARS)
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert result.errors == []

    def test_boundary_max_exactly(self) -> None:
        body = _make_body(MAX_CHARS)
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert result.errors == []

    def test_boundary_one_below_min(self) -> None:
        body = _make_body(MIN_CHARS - 1)
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert len(result.errors) == 1

    def test_boundary_one_above_max(self) -> None:
        body = _make_body(MAX_CHARS + 1)
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert len(result.errors) == 1

    def test_trailing_whitespace_stripped(self) -> None:
        """Trailing whitespace on body should be trimmed before counting."""
        body = _make_valid_body() + "   \n  "
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert result.errors == []

    def test_body_before_next_slide(self) -> None:
        """Body followed by *Slide marker should be parsed correctly."""
        body = _make_valid_body()
        raw = f"*Body:*\n{body}\n\n*Slide 4: Next*"
        result = validate_slide_bodies(raw)
        assert result.errors == []

    def test_body_before_separator(self) -> None:
        """Body followed by --- separator should be parsed correctly."""
        body = _make_valid_body()
        raw = f"*Body:*\n{body}\n\n---\n\nOther section"
        result = validate_slide_bodies(raw)
        assert result.errors == []

    def test_annotation_appended(self) -> None:
        body = _make_body(290)
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert "*Character count:* 290 characters" in result.annotated_output

    def test_eight_slides_all_valid(self) -> None:
        """Full 8-slide output (Slides 3-10) with all valid bodies."""
        bodies = [_make_valid_body() for _ in range(8)]
        raw = _make_slide_output(*bodies)
        result = validate_slide_bodies(raw)
        assert result.errors == []
        assert result.annotated_output.count("*Character count:*") == 8

    def test_error_slide_body_preserved(self) -> None:
        """The error should contain the exact slide body text."""
        body = _make_short_body()
        raw = f"*Body:*\n{body}"
        result = validate_slide_bodies(raw)
        assert result.errors[0].slide_body == body

    def test_returns_validation_result_type(self) -> None:
        result = validate_slide_bodies("")
        assert isinstance(result, ValidationResult)


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════


class TestConstants:
    """Tests for module-level constants."""

    def test_min_max_chars(self) -> None:
        assert MIN_CHARS == 265
        assert MAX_CHARS == 315

    def test_max_validation_attempts(self) -> None:
        assert MAX_VALIDATION_ATTEMPTS == 2

    def test_slack_channel(self) -> None:
        assert SLACK_CHANNEL == "#n8n-is2"

    def test_next_steps_options(self) -> None:
        assert NEXT_STEPS_OPTIONS == ["Yes", "Regenerate", "Provide Feedback"]

    def test_google_doc_title(self) -> None:
        assert GOOGLE_DOC_TITLE == "Linkedin-posts"


# ═══════════════════════════════════════════════════════════════════════════
# build_next_steps_form
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildNextStepsForm:
    """Tests for the Slack form builder."""

    def test_returns_list(self) -> None:
        form = build_next_steps_form()
        assert isinstance(form, list)
        assert len(form) == 1

    def test_field_label(self) -> None:
        form = build_next_steps_form()
        assert form[0]["fieldLabel"] == NEXT_STEPS_FIELD

    def test_field_type_dropdown(self) -> None:
        form = build_next_steps_form()
        assert form[0]["fieldType"] == "dropdown"

    def test_required_field(self) -> None:
        form = build_next_steps_form()
        assert form[0]["requiredField"] is True

    def test_three_options(self) -> None:
        form = build_next_steps_form()
        options = form[0]["fieldOptions"]
        assert isinstance(options, dict)
        values = options["values"]
        assert len(values) == 3

    def test_option_values(self) -> None:
        form = build_next_steps_form()
        options = form[0]["fieldOptions"]["values"]
        labels = [v["option"] for v in options]
        assert labels == ["Yes", "Regenerate", "Provide Feedback"]

    def test_json_serializable(self) -> None:
        form = build_next_steps_form()
        json.dumps(form)


# ═══════════════════════════════════════════════════════════════════════════
# call_carousel_llm
# ═══════════════════════════════════════════════════════════════════════════


class TestCallCarouselLlm:
    """Tests for the LLM generation call."""

    @pytest.mark.asyncio
    async def test_returns_stripped_content(self) -> None:
        mock_resp = _mock_llm_response("  carousel output  ")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            result = await call_carousel_llm(
                formatted_theme="{}",
                newsletter_content="<html>content</html>",
            )
        assert result == "carousel output"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self) -> None:
        mock_resp = _mock_llm_response("")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_carousel_llm(
                    formatted_theme="{}",
                    newsletter_content="content",
                )

    @pytest.mark.asyncio
    async def test_raises_on_whitespace_only(self) -> None:
        mock_resp = _mock_llm_response("   \n  ")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_carousel_llm(
                    formatted_theme="{}",
                    newsletter_content="content",
                )

    @pytest.mark.asyncio
    async def test_uses_default_model(self) -> None:
        mock_resp = _mock_llm_response("output")
        with (
            patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm,
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_carousel_llm(
                formatted_theme="{}",
                newsletter_content="content",
            )
            call_args = mock_litellm.acompletion.call_args
            assert call_args.kwargs["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_model_override(self) -> None:
        mock_resp = _mock_llm_response("output")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_carousel_llm(
                formatted_theme="{}",
                newsletter_content="content",
                model="custom/model",
            )
            call_args = mock_litellm.acompletion.call_args
            assert call_args.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_passes_previous_output(self) -> None:
        """When previous_output is provided, it should appear in the prompt."""
        mock_resp = _mock_llm_response("output")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_carousel_llm(
                formatted_theme="{}",
                newsletter_content="content",
                previous_output="previous content with errors",
            )
            call_args = mock_litellm.acompletion.call_args
            messages = call_args.kwargs["messages"]
            user_msg = messages[1]["content"]
            assert "previous content with errors" in user_msg

    @pytest.mark.asyncio
    async def test_system_and_user_messages(self) -> None:
        mock_resp = _mock_llm_response("output")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_carousel_llm(
                formatted_theme="theme data",
                newsletter_content="html content",
            )
            call_args = mock_litellm.acompletion.call_args
            messages = call_args.kwargs["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"


# ═══════════════════════════════════════════════════════════════════════════
# call_regeneration_llm
# ═══════════════════════════════════════════════════════════════════════════


class TestCallRegenerationLlm:
    """Tests for the feedback-driven regeneration LLM call."""

    @pytest.mark.asyncio
    async def test_returns_stripped_content(self) -> None:
        mock_resp = _mock_llm_response("  regenerated output  ")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            result = await call_regeneration_llm(
                previous_output="original",
                feedback_text="fix the title",
                formatted_theme="{}",
                newsletter_content="html",
            )
        assert result == "regenerated output"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self) -> None:
        mock_resp = _mock_llm_response("")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_regeneration_llm(
                    previous_output="original",
                    feedback_text="fix it",
                    formatted_theme="{}",
                    newsletter_content="html",
                )

    @pytest.mark.asyncio
    async def test_uses_regeneration_model(self) -> None:
        mock_resp = _mock_llm_response("output")
        with (
            patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm,
            patch(
                "ica.pipeline.linkedin_carousel.get_model",
                return_value="regen-model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_regeneration_llm(
                previous_output="original",
                feedback_text="fix",
                formatted_theme="{}",
                newsletter_content="html",
            )
            call_args = mock_litellm.acompletion.call_args
            assert call_args.kwargs["model"] == "regen-model"

    @pytest.mark.asyncio
    async def test_model_override(self) -> None:
        mock_resp = _mock_llm_response("output")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_regeneration_llm(
                previous_output="original",
                feedback_text="fix",
                formatted_theme="{}",
                newsletter_content="html",
                model="my/custom",
            )
            call_args = mock_litellm.acompletion.call_args
            assert call_args.kwargs["model"] == "my/custom"

    @pytest.mark.asyncio
    async def test_passes_feedback_in_prompt(self) -> None:
        mock_resp = _mock_llm_response("output")
        with patch("ica.pipeline.linkedin_carousel.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_resp)
            await call_regeneration_llm(
                previous_output="original",
                feedback_text="make slide 5 shorter",
                formatted_theme="{}",
                newsletter_content="html",
            )
            call_args = mock_litellm.acompletion.call_args
            messages = call_args.kwargs["messages"]
            user_msg = messages[1]["content"]
            assert "make slide 5 shorter" in user_msg


# ═══════════════════════════════════════════════════════════════════════════
# generate_with_validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerateWithValidation:
    """Tests for the generation + validation retry loop."""

    @pytest.mark.asyncio
    async def test_passes_on_first_try(self) -> None:
        """When all slides are valid, returns immediately."""
        valid_output = _make_slide_output(_make_valid_body(), _make_valid_body())
        with patch(
            "ica.pipeline.linkedin_carousel.call_carousel_llm",
            new_callable=AsyncMock,
            return_value=valid_output,
        ) as mock_llm:
            output, errors = await generate_with_validation(
                formatted_theme="{}",
                newsletter_content="html",
            )
        assert errors == []
        assert "*Character count:*" in output
        assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_validation_error(self) -> None:
        """When first output has errors, retries with error context."""
        short_output = _make_slide_output(_make_short_body())
        valid_output = _make_slide_output(_make_valid_body())

        call_count = 0

        async def fake_llm(*args: object, **kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return short_output
            return valid_output

        with patch(
            "ica.pipeline.linkedin_carousel.call_carousel_llm",
            side_effect=fake_llm,
        ):
            output, errors = await generate_with_validation(
                formatted_theme="{}",
                newsletter_content="html",
            )
        assert errors == []
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_force_accepts_after_max_attempts(self) -> None:
        """After max_attempts, accepts output regardless of errors."""
        short_output = _make_slide_output(_make_short_body())

        with patch(
            "ica.pipeline.linkedin_carousel.call_carousel_llm",
            new_callable=AsyncMock,
            return_value=short_output,
        ) as mock_llm:
            output, errors = await generate_with_validation(
                formatted_theme="{}",
                newsletter_content="html",
                max_attempts=2,
            )
        # After 2 attempts, errors are cleared (force-accept)
        assert errors == []
        # First call + 1 retry = 2 calls total
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_includes_error_context(self) -> None:
        """The retry call should include character_errors in previous_output."""
        short_output = _make_slide_output(_make_short_body())
        valid_output = _make_slide_output(_make_valid_body())

        call_args_list: list[dict[str, object]] = []

        async def fake_llm(**kwargs: object) -> str:
            call_args_list.append(kwargs)
            if len(call_args_list) == 1:
                return short_output
            return valid_output

        with patch(
            "ica.pipeline.linkedin_carousel.call_carousel_llm",
            side_effect=fake_llm,
        ):
            await generate_with_validation(
                formatted_theme="{}",
                newsletter_content="html",
            )

        # Second call should have previous_output with errors
        assert len(call_args_list) == 2
        prev_output = call_args_list[1].get("previous_output", "")
        assert "character_errors" in str(prev_output)
        assert "CHARACTER_LIMIT_VIOLATION" in str(prev_output)

    @pytest.mark.asyncio
    async def test_max_attempts_one(self) -> None:
        """With max_attempts=1, never retries."""
        short_output = _make_slide_output(_make_short_body())

        with patch(
            "ica.pipeline.linkedin_carousel.call_carousel_llm",
            new_callable=AsyncMock,
            return_value=short_output,
        ) as mock_llm:
            output, errors = await generate_with_validation(
                formatted_theme="{}",
                newsletter_content="html",
                max_attempts=1,
            )
        assert mock_llm.call_count == 1
        assert errors == []  # force-accepted

    @pytest.mark.asyncio
    async def test_no_body_markers_no_errors(self) -> None:
        """Output with no *Body:* markers passes validation trivially."""
        with patch(
            "ica.pipeline.linkedin_carousel.call_carousel_llm",
            new_callable=AsyncMock,
            return_value="Post copy only, no slides",
        ):
            output, errors = await generate_with_validation(
                formatted_theme="{}",
                newsletter_content="html",
            )
        assert errors == []


# ═══════════════════════════════════════════════════════════════════════════
# create_carousel_doc
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateCarouselDoc:
    """Tests for Google Doc creation."""

    @pytest.mark.asyncio
    async def test_creates_doc_with_content(self) -> None:
        docs = AsyncMock()
        docs.create_document = AsyncMock(return_value="doc-id-123")
        docs.insert_content = AsyncMock()

        doc_id, doc_url = await create_carousel_doc(docs, "carousel content")

        assert doc_id == "doc-id-123"
        assert "doc-id-123" in doc_url
        docs.create_document.assert_awaited_once_with(GOOGLE_DOC_TITLE)
        docs.insert_content.assert_awaited_once_with("doc-id-123", "carousel content")

    @pytest.mark.asyncio
    async def test_custom_title(self) -> None:
        docs = AsyncMock()
        docs.create_document = AsyncMock(return_value="doc-456")
        docs.insert_content = AsyncMock()

        await create_carousel_doc(docs, "content", title="Custom Title")
        docs.create_document.assert_awaited_once_with("Custom Title")

    @pytest.mark.asyncio
    async def test_doc_url_format(self) -> None:
        docs = AsyncMock()
        docs.create_document = AsyncMock(return_value="abc")
        docs.insert_content = AsyncMock()

        _, doc_url = await create_carousel_doc(docs, "content")
        assert doc_url == "https://docs.google.com/document/d/abc/edit"


# ═══════════════════════════════════════════════════════════════════════════
# run_linkedin_carousel_generation — full orchestration
# ═══════════════════════════════════════════════════════════════════════════


class TestRunLinkedInCarouselGeneration:
    """Tests for the full orchestration function."""

    def _setup_slack(
        self,
        *,
        next_steps_choice: str = "Yes",
        feedback_text: str = "improve it",
    ) -> AsyncMock:
        """Build a mock Slack handler with configurable responses."""
        slack = AsyncMock()
        slack.send_and_wait = AsyncMock(return_value="approved")
        slack.send_channel_message = AsyncMock()
        slack.send_and_wait_freetext = AsyncMock(return_value=feedback_text)

        # Form response: the next-steps dropdown
        slack.send_and_wait_form = AsyncMock(return_value={NEXT_STEPS_FIELD: next_steps_choice})

        return slack

    def _setup_docs(self, *, content: str = "<html>newsletter</html>") -> AsyncMock:
        docs = AsyncMock()
        docs.get_content = AsyncMock(return_value=content)
        docs.create_document = AsyncMock(return_value="new-doc-id")
        docs.insert_content = AsyncMock()
        return docs

    @pytest.mark.asyncio
    async def test_happy_path_yes(self) -> None:
        """User approves → Google Doc created → result returned."""
        slack = self._setup_slack(next_steps_choice="Yes")
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch(
                "ica.pipeline.linkedin_carousel.get_model",
                return_value="anthropic/claude-sonnet-4.5",
            ),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert isinstance(result, LinkedInCarouselResult)
        assert result.doc_id == "new-doc-id"
        assert "new-doc-id" in result.doc_url
        assert result.model == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_sends_approval_first(self) -> None:
        """Should send approval message before generating."""
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        slack.send_and_wait.assert_awaited_once()
        call_args = slack.send_and_wait.call_args
        assert call_args.args[0] == SLACK_CHANNEL
        assert call_args.args[1] == APPROVAL_MESSAGE

    @pytest.mark.asyncio
    async def test_fetches_html_content(self) -> None:
        """Should fetch HTML from Google Docs."""
        slack = self._setup_slack()
        docs = self._setup_docs(content="my html content")
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ) as mock_gen,
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="html-doc-abc",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        docs.get_content.assert_awaited_once_with("html-doc-abc")

    @pytest.mark.asyncio
    async def test_shares_content_in_slack(self) -> None:
        """After generation, content should be shared in Slack."""
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # First send_channel_message call should be the content
        calls = slack.send_channel_message.call_args_list
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_shares_doc_link_after_creation(self) -> None:
        """After creating the doc, the link should be shared in Slack."""
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # Last send_channel_message call should contain the doc URL
        last_call = slack.send_channel_message.call_args_list[-1]
        assert "new-doc-id" in last_call.args[0]
        assert "usp=sharing" in last_call.args[0]

    @pytest.mark.asyncio
    async def test_feedback_loop(self) -> None:
        """Feedback → regeneration → re-share → approve."""
        call_count = 0

        async def form_responses(*args: object, **kwargs: object) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {NEXT_STEPS_FIELD: "Provide Feedback"}
            return {NEXT_STEPS_FIELD: "Yes"}

        slack = self._setup_slack()
        slack.send_and_wait_form = AsyncMock(side_effect=form_responses)
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch(
                "ica.pipeline.linkedin_carousel.call_regeneration_llm",
                new_callable=AsyncMock,
                return_value="regenerated carousel content",
            ) as mock_regen,
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # Feedback was collected
        slack.send_and_wait_freetext.assert_awaited_once()
        # Regeneration was called
        mock_regen.assert_awaited_once()
        # Result uses the regenerated content
        assert result.final_content == "regenerated carousel content"

    @pytest.mark.asyncio
    async def test_regenerate_choice(self) -> None:
        """Regenerate → full re-generation → approve."""
        call_count = 0

        async def form_responses(*args: object, **kwargs: object) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {NEXT_STEPS_FIELD: "Regenerate"}
            return {NEXT_STEPS_FIELD: "Yes"}

        slack = self._setup_slack()
        slack.send_and_wait_form = AsyncMock(side_effect=form_responses)
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ) as mock_gen,
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # generate_with_validation called twice (initial + regeneration)
        assert mock_gen.call_count == 2
        # Docs re-fetched content for regeneration
        assert docs.get_content.call_count >= 2

    @pytest.mark.asyncio
    async def test_no_docs_service(self) -> None:
        """Works without Google Docs service — returns empty doc_id/url."""
        slack = self._setup_slack()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=None,
            )

        assert result.doc_id == ""
        assert result.doc_url == ""
        assert result.final_content == valid_output

    @pytest.mark.asyncio
    async def test_next_steps_form_configuration(self) -> None:
        """The next-steps form should use correct labels and options."""
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        form_call = slack.send_and_wait_form.call_args
        assert form_call.args[0] == NEXT_STEPS_MESSAGE
        assert form_call.kwargs["button_label"] == NEXT_STEPS_BUTTON_LABEL
        assert form_call.kwargs["form_title"] == NEXT_STEPS_FORM_TITLE
        assert form_call.kwargs["form_description"] == NEXT_STEPS_FORM_DESCRIPTION

    @pytest.mark.asyncio
    async def test_feedback_form_configuration(self) -> None:
        """The feedback form should use correct labels."""
        call_count = 0

        async def form_responses(*args: object, **kwargs: object) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {NEXT_STEPS_FIELD: "Provide Feedback"}
            return {NEXT_STEPS_FIELD: "Yes"}

        slack = self._setup_slack()
        slack.send_and_wait_form = AsyncMock(side_effect=form_responses)
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch(
                "ica.pipeline.linkedin_carousel.call_regeneration_llm",
                new_callable=AsyncMock,
                return_value="regen output",
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        feedback_call = slack.send_and_wait_freetext.call_args
        assert feedback_call.args[0] == FEEDBACK_MESSAGE
        assert feedback_call.kwargs["button_label"] == FEEDBACK_BUTTON_LABEL
        assert feedback_call.kwargs["form_title"] == FEEDBACK_FORM_TITLE
        assert feedback_call.kwargs["form_description"] == FEEDBACK_FORM_DESCRIPTION

    @pytest.mark.asyncio
    async def test_formatted_theme_serialized(self) -> None:
        """formatted_theme dict should be JSON-serialized for LLM calls."""
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ) as mock_gen,
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        gen_call = mock_gen.call_args
        theme_str = gen_call.kwargs["formatted_theme"]
        # Should be valid JSON
        parsed = json.loads(theme_str)
        assert "FEATURED ARTICLE" in parsed

    @pytest.mark.asyncio
    async def test_unknown_choice_loops(self) -> None:
        """Unknown choice should loop back to form."""
        call_count = 0

        async def form_responses(*args: object, **kwargs: object) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {NEXT_STEPS_FIELD: "Something Random"}
            return {NEXT_STEPS_FIELD: "Yes"}

        slack = self._setup_slack()
        slack.send_and_wait_form = AsyncMock(side_effect=form_responses)
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # Form was shown twice
        assert slack.send_and_wait_form.call_count == 2
        assert isinstance(result, LinkedInCarouselResult)

    @pytest.mark.asyncio
    async def test_multiple_feedback_rounds(self) -> None:
        """User provides feedback multiple times before approving."""
        call_count = 0

        async def form_responses(*args: object, **kwargs: object) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {NEXT_STEPS_FIELD: "Provide Feedback"}
            return {NEXT_STEPS_FIELD: "Yes"}

        slack = self._setup_slack()
        slack.send_and_wait_form = AsyncMock(side_effect=form_responses)
        docs = self._setup_docs()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch(
                "ica.pipeline.linkedin_carousel.call_regeneration_llm",
                new_callable=AsyncMock,
                return_value="final regen",
            ) as mock_regen,
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # Regeneration called twice
        assert mock_regen.call_count == 2
        # Final content uses the regenerated version
        assert result.final_content == "final regen"

    @pytest.mark.asyncio
    async def test_regeneration_uses_latest_output(self) -> None:
        """Second feedback round uses the first regeneration as base."""
        call_count = 0
        regen_inputs: list[str] = []

        async def form_responses(*args: object, **kwargs: object) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {NEXT_STEPS_FIELD: "Provide Feedback"}
            return {NEXT_STEPS_FIELD: "Yes"}

        regen_count = 0

        async def fake_regen(previous_output: str, **kwargs: object) -> str:
            nonlocal regen_count
            regen_inputs.append(previous_output)
            regen_count += 1
            return f"regen-{regen_count}"

        slack = self._setup_slack()
        slack.send_and_wait_form = AsyncMock(side_effect=form_responses)
        docs = self._setup_docs()
        valid_output = "original validated output"

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch(
                "ica.pipeline.linkedin_carousel.call_regeneration_llm",
                side_effect=fake_regen,
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # First regen: base is the original validated output
        assert regen_inputs[0] == valid_output
        # Second regen: base is the first regeneration
        assert regen_inputs[1] == "regen-1"
        assert result.final_content == "regen-2"

    @pytest.mark.asyncio
    async def test_doc_creation_on_approval(self) -> None:
        """Google Doc is created with the final output content."""
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = "Final carousel content"

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        docs.create_document.assert_awaited_once_with(GOOGLE_DOC_TITLE)
        docs.insert_content.assert_awaited_once_with("new-doc-id", valid_output)

    @pytest.mark.asyncio
    async def test_no_doc_link_shared_without_docs(self) -> None:
        """When docs is None, no doc link message is shared."""
        slack = self._setup_slack()
        valid_output = _make_slide_output(_make_valid_body())

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch("ica.pipeline.linkedin_carousel.get_model", return_value="m"),
        ):
            await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=None,
            )

        # Only the content share message is sent (no doc link)
        calls = slack.send_channel_message.call_args_list
        assert len(calls) == 1  # just the content display

    @pytest.mark.asyncio
    async def test_result_dataclass_fields(self) -> None:
        slack = self._setup_slack()
        docs = self._setup_docs()
        valid_output = "carousel text"

        with (
            patch(
                "ica.pipeline.linkedin_carousel.generate_with_validation",
                new_callable=AsyncMock,
                return_value=(valid_output, []),
            ),
            patch(
                "ica.pipeline.linkedin_carousel.get_model",
                return_value="test/model-id",
            ),
        ):
            result = await run_linkedin_carousel_generation(
                html_doc_id="doc-1",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert result.doc_id == "new-doc-id"
        assert result.doc_url == "https://docs.google.com/document/d/new-doc-id/edit"
        assert result.final_content == "carousel text"
        assert result.model == "test/model-id"


# ═══════════════════════════════════════════════════════════════════════════
# LinkedInCarouselResult
# ═══════════════════════════════════════════════════════════════════════════


class TestLinkedInCarouselResult:
    """Tests for the result data class."""

    def test_frozen(self) -> None:
        result = LinkedInCarouselResult(
            doc_id="id",
            doc_url="url",
            final_content="text",
            model="model",
        )
        with pytest.raises(AttributeError):
            result.doc_id = "other"  # type: ignore[misc]

    def test_fields(self) -> None:
        result = LinkedInCarouselResult(
            doc_id="d",
            doc_url="u",
            final_content="c",
            model="m",
        )
        assert result.doc_id == "d"
        assert result.doc_url == "u"
        assert result.final_content == "c"
        assert result.model == "m"
