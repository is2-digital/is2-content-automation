"""Tests for ica.utils.marker_parser — %XX_ marker extraction.

Verifies regex extraction of FA, M1, M2, Q1-Q3, I1-I2 markers with
various LLM output formats.  Covers the "Selected Theme output" and
"Prepare AI generated themes" n8n Code nodes.
"""

from __future__ import annotations

import pytest

from ica.utils.marker_parser import (
    FeaturedArticle,
    FormattedTheme,
    IndustryDevelopment,
    MainArticle,
    ParsedThemeBlock,
    QuickHit,
    RequirementsVerified,
    ThemeParseResult,
    parse_markers,
    split_themes,
)


# ======================================================================
# Fixtures — realistic LLM output samples
# ======================================================================

THEME_BODY_COMPLETE = """\
THEME: AI Reshaping Enterprise Workflows
Theme Description: How artificial intelligence is transforming daily business operations across industries.

Articles that fit.
FEATURED ARTICLE:
%FA_TITLE: The Rise of AI Agents in Enterprise Software
%FA_SOURCE: 3
%FA_ORIGIN: TechCrunch
%FA_URL: https://techcrunch.com/2026/02/ai-agents-enterprise
%FA_CATEGORY: Enterprise AI
%FA_WHY FEATURED: Comprehensive analysis of the most impactful trend

%M1_TITLE: How Small Businesses Are Using LLMs to Cut Costs
%M1_SOURCE: 1
%M1_ORIGIN: Forbes
%M1_URL: https://forbes.com/2026/02/smb-llm-costs
%M1_CATEGORY: SMB Technology
%M1_RATIONALE: Directly relevant to solopreneur audience

%M2_TITLE: OpenAI Launches New Developer Tools
%M2_SOURCE: 5
%M2_ORIGIN: The Verge
%M2_URL: https://theverge.com/2026/02/openai-dev-tools
%M2_CATEGORY: Developer Tools
%M2_RATIONALE: High interest topic for technical audience

%Q1_TITLE: Google Announces Gemini 3.0
%Q1_SOURCE: 2
%Q1_ORIGIN: Ars Technica
%Q1_URL: https://arstechnica.com/2026/02/gemini-3
%Q1_CATEGORY: AI Models

%Q2_TITLE: EU Passes Comprehensive AI Regulation
%Q2_SOURCE: 7
%Q2_ORIGIN: Reuters
%Q2_URL: https://reuters.com/2026/02/eu-ai-act
%Q2_CATEGORY: AI Policy

%Q3_TITLE: Anthropic Raises $5B Series D
%Q3_SOURCE: 4
%Q3_ORIGIN: Bloomberg
%Q3_URL: https://bloomberg.com/2026/02/anthropic-series-d
%Q3_CATEGORY: AI Industry

%I1_TITLE: Microsoft Integrates Copilot Across Office Suite
%I1_SOURCE: 6
%I1_ORIGIN: Microsoft Blog
%I1_URL: https://blogs.microsoft.com/2026/02/copilot-office
%I1_Major AI Player: Microsoft

%I2_TITLE: Amazon Expands Bedrock with Custom Model Training
%I2_SOURCE: 8
%I2_ORIGIN: AWS Blog
%I2_URL: https://aws.amazon.com/blogs/2026/02/bedrock-custom
%I2_Major AI Player: Amazon

2-2-2 Distribution:
%222_tactical:% (Source 1) SMB cost cutting, (Source 3) enterprise agents
%222_educational:% (Source 2) Gemini capabilities, (Source 7) EU regulation
%222_forward-thinking:% (Source 5) developer tools, (Source 4) Anthropic growth

Source mix:
%SM_smaller_publisher:% Ars Technica (Source 2), Microsoft Blog (Source 6)
%SM_major_ai_player_coverage:% Microsoft Copilot integration (Source 6)

REQUIREMENTS VERIFIED,
%RV_2-2-2 Distribution Achieved:% SMB LLMs Source(1), AI Agents Source(3), Gemini Source(2), EU AI Act Source(7), Dev Tools Source(5), Anthropic Source(4)
%RV_Source mix:% (Source 2) Ars Technica, (Source 6) Microsoft Blog
%RV_Technical complexity:% (Source 5) OpenAI developer platform
%RV_Major AI player coverage:% (Source 6) Microsoft Copilot
"""

