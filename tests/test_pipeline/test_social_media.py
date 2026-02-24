"""Tests for the social media generator pipeline step.

Covers:
- Post title parsing (Phase 1 and Phase 2 formats)
- Source URL resolution from formatted_theme
- Phase 1 post parsing with selection filtering
- Final content filtering
- Form builders (Phase 1, Phase 2, selection, final)
- LLM call wrappers (posts, captions, regeneration)
- Google Doc creation
- Checkbox response parsing
- Full orchestration (run_social_media_generation)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.social_media import (
    APPROVAL_MESSAGE,
    FEEDBACK_BUTTON_LABEL,
    FEEDBACK_FORM_DESCRIPTION,
    FEEDBACK_FORM_TITLE,
    FEEDBACK_MESSAGE,
    FINAL_SELECTION_BUTTON,
    FINAL_SELECTION_FIELD,
    FINAL_SELECTION_FORM_DESCRIPTION,
    FINAL_SELECTION_FORM_TITLE,
    FINAL_SELECTION_MESSAGE,
    GOOGLE_DOC_TITLE,
    PHASE1_BUTTON_LABEL,
    PHASE1_FORM_DESCRIPTION,
    PHASE1_FORM_TITLE,
    PHASE1_NEXT_STEPS_FIELD,
    PHASE1_NEXT_STEPS_MESSAGE,
    PHASE2_BUTTON_LABEL,
    PHASE2_FORM_DESCRIPTION,
    PHASE2_FORM_TITLE,
    PHASE2_NEXT_STEPS_FIELD,
    PHASE2_NEXT_STEPS_MESSAGE,
    POST_SELECTION_BUTTON,
    POST_SELECTION_FIELD,
    POST_SELECTION_FORM_DESCRIPTION,
    POST_SELECTION_FORM_TITLE,
    POST_SELECTION_MESSAGE,
    ParsedPost,
    SocialMediaResult,
    _parse_checkbox_response,
    build_final_selection_form,
    build_phase1_next_steps_form,
    build_phase2_next_steps_form,
    build_post_selection_form,
    call_caption_llm,
    call_caption_regeneration_llm,
    call_social_media_post_llm,
    create_social_media_doc,
    filter_final_posts,
    get_source_url,
    parse_phase1_posts,
    parse_phase1_titles,
    parse_phase2_titles,
    run_social_media_generation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FORMATTED_THEME: dict[str, object] = {
    "THEME": "THEME: Test Theme",
    "FEATURED ARTICLE": {
        "Title": "Featured Article Title",
        "Source": "1",
        "URL": "https://example.com/featured",
        "Category": "AI",
    },
    "MAIN ARTICLE 1": {
        "Title": "Main Article 1 Title",
        "Source": "2",
        "URL": "https://example.com/main1",
        "Category": "Tech",
    },
    "MAIN ARTICLE 2": {
        "Title": "Main Article 2 Title",
        "Source": "3",
        "URL": "https://example.com/main2",
        "Category": "Business",
    },
    "QUICK HIT 1": {
        "Title": "Quick Hit 1 Title",
        "Source": "4",
        "URL": "https://example.com/qh1",
        "Category": "AI",
    },
    "QUICK HIT 2": {
        "Title": "Quick Hit 2 Title",
        "Source": "5",
        "URL": "https://example.com/qh2",
        "Category": "AI",
    },
    "QUICK HIT 3": {
        "Title": "Quick Hit 3 Title",
        "Source": "6",
        "URL": "https://example.com/qh3",
        "Category": "AI",
    },
    "INDUSTRY DEVELOPMENT 1": {
        "Title": "Industry Dev 1 Title",
        "Source": "7",
        "URL": "https://example.com/ind1",
    },
    "INDUSTRY DEVELOPMENT 2": {
        "Title": "Industry Dev 2 Title",
        "Source": "8",
        "URL": "https://example.com/ind2",
    },
}

SAMPLE_PHASE1_OUTPUT = """\
*I've created 12 social media posts (6 DYK + 6 IT) from your newsletter.*

