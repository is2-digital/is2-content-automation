"""Tests for markdown generation pipeline step (Step 4).

Tests cover:
- MarkdownGenerationResult dataclass
- ValidationResult dataclass
- SlackMarkdownReview protocol
- GoogleDocsWriter protocol
- aggregate_feedback: notes → bullet-point string
- call_markdown_llm: generation and regeneration LLM calls
- format_char_errors_json: character errors → JSON
- run_structural_validation: Layer 2 LLM validation
- run_voice_validation: Layer 3 LLM validation
- _parse_validation_response: JSON response parsing
- run_three_layer_validation: combined validation pipeline
- generate_with_validation: validation + retry loop
- build_next_steps_form: dropdown form definition
- parse_next_steps_response: dropdown value → UserChoice
- call_user_feedback_regeneration: user feedback LLM regeneration
- extract_markdown_learning_data: learning data extraction with JSON parsing
- store_markdown_feedback: notes table insertion
- create_markdown_doc: Google Doc creation
- run_markdown_review: orchestrated review loop with feedback
- Constants: Slack field labels, messages
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.errors import LLMError
from ica.pipeline.markdown_generation import (
    FEEDBACK_BUTTON_LABEL,
    FEEDBACK_FORM_TITLE,
    FEEDBACK_MESSAGE,
    GOOGLE_DOC_TITLE,
    MARKDOWN_REVIEW_HEADER,
    NEXT_STEPS_BUTTON_LABEL,
    NEXT_STEPS_FIELD_LABEL,
    NEXT_STEPS_FORM_DESCRIPTION,
    NEXT_STEPS_FORM_TITLE,
    NEXT_STEPS_OPTIONS,
    MarkdownGenerationResult,
    ValidationResult,
    _parse_validation_response,
    aggregate_feedback,
    build_next_steps_form,
    call_markdown_llm,
    call_user_feedback_regeneration,
    create_markdown_doc,
    extract_markdown_learning_data,
    format_char_errors_json,
    generate_with_validation,
    parse_next_steps_response,
    run_markdown_review,
    run_structural_validation,
    run_three_layer_validation,
    run_voice_validation,
    store_markdown_feedback,
)
from ica.services.llm import LLMResponse
from ica.utils.output_router import UserChoice
from ica.validators.character_count import CharacterCountError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_FORMATTED_THEME = '{"theme": "AI Governance", "articles": []}'
SAMPLE_MARKDOWN = """# *INTRODUCTION*

This week's newsletter explores AI governance.

# *QUICK HIGHLIGHTS*

• Bullet one about featured article with bold terms.
• Bullet two about main article one content here.
• Bullet three about main article two details here.

# *FEATURED ARTICLE*

## Headline

Paragraph one of the featured article content here.

Paragraph two of the featured article content here.

**Strategic Insight:** Key insight paragraph here.