THEME_BODY_MINIMAL = """\
THEME: Quick AI Roundup
%FA_TITLE: AI News Digest
%FA_SOURCE: 1
%FA_URL: https://example.com/article1
%M1_TITLE: Main Story One
%M1_SOURCE: 2
%M1_URL: https://example.com/article2
%M2_TITLE: Main Story Two
%M2_SOURCE: 3
%M2_URL: https://example.com/article3
%Q1_TITLE: Quick One
%Q1_SOURCE: 4
%Q1_URL: https://example.com/article4
%Q2_TITLE: Quick Two
%Q2_SOURCE: 5
%Q2_URL: https://example.com/article5
%Q3_TITLE: Quick Three
%Q3_SOURCE: 6
%Q3_URL: https://example.com/article6
%I1_TITLE: Industry One
%I1_SOURCE: 7
%I1_URL: https://example.com/article7
%I1_Major AI Player: Google
%I2_TITLE: Industry Two
%I2_SOURCE: 8
%I2_URL: https://example.com/article8
%I2_Major AI Player: Meta
"""

TWO_THEMES_RAW = (
    THEME_BODY_COMPLETE
    + "\n-----\n\n"
    + THEME_BODY_MINIMAL
    + "\n-----\n\n"
    + "RECOMMENDATION: Theme 1 - AI Reshaping Enterprise Workflows\n"
    + "Rationale:\n"
    + "1. Featured Article: Strong enterprise focus\n"
    + "2. Main Articles: Good audience fit\n"
    + "3. Quick Hits: Diverse coverage\n"
    + "This theme provides the best overall narrative.\n"
)


# ======================================================================
# Tests — parse_markers / Featured Article (FA)
# ======================================================================


class TestFeaturedArticle:
    """FA marker extraction."""

    def test_extracts_all_fa_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        fa = result.featured_article
        assert fa.title == "The Rise of AI Agents in Enterprise Software"
        assert fa.source == "3"
        assert fa.origin == "TechCrunch"
        assert fa.url == "https://techcrunch.com/2026/02/ai-agents-enterprise"
        assert fa.category == "Enterprise AI"
        assert fa.why_featured == "Comprehensive analysis of the most impactful trend"

    def test_fa_title_with_colon_in_value(self) -> None:
        body = "%FA_TITLE: AI: The Next Frontier"
        result = parse_markers(body)
        assert result.featured_article.title == "AI: The Next Frontier"

    def test_fa_with_extra_whitespace(self) -> None:
        body = "%FA_TITLE:   Lots of Spaces   "
        result = parse_markers(body)
        assert result.featured_article.title == "Lots of Spaces"

    def test_fa_missing_why_featured(self) -> None:
        body = "%FA_TITLE: Some Title\n%FA_SOURCE: 1"
        result = parse_markers(body)
        assert result.featured_article.title == "Some Title"
        assert result.featured_article.why_featured is None

    def test_fa_empty_value_is_none(self) -> None:
        body = "%FA_TITLE:   \n%FA_SOURCE: 2"
        result = parse_markers(body)
        assert result.featured_article.title is None
        assert result.featured_article.source == "2"

    def test_fa_url_with_query_params(self) -> None:
        body = "%FA_URL: https://example.com/article?id=123&ref=ai"
        result = parse_markers(body)
        assert result.featured_article.url == "https://example.com/article?id=123&ref=ai"

    def test_fa_why_featured_with_special_chars(self) -> None:
        body = "%FA_WHY FEATURED: It's the #1 article — very insightful!"
        result = parse_markers(body)
        assert result.featured_article.why_featured == "It's the #1 article — very insightful!"


# ======================================================================
# Tests — parse_markers / Main Articles (M1, M2)
# ======================================================================