:bulb: *DID YOU KNOW POSTS*

*DYK #1 — AI Governance ROI*

*Source*: Featured Article Title
*Graphic Component* (45 words, 280 characters)
*Emphasis Recommendation*: Bold the headline and 50% stat
Did You Know?
*AI Governance ROI*
Companies implementing AI governance frameworks saw 50% improvement in deployment speed.
–––––––––––––––––
*DYK #2 — Construction AI Market Surge*

*Source*: Main Article 1 Title
*Graphic Component* (50 words, 310 characters)
*Emphasis Recommendation*: Bold market figures
Did You Know?
*Construction AI Market Surge*
The AI in construction market is projected to grow from $11.1B to $24.3B by 2030.
–––––––––––––––––
*DYK #3 — AGI Timeline Prediction*

*Source*: Main Article 2 Title
*Graphic Component* (48 words, 290 characters)
*Emphasis Recommendation*: Bold the timeline
Did You Know?
*AGI Timeline Prediction*
Some leaders predict AGI could arrive by 2026 or 2027.
–––––––––––––––––
*DYK #4 — Workforce Skills Shift*

*Source*: Quick Hit 1 Title
*Graphic Component* (42 words, 260 characters)
*Emphasis Recommendation*: Bold skills terms
Did You Know?
*Workforce Skills Shift*
CTE programs are shifting to AI-focused pathways.
–––––––––––––––––
*DYK #5 — Senate AI Hearing*

*Source*: Quick Hit 2 Title
*Graphic Component* (40 words, 250 characters)
*Emphasis Recommendation*: Bold policy terms
Did You Know?
*Senate AI Hearing*
Senate hearing on AI competition with China.
–––––––––––––––––
*DYK #6 — Smart Implementation*

*Source*: Quick Hit 3 Title
*Graphic Component* (43 words, 270 characters)
*Emphasis Recommendation*: Bold implementation terms
Did You Know?
*Smart Implementation*
Implementation protocols for AI adoption.
–––––––––––––––––

:gear: *INSIDE TIP POSTS*

*IT #1 — Start With Governance*

*Source*: Featured Article Title
*Graphic Component* (47 words, 290 characters)
*Emphasis Recommendation*: Bold action verbs
Inside Tip:
*Start With Governance*
Build your AI governance framework before scaling.
–––––––––––––––––
*IT #2 — Audit Your AI Stack*

*Source*: Main Article 1 Title
*Graphic Component* (44 words, 275 characters)
*Emphasis Recommendation*: Bold audit framework
Inside Tip:
*Audit Your AI Stack*
Review existing AI tools for compliance.
–––––––––––––––––
*IT #3 — Plan for Corrections*

*Source*: Main Article 2 Title
*Graphic Component* (46 words, 285 characters)
*Emphasis Recommendation*: Bold planning terms
Inside Tip:
*Plan for Corrections*
Prepare contingency plans for market shifts.
–––––––––––––––––
*IT #4 — Upskill Strategically*

*Source*: Quick Hit 1 Title
*Graphic Component* (41 words, 255 characters)
*Emphasis Recommendation*: Bold skill terms
Inside Tip:
*Upskill Strategically*
Focus on AI fundamentals before specialized tools.
–––––––––––––––––
*IT #5 — Monitor Policy Shifts*

*Source*: Industry Dev 1 Title
*Graphic Component* (39 words, 245 characters)
*Emphasis Recommendation*: Bold monitoring terms
Inside Tip:
*Monitor Policy Shifts*
Track regulatory developments in AI governance.
–––––––––––––––––
*IT #6 — Diversify Tech Bets*

*Source*: Industry Dev 2 Title
*Graphic Component* (42 words, 265 characters)
*Emphasis Recommendation*: Bold diversification terms
Inside Tip:
*Diversify Tech Bets*
Spread investments across AI modalities."""

SAMPLE_PHASE2_OUTPUT = """\
*DYK #1:* *AI Governance ROI*
*Source:* Featured Article Title

