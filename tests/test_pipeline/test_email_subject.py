"""Tests for email subject & preview generator pipeline step (Step 6b).

Tests cover:
- ParsedSubject dataclass
- EmailSubjectResult dataclass
- strip_html_to_text: HTML-to-text conversion
- aggregate_feedback: notes → bullet-point string
- call_email_subject_llm: subject generation LLM call
- parse_subjects: raw LLM output → subjects + recommendation
- format_recommendation: Slack mrkdwn bold formatting
- build_subjects_slack_blocks: Block Kit construction
- format_subjects_slack_message: flattened message from blocks
- build_subject_selection_form: radio buttons + textarea
- is_subject_selection: subject vs feedback detection
- extract_selected_subject: parse selection → ParsedSubject
- call_email_review_llm: review generation LLM call
- build_review_slack_blocks: Block Kit construction for review
- format_review_slack_message: flattened review message
- build_review_approval_form: Approve/Reset/Feedback form
- parse_review_approval: approval response routing
- extract_email_learning_data: learning data extraction with JSON parsing
- store_email_feedback: notes table insertion
- create_email_doc: Google Doc creation
- run_email_subject_generation: full orchestrated pipeline step
- Constants: Slack field labels, messages, button labels
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.email_subject import (
    FEEDBACK_FIELD_LABEL,
    GOOGLE_DOC_TITLE,
    REVIEW_APPROVAL_FIELD_LABEL,
    REVIEW_APPROVAL_MESSAGE,
    REVIEW_APPROVAL_OPTIONS,
    REVIEW_HEADER,
    REVIEW_NOTES_FIELD_LABEL,
    SUBJECT_SELECTION_FIELD_LABEL,
    SUBJECT_SELECTION_MESSAGE,
    SUBJECTS_HEADER,
    EmailSubjectResult,
    ParsedSubject,
    aggregate_feedback,
    build_review_approval_form,
    build_review_slack_blocks,
    build_subject_selection_form,
    build_subjects_slack_blocks,
    call_email_review_llm,
    call_email_subject_llm,
    create_email_doc,
    extract_email_learning_data,
    extract_selected_subject,
    format_recommendation,
    format_review_slack_message,
    format_subjects_slack_message,
    is_subject_selection,
    parse_review_approval,
    parse_subjects,
    run_email_subject_generation,
    store_email_feedback,
    strip_html_to_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Newsletter</title>
    <style>body { color: black; }</style>
</head>
<body>
    <h1>AI Newsletter</h1>
    <p>This week's content about <b>artificial intelligence</b>.</p>
    <script>alert('x');</script>
</body>
</html>
"""

SAMPLE_LLM_OUTPUT = """\
Subject_1: AI Revolution Hits Reality Check

-----

Subject_2: When Machines Meet Markets

-----

Subject_3: The Future Isn't What Expected

-----

RECOMMENDATION: Subject 2 - When Machines Meet Markets
Explanation: This subject captures the core tension of the newsletter.
"""

SAMPLE_NEWSLETTER_TEXT = "AI Newsletter This week's content about artificial intelligence."