class TestMainArticles:
    """M1 and M2 marker extraction."""

    def test_extracts_all_m1_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        m1 = result.main_article_1
        assert m1.title == "How Small Businesses Are Using LLMs to Cut Costs"
        assert m1.source == "1"
        assert m1.origin == "Forbes"
        assert m1.url == "https://forbes.com/2026/02/smb-llm-costs"
        assert m1.category == "SMB Technology"
        assert m1.rationale == "Directly relevant to solopreneur audience"

    def test_extracts_all_m2_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        m2 = result.main_article_2
        assert m2.title == "OpenAI Launches New Developer Tools"
        assert m2.source == "5"
        assert m2.origin == "The Verge"
        assert m2.url == "https://theverge.com/2026/02/openai-dev-tools"
        assert m2.category == "Developer Tools"
        assert m2.rationale == "High interest topic for technical audience"

    def test_m1_without_rationale(self) -> None:
        body = "%M1_TITLE: No Rationale Article\n%M1_SOURCE: 2\n%M1_URL: https://x.com"
        result = parse_markers(body)
        assert result.main_article_1.title == "No Rationale Article"
        assert result.main_article_1.rationale is None

    def test_m2_without_origin(self) -> None:
        body = "%M2_TITLE: Missing Origin\n%M2_SOURCE: 4"
        result = parse_markers(body)
        assert result.main_article_2.origin is None

    def test_m1_and_m2_do_not_cross_contaminate(self) -> None:
        body = "%M1_TITLE: First\n%M2_TITLE: Second"
        result = parse_markers(body)
        assert result.main_article_1.title == "First"
        assert result.main_article_2.title == "Second"


# ======================================================================
# Tests — parse_markers / Quick Hits (Q1, Q2, Q3)
# ======================================================================


class TestQuickHits:
    """Q1, Q2, Q3 marker extraction."""

    def test_extracts_all_q1_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        q = result.quick_hit_1
        assert q.title == "Google Announces Gemini 3.0"
        assert q.source == "2"
        assert q.origin == "Ars Technica"
        assert q.url == "https://arstechnica.com/2026/02/gemini-3"
        assert q.category == "AI Models"

    def test_extracts_all_q2_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        q = result.quick_hit_2
        assert q.title == "EU Passes Comprehensive AI Regulation"
        assert q.source == "7"
        assert q.origin == "Reuters"

    def test_extracts_all_q3_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        q = result.quick_hit_3
        assert q.title == "Anthropic Raises $5B Series D"
        assert q.source == "4"
        assert q.origin == "Bloomberg"

    def test_quick_hits_have_no_rationale(self) -> None:
        """Quick Hits do not use a RATIONALE field (unlike Main Articles)."""
        result = parse_markers(THEME_BODY_COMPLETE)
        # QuickHit dataclass doesn't even have a rationale attr
        assert not hasattr(result.quick_hit_1, "rationale")

    def test_q_markers_do_not_cross_contaminate(self) -> None:
        body = "%Q1_TITLE: One\n%Q2_TITLE: Two\n%Q3_TITLE: Three"
        result = parse_markers(body)
        assert result.quick_hit_1.title == "One"
        assert result.quick_hit_2.title == "Two"
        assert result.quick_hit_3.title == "Three"

    def test_q_partial_only_q2(self) -> None:
        body = "%Q2_TITLE: Only This One\n%Q2_SOURCE: 5"
        result = parse_markers(body)
        assert result.quick_hit_1.title is None
        assert result.quick_hit_2.title == "Only This One"
        assert result.quick_hit_3.title is None


# ======================================================================
# Tests — parse_markers / Industry Developments (I1, I2)
# ======================================================================


class TestIndustryDevelopments:
    """I1, I2 marker extraction."""

    def test_extracts_all_i1_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        i = result.industry_development_1
        assert i.title == "Microsoft Integrates Copilot Across Office Suite"
        assert i.source == "6"
        assert i.origin == "Microsoft Blog"
        assert i.url == "https://blogs.microsoft.com/2026/02/copilot-office"
        assert i.major_ai_player == "Microsoft"

    def test_extracts_all_i2_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        i = result.industry_development_2
        assert i.title == "Amazon Expands Bedrock with Custom Model Training"
        assert i.source == "8"
        assert i.major_ai_player == "Amazon"

    def test_industry_has_major_ai_player_not_category(self) -> None:
        """Industry uses 'Major AI Player' instead of CATEGORY."""
        result = parse_markers(THEME_BODY_COMPLETE)
        assert not hasattr(result.industry_development_1, "category")
        assert result.industry_development_1.major_ai_player is not None

    def test_i_markers_do_not_cross_contaminate(self) -> None:
        body = (
            "%I1_TITLE: First Industry\n%I1_Major AI Player: Google\n"
            "%I2_TITLE: Second Industry\n%I2_Major AI Player: Meta"
        )
        result = parse_markers(body)
        assert result.industry_development_1.title == "First Industry"
        assert result.industry_development_1.major_ai_player == "Google"
        assert result.industry_development_2.title == "Second Industry"
        assert result.industry_development_2.major_ai_player == "Meta"

    def test_i_major_ai_player_with_spaces(self) -> None:
        body = "%I1_Major AI Player: Google DeepMind"
        result = parse_markers(body)
        assert result.industry_development_1.major_ai_player == "Google DeepMind"