*GRAPHIC COMPONENT* (45 words, 280 characters):

Did You Know?
*AI Governance ROI*
Companies implementing AI governance frameworks saw 50% improvement.

*CAPTION* (210 characters):
Did you know?

Smart companies are finding that governance pays dividends.

AI governance frameworks deliver measurable speed improvements.

https://example.com/featured

*#AIGovernance #ComplianceROI #iS2Digital #iS2 #AI*

---

*IT #2:* *Audit Your AI Stack*
*Source:* Main Article 1 Title

*GRAPHIC COMPONENT* (44 words, 275 characters):

Inside Tip:
*Audit Your AI Stack*
Review existing AI tools for compliance.

*CAPTION* (195 characters):
Inside Tip:

Ready to optimize your AI toolkit?

Regular audits surface hidden compliance gaps.

https://example.com/main1

*#AIAudit #TechStack #iS2Digital #iS2 #Tech*

---

*DYK #3:* *AGI Timeline Prediction*
*Source:* Main Article 2 Title

*GRAPHIC COMPONENT* (48 words, 290 characters):

Did You Know?
*AGI Timeline Prediction*
Some leaders predict AGI could arrive by 2026 or 2027.

*CAPTION* (180 characters):
Did you know?

The AGI timeline is accelerating faster than expected.

Industry leaders now predict AGI arrival by 2026-2027.

https://example.com/main2

*#AGI #AIPredictions #iS2Digital #iS2 #Tech*"""


# ===========================================================================
# parse_phase1_titles
# ===========================================================================


class TestParsePhase1Titles:
    def test_extracts_dyk_titles(self):
        titles = parse_phase1_titles(SAMPLE_PHASE1_OUTPUT)
        dyk = [t for t in titles if t.startswith("DYK")]
        assert len(dyk) == 6

    def test_extracts_it_titles(self):
        titles = parse_phase1_titles(SAMPLE_PHASE1_OUTPUT)
        it = [t for t in titles if t.startswith("IT")]
        assert len(it) == 6

    def test_total_count(self):
        titles = parse_phase1_titles(SAMPLE_PHASE1_OUTPUT)
        assert len(titles) == 12

    def test_title_format(self):
        titles = parse_phase1_titles(SAMPLE_PHASE1_OUTPUT)
        assert "DYK #1 — AI Governance ROI" in titles
        assert "IT #1 — Start With Governance" in titles

    def test_empty_input(self):
        assert parse_phase1_titles("") == []

    def test_no_matches(self):
        assert parse_phase1_titles("no posts here") == []

    def test_dash_variants(self):
        """Should handle em-dash, en-dash, and hyphen."""
        text = "*DYK #1 — Headline A*\n*IT #2 – Headline B*\n*DYK #3 - Headline C*"
        titles = parse_phase1_titles(text)
        assert len(titles) == 3


# ===========================================================================
# parse_phase2_titles
# ===========================================================================


class TestParsePhase2Titles:
    def test_extracts_titles(self):
        titles = parse_phase2_titles(SAMPLE_PHASE2_OUTPUT)
        assert len(titles) == 3

    def test_title_format(self):
        titles = parse_phase2_titles(SAMPLE_PHASE2_OUTPUT)
        assert "DYK #1 — AI Governance ROI" in titles
        assert "IT #2 — Audit Your AI Stack" in titles

    def test_empty_input(self):
        assert parse_phase2_titles("") == []

    def test_colon_format(self):
        text = "*DYK #1:* *Test Headline*"
        titles = parse_phase2_titles(text)
        assert titles == ["DYK #1 — Test Headline"]

    def test_no_colon_format(self):
        text = "*IT #3* *Another Headline*"
        titles = parse_phase2_titles(text)
        assert titles == ["IT #3 — Another Headline"]