def _mock_llm_response(content: str) -> MagicMock:
    """Create a mock litellm.acompletion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


def _make_note(feedback_text: str | None) -> MagicMock:
    """Create a mock Note object."""
    note = MagicMock()
    note.feedback_text = feedback_text
    return note


def _make_subjects() -> list[ParsedSubject]:
    """Create a sample list of parsed subjects."""
    return [
        ParsedSubject(
            subject="AI Revolution Hits Reality Check",
            subject_id="1",
            subject_body="Subject_1: AI Revolution Hits Reality Check",
        ),
        ParsedSubject(
            subject="When Machines Meet Markets",
            subject_id="2",
            subject_body="Subject_2: When Machines Meet Markets",
        ),
        ParsedSubject(
            subject="The Future Isn't What Expected",
            subject_id="3",
            subject_body="Subject_3: The Future Isn't What Expected",
        ),
    ]


# ===================================================================
# ParsedSubject dataclass
# ===================================================================


class TestParsedSubject:
    def test_frozen(self) -> None:
        s = ParsedSubject(subject="Test", subject_id="1", subject_body="body")
        with pytest.raises(AttributeError):
            s.subject = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        s = ParsedSubject(subject="Test Sub", subject_id="3", subject_body="raw")
        assert s.subject == "Test Sub"
        assert s.subject_id == "3"
        assert s.subject_body == "raw"


# ===================================================================
# EmailSubjectResult dataclass
# ===================================================================


class TestEmailSubjectResult:
    def test_frozen(self) -> None:
        r = EmailSubjectResult(
            selected_subject="Test",
            review_text="review",
            doc_id="abc",
            doc_url="https://example.com",
            model="test-model",
        )
        with pytest.raises(AttributeError):
            r.selected_subject = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        r = EmailSubjectResult(
            selected_subject="AI Tomorrow",
            review_text="Great newsletter",
            doc_id="doc-123",
            doc_url="https://docs.google.com/document/d/doc-123/edit",
            model="anthropic/claude-sonnet-4.5",
        )
        assert r.selected_subject == "AI Tomorrow"
        assert r.review_text == "Great newsletter"
        assert r.doc_id == "doc-123"
        assert "doc-123" in r.doc_url
        assert r.model == "anthropic/claude-sonnet-4.5"


# ===================================================================
# strip_html_to_text
# ===================================================================


class TestStripHtmlToText:
    def test_basic_html_stripping(self) -> None:
        result = strip_html_to_text("<p>Hello <b>world</b></p>")
        assert result == "Hello world"

    def test_style_script_removal(self) -> None:
        result = strip_html_to_text(SAMPLE_HTML)
        assert "color: black" not in result
        assert "alert" not in result
        assert "AI Newsletter" in result
        assert "artificial intelligence" in result

    def test_nbsp_replacement(self) -> None:
        result = strip_html_to_text("Hello&nbsp;World")
        assert result == "Hello World"

    def test_whitespace_collapse(self) -> None:
        result = strip_html_to_text("<p>Hello   \n\n  World</p>")
        assert result == "Hello World"

    def test_empty_input(self) -> None:
        assert strip_html_to_text("") == ""

    def test_plain_text_passthrough(self) -> None:
        assert strip_html_to_text("Just plain text") == "Just plain text"

    def test_nested_tags(self) -> None:
        result = strip_html_to_text("<div><span><em>deep</em></span></div>")
        assert result == "deep"

    def test_style_case_insensitive(self) -> None:
        result = strip_html_to_text("<STYLE>body{}</STYLE>text")
        assert result == "text"


# ===================================================================
# aggregate_feedback
# ===================================================================


class TestAggregateFeedback:
    def test_empty_list(self) -> None:
        assert aggregate_feedback([]) is None

    def test_none_feedback_text(self) -> None:
        assert aggregate_feedback([_make_note(None)]) is None

    def test_single_entry(self) -> None:
        result = aggregate_feedback([_make_note("Be more concise")])
        assert result == "\u2022 Be more concise"

    def test_multiple_entries(self) -> None:
        notes = [_make_note("Point A"), _make_note("Point B")]
        result = aggregate_feedback(notes)
        assert "\u2022 Point A" in result
        assert "\u2022 Point B" in result

    def test_filters_none(self) -> None:
        notes = [_make_note("Valid"), _make_note(None), _make_note("Also valid")]
        result = aggregate_feedback(notes)
        assert "\u2022 Valid" in result
        assert "\u2022 Also valid" in result


# ===================================================================
# call_email_subject_llm
# ===================================================================


class TestCallEmailSubjectLlm:
    @pytest.mark.asyncio
    async def test_basic_call(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response(SAMPLE_LLM_OUTPUT)
            )
            result = await call_email_subject_llm("newsletter text")
            assert "Subject_1" in result
            mock_litellm.acompletion.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_feedback(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response("Subject_1: Test\n-----")
            )
            result = await call_email_subject_llm("text", aggregated_feedback="Be creative")
            assert "Subject_1" in result

    @pytest.mark.asyncio
    async def test_custom_model(self) -> None:
        with patch("ica.pipeline.email_subject.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response("Subject_1: Custom\n-----")
            )
            await call_email_subject_llm("text", model="custom/model")
            call_args = mock_litellm.acompletion.call_args
            assert call_args.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=_mock_llm_response(""))
            with pytest.raises(RuntimeError, match="empty response"):
                await call_email_subject_llm("text")

    @pytest.mark.asyncio
    async def test_none_response_raises(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response(None)  # type: ignore[arg-type]
            )
            with pytest.raises(RuntimeError, match="empty response"):
                await call_email_subject_llm("text")


# ===================================================================
# parse_subjects
# ===================================================================


class TestParseSubjects:
    def test_basic_parsing(self) -> None:
        subjects, recommendation = parse_subjects(SAMPLE_LLM_OUTPUT)
        assert len(subjects) == 3
        assert subjects[0].subject == "AI Revolution Hits Reality Check"
        assert subjects[0].subject_id == "1"
        assert subjects[1].subject == "When Machines Meet Markets"
        assert subjects[1].subject_id == "2"
        assert subjects[2].subject == "The Future Isn't What Expected"
        assert subjects[2].subject_id == "3"

    def test_recommendation_extracted(self) -> None:
        _, recommendation = parse_subjects(SAMPLE_LLM_OUTPUT)
        assert "RECOMMENDATION" in recommendation
        assert "Subject 2" in recommendation

    def test_empty_input(self) -> None:
        subjects, recommendation = parse_subjects("")
        assert subjects == []
        assert recommendation == ""

    def test_no_recommendation(self) -> None:
        raw = "Subject_1: Test One\n-----\nSubject_2: Test Two"
        subjects, recommendation = parse_subjects(raw)
        assert len(subjects) == 2
        assert recommendation == ""

    def test_only_recommendation(self) -> None:
        raw = "RECOMMENDATION: Subject 1 - The Best\n-----"
        subjects, recommendation = parse_subjects(raw)
        assert len(subjects) == 0
        assert "RECOMMENDATION" in recommendation

    def test_malformed_block_skipped(self) -> None:
        raw = "Some random text\n-----\nSubject_1: Valid One"
        subjects, _ = parse_subjects(raw)
        assert len(subjects) == 1
        assert subjects[0].subject == "Valid One"

    def test_subject_body_preserved(self) -> None:
        raw = "Subject_1: Test\nExtra context here\n-----"
        subjects, _ = parse_subjects(raw)
        assert "Extra context" in subjects[0].subject_body

    def test_case_insensitive_pattern(self) -> None:
        raw = "subject_1: Lower Case\n-----"
        subjects, _ = parse_subjects(raw)
        assert len(subjects) == 1
        assert subjects[0].subject == "Lower Case"


# ===================================================================
# format_recommendation
# ===================================================================


class TestFormatRecommendation:
    def test_bold_recommendation(self) -> None:
        result = format_recommendation("RECOMMENDATION: Subject 1")
        assert "*RECOMMENDATION:*" in result

    def test_bold_explanation(self) -> None:
        result = format_recommendation("Explanation: it's the best")
        assert "*Explanation:*" in result

    def test_bold_uppercase_explanation(self) -> None:
        result = format_recommendation("EXPLANATION: reason here")
        assert "*EXPLANATION:*" in result

    def test_no_keywords(self) -> None:
        result = format_recommendation("Just plain text")
        assert result == "Just plain text"

    def test_empty_string(self) -> None:
        assert format_recommendation("") == ""

    def test_none_input(self) -> None:
        assert format_recommendation(None) == ""  # type: ignore[arg-type]


# ===================================================================
# build_subjects_slack_blocks
# ===================================================================


class TestBuildSubjectsSlackBlocks:
    def test_structure(self) -> None:
        subjects = _make_subjects()
        blocks = build_subjects_slack_blocks(subjects, "RECOMMENDATION: ...")
        # Header + divider + (section + divider) * 3 + recommendation = 9
        assert len(blocks) == 9

    def test_header_present(self) -> None:
        blocks = build_subjects_slack_blocks(_make_subjects(), "rec")
        assert SUBJECTS_HEADER in blocks[0]["text"]["text"]  # type: ignore[index]

    def test_subjects_numbered(self) -> None:
        blocks = build_subjects_slack_blocks(_make_subjects(), "")
        # Blocks at indices 2, 4, 6 are subject sections
        text1 = blocks[2]["text"]["text"]  # type: ignore[index]
        assert "*SUBJECT 1:*" in text1

    def test_recommendation_present(self) -> None:
        blocks = build_subjects_slack_blocks(_make_subjects(), "RECOMMENDATION: Pick 2")
        last_block = blocks[-1]
        assert "*RECOMMENDATION:*" in last_block["text"]["text"]  # type: ignore[index]

    def test_empty_recommendation_omitted(self) -> None:
        blocks = build_subjects_slack_blocks(_make_subjects(), "")
        # Without recommendation: header + divider + (section + divider) * 3 = 8
        assert len(blocks) == 8

    def test_empty_subjects(self) -> None:
        blocks = build_subjects_slack_blocks([], "rec")
        # header + divider + recommendation = 3
        assert len(blocks) == 3


# ===================================================================
# format_subjects_slack_message
# ===================================================================


class TestFormatSubjectsSlackMessage:
    def test_contains_subjects(self) -> None:
        msg = format_subjects_slack_message(_make_subjects(), "rec text")
        assert "SUBJECT 1" in msg
        assert "SUBJECT 2" in msg
        assert "SUBJECT 3" in msg

    def test_contains_recommendation(self) -> None:
        msg = format_subjects_slack_message(_make_subjects(), "RECOMMENDATION: Subject 2")
        assert "*RECOMMENDATION:*" in msg

    def test_separator_present(self) -> None:
        msg = format_subjects_slack_message(_make_subjects(), "rec")
        assert "\u2500" in msg


# ===================================================================
# build_subject_selection_form
# ===================================================================


class TestBuildSubjectSelectionForm:
    def test_form_structure(self) -> None:
        subjects = _make_subjects()
        form = build_subject_selection_form(subjects)
        assert len(form) == 2  # radio + textarea

    def test_radio_options(self) -> None:
        subjects = _make_subjects()
        form = build_subject_selection_form(subjects)
        radio_field = form[0]
        options = radio_field["fieldOptions"]["values"]  # type: ignore[index]
        # 3 subjects + "Add Feedback"
        assert len(options) == 4
        assert options[-1]["option"] == "Add Feedback"

    def test_subject_option_format(self) -> None:
        subjects = _make_subjects()
        form = build_subject_selection_form(subjects)
        options = form[0]["fieldOptions"]["values"]  # type: ignore[index]
        assert "SUBJECT 1:" in options[0]["option"]
        assert "AI Revolution" in options[0]["option"]

    def test_textarea_field(self) -> None:
        form = build_subject_selection_form(_make_subjects())
        textarea = form[1]
        assert textarea["fieldLabel"] == FEEDBACK_FIELD_LABEL
        assert textarea["fieldType"] == "textarea"

    def test_radio_field_label(self) -> None:
        form = build_subject_selection_form(_make_subjects())
        assert form[0]["fieldLabel"] == SUBJECT_SELECTION_FIELD_LABEL


# ===================================================================
# is_subject_selection
# ===================================================================


class TestIsSubjectSelection:
    def test_subject_selected(self) -> None:
        assert is_subject_selection("SUBJECT 1: AI Revolution") is True

    def test_feedback_selected(self) -> None:
        assert is_subject_selection("Add Feedback") is False

    def test_empty_string(self) -> None:
        assert is_subject_selection("") is False

    def test_case_sensitive(self) -> None:
        # n8n Switch uses caseSensitive=true; SUBJECT is uppercase
        assert is_subject_selection("subject 1: test") is False


# ===================================================================
# extract_selected_subject
# ===================================================================


class TestExtractSelectedSubject:
    def test_basic_extraction(self) -> None:
        subjects = _make_subjects()
        result = extract_selected_subject("SUBJECT 2: When Machines Meet Markets", subjects)
        assert result is not None
        assert result.subject == "When Machines Meet Markets"

    def test_first_subject(self) -> None:
        result = extract_selected_subject("SUBJECT 1: ...", _make_subjects())
        assert result is not None
        assert result.subject_id == "1"

    def test_last_subject(self) -> None:
        result = extract_selected_subject("SUBJECT 3: ...", _make_subjects())
        assert result is not None
        assert result.subject_id == "3"

    def test_no_match(self) -> None:
        result = extract_selected_subject("Add Feedback", _make_subjects())
        assert result is None

    def test_out_of_range(self) -> None:
        result = extract_selected_subject("SUBJECT 99: ...", _make_subjects())
        assert result is None

    def test_zero_index(self) -> None:
        result = extract_selected_subject("SUBJECT 0: ...", _make_subjects())
        assert result is None

    def test_case_insensitive(self) -> None:
        result = extract_selected_subject("Subject 2: ...", _make_subjects())
        assert result is not None


# ===================================================================
# call_email_review_llm
# ===================================================================


class TestCallEmailReviewLlm:
    @pytest.mark.asyncio
    async def test_basic_call(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response("Hi Friend, great newsletter")
            )
            result = await call_email_review_llm("newsletter text")
            assert "Hi Friend" in result

    @pytest.mark.asyncio
    async def test_with_feedback(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=_mock_llm_response("Updated review"))
            result = await call_email_review_llm("text", user_review_feedback="Be warmer")
            assert result == "Updated review"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=_mock_llm_response(""))
            with pytest.raises(RuntimeError, match="empty response"):
                await call_email_review_llm("text")


# ===================================================================
# build_review_slack_blocks
# ===================================================================


class TestBuildReviewSlackBlocks:
    def test_structure(self) -> None:
        blocks = build_review_slack_blocks("Some review text")
        assert len(blocks) == 4  # divider + header + divider + review

    def test_review_text_present(self) -> None:
        blocks = build_review_slack_blocks("Hi Friend, ...")
        last_block = blocks[-1]
        assert "Hi Friend" in last_block["text"]["text"]  # type: ignore[index]

    def test_header_label(self) -> None:
        blocks = build_review_slack_blocks("text")
        # Second block is the header section
        assert "Review:" in blocks[1]["text"]["text"]  # type: ignore[index]


# ===================================================================
# format_review_slack_message
# ===================================================================


class TestFormatReviewSlackMessage:
    def test_contains_review(self) -> None:
        msg = format_review_slack_message("Hi Friend, this is great")
        assert "Hi Friend" in msg

    def test_contains_separator(self) -> None:
        msg = format_review_slack_message("review text")
        assert "\u2500" in msg


# ===================================================================
# build_review_approval_form
# ===================================================================


class TestBuildReviewApprovalForm:
    def test_form_structure(self) -> None:
        form = build_review_approval_form()
        assert len(form) == 2  # radio + textarea

    def test_radio_options(self) -> None:
        form = build_review_approval_form()
        options = form[0]["fieldOptions"]["values"]  # type: ignore[index]
        assert len(options) == 3
        option_texts = [o["option"] for o in options]
        assert any("Approve" in t for t in option_texts)
        assert any("Reset" in t for t in option_texts)
        assert any("feedback" in t for t in option_texts)

    def test_radio_field_label(self) -> None:
        form = build_review_approval_form()
        assert form[0]["fieldLabel"] == REVIEW_APPROVAL_FIELD_LABEL

    def test_textarea_field(self) -> None:
        form = build_review_approval_form()
        assert form[1]["fieldLabel"] == REVIEW_NOTES_FIELD_LABEL
        assert form[1]["fieldType"] == "textarea"


# ===================================================================
# parse_review_approval
# ===================================================================


class TestParseReviewApproval:
    def test_approve(self) -> None:
        response = {REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue"}
        assert parse_review_approval(response) == "approve"

    def test_feedback(self) -> None:
        response = {REVIEW_APPROVAL_FIELD_LABEL: "Add a feedback"}
        assert parse_review_approval(response) == "feedback"

    def test_reset(self) -> None:
        response = {REVIEW_APPROVAL_FIELD_LABEL: "Reset All (Generate Subjects and Review Again)"}
        assert parse_review_approval(response) == "reset"

    def test_unknown(self) -> None:
        response = {REVIEW_APPROVAL_FIELD_LABEL: "Something else"}
        assert parse_review_approval(response) == "unknown"

    def test_empty_response(self) -> None:
        assert parse_review_approval({}) == "unknown"

    def test_case_sensitive_approve(self) -> None:
        # n8n uses caseSensitive=true; "Approve" with capital A
        response = {REVIEW_APPROVAL_FIELD_LABEL: "approve review"}
        # Does NOT match because 'a' != 'A' in contains check
        assert parse_review_approval(response) != "approve"

    def test_case_sensitive_feedback(self) -> None:
        # "feedback" is lowercase in the n8n switch condition
        response = {REVIEW_APPROVAL_FIELD_LABEL: "Add a feedback"}
        assert parse_review_approval(response) == "feedback"


# ===================================================================
# extract_email_learning_data
# ===================================================================


class TestExtractEmailLearningData:
    @pytest.mark.asyncio
    async def test_json_response(self) -> None:
        json_data = json.dumps({"learning_feedback": "Be more concise"})
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=_mock_llm_response(json_data))
            result = await extract_email_learning_data("feedback", "output")
            assert result == "Be more concise"

    @pytest.mark.asyncio
    async def test_plain_text_fallback(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response("Plain learning note")
            )
            result = await extract_email_learning_data("feedback", "output")
            assert result == "Plain learning note"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=_mock_llm_response(""))
            with pytest.raises(RuntimeError, match="empty response"):
                await extract_email_learning_data("feedback", "output")

    @pytest.mark.asyncio
    async def test_invalid_json_fallback(self) -> None:
        with (
            patch("ica.pipeline.email_subject.litellm") as mock_litellm,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=_mock_llm_response("{invalid json"))
            result = await extract_email_learning_data("feedback", "output")
            assert result == "{invalid json"


# ===================================================================
# store_email_feedback
# ===================================================================


class TestStoreEmailFeedback:
    @pytest.mark.asyncio
    async def test_stores_with_correct_type(self) -> None:
        with patch("ica.pipeline.email_subject.add_note") as mock_add_note:
            mock_add_note.return_value = None
            session = AsyncMock()
            await store_email_feedback(session, "test feedback")
            mock_add_note.assert_called_once_with(
                session,
                "user_email_subject",
                "test feedback",
                newsletter_id=None,
            )

    @pytest.mark.asyncio
    async def test_stores_with_newsletter_id(self) -> None:
        with patch("ica.pipeline.email_subject.add_note") as mock_add_note:
            mock_add_note.return_value = None
            session = AsyncMock()
            await store_email_feedback(session, "feedback", newsletter_id="N20260223")
            mock_add_note.assert_called_once_with(
                session,
                "user_email_subject",
                "feedback",
                newsletter_id="N20260223",
            )


# ===================================================================
# create_email_doc
# ===================================================================


class TestCreateEmailDoc:
    @pytest.mark.asyncio
    async def test_creates_document(self) -> None:
        docs = AsyncMock()
        docs.create_document.return_value = "doc-abc"
        doc_id, doc_url = await create_email_doc(docs, "Test Subject", "Review")
        assert doc_id == "doc-abc"
        assert "doc-abc" in doc_url
        docs.create_document.assert_called_once_with(GOOGLE_DOC_TITLE)

    @pytest.mark.asyncio
    async def test_inserts_content(self) -> None:
        docs = AsyncMock()
        docs.create_document.return_value = "doc-xyz"
        await create_email_doc(docs, "My Subject", "My Review")
        content = docs.insert_content.call_args[0][1]
        assert "SUBJECT: My Subject" in content
        assert "My Review" in content

    @pytest.mark.asyncio
    async def test_custom_title(self) -> None:
        docs = AsyncMock()
        docs.create_document.return_value = "doc-1"
        await create_email_doc(docs, "Sub", "Rev", title="Custom Title")
        docs.create_document.assert_called_once_with("Custom Title")

    @pytest.mark.asyncio
    async def test_doc_url_format(self) -> None:
        docs = AsyncMock()
        docs.create_document.return_value = "abc123"
        _, url = await create_email_doc(docs, "S", "R")
        assert url == "https://docs.google.com/document/d/abc123/edit"


# ===================================================================
# run_email_subject_generation — approval flow
# ===================================================================


class TestRunEmailSubjectGenerationApproval:
    """Tests for the happy path: select subject → approve review → done."""

    @pytest.mark.asyncio
    async def test_approval_flow_returns_result(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = SAMPLE_HTML
        docs.create_document.return_value = "doc-final"

        # First form: select subject 1
        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: AI Revolution", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_subject,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_review,
            patch("ica.pipeline.email_subject.get_model", return_value="test-model"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_subject.return_value = SAMPLE_LLM_OUTPUT
            mock_review.return_value = "Hi Friend, great newsletter"

            result = await run_email_subject_generation(
                "html-doc-id",
                slack=slack,
                docs=docs,
                session=AsyncMock(),
            )

            assert isinstance(result, EmailSubjectResult)
            assert result.selected_subject == "AI Revolution Hits Reality Check"
            assert result.review_text == "Hi Friend, great newsletter"
            assert result.doc_id == "doc-final"
            assert result.model == "test-model"

    @pytest.mark.asyncio
    async def test_approval_creates_google_doc(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "<p>text</p>"
        docs.create_document.return_value = "doc-123"

        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: Test", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_subject,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_review,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_subject.return_value = "Subject_1: Test\n-----"
            mock_review.return_value = "review text"

            await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            docs.create_document.assert_called_once_with(GOOGLE_DOC_TITLE)
            docs.insert_content.assert_called()

    @pytest.mark.asyncio
    async def test_approval_sends_doc_link(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-xyz"

        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: X", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_sub.return_value = "Subject_1: X\n-----"
            mock_rev.return_value = "r"

            await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            # Last send_channel_message should be the doc link
            last_msg_call = slack.send_channel_message.call_args_list[-1]
            assert "doc-xyz" in last_msg_call[0][0]


# ===================================================================
# run_email_subject_generation — feedback flow
# ===================================================================


class TestRunEmailSubjectGenerationFeedback:
    """Tests for: select feedback → store learning → regenerate → select → approve."""

    @pytest.mark.asyncio
    async def test_feedback_regenerates_subjects(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-1"

        # Call 1: feedback, Call 2: select subject, Call 3: approve review
        slack.send_and_wait_form.side_effect = [
            {
                SUBJECT_SELECTION_FIELD_LABEL: "Add Feedback",
                FEEDBACK_FIELD_LABEL: "Be more creative",
            },
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: Better Subject", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_subject,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_review,
            patch(
                "ica.pipeline.email_subject.extract_email_learning_data", new_callable=AsyncMock
            ) as mock_extract,
            patch("ica.pipeline.email_subject.store_email_feedback", new_callable=AsyncMock),
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_subject.side_effect = [
                SAMPLE_LLM_OUTPUT,  # Initial generation
                "Subject_1: Better Subject\n-----",  # Regeneration
            ]
            mock_review.return_value = "review"
            mock_extract.return_value = "learning note"

            result = await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            assert mock_subject.call_count == 2
            assert result.selected_subject == "Better Subject"

    @pytest.mark.asyncio
    async def test_feedback_stores_learning_data(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-1"

        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "Add Feedback", FEEDBACK_FIELD_LABEL: "More creative"},
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: X", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch(
                "ica.pipeline.email_subject.extract_email_learning_data", new_callable=AsyncMock
            ) as mock_extract,
            patch(
                "ica.pipeline.email_subject.store_email_feedback", new_callable=AsyncMock
            ) as mock_store,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_sub.side_effect = [
                SAMPLE_LLM_OUTPUT,
                "Subject_1: X\n-----",
            ]
            mock_rev.return_value = "review"
            mock_extract.return_value = "extracted learning"

            await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            mock_extract.assert_called_once()
            mock_store.assert_called_once()


# ===================================================================
# run_email_subject_generation — review feedback flow
# ===================================================================


class TestRunEmailSubjectGenerationReviewFeedback:
    """Tests for: select subject → review with feedback → re-generate review → approve."""

    @pytest.mark.asyncio
    async def test_review_feedback_regenerates(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-1"

        # Select subject, feedback on review, then approve
        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: Test", FEEDBACK_FIELD_LABEL: ""},
            {REVIEW_APPROVAL_FIELD_LABEL: "Add a feedback", REVIEW_NOTES_FIELD_LABEL: "Be warmer"},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_sub.return_value = "Subject_1: Test\n-----"
            mock_rev.side_effect = ["First review", "Warmer review"]

            result = await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            assert mock_rev.call_count == 2
            assert result.review_text == "Warmer review"

    @pytest.mark.asyncio
    async def test_review_feedback_passes_to_llm(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-1"

        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: T", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Add a feedback",
                REVIEW_NOTES_FIELD_LABEL: "More warmth",
            },
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_sub.return_value = "Subject_1: T\n-----"
            mock_rev.side_effect = ["r1", "r2"]

            await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            # Second call should have the feedback
            second_call = mock_rev.call_args_list[1]
            assert second_call.kwargs.get("user_review_feedback") == "More warmth"


# ===================================================================
# run_email_subject_generation — reset flow
# ===================================================================


class TestRunEmailSubjectGenerationReset:
    """Tests for: select subject → review → Reset All → regenerate from scratch."""

    @pytest.mark.asyncio
    async def test_reset_regenerates_subjects(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-1"

        # Round 1: select subject → reset
        # Round 2: select subject → approve
        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: Old", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Reset All (Generate Subjects and Review Again)",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: New", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
            patch(
                "ica.pipeline.email_subject.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_sub.side_effect = [
                "Subject_1: Old\n-----",
                "Subject_1: New\n-----",
            ]
            mock_rev.side_effect = ["review 1", "review 2"]

            result = await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=AsyncMock()
            )

            assert mock_sub.call_count == 2
            assert result.selected_subject == "New"


# ===================================================================
# run_email_subject_generation — no docs / no session
# ===================================================================


class TestRunEmailSubjectGenerationNoDeps:
    """Tests for running without Google Docs or database session."""

    @pytest.mark.asyncio
    async def test_no_docs_service(self) -> None:
        slack = AsyncMock()

        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: Test", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
        ):
            mock_sub.return_value = "Subject_1: Test\n-----"
            mock_rev.return_value = "review"

            result = await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=None, session=None
            )

            assert result.doc_id == ""
            assert result.doc_url == ""
            assert result.selected_subject == "Test"

    @pytest.mark.asyncio
    async def test_no_session_skips_feedback(self) -> None:
        slack = AsyncMock()
        docs = AsyncMock()
        docs.get_content.return_value = "text"
        docs.create_document.return_value = "doc-1"

        slack.send_and_wait_form.side_effect = [
            {SUBJECT_SELECTION_FIELD_LABEL: "SUBJECT 1: T", FEEDBACK_FIELD_LABEL: ""},
            {
                REVIEW_APPROVAL_FIELD_LABEL: "Approve review and continue",
                REVIEW_NOTES_FIELD_LABEL: "",
            },
        ]

        with (
            patch(
                "ica.pipeline.email_subject.call_email_subject_llm", new_callable=AsyncMock
            ) as mock_sub,
            patch(
                "ica.pipeline.email_subject.call_email_review_llm", new_callable=AsyncMock
            ) as mock_rev,
            patch("ica.pipeline.email_subject.get_model", return_value="m"),
        ):
            mock_sub.return_value = "Subject_1: T\n-----"
            mock_rev.return_value = "r"

            result = await run_email_subject_generation(
                "html-doc-id", slack=slack, docs=docs, session=None
            )

            assert result.selected_subject == "T"


# ===================================================================
# Constants verification
# ===================================================================


class TestConstants:
    def test_review_approval_options_count(self) -> None:
        assert len(REVIEW_APPROVAL_OPTIONS) == 3

    def test_review_approval_options_content(self) -> None:
        assert any("Approve" in o for o in REVIEW_APPROVAL_OPTIONS)
        assert any("Reset" in o for o in REVIEW_APPROVAL_OPTIONS)
        assert any("feedback" in o for o in REVIEW_APPROVAL_OPTIONS)

    def test_google_doc_title(self) -> None:
        assert GOOGLE_DOC_TITLE == "Email-subject-preview"

    def test_field_labels_non_empty(self) -> None:
        assert SUBJECT_SELECTION_FIELD_LABEL
        assert FEEDBACK_FIELD_LABEL
        assert REVIEW_APPROVAL_FIELD_LABEL
        assert REVIEW_NOTES_FIELD_LABEL

    def test_message_strings(self) -> None:
        assert SUBJECT_SELECTION_MESSAGE
        assert REVIEW_APPROVAL_MESSAGE
        assert SUBJECTS_HEADER
        assert REVIEW_HEADER