# ======================================================================
# Tests — parse_markers / Requirements Verified (RV)
# ======================================================================


class TestRequirementsVerified:
    """RV marker extraction (note the trailing % in field names)."""

    def test_extracts_all_rv_fields(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        rv = result.requirements_verified
        assert rv.distribution_achieved is not None
        assert "Source(1)" in rv.distribution_achieved
        assert rv.source_mix is not None
        assert rv.technical_complexity is not None
        assert rv.major_ai_player_coverage is not None

    def test_rv_distribution_achieved_content(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        rv = result.requirements_verified
        assert "SMB LLMs" in rv.distribution_achieved
        assert "Gemini" in rv.distribution_achieved

    def test_rv_partial_only_source_mix(self) -> None:
        body = "%RV_Source mix:% (Source 2) Ars Technica"
        result = parse_markers(body)
        assert result.requirements_verified.source_mix == "(Source 2) Ars Technica"
        assert result.requirements_verified.distribution_achieved is None

    def test_rv_fields_have_trailing_percent_in_pattern(self) -> None:
        """RV markers use ``%RV_Field:% value`` (trailing %)."""
        body = "%RV_Technical complexity:% (Source 5) Advanced topic"
        result = parse_markers(body)
        assert result.requirements_verified.technical_complexity == "(Source 5) Advanced topic"


# ======================================================================
# Tests — parse_markers / Theme title
# ======================================================================


class TestThemeTitle:
    """Theme title resolution."""

    def test_title_from_body(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        assert result.theme == "AI Reshaping Enterprise Workflows"

    def test_title_override(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE, theme_title="Custom Title")
        assert result.theme == "Custom Title"

    def test_title_none_when_missing(self) -> None:
        body = "%FA_TITLE: No theme line here"
        result = parse_markers(body)
        assert result.theme is None

    def test_title_with_colon(self) -> None:
        body = "THEME: AI: The Next Chapter"
        result = parse_markers(body)
        assert result.theme == "AI: The Next Chapter"


# ======================================================================
# Tests — parse_markers / Edge cases
# ======================================================================


class TestEdgeCases:
    """Edge cases and LLM output format variations."""

    def test_empty_string(self) -> None:
        result = parse_markers("")
        assert result.theme is None
        assert result.featured_article.title is None
        assert result.main_article_1.title is None

    def test_no_markers_at_all(self) -> None:
        result = parse_markers("Just some plain text with no markers.")
        assert result.featured_article == FeaturedArticle()
        assert result.main_article_1 == MainArticle()

    def test_markers_with_no_space_after_colon(self) -> None:
        """LLM sometimes omits space after colon."""
        body = "%FA_TITLE:No Space Title"
        result = parse_markers(body)
        # regex is `:\s*(.+)` so zero spaces should still match
        assert result.featured_article.title == "No Space Title"

    def test_markers_with_multiple_spaces(self) -> None:
        body = "%FA_TITLE:    Extra Spaces   "
        result = parse_markers(body)
        assert result.featured_article.title == "Extra Spaces"

    def test_markers_with_tab_after_colon(self) -> None:
        body = "%FA_TITLE:\tTab Title"
        result = parse_markers(body)
        assert result.featured_article.title == "Tab Title"

    def test_duplicate_markers_uses_first(self) -> None:
        """If LLM repeats a marker, the first occurrence is used (re.search)."""
        body = "%FA_TITLE: First Title\n%FA_TITLE: Second Title"
        result = parse_markers(body)
        assert result.featured_article.title == "First Title"

    def test_markers_case_sensitive(self) -> None:
        """Markers must match exact case (e.g., %FA_TITLE not %fa_title)."""
        body = "%fa_title: Lowercase Marker"
        result = parse_markers(body)
        assert result.featured_article.title is None

    def test_markers_with_windows_line_endings(self) -> None:
        body = "%FA_TITLE: Windows Title\r\n%FA_SOURCE: 1\r\n"
        result = parse_markers(body)
        assert result.featured_article.title == "Windows Title"
        assert result.featured_article.source == "1"

    def test_value_with_url_brackets(self) -> None:
        body = "%FA_URL: [https://example.com](https://example.com)"
        result = parse_markers(body)
        assert "example.com" in result.featured_article.url

    def test_minimal_theme_body(self) -> None:
        result = parse_markers(THEME_BODY_MINIMAL)
        assert result.theme == "Quick AI Roundup"
        assert result.featured_article.title == "AI News Digest"
        assert result.main_article_1.title == "Main Story One"
        assert result.main_article_2.title == "Main Story Two"
        assert result.quick_hit_1.title == "Quick One"
        assert result.quick_hit_2.title == "Quick Two"
        assert result.quick_hit_3.title == "Quick Three"
        assert result.industry_development_1.title == "Industry One"
        assert result.industry_development_1.major_ai_player == "Google"
        assert result.industry_development_2.title == "Industry Two"
        assert result.industry_development_2.major_ai_player == "Meta"

    def test_full_theme_body_all_slots_populated(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        assert result.featured_article.title is not None
        assert result.main_article_1.title is not None
        assert result.main_article_2.title is not None
        assert result.quick_hit_1.title is not None
        assert result.quick_hit_2.title is not None
        assert result.quick_hit_3.title is not None
        assert result.industry_development_1.title is not None
        assert result.industry_development_2.title is not None

    def test_value_with_parentheses(self) -> None:
        body = "%FA_WHY FEATURED: Strong coverage (including 5 case studies)"
        result = parse_markers(body)
        assert result.featured_article.why_featured == (
            "Strong coverage (including 5 case studies)"
        )

    def test_value_with_comma_separated_list(self) -> None:
        body = "%RV_2-2-2 Distribution Achieved:% A, B, C"
        result = parse_markers(body)
        assert result.requirements_verified.distribution_achieved == "A, B, C"


# ======================================================================
# Tests — parse_markers / LLM format variations
# ======================================================================


class TestLlmFormatVariations:
    """Handle variations in how different LLMs format marker output."""

    def test_markers_with_markdown_bold(self) -> None:
        """Some LLMs wrap markers in markdown bold — regex still finds the
        marker substring inside the bold wrapper, capturing trailing ``**``."""
        body = "**%FA_TITLE:** AI Revolution"
        result = parse_markers(body)
        # The regex finds %FA_TITLE: inside the bold, captures "** AI Revolution"
        assert result.featured_article.title == "** AI Revolution"

    def test_markers_at_line_start(self) -> None:
        body = "%FA_TITLE: At Line Start"
        result = parse_markers(body)
        assert result.featured_article.title == "At Line Start"

    def test_markers_after_whitespace(self) -> None:
        """Some LLMs indent markers."""
        body = "  %FA_TITLE: Indented"
        result = parse_markers(body)
        assert result.featured_article.title == "Indented"

    def test_markers_with_extra_newlines_between(self) -> None:
        body = "%FA_TITLE: First\n\n\n%FA_SOURCE: 1"
        result = parse_markers(body)
        assert result.featured_article.title == "First"
        assert result.featured_article.source == "1"

    def test_semicolon_after_url(self) -> None:
        """n8n prompt has a semicolon after M1_URL."""
        body = "%M1_URL: https://example.com/article;"
        result = parse_markers(body)
        assert result.main_article_1.url == "https://example.com/article;"

    def test_multiline_value_only_captures_first_line(self) -> None:
        """regex `.+` doesn't cross newlines, so only first line is captured."""
        body = "%FA_WHY FEATURED: First line reason\nContinued on next line"
        result = parse_markers(body)
        assert result.featured_article.why_featured == "First line reason"


# ======================================================================
# Tests — split_themes
# ======================================================================


class TestSplitThemes:
    """Theme splitting from raw LLM output."""

    def test_splits_two_themes_and_recommendation(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        assert len(result.themes) == 2
        assert result.recommendation != ""

    def test_first_theme_name(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        assert result.themes[0].theme_name == "AI Reshaping Enterprise Workflows"

    def test_second_theme_name(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        assert result.themes[1].theme_name == "Quick AI Roundup"

    def test_first_theme_description(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        desc = result.themes[0].theme_description
        assert desc is not None
        assert "artificial intelligence" in desc

    def test_second_theme_no_description(self) -> None:
        """Minimal theme body has no Theme Description line."""
        result = split_themes(TWO_THEMES_RAW)
        assert result.themes[1].theme_description is None

    def test_theme_body_contains_markers(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        assert "%FA_TITLE:" in result.themes[0].theme_body
        assert "%I2_Major AI Player:" in result.themes[1].theme_body

    def test_recommendation_contains_theme_name(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        assert "AI Reshaping Enterprise Workflows" in result.recommendation

    def test_recommendation_contains_rationale(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        assert "Rationale:" in result.recommendation

    def test_empty_input(self) -> None:
        result = split_themes("")
        assert result.themes == []
        assert result.recommendation == ""

    def test_single_theme_no_separator(self) -> None:
        result = split_themes(THEME_BODY_COMPLETE)
        assert len(result.themes) == 1
        assert result.themes[0].theme_name == "AI Reshaping Enterprise Workflows"
        assert result.recommendation == ""

    def test_only_separators(self) -> None:
        result = split_themes("-----\n-----\n-----")
        assert result.themes == []

    def test_extra_whitespace_around_separators(self) -> None:
        raw = f"  {THEME_BODY_MINIMAL}  \n  -----  \n  RECOMMENDATION: Theme 1  "
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert result.recommendation != ""

    def test_three_themes(self) -> None:
        """Edge case: LLM generates 3 themes instead of 2."""
        raw = (
            "THEME: First\n-----\n"
            "THEME: Second\n-----\n"
            "THEME: Third\n-----\n"
            "RECOMMENDATION: Theme 2 - Second"
        )
        result = split_themes(raw)
        assert len(result.themes) == 3
        assert result.themes[2].theme_name == "Third"

    def test_recommendation_not_in_themes(self) -> None:
        result = split_themes(TWO_THEMES_RAW)
        for theme in result.themes:
            assert "RECOMMENDATION:" not in theme.theme_body


# ======================================================================
# Tests — split_themes + parse_markers integration
# ======================================================================


class TestSplitAndParse:
    """End-to-end: split themes then parse markers for each."""

    def test_round_trip_first_theme(self) -> None:
        split_result = split_themes(TWO_THEMES_RAW)
        parsed = parse_markers(split_result.themes[0].theme_body)
        assert parsed.featured_article.title == "The Rise of AI Agents in Enterprise Software"
        assert parsed.main_article_1.source == "1"
        assert parsed.industry_development_1.major_ai_player == "Microsoft"

    def test_round_trip_second_theme(self) -> None:
        split_result = split_themes(TWO_THEMES_RAW)
        parsed = parse_markers(split_result.themes[1].theme_body)
        assert parsed.featured_article.title == "AI News Digest"
        assert parsed.industry_development_2.major_ai_player == "Meta"

    def test_round_trip_with_title_override(self) -> None:
        split_result = split_themes(TWO_THEMES_RAW)
        theme_block = split_result.themes[0]
        parsed = parse_markers(theme_block.theme_body, theme_title=theme_block.theme_name)
        assert parsed.theme == "AI Reshaping Enterprise Workflows"

    def test_all_article_urls_present_in_first_theme(self) -> None:
        split_result = split_themes(TWO_THEMES_RAW)
        parsed = parse_markers(split_result.themes[0].theme_body)
        urls = [
            parsed.featured_article.url,
            parsed.main_article_1.url,
            parsed.main_article_2.url,
            parsed.quick_hit_1.url,
            parsed.quick_hit_2.url,
            parsed.quick_hit_3.url,
            parsed.industry_development_1.url,
            parsed.industry_development_2.url,
        ]
        assert all(u is not None and u.startswith("https://") for u in urls)


# ======================================================================
# Tests — dataclass integrity
# ======================================================================


class TestDataclasses:
    """Verify dataclass construction and immutability."""

    def test_formatted_theme_is_frozen(self) -> None:
        result = parse_markers(THEME_BODY_COMPLETE)
        with pytest.raises(AttributeError):
            result.theme = "Mutated"  # type: ignore[misc]

    def test_featured_article_is_frozen(self) -> None:
        fa = FeaturedArticle(title="Test")
        with pytest.raises(AttributeError):
            fa.title = "Mutated"  # type: ignore[misc]

    def test_default_formatted_theme_all_none(self) -> None:
        ft = FormattedTheme()
        assert ft.theme is None
        assert ft.featured_article == FeaturedArticle()
        assert ft.main_article_1 == MainArticle()

    def test_parsed_theme_block_defaults(self) -> None:
        ptb = ParsedThemeBlock()
        assert ptb.theme_name is None
        assert ptb.theme_description is None
        assert ptb.theme_body == ""

    def test_theme_parse_result_defaults(self) -> None:
        tpr = ThemeParseResult()
        assert tpr.themes == []
        assert tpr.recommendation == ""

    def test_equality_for_same_values(self) -> None:
        a = FeaturedArticle(title="Same", source="1")
        b = FeaturedArticle(title="Same", source="1")
        assert a == b

    def test_inequality_for_different_values(self) -> None:
        a = FeaturedArticle(title="A")
        b = FeaturedArticle(title="B")
        assert a != b


# ======================================================================
# Tests — parametrized marker extraction
# ======================================================================


@pytest.mark.parametrize(
    "marker_line, field, expected",
    [
        ("%FA_TITLE: AI Revolution", "featured_article.title", "AI Revolution"),
        ("%FA_SOURCE: 3", "featured_article.source", "3"),
        ("%FA_ORIGIN: TechCrunch", "featured_article.origin", "TechCrunch"),
        ("%FA_URL: https://x.com/a", "featured_article.url", "https://x.com/a"),
        ("%FA_CATEGORY: AI", "featured_article.category", "AI"),
        ("%FA_WHY FEATURED: Best one", "featured_article.why_featured", "Best one"),
        ("%M1_TITLE: Main One", "main_article_1.title", "Main One"),
        ("%M1_SOURCE: 1", "main_article_1.source", "1"),
        ("%M1_ORIGIN: Forbes", "main_article_1.origin", "Forbes"),
        ("%M1_URL: https://y.com", "main_article_1.url", "https://y.com"),
        ("%M1_CATEGORY: Tech", "main_article_1.category", "Tech"),
        ("%M1_RATIONALE: Relevant", "main_article_1.rationale", "Relevant"),
        ("%M2_TITLE: Main Two", "main_article_2.title", "Main Two"),
        ("%M2_RATIONALE: Good fit", "main_article_2.rationale", "Good fit"),
        ("%Q1_TITLE: Quick 1", "quick_hit_1.title", "Quick 1"),
        ("%Q2_TITLE: Quick 2", "quick_hit_2.title", "Quick 2"),
        ("%Q3_TITLE: Quick 3", "quick_hit_3.title", "Quick 3"),
        ("%Q1_CATEGORY: Policy", "quick_hit_1.category", "Policy"),
        ("%I1_TITLE: Industry 1", "industry_development_1.title", "Industry 1"),
        ("%I2_TITLE: Industry 2", "industry_development_2.title", "Industry 2"),
        ("%I1_Major AI Player: OpenAI", "industry_development_1.major_ai_player", "OpenAI"),
        ("%I2_Major AI Player: Anthropic", "industry_development_2.major_ai_player", "Anthropic"),
        (
            "%RV_2-2-2 Distribution Achieved:% Yes",
            "requirements_verified.distribution_achieved",
            "Yes",
        ),
        ("%RV_Source mix:% Good", "requirements_verified.source_mix", "Good"),
        (
            "%RV_Technical complexity:% High",
            "requirements_verified.technical_complexity",
            "High",
        ),
        (
            "%RV_Major AI player coverage:% Microsoft",
            "requirements_verified.major_ai_player_coverage",
            "Microsoft",
        ),
    ],
    ids=lambda val: val if isinstance(val, str) and val.startswith("%") else "",
)
def test_individual_marker_extraction(
    marker_line: str,
    field: str,
    expected: str,
) -> None:
    """Parametrized test: each marker line extracts to the correct field."""
    result = parse_markers(marker_line)
    # Navigate dotted field path (e.g., "featured_article.title")
    obj = result
    for attr in field.split("."):
        obj = getattr(obj, attr)
    assert obj == expected