# ===========================================================================
# get_source_url
# ===========================================================================


class TestGetSourceUrl:
    def test_matches_by_key_name(self):
        url = get_source_url("FEATURED ARTICLE", SAMPLE_FORMATTED_THEME)
        assert url == "https://example.com/featured"

    def test_case_insensitive(self):
        url = get_source_url("featured article", SAMPLE_FORMATTED_THEME)
        assert url == "https://example.com/featured"

    def test_matches_main_article(self):
        url = get_source_url("MAIN ARTICLE 1", SAMPLE_FORMATTED_THEME)
        assert url == "https://example.com/main1"

    def test_matches_by_source_number(self):
        url = get_source_url("Source 4", SAMPLE_FORMATTED_THEME)
        assert url == "https://example.com/qh1"

    def test_strips_prefix_before_dash(self):
        url = get_source_url("MAIN ARTICLE 2 - extra info", SAMPLE_FORMATTED_THEME)
        assert url == "https://example.com/main2"

    def test_empty_source(self):
        assert get_source_url("", SAMPLE_FORMATTED_THEME) == ""

    def test_no_match(self):
        assert get_source_url("Unknown Source", SAMPLE_FORMATTED_THEME) == ""

    def test_non_dict_values_skipped(self):
        theme = {"THEME": "THEME: Test", "FEATURED ARTICLE": {"URL": "https://x.com"}}
        url = get_source_url("FEATURED ARTICLE", theme)
        assert url == "https://x.com"

    def test_missing_url_key(self):
        theme = {"FEATURED ARTICLE": {"Title": "No URL"}}
        url = get_source_url("FEATURED ARTICLE", theme)
        assert url == ""


# ===========================================================================
# parse_phase1_posts
# ===========================================================================


class TestParsePhase1Posts:
    def test_parses_selected_posts(self):
        selected = ["DYK #1 — AI Governance ROI", "IT #1 — Start With Governance"]
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT, selected, SAMPLE_FORMATTED_THEME
        )
        assert len(posts) == 2

    def test_post_fields(self):
        selected = ["DYK #1 — AI Governance ROI"]
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT, selected, SAMPLE_FORMATTED_THEME
        )
        assert len(posts) == 1
        p = posts[0]
        assert p.post_type == "DYK"
        assert p.number == 1
        assert p.headline == "AI Governance ROI"
        assert p.source == "Featured Article Title"
        assert p.graphic_info == "45 words, 280 characters"
        assert "Bold the headline" in p.emphasis

    def test_source_url_resolved(self):
        selected = ["IT #5 — Monitor Policy Shifts"]
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT, selected, SAMPLE_FORMATTED_THEME
        )
        assert len(posts) == 1
        # "Industry Dev 1 Title" → source number "1" matches FEATURED ARTICLE
        # (Source="1") via fallback. Source name doesn't match any key exactly.
        assert posts[0].source == "Industry Dev 1 Title"
        assert posts[0].source_url != ""

    def test_no_selection(self):
        posts = parse_phase1_posts(SAMPLE_PHASE1_OUTPUT, [], SAMPLE_FORMATTED_THEME)
        assert posts == []

    def test_unmatched_selection_ignored(self):
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT,
            ["DYK #99 — Nonexistent"],
            SAMPLE_FORMATTED_THEME,
        )
        assert posts == []

    def test_graphic_text_extracted(self):
        selected = ["DYK #1 — AI Governance ROI"]
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT, selected, SAMPLE_FORMATTED_THEME
        )
        assert "Did You Know?" in posts[0].graphic_text

    def test_it_post_parsed(self):
        selected = ["IT #1 — Start With Governance"]
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT, selected, SAMPLE_FORMATTED_THEME
        )
        assert len(posts) == 1
        assert posts[0].post_type == "IT"
        assert "Inside Tip:" in posts[0].graphic_text

    def test_frozen_dataclass(self):
        selected = ["DYK #1 — AI Governance ROI"]
        posts = parse_phase1_posts(
            SAMPLE_PHASE1_OUTPUT, selected, SAMPLE_FORMATTED_THEME
        )
        with pytest.raises(AttributeError):
            posts[0].title = "changed"  # type: ignore[misc]