[Read more →](https://example.com/article)

# *MAIN ARTICLE 1*

## Main Article 1 Headline

Content paragraph for main article one here.

*Strategic Take-away:* Callout paragraph for main article one.

[Source →](https://example.com/main1)

# *MAIN ARTICLE 2*

## Main Article 2 Headline

Content paragraph for main article two here.

*Actionable Steps:* Callout for main article two content.

[Source →](https://example.com/main2)

# *QUICK HITS*

- [Quick Hit 1](https://example.com/qh1) - Summary
- [Quick Hit 2](https://example.com/qh2) - Summary
- [Quick Hit 3](https://example.com/qh3) - Summary

# *INDUSTRY DEVELOPMENTS*

- [Industry 1](https://example.com/ind1) - Summary
- [Industry 2](https://example.com/ind2) - Summary

# *FOOTER*

Alright, that's a wrap for the week!

Reflective paragraph here.

Thoughts?
"""


def _llm_response(content: str) -> LLMResponse:
    """Create an LLMResponse with stripped text, mirroring the completion() wrapper."""
    return LLMResponse(text=content.strip(), model="test-model")


def _make_note(feedback_text: str) -> MagicMock:
    """Create a mock Note row."""
    note = MagicMock()
    note.feedback_text = feedback_text
    return note


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------


class TestMarkdownGenerationResult:
    def test_creation(self):
        result = MarkdownGenerationResult(
            markdown="# Newsletter",
            markdown_doc_id="doc-123",
            doc_url="https://docs.google.com/document/d/doc-123/edit",
            model="anthropic/claude-sonnet-4.5",
        )
        assert result.markdown == "# Newsletter"
        assert result.markdown_doc_id == "doc-123"
        assert result.doc_url == "https://docs.google.com/document/d/doc-123/edit"
        assert result.model == "anthropic/claude-sonnet-4.5"

    def test_frozen(self):
        result = MarkdownGenerationResult(
            markdown="x",
            markdown_doc_id="y",
            doc_url="z",
            model="m",
        )
        with pytest.raises(AttributeError):
            result.markdown = "new"  # type: ignore[misc]


class TestValidationResult:
    def test_valid(self):
        result = ValidationResult(is_valid=True, errors=[], char_errors_json="[]")
        assert result.is_valid is True
        assert result.errors == []

    def test_invalid(self):
        result = ValidationResult(
            is_valid=False,
            errors=["err1", "err2"],
            char_errors_json='["err"]',
        )
        assert result.is_valid is False
        assert len(result.errors) == 2

    def test_frozen(self):
        result = ValidationResult(is_valid=True, errors=[], char_errors_json="[]")
        with pytest.raises(AttributeError):
            result.is_valid = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_next_steps_options(self):
        assert NEXT_STEPS_OPTIONS == ["Yes", "Provide Feedback", "Restart Chat"]

    def test_field_label(self):
        assert NEXT_STEPS_FIELD_LABEL == "Ready to proceed to next step ?"

    def test_review_header(self):
        assert MARKDOWN_REVIEW_HEADER == "# *INTRODUCTION*"

    def test_google_doc_title(self):
        assert GOOGLE_DOC_TITLE == "Newsletter Markdown"


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
        note = _make_note("Improve tone")
        result = aggregate_feedback([note])
        assert result == "\u2022 Improve tone"

    def test_multiple_notes(self):
        notes = [_make_note("Note 1"), _make_note("Note 2")]
        result = aggregate_feedback(notes)
        assert result == "\u2022 Note 1\n\u2022 Note 2"

    def test_skips_empty_feedback(self):
        notes = [_make_note("Good"), _make_note(""), _make_note("Better")]
        result = aggregate_feedback(notes)
        assert result == "\u2022 Good\n\u2022 Better"


# ---------------------------------------------------------------------------
# call_markdown_llm tests
# ---------------------------------------------------------------------------


class TestCallMarkdownLlm:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        mock_resp = _llm_response(SAMPLE_MARKDOWN)
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            result = await call_markdown_llm(
                SAMPLE_FORMATTED_THEME,
                model="test-model",
            )
            assert "INTRODUCTION" in result
            mock_call.assert_called_once()
            call_args = mock_call.call_args
            assert call_args.kwargs["model"] == "test-model"
            assert call_args.kwargs["purpose"].name == "MARKDOWN"
            assert "system_prompt" in call_args.kwargs
            assert "user_prompt" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_with_feedback(self):
        mock_resp = _llm_response("# *INTRODUCTION*\nContent")
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            await call_markdown_llm(
                SAMPLE_FORMATTED_THEME,
                aggregated_feedback="• feedback note",
                model="test-model",
            )
            assert "feedback note" in mock_call.call_args.kwargs["user_prompt"]

    @pytest.mark.asyncio
    async def test_with_validator_errors(self):
        mock_resp = _llm_response("# *INTRODUCTION*\nFixed")
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            await call_markdown_llm(
                SAMPLE_FORMATTED_THEME,
                previous_markdown="old markdown",
                validator_errors="err1\nerr2",
                model="test-model",
            )
            # Shared system prompt has no {previous_markdown} placeholder;
            # format() is a no-op so previous markdown is NOT in system prompt.
            assert "old markdown" not in mock_call.call_args.kwargs["system_prompt"]
            assert "err1" in mock_call.call_args.kwargs["user_prompt"]

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=LLMError("markdown_generation", "LLM returned an empty response"),
            ),
            pytest.raises(LLMError, match="empty response"),
        ):
            await call_markdown_llm(SAMPLE_FORMATTED_THEME, model="m")

    @pytest.mark.asyncio
    async def test_whitespace_only_raises(self):
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=LLMError("markdown_generation", "LLM returned an empty response"),
            ),
            pytest.raises(LLMError, match="empty response"),
        ):
            await call_markdown_llm(SAMPLE_FORMATTED_THEME, model="m")

    @pytest.mark.asyncio
    async def test_default_model(self):
        mock_resp = _llm_response("markdown")
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            await call_markdown_llm(SAMPLE_FORMATTED_THEME)
            # model=None is passed through; completion() resolves via purpose
            assert mock_call.call_args.kwargs["model"] is None
            assert mock_call.call_args.kwargs["purpose"].name == "MARKDOWN"


# ---------------------------------------------------------------------------
# format_char_errors_json tests
# ---------------------------------------------------------------------------


class TestFormatCharErrorsJson:
    def test_empty_errors(self):
        assert format_char_errors_json([]) == "[]"

    def test_single_error(self):
        err = CharacterCountError(
            section="Quick Highlights",
            field="Bullet 1",
            current=130,
            target_min=150,
            target_max=190,
            delta=-20,
        )
        result = json.loads(format_char_errors_json([err]))
        assert len(result) == 1
        assert "Quick Highlights" in result[0]
        assert "delta=-20" in result[0]

    def test_multiple_errors(self):
        errors = [
            CharacterCountError("Sec1", "F1", 100, 150, 190, -50),
            CharacterCountError("Sec2", "F2", 800, 0, 750, 50),
        ]
        result = json.loads(format_char_errors_json(errors))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _parse_validation_response tests
# ---------------------------------------------------------------------------


class TestParseValidationResponse:
    def test_empty_string(self):
        is_valid, errors = _parse_validation_response("")
        assert is_valid is True
        assert errors == []

    def test_valid_json(self):
        data = {"output": {"isValid": True, "errors": []}}
        is_valid, errors = _parse_validation_response(json.dumps(data))
        assert is_valid is True
        assert errors == []

    def test_invalid_json_with_errors(self):
        data = {"output": {"isValid": False, "errors": ["err1", "err2"]}}
        is_valid, errors = _parse_validation_response(json.dumps(data))
        assert is_valid is False
        assert errors == ["err1", "err2"]

    def test_flat_json_without_output_key(self):
        data = {"isValid": False, "errors": ["flat error"]}
        is_valid, errors = _parse_validation_response(json.dumps(data))
        assert is_valid is False
        assert errors == ["flat error"]

    def test_json_in_code_block(self):
        text = '```json\n{"output": {"isValid": false, "errors": ["err"]}}\n```'
        is_valid, errors = _parse_validation_response(text)
        assert is_valid is False
        assert errors == ["err"]

    def test_unparseable_text(self):
        is_valid, errors = _parse_validation_response("this is not json")
        assert is_valid is False
        assert len(errors) == 1
        assert "Unparseable" in errors[0]

    def test_numeric_errors_converted_to_str(self):
        data = {"output": {"isValid": False, "errors": [42, 3.14]}}
        _, errors = _parse_validation_response(json.dumps(data))
        assert errors == ["42", "3.14"]

    def test_missing_errors_key(self):
        data = {"output": {"isValid": True}}
        is_valid, errors = _parse_validation_response(json.dumps(data))
        assert is_valid is True
        assert errors == []


# ---------------------------------------------------------------------------
# run_structural_validation tests
# ---------------------------------------------------------------------------


class TestRunStructuralValidation:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        response_data = {"output": {"isValid": True, "errors": []}}
        mock_resp = _llm_response(json.dumps(response_data))
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            is_valid, errors = await run_structural_validation(
                SAMPLE_MARKDOWN,
                "[]",
                model="test",
            )
            assert is_valid is True
            assert errors == []

    @pytest.mark.asyncio
    async def test_invalid_response(self):
        response_data = {"output": {"isValid": False, "errors": ["Missing CTA"]}}
        mock_resp = _llm_response(json.dumps(response_data))
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            is_valid, errors = await run_structural_validation(
                SAMPLE_MARKDOWN,
                "[]",
                model="test",
            )
            assert is_valid is False
            assert "Missing CTA" in errors

    @pytest.mark.asyncio
    async def test_default_model(self):
        mock_resp = _llm_response('{"output":{"isValid":true,"errors":[]}}')
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            await run_structural_validation(SAMPLE_MARKDOWN, "[]")
            # model=None passed through; completion() resolves via purpose
            assert mock_call.call_args.kwargs["model"] is None
            assert mock_call.call_args.kwargs["purpose"].name == "MARKDOWN_VALIDATOR"


# ---------------------------------------------------------------------------
# run_voice_validation tests
# ---------------------------------------------------------------------------


class TestRunVoiceValidation:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        response_data = {"output": {"isValid": True, "errors": []}}
        mock_resp = _llm_response(json.dumps(response_data))
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            is_valid, errors = await run_voice_validation(
                SAMPLE_MARKDOWN,
                "[]",
                model="test",
            )
            assert is_valid is True
            assert errors == []

    @pytest.mark.asyncio
    async def test_voice_errors_merged(self):
        response_data = {
            "output": {
                "isValid": False,
                "errors": ["prior error", "VOICE: missing contractions"],
            }
        }
        mock_resp = _llm_response(json.dumps(response_data))
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            is_valid, errors = await run_voice_validation(
                SAMPLE_MARKDOWN,
                '{"output":{"isValid":false,"errors":["prior error"]}}',
                model="test",
            )
            assert is_valid is False
            assert len(errors) == 2
            assert "VOICE" in errors[1]


# ---------------------------------------------------------------------------
# run_three_layer_validation tests
# ---------------------------------------------------------------------------


class TestRunThreeLayerValidation:
    @pytest.mark.asyncio
    async def test_all_valid(self):
        valid_resp = _llm_response('{"output":{"isValid":true,"errors":[]}}')
        with (
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[],
            ),
            patch(
                "ica.pipeline.markdown_generation.completion",
                return_value=valid_resp,
            ),
        ):
            result = await run_three_layer_validation(
                SAMPLE_MARKDOWN,
                validator_model="test",
            )
            assert result.is_valid is True
            assert result.errors == []

    @pytest.mark.asyncio
    async def test_char_errors_propagate(self):
        char_err = CharacterCountError("QH", "B1", 100, 150, 190, -50)
        struct_resp = _llm_response(
            json.dumps({"output": {"isValid": False, "errors": [char_err.format()]}})
        )
        voice_resp = _llm_response(
            json.dumps({"output": {"isValid": False, "errors": [char_err.format()]}})
        )
        with (
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[char_err],
            ),
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[struct_resp, voice_resp],
            ),
        ):
            result = await run_three_layer_validation(
                SAMPLE_MARKDOWN,
                validator_model="test",
            )
            assert result.is_valid is False
            assert len(result.errors) >= 1

    @pytest.mark.asyncio
    async def test_returns_char_errors_json(self):
        valid_resp = _llm_response('{"output":{"isValid":true,"errors":[]}}')
        with (
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[],
            ),
            patch(
                "ica.pipeline.markdown_generation.completion",
                return_value=valid_resp,
            ),
        ):
            result = await run_three_layer_validation(
                SAMPLE_MARKDOWN,
                validator_model="test",
            )
            assert result.char_errors_json == "[]"


# ---------------------------------------------------------------------------
# generate_with_validation tests
# ---------------------------------------------------------------------------


class TestGenerateWithValidation:
    @pytest.mark.asyncio
    async def test_valid_on_first_try(self):
        """First generation passes validation → returned immediately."""
        gen_resp = _llm_response(SAMPLE_MARKDOWN)
        valid_resp = _llm_response('{"output":{"isValid":true,"errors":[]}}')
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[gen_resp, valid_resp, valid_resp],
            ),
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[],
            ),
        ):
            result = await generate_with_validation(
                SAMPLE_FORMATTED_THEME,
                generation_model="gen",
                validator_model="val",
            )
            assert "INTRODUCTION" in result

    @pytest.mark.asyncio
    async def test_retry_on_invalid(self):
        """First try invalid, second try valid → 2 generations."""
        gen_resp_1 = _llm_response("bad markdown")
        gen_resp_2 = _llm_response("fixed markdown")
        invalid_resp = _llm_response('{"output":{"isValid":false,"errors":["err"]}}')
        valid_resp = _llm_response('{"output":{"isValid":true,"errors":[]}}')
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[
                    gen_resp_1,  # first generation
                    invalid_resp,  # struct validation (invalid)
                    invalid_resp,  # voice validation (invalid)
                    gen_resp_2,  # second generation (regen with errors)
                    valid_resp,  # struct validation (valid)
                    valid_resp,  # voice validation (valid)
                ],
            ),
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[],
            ),
        ):
            result = await generate_with_validation(
                SAMPLE_FORMATTED_THEME,
                generation_model="gen",
                validator_model="val",
            )
            assert result == "fixed markdown"

    @pytest.mark.asyncio
    async def test_force_accept_after_max_attempts(self):
        """After max_attempts, force-accept even if invalid."""
        gen_resp = _llm_response("force accepted")
        invalid_resp = _llm_response(
            '{"output":{"isValid":false,"errors":["persistent err"]}}'
        )
        # max_attempts=2 flow:
        # 1. gen(1) → validate(2,3) → count=0, not exhausted → incr(1) → regen(4)
        # 2. validate(5,6) → count=1, not exhausted → incr(2) → regen(7)
        # 3. validate(8,9) → count=2, exhausted → return
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[
                    gen_resp,  # 1: first generation
                    invalid_resp,  # 2: struct validation
                    invalid_resp,  # 3: voice validation
                    gen_resp,  # 4: regen after attempt 1
                    invalid_resp,  # 5: struct validation
                    invalid_resp,  # 6: voice validation
                    gen_resp,  # 7: regen after attempt 2
                    invalid_resp,  # 8: struct validation
                    invalid_resp,  # 9: voice validation
                ],
            ),
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[],
            ),
        ):
            result = await generate_with_validation(
                SAMPLE_FORMATTED_THEME,
                generation_model="gen",
                validator_model="val",
                max_attempts=2,
            )
            assert result == "force accepted"

    @pytest.mark.asyncio
    async def test_feedback_injected(self):
        gen_resp = _llm_response("markdown")
        valid_resp = _llm_response('{"output":{"isValid":true,"errors":[]}}')
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[gen_resp, valid_resp, valid_resp],
            ) as mock_call,
            patch(
                "ica.pipeline.markdown_generation.validate_character_counts",
                return_value=[],
            ),
        ):
            await generate_with_validation(
                SAMPLE_FORMATTED_THEME,
                aggregated_feedback="• improve tone",
                generation_model="gen",
                validator_model="val",
            )
            # First call is generation — check feedback in user prompt
            gen_call = mock_call.call_args_list[0]
            assert "improve tone" in gen_call.kwargs["user_prompt"]


# ---------------------------------------------------------------------------
# build_next_steps_form tests
# ---------------------------------------------------------------------------


class TestBuildNextStepsForm:
    def test_form_structure(self):
        form = build_next_steps_form()
        assert len(form) == 1
        field = form[0]
        assert field["fieldLabel"] == NEXT_STEPS_FIELD_LABEL
        assert field["fieldType"] == "dropdown"
        assert field["requiredField"] is True

    def test_options(self):
        form = build_next_steps_form()
        options = form[0]["fieldOptions"]["values"]
        labels = [o["option"] for o in options]
        assert labels == NEXT_STEPS_OPTIONS


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

    def test_restart(self):
        response = {NEXT_STEPS_FIELD_LABEL: "Restart Chat"}
        assert parse_next_steps_response(response) == UserChoice.RESTART

    def test_missing_field(self):
        assert parse_next_steps_response({}) is None

    def test_empty_value(self):
        response = {NEXT_STEPS_FIELD_LABEL: ""}
        assert parse_next_steps_response(response) is None


# ---------------------------------------------------------------------------
# call_user_feedback_regeneration tests
# ---------------------------------------------------------------------------


class TestCallUserFeedbackRegeneration:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        mock_resp = _llm_response("regenerated markdown")
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            result = await call_user_feedback_regeneration(
                "original",
                "feedback",
                model="test-model",
            )
            assert result == "regenerated markdown"
            assert mock_call.call_args.kwargs["model"] == "test-model"
            assert mock_call.call_args.kwargs["purpose"].name == "MARKDOWN_REGENERATION"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=LLMError("markdown_regeneration", "LLM returned an empty response"),
            ),
            pytest.raises(LLMError, match="empty response"),
        ):
            await call_user_feedback_regeneration("orig", "fb", model="m")

    @pytest.mark.asyncio
    async def test_default_model(self):
        mock_resp = _llm_response("regen")
        with patch(
            "ica.pipeline.markdown_generation.completion", return_value=mock_resp
        ) as mock_call:
            await call_user_feedback_regeneration("orig", "fb")
            # model=None passed through; completion() resolves via purpose
            assert mock_call.call_args.kwargs["model"] is None
            assert mock_call.call_args.kwargs["purpose"].name == "MARKDOWN_REGENERATION"


# ---------------------------------------------------------------------------
# extract_markdown_learning_data tests
# ---------------------------------------------------------------------------


class TestExtractMarkdownLearningData:
    @pytest.mark.asyncio
    async def test_json_response(self):
        learning = '{"learning_feedback": "Improve structure"}'
        mock_resp = _llm_response(learning)
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            result = await extract_markdown_learning_data(
                "fb",
                "input",
                "output",
                model="m",
            )
            assert result == "Improve structure"

    @pytest.mark.asyncio
    async def test_plain_text_response(self):
        mock_resp = _llm_response("plain text note")
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            result = await extract_markdown_learning_data(
                "fb",
                "input",
                "output",
                model="m",
            )
            assert result == "plain text note"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=LLMError("markdown_learning_data", "LLM returned an empty response"),
            ),
            pytest.raises(LLMError, match="empty response"),
        ):
            await extract_markdown_learning_data("fb", "in", "out", model="m")

    @pytest.mark.asyncio
    async def test_invalid_json_returns_raw(self):
        mock_resp = _llm_response("not json {bad")
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            result = await extract_markdown_learning_data(
                "fb",
                "input",
                "output",
                model="m",
            )
            assert result == "not json {bad"

    @pytest.mark.asyncio
    async def test_json_without_learning_key(self):
        mock_resp = _llm_response('{"other_key": "value"}')
        with patch("ica.pipeline.markdown_generation.completion", return_value=mock_resp):
            result = await extract_markdown_learning_data(
                "fb",
                "input",
                "output",
                model="m",
            )
            assert "other_key" in result


# ---------------------------------------------------------------------------
# store_markdown_feedback tests
# ---------------------------------------------------------------------------


class TestStoreMarkdownFeedback:
    @pytest.mark.asyncio
    async def test_stores_with_correct_type(self):
        session = AsyncMock()
        with patch("ica.pipeline.markdown_generation.add_note") as mock_add:
            await store_markdown_feedback(session, "learning note")
            mock_add.assert_called_once_with(
                session,
                "user_markdowngenerator",
                "learning note",
                newsletter_id=None,
            )

    @pytest.mark.asyncio
    async def test_stores_with_newsletter_id(self):
        session = AsyncMock()
        with patch("ica.pipeline.markdown_generation.add_note") as mock_add:
            await store_markdown_feedback(
                session,
                "note",
                newsletter_id="NL-001",
            )
            mock_add.assert_called_once_with(
                session,
                "user_markdowngenerator",
                "note",
                newsletter_id="NL-001",
            )


# ---------------------------------------------------------------------------
# create_markdown_doc tests
# ---------------------------------------------------------------------------


class TestCreateMarkdownDoc:
    @pytest.mark.asyncio
    async def test_creates_doc_and_inserts_content(self):
        docs = AsyncMock()
        docs.create_document.return_value = "doc-abc"
        doc_id, doc_url = await create_markdown_doc(docs, "# Content")
        assert doc_id == "doc-abc"
        assert doc_url == "https://docs.google.com/document/d/doc-abc/edit"
        docs.create_document.assert_called_once_with(GOOGLE_DOC_TITLE)
        docs.insert_content.assert_called_once_with("doc-abc", "# Content")

    @pytest.mark.asyncio
    async def test_custom_title(self):
        docs = AsyncMock()
        docs.create_document.return_value = "doc-123"
        await create_markdown_doc(docs, "content", title="Custom Title")
        docs.create_document.assert_called_once_with("Custom Title")


# ---------------------------------------------------------------------------
# run_markdown_review tests
# ---------------------------------------------------------------------------


class TestRunMarkdownReview:
    def _make_slack(self, choices: list[dict[str, str]]) -> AsyncMock:
        """Create a mock Slack with sequential form responses."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = choices
        return slack

    @pytest.mark.asyncio
    async def test_approve_immediately(self):
        """User selects Yes → Google Doc created, result returned."""
        slack = self._make_slack(
            [
                {NEXT_STEPS_FIELD_LABEL: "Yes"},
            ]
        )
        docs = AsyncMock()
        docs.create_document.return_value = "doc-final"

        result = await run_markdown_review(
            SAMPLE_MARKDOWN,
            SAMPLE_FORMATTED_THEME,
            slack=slack,
            docs=docs,
        )

        assert isinstance(result, MarkdownGenerationResult)
        assert result.markdown_doc_id == "doc-final"
        assert "doc-final" in result.doc_url
        docs.create_document.assert_called_once()
        docs.insert_content.assert_called_once()
        # Slack doc link notification
        assert slack.send_channel_message.call_count == 2  # markdown + doc link

    @pytest.mark.asyncio
    async def test_approve_without_docs(self):
        """User selects Yes but no Google Docs writer → empty doc_id."""
        slack = self._make_slack(
            [
                {NEXT_STEPS_FIELD_LABEL: "Yes"},
            ]
        )

        result = await run_markdown_review(
            SAMPLE_MARKDOWN,
            SAMPLE_FORMATTED_THEME,
            slack=slack,
            docs=None,
        )

        assert result.markdown_doc_id == ""
        assert result.doc_url == ""

    @pytest.mark.asyncio
    async def test_feedback_then_approve(self):
        """User provides feedback, then approves on second round."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "fix the intro"

        regen_resp = _llm_response("# *INTRODUCTION*\nRegenerated content")
        learning_resp = _llm_response('{"learning_feedback": "note"}')

        with patch(
            "ica.pipeline.markdown_generation.completion",
            side_effect=[regen_resp, learning_resp],
        ):
            result = await run_markdown_review(
                SAMPLE_MARKDOWN,
                SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=None,
            )

            assert result.markdown is not None
            # Feedback form was called
            slack.send_and_wait_freetext.assert_called_once()

    @pytest.mark.asyncio
    async def test_feedback_stores_learning_data(self):
        """Feedback loop stores learning note in DB."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback text"

        regen_resp = _llm_response("# *INTRODUCTION*\nRegen")
        learning_resp = _llm_response('{"learning_feedback": "stored"}')
        session = AsyncMock()

        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[regen_resp, learning_resp],
            ),
            patch("ica.pipeline.markdown_generation.store_markdown_feedback") as mock_store,
        ):
            await run_markdown_review(
                SAMPLE_MARKDOWN,
                SAMPLE_FORMATTED_THEME,
                slack=slack,
                session=session,
                newsletter_id="NL-001",
            )

            mock_store.assert_called_once_with(
                session,
                "stored",
                newsletter_id="NL-001",
            )

    @pytest.mark.asyncio
    async def test_restart_resets_regeneration(self):
        """Restart Chat resets to original markdown, then approve."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Restart Chat"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]

        result = await run_markdown_review(
            SAMPLE_MARKDOWN,
            SAMPLE_FORMATTED_THEME,
            slack=slack,
            docs=None,
        )

        assert result.markdown == SAMPLE_MARKDOWN

    @pytest.mark.asyncio
    async def test_slack_receives_correct_form_params(self):
        """Verify Slack form is called with correct labels."""
        slack = self._make_slack(
            [
                {NEXT_STEPS_FIELD_LABEL: "Yes"},
            ]
        )

        await run_markdown_review(
            SAMPLE_MARKDOWN,
            SAMPLE_FORMATTED_THEME,
            slack=slack,
            docs=None,
        )

        form_call = slack.send_and_wait_form.call_args
        assert form_call.kwargs["button_label"] == NEXT_STEPS_BUTTON_LABEL
        assert form_call.kwargs["form_title"] == NEXT_STEPS_FORM_TITLE
        assert form_call.kwargs["form_description"] == NEXT_STEPS_FORM_DESCRIPTION

    @pytest.mark.asyncio
    async def test_feedback_form_params(self):
        """Verify feedback form params when user provides feedback."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "fb"

        regen_resp = _llm_response("# *INTRODUCTION*\nRegen")
        learning_resp = _llm_response('{"learning_feedback": "note"}')

        with patch(
            "ica.pipeline.markdown_generation.completion",
            side_effect=[regen_resp, learning_resp],
        ):
            await run_markdown_review(
                SAMPLE_MARKDOWN,
                SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=None,
            )

            freetext_call = slack.send_and_wait_freetext.call_args
            assert freetext_call.args[0] == FEEDBACK_MESSAGE
            assert freetext_call.kwargs["button_label"] == FEEDBACK_BUTTON_LABEL
            assert freetext_call.kwargs["form_title"] == FEEDBACK_FORM_TITLE

    @pytest.mark.asyncio
    async def test_no_session_skips_storage(self):
        """When session is None, feedback storage is skipped."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "fb"

        regen_resp = _llm_response("# *INTRODUCTION*\nRegen")
        learning_resp = _llm_response('{"learning_feedback": "note"}')

        with (
            patch(
                "ica.pipeline.markdown_generation.completion",
                side_effect=[regen_resp, learning_resp],
            ),
            patch("ica.pipeline.markdown_generation.store_markdown_feedback") as mock_store,
        ):
            await run_markdown_review(
                SAMPLE_MARKDOWN,
                SAMPLE_FORMATTED_THEME,
                slack=slack,
                session=None,
            )

            mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_feedback_rounds(self):
        """Two feedback rounds then approve."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.side_effect = ["fb1", "fb2"]

        regen_resp_1 = _llm_response("# *INTRODUCTION*\nRegen1")
        learning_resp_1 = _llm_response('{"learning_feedback": "n1"}')
        regen_resp_2 = _llm_response("# *INTRODUCTION*\nRegen2")
        learning_resp_2 = _llm_response('{"learning_feedback": "n2"}')

        with patch(
            "ica.pipeline.markdown_generation.completion",
            side_effect=[
                regen_resp_1,
                learning_resp_1,
                regen_resp_2,
                learning_resp_2,
            ],
        ):
            result = await run_markdown_review(
                SAMPLE_MARKDOWN,
                SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=None,
            )

            assert slack.send_and_wait_freetext.call_count == 2
            assert result.markdown is not None