# ===========================================================================
# filter_final_posts
# ===========================================================================


class TestFilterFinalPosts:
    def test_filters_selected(self):
        selected = ["DYK #1 — AI Governance ROI", "IT #2 — Audit Your AI Stack"]
        result = filter_final_posts(SAMPLE_PHASE2_OUTPUT, selected)
        assert "AI Governance ROI" in result
        assert "Audit Your AI Stack" in result
        # DYK #3 should NOT be included
        assert "AGI Timeline Prediction" not in result

    def test_all_selected(self):
        selected = [
            "DYK #1 — AI Governance ROI",
            "IT #2 — Audit Your AI Stack",
            "DYK #3 — AGI Timeline Prediction",
        ]
        result = filter_final_posts(SAMPLE_PHASE2_OUTPUT, selected)
        assert "AI Governance ROI" in result
        assert "Audit Your AI Stack" in result
        assert "AGI Timeline Prediction" in result

    def test_none_selected(self):
        result = filter_final_posts(SAMPLE_PHASE2_OUTPUT, [])
        assert result == ""

    def test_separator_format(self):
        selected = ["DYK #1 — AI Governance ROI", "IT #2 — Audit Your AI Stack"]
        result = filter_final_posts(SAMPLE_PHASE2_OUTPUT, selected)
        assert "---" in result

    def test_empty_input(self):
        result = filter_final_posts("", ["DYK #1 — Test"])
        assert result == ""


# ===========================================================================
# Form builders
# ===========================================================================


class TestBuildPhase1NextStepsForm:
    def test_structure(self):
        form = build_phase1_next_steps_form()
        assert len(form) == 1
        assert form[0]["fieldLabel"] == PHASE1_NEXT_STEPS_FIELD
        assert form[0]["fieldType"] == "dropdown"
        assert form[0]["requiredField"] is True

    def test_options(self):
        form = build_phase1_next_steps_form()
        options = form[0]["fieldOptions"]["values"]  # type: ignore[index]
        labels = [o["option"] for o in options]  # type: ignore[index]
        assert "Yes" in labels
        assert "Regenerate" in labels


class TestBuildPostSelectionForm:
    def test_with_titles(self):
        titles = ["DYK #1 — A", "IT #2 — B"]
        form = build_post_selection_form(titles)
        assert len(form) == 1
        assert form[0]["fieldLabel"] == POST_SELECTION_FIELD
        assert form[0]["fieldType"] == "checkbox"
        options = form[0]["fieldOptions"]["values"]  # type: ignore[index]
        assert len(options) == 2

    def test_empty_titles(self):
        form = build_post_selection_form([])
        options = form[0]["fieldOptions"]["values"]  # type: ignore[index]
        assert len(options) == 0


class TestBuildPhase2NextStepsForm:
    def test_structure(self):
        form = build_phase2_next_steps_form()
        assert len(form) == 1
        assert form[0]["fieldLabel"] == PHASE2_NEXT_STEPS_FIELD

    def test_options(self):
        form = build_phase2_next_steps_form()
        options = form[0]["fieldOptions"]["values"]  # type: ignore[index]
        labels = [o["option"] for o in options]  # type: ignore[index]
        assert "Yes" in labels
        assert "Provide Feedback" in labels
        assert "Restart Chat" in labels


class TestBuildFinalSelectionForm:
    def test_structure(self):
        titles = ["DYK #1 — A"]
        form = build_final_selection_form(titles)
        assert form[0]["fieldLabel"] == FINAL_SELECTION_FIELD
        assert form[0]["fieldType"] == "checkbox"


# ===========================================================================
# _parse_checkbox_response
# ===========================================================================


class TestParseCheckboxResponse:
    def test_json_array(self):
        raw = json.dumps(["DYK #1 — A", "IT #2 — B"])
        result = _parse_checkbox_response(raw)
        assert result == ["DYK #1 — A", "IT #2 — B"]

    def test_comma_separated(self):
        raw = "DYK #1 — A, IT #2 — B"
        result = _parse_checkbox_response(raw)
        assert result == ["DYK #1 — A", "IT #2 — B"]

    def test_empty_string(self):
        assert _parse_checkbox_response("") == []

    def test_single_item(self):
        result = _parse_checkbox_response("DYK #1 — A")
        assert result == ["DYK #1 — A"]

    def test_json_single_item(self):
        raw = json.dumps(["DYK #1 — A"])
        result = _parse_checkbox_response(raw)
        assert result == ["DYK #1 — A"]

    def test_strips_whitespace(self):
        raw = " DYK #1 — A ,  IT #2 — B "
        result = _parse_checkbox_response(raw)
        assert result == ["DYK #1 — A", "IT #2 — B"]


# ===========================================================================
# LLM calls
# ===========================================================================


class TestCallSocialMediaPostLLM:
    @pytest.mark.asyncio
    async def test_returns_content(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated posts"

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await call_social_media_post_llm(
                newsletter_content="<html>test</html>",
                formatted_theme='{"THEME": "test"}',
            )
        assert result == "Generated posts"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_social_media_post_llm(
                    newsletter_content="test",
                    formatted_theme="test",
                )

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  content  \n"

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await call_social_media_post_llm(
                newsletter_content="test",
                formatted_theme="test",
            )
        assert result == "content"

    @pytest.mark.asyncio
    async def test_uses_custom_model(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await call_social_media_post_llm(
                newsletter_content="test",
                formatted_theme="test",
                model="custom/model",
            )
            call_kwargs = mock_litellm.acompletion.call_args
            assert call_kwargs.kwargs["model"] == "custom/model"


class TestCallCaptionLLM:
    @pytest.mark.asyncio
    async def test_returns_content(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated captions"

        posts = [
            ParsedPost(
                title="DYK #1 — Test",
                post_type="DYK",
                number=1,
                headline="Test",
                source="Source",
                source_url="https://example.com",
                graphic_info="45 words",
                emphasis="Bold it",
                graphic_text="Did You Know? Test content.",
            ),
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await call_caption_llm(posts, SAMPLE_FORMATTED_THEME)
        assert result == "Generated captions"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_caption_llm([], SAMPLE_FORMATTED_THEME)

    @pytest.mark.asyncio
    async def test_posts_json_includes_fields(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"

        posts = [
            ParsedPost(
                title="IT #1 — Test",
                post_type="IT",
                number=1,
                headline="Test",
                source="Test Source",
                source_url="https://example.com",
                graphic_info="40 words",
                emphasis="Bold headline",
                graphic_text="Inside Tip: Test",
            ),
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await call_caption_llm(posts, SAMPLE_FORMATTED_THEME)
            call_args = mock_litellm.acompletion.call_args
            user_msg = call_args.kwargs["messages"][1]["content"]
            # Em-dash may be JSON-encoded as \u2014
            assert "IT #1" in user_msg
            assert "Test" in user_msg
            assert "https://example.com" in user_msg


class TestCallCaptionRegenerationLLM:
    @pytest.mark.asyncio
    async def test_returns_content(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Regenerated captions"

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await call_caption_regeneration_llm(
                feedback_text="Make it better",
                previous_captions="Old captions",
            )
        assert result == "Regenerated captions"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_caption_regeneration_llm(
                    feedback_text="feedback",
                    previous_captions="old",
                )


# ===========================================================================
# Google Doc creation
# ===========================================================================


class TestCreateSocialMediaDoc:
    @pytest.mark.asyncio
    async def test_creates_document(self):
        docs = AsyncMock()
        docs.create_document.return_value = "doc-123"

        doc_id, doc_url = await create_social_media_doc(docs, "content")

        docs.create_document.assert_awaited_once_with(GOOGLE_DOC_TITLE)
        docs.insert_content.assert_awaited_once_with("doc-123", "content")
        assert doc_id == "doc-123"
        assert "doc-123" in doc_url

    @pytest.mark.asyncio
    async def test_custom_title(self):
        docs = AsyncMock()
        docs.create_document.return_value = "doc-456"

        await create_social_media_doc(docs, "content", title="Custom Title")
        docs.create_document.assert_awaited_once_with("Custom Title")


# ===========================================================================
# Data types
# ===========================================================================


class TestParsedPost:
    def test_frozen(self):
        post = ParsedPost(
            title="DYK #1 — Test",
            post_type="DYK",
            number=1,
            headline="Test",
            source="Source",
            source_url="https://example.com",
            graphic_info="45 words",
            emphasis="Bold it",
            graphic_text="text",
        )
        with pytest.raises(AttributeError):
            post.title = "changed"  # type: ignore[misc]


class TestSocialMediaResult:
    def test_frozen(self):
        result = SocialMediaResult(
            doc_id="d1",
            doc_url="https://docs.google.com/d1",
            final_content="content",
            model="test/model",
        )
        with pytest.raises(AttributeError):
            result.doc_id = "changed"  # type: ignore[misc]

    def test_fields(self):
        result = SocialMediaResult(
            doc_id="d1",
            doc_url="url",
            final_content="content",
            model="model",
        )
        assert result.doc_id == "d1"
        assert result.doc_url == "url"
        assert result.final_content == "content"
        assert result.model == "model"


# ===========================================================================
# Full orchestration — run_social_media_generation
# ===========================================================================


class TestRunSocialMediaGeneration:
    """Tests for the main orchestration function."""

    def _make_slack(self) -> AsyncMock:
        slack = AsyncMock()
        return slack

    def _make_docs(self, html_content: str = "<html>test</html>") -> AsyncMock:
        docs = AsyncMock()
        docs.get_content.return_value = html_content
        docs.create_document.return_value = "doc-final"
        return docs

    def _mock_llm_response(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Full flow: approve → generate → approve → select → captions → approve → final select → doc."""
        slack = self._make_slack()
        docs = self._make_docs()

        # Phase 1: approve, generate, user says Yes
        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            # Phase 1 next steps: Yes
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            # Post selection
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            # Phase 2 next steps: Yes
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            # Final selection
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            # Phase 1 LLM call, then Phase 2 LLM call
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                ]
            )

            result = await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert isinstance(result, SocialMediaResult)
        assert result.doc_id == "doc-final"
        assert "doc-final" in result.doc_url
        assert result.final_content  # Non-empty

        # Verify approval was sent
        slack.send_and_wait.assert_awaited_once()

        # Verify Google Doc was created
        docs.create_document.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase1_regenerate_then_approve(self):
        """Phase 1: Regenerate once, then approve."""
        slack = self._make_slack()
        docs = self._make_docs()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            # Phase 1: Regenerate
            {PHASE1_NEXT_STEPS_FIELD: "Regenerate"},
            # Phase 1: Yes (after regen)
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            # Post selection
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            # Phase 2: Yes
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            # Final selection
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),  # regen
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                ]
            )

            result = await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert result.doc_id == "doc-final"
        # Phase 1 LLM called twice (initial + regen)
        assert mock_litellm.acompletion.await_count == 3

    @pytest.mark.asyncio
    async def test_phase2_feedback_then_approve(self):
        """Phase 2: Provide feedback once, then approve."""
        slack = self._make_slack()
        docs = self._make_docs()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_freetext.return_value = "Make captions shorter"
        slack.send_and_wait_form.side_effect = [
            # Phase 1: Yes
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            # Post selection
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            # Phase 2: Feedback
            {PHASE2_NEXT_STEPS_FIELD: "Provide Feedback"},
            # Phase 2: Yes (after regen)
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            # Final selection
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),  # regen
                ]
            )

            result = await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert result.doc_id == "doc-final"
        slack.send_and_wait_freetext.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase2_restart(self):
        """Phase 2: Restart once, then approve."""
        slack = self._make_slack()
        docs = self._make_docs()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            # Phase 1: Yes
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            # Post selection
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            # Phase 2: Restart
            {PHASE2_NEXT_STEPS_FIELD: "Restart Chat"},
            # Phase 2: Yes (after restart)
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            # Final selection
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),  # restart regen
                ]
            )

            result = await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert result.doc_id == "doc-final"

    @pytest.mark.asyncio
    async def test_no_docs_service(self):
        """Works without docs service (no Google Doc operations)."""
        slack = self._make_slack()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                ]
            )

            result = await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=None,
            )

        assert result.doc_id == ""
        assert result.doc_url == ""
        assert result.final_content  # Still has content

    @pytest.mark.asyncio
    async def test_doc_link_shared_in_slack(self):
        """Verifies the Google Doc link is shared in Slack."""
        slack = self._make_slack()
        docs = self._make_docs()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                ]
            )

            await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        # Last send_channel_message should contain the doc link
        last_call = slack.send_channel_message.call_args_list[-1]
        assert "doc-final" in last_call.args[0]

    @pytest.mark.asyncio
    async def test_approval_called_first(self):
        """The initial Slack approval is called before anything else."""
        slack = self._make_slack()
        docs = self._make_docs()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            {POST_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            {FINAL_SELECTION_FIELD: json.dumps(["DYK #1 — AI Governance ROI"])},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                ]
            )

            await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        slack.send_and_wait.assert_awaited_once_with(
            "#n8n-is2",
            APPROVAL_MESSAGE,
            approve_label="Yes",
        )

    @pytest.mark.asyncio
    async def test_comma_separated_selection(self):
        """Handles comma-separated checkbox response format."""
        slack = self._make_slack()
        docs = self._make_docs()

        slack.send_and_wait.return_value = "approved"
        slack.send_and_wait_form.side_effect = [
            {PHASE1_NEXT_STEPS_FIELD: "Yes"},
            # Comma-separated format instead of JSON
            {POST_SELECTION_FIELD: "DYK #1 — AI Governance ROI, IT #1 — Start With Governance"},
            {PHASE2_NEXT_STEPS_FIELD: "Yes"},
            {FINAL_SELECTION_FIELD: "DYK #1 — AI Governance ROI"},
        ]

        with patch("ica.pipeline.social_media.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    self._mock_llm_response(SAMPLE_PHASE1_OUTPUT),
                    self._mock_llm_response(SAMPLE_PHASE2_OUTPUT),
                ]
            )

            result = await run_social_media_generation(
                html_doc_id="html-doc-id",
                formatted_theme=SAMPLE_FORMATTED_THEME,
                slack=slack,
                docs=docs,
            )

        assert result.doc_id == "doc-final"


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    """Verify key constants match expected values."""

    def test_google_doc_title(self):
        assert GOOGLE_DOC_TITLE == "Social-media-posts"

    def test_phase1_options(self):
        from ica.pipeline.social_media import PHASE1_NEXT_STEPS_OPTIONS

        assert PHASE1_NEXT_STEPS_OPTIONS == ["Yes", "Regenerate"]

    def test_phase2_options(self):
        from ica.pipeline.social_media import PHASE2_NEXT_STEPS_OPTIONS

        assert PHASE2_NEXT_STEPS_OPTIONS == ["Yes", "Provide Feedback", "Restart Chat"]

    def test_slack_channel(self):
        from ica.pipeline.social_media import SLACK_CHANNEL

        assert SLACK_CHANNEL == "#n8n-is2"
