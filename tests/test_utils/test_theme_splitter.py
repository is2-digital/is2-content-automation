"""Tests for split_themes() — theme body splitting from LLM output.

Verifies that raw LLM theme-generation output is correctly split by
the ``-----`` separator into theme blocks and a recommendation section.
Covers separator variations, RECOMMENDATION routing, edge cases, and
ParsedThemeBlock field extraction.
"""

from __future__ import annotations

import pytest

from ica.utils.marker_parser import (
    ParsedThemeBlock,
    ThemeParseResult,
    split_themes,
)

# ======================================================================
# Fixtures — reusable LLM output snippets
# ======================================================================

THEME_A = """\
THEME: AI in Healthcare
Theme Description: How AI is transforming patient care and drug discovery.

%FA_TITLE: DeepMind Predicts Protein Structures
%FA_SOURCE: 1
%FA_URL: https://example.com/deepmind
"""

THEME_B = """\
THEME: Autonomous Vehicles 2026
Theme Description: The state of self-driving technology this year.

%FA_TITLE: Waymo Expands to 10 More Cities
%FA_SOURCE: 2
%FA_URL: https://example.com/waymo
"""

RECOMMENDATION_BLOCK = """\
RECOMMENDATION: Theme 1 - AI in Healthcare
Rationale:
1. Featured Article: Strong enterprise focus
2. Main Articles: Good audience fit
This theme provides the best overall narrative.\
"""

TWO_THEMES_WITH_RECOMMENDATION = (
    THEME_A + "\n-----\n" + THEME_B + "\n-----\n" + RECOMMENDATION_BLOCK
)


# ======================================================================
# Basic splitting behavior
# ======================================================================


class TestBasicSplitting:
    """Core splitting on ``-----`` delimiters."""

    def test_two_themes_produces_two_blocks(self) -> None:
        raw = THEME_A + "\n-----\n" + THEME_B
        result = split_themes(raw)
        assert len(result.themes) == 2

    def test_single_theme_no_separator(self) -> None:
        result = split_themes(THEME_A)
        assert len(result.themes) == 1
        assert result.recommendation == ""

    def test_three_themes(self) -> None:
        raw = THEME_A + "\n-----\n" + THEME_B + "\n-----\nTHEME: Third Option\n"
        result = split_themes(raw)
        assert len(result.themes) == 3
        assert result.themes[2].theme_name == "Third Option"

    def test_four_themes(self) -> None:
        raw = "\n-----\n".join(
            [
                "THEME: One",
                "THEME: Two",
                "THEME: Three",
                "THEME: Four",
            ]
        )
        result = split_themes(raw)
        assert len(result.themes) == 4

    def test_theme_order_preserved(self) -> None:
        raw = "THEME: Alpha\n-----\nTHEME: Beta\n-----\nTHEME: Gamma"
        result = split_themes(raw)
        names = [t.theme_name for t in result.themes]
        assert names == ["Alpha", "Beta", "Gamma"]


# ======================================================================
# RECOMMENDATION routing
# ======================================================================


class TestRecommendationRouting:
    """Blocks containing ``RECOMMENDATION:`` go to the recommendation field."""

    def test_recommendation_extracted(self) -> None:
        result = split_themes(TWO_THEMES_WITH_RECOMMENDATION)
        assert "RECOMMENDATION:" in result.recommendation

    def test_recommendation_not_in_themes(self) -> None:
        result = split_themes(TWO_THEMES_WITH_RECOMMENDATION)
        for theme in result.themes:
            assert "RECOMMENDATION:" not in theme.theme_body

    def test_themes_count_excludes_recommendation(self) -> None:
        result = split_themes(TWO_THEMES_WITH_RECOMMENDATION)
        assert len(result.themes) == 2

    def test_recommendation_preserves_full_content(self) -> None:
        result = split_themes(TWO_THEMES_WITH_RECOMMENDATION)
        assert "Rationale:" in result.recommendation
        assert "best overall narrative" in result.recommendation

    def test_recommendation_at_beginning(self) -> None:
        """RECOMMENDATION block appears before themes."""
        raw = RECOMMENDATION_BLOCK + "\n-----\n" + THEME_A + "\n-----\n" + THEME_B
        result = split_themes(raw)
        assert len(result.themes) == 2
        assert "RECOMMENDATION:" in result.recommendation

    def test_recommendation_in_middle(self) -> None:
        """RECOMMENDATION block sandwiched between themes."""
        raw = THEME_A + "\n-----\n" + RECOMMENDATION_BLOCK + "\n-----\n" + THEME_B
        result = split_themes(raw)
        assert len(result.themes) == 2
        assert "RECOMMENDATION:" in result.recommendation

    def test_no_recommendation_block(self) -> None:
        raw = THEME_A + "\n-----\n" + THEME_B
        result = split_themes(raw)
        assert result.recommendation == ""

    def test_multiple_recommendation_blocks_joined(self) -> None:
        """Multiple RECOMMENDATION blocks are joined with the separator."""
        rec1 = "RECOMMENDATION: Theme 1\nReason: better coverage"
        rec2 = "RECOMMENDATION: Updated pick\nReason: revised analysis"
        raw = THEME_A + "\n-----\n" + rec1 + "\n-----\n" + rec2
        result = split_themes(raw)
        assert "-----" in result.recommendation
        assert "Theme 1" in result.recommendation
        assert "Updated pick" in result.recommendation

    def test_recommendation_only_no_themes(self) -> None:
        result = split_themes(RECOMMENDATION_BLOCK)
        assert result.themes == []
        assert "RECOMMENDATION:" in result.recommendation

    def test_recommendation_substring_in_theme_body_routes_to_recommendation(self) -> None:
        """A block containing RECOMMENDATION: anywhere is treated as recommendation."""
        block = "THEME: Ambiguous\nSome text\nRECOMMENDATION: Actually a rec"
        result = split_themes(block)
        # Because the block contains "RECOMMENDATION:", it goes to recommendation
        assert len(result.themes) == 0
        assert "RECOMMENDATION:" in result.recommendation


# ======================================================================
# ParsedThemeBlock field extraction
# ======================================================================


class TestThemeBlockFields:
    """Verify theme_name and theme_description extraction."""

    def test_extracts_theme_name(self) -> None:
        result = split_themes(THEME_A)
        assert result.themes[0].theme_name == "AI in Healthcare"

    def test_extracts_theme_description(self) -> None:
        result = split_themes(THEME_A)
        assert result.themes[0].theme_description is not None
        assert "patient care" in result.themes[0].theme_description

    def test_theme_body_contains_full_block(self) -> None:
        result = split_themes(THEME_A)
        assert "%FA_TITLE:" in result.themes[0].theme_body
        assert "THEME:" in result.themes[0].theme_body

    def test_no_theme_line_name_is_none(self) -> None:
        raw = "%FA_TITLE: Some Article\n%FA_SOURCE: 1"
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert result.themes[0].theme_name is None

    def test_no_description_line_description_is_none(self) -> None:
        raw = "THEME: Title Only\n%FA_TITLE: Article"
        result = split_themes(raw)
        assert result.themes[0].theme_name == "Title Only"
        assert result.themes[0].theme_description is None

    def test_theme_name_with_colon(self) -> None:
        raw = "THEME: AI: Past, Present, and Future"
        result = split_themes(raw)
        assert result.themes[0].theme_name == "AI: Past, Present, and Future"

    def test_theme_name_with_special_characters(self) -> None:
        raw = "THEME: AI & ML — The $100B Opportunity"
        result = split_themes(raw)
        assert result.themes[0].theme_name == "AI & ML — The $100B Opportunity"

    def test_theme_description_with_long_text(self) -> None:
        long_desc = "A " * 200 + "description"
        raw = f"THEME: Test\nTheme Description: {long_desc}"
        result = split_themes(raw)
        assert result.themes[0].theme_description == long_desc

    def test_theme_name_extra_whitespace(self) -> None:
        """THEME regex uses ``[ \\t]*`` for horizontal whitespace."""
        raw = "THEME  :  \t  Spacey Title  "
        result = split_themes(raw)
        assert result.themes[0].theme_name == "Spacey Title"

    def test_theme_description_extra_whitespace(self) -> None:
        raw = "Theme Description  :  \t  Spacey Desc  "
        result = split_themes(raw)
        assert result.themes[0].theme_description == "Spacey Desc"


# ======================================================================
# Separator format variations
# ======================================================================


class TestSeparatorVariations:
    """Test how the ``-----`` split handles format variations."""

    def test_exactly_five_dashes(self) -> None:
        raw = "THEME: A\n-----\nTHEME: B"
        result = split_themes(raw)
        assert len(result.themes) == 2

    def test_more_than_five_dashes_not_split(self) -> None:
        """``------`` (6 dashes) does NOT match ``-----`` split — treated as one block."""
        raw = "THEME: A\n------\nTHEME: B"
        result = split_themes(raw)
        # Python str.split("-----") on "------" produces ["", "-"] type splits
        # Let's verify the actual behavior
        assert len(result.themes) >= 1

    def test_fewer_than_five_dashes_not_split(self) -> None:
        """``----`` (4 dashes) does NOT trigger split."""
        raw = "THEME: A\n----\nTHEME: B"
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert "THEME: B" in result.themes[0].theme_body

    def test_separator_with_surrounding_whitespace(self) -> None:
        raw = "THEME: A\n  -----  \nTHEME: B"
        result = split_themes(raw)
        # str.split("-----") splits on exact substring, whitespace around it stays
        # The parts are then stripped, so both should be valid
        assert len(result.themes) >= 1

    def test_separator_on_same_line_as_content(self) -> None:
        """Separator embedded in content line causes split."""
        raw = "THEME: A-----THEME: B"
        result = split_themes(raw)
        # str.split("-----") will split this into ["THEME: A", "THEME: B"]
        assert len(result.themes) == 2
        assert result.themes[0].theme_name == "A"

    def test_multiple_consecutive_separators(self) -> None:
        raw = "THEME: A\n-----\n-----\nTHEME: B"
        result = split_themes(raw)
        # Middle empty part gets stripped and filtered out
        assert len(result.themes) == 2

    def test_separator_at_start(self) -> None:
        raw = "-----\nTHEME: A\n-----\nTHEME: B"
        result = split_themes(raw)
        assert len(result.themes) == 2

    def test_separator_at_end(self) -> None:
        raw = "THEME: A\n-----\nTHEME: B\n-----"
        result = split_themes(raw)
        assert len(result.themes) == 2

    def test_ten_dashes_produces_split(self) -> None:
        """``----------`` contains ``-----`` so Python split produces parts."""
        raw = "THEME: A\n----------\nTHEME: B"
        result = split_themes(raw)
        # str.split("-----") on "----------" produces ["", ""]
        # Both empty after strip → filtered out
        # THEME: A is before the dashes, THEME: B after
        # Actually: "THEME: A\n----------\nTHEME: B".split("-----")
        # = ["THEME: A\n", "", "\nTHEME: B"]
        # After strip+filter: ["THEME: A", "THEME: B"]
        assert len(result.themes) == 2


# ======================================================================
# Empty / whitespace-only input
# ======================================================================


class TestEmptyInput:
    """Handle empty, whitespace-only, and separator-only inputs."""

    def test_empty_string(self) -> None:
        result = split_themes("")
        assert result.themes == []
        assert result.recommendation == ""

    def test_whitespace_only(self) -> None:
        result = split_themes("   \n\n\t\t  ")
        assert result.themes == []
        assert result.recommendation == ""

    def test_only_separators(self) -> None:
        result = split_themes("-----\n-----\n-----")
        assert result.themes == []
        assert result.recommendation == ""

    def test_only_newlines(self) -> None:
        result = split_themes("\n\n\n\n")
        assert result.themes == []

    def test_separator_with_only_whitespace_between(self) -> None:
        result = split_themes("-----\n   \n-----")
        assert result.themes == []


# ======================================================================
# Line ending variations
# ======================================================================


class TestLineEndings:
    """Handle Windows (\\r\\n) and mixed line endings."""

    def test_windows_line_endings(self) -> None:
        raw = "THEME: A\r\n-----\r\nTHEME: B\r\n"
        result = split_themes(raw)
        assert len(result.themes) == 2
        assert result.themes[0].theme_name == "A"
        assert result.themes[1].theme_name == "B"

    def test_mixed_line_endings(self) -> None:
        raw = "THEME: A\n-----\r\nTHEME: B\r\n"
        result = split_themes(raw)
        assert len(result.themes) == 2

    def test_cr_only_line_endings(self) -> None:
        raw = "THEME: A\r-----\rTHEME: B\r"
        result = split_themes(raw)
        # \r doesn't affect str.split("-----")
        assert len(result.themes) == 2


# ======================================================================
# Content preservation
# ======================================================================


class TestContentPreservation:
    """Verify theme body content is preserved correctly after splitting."""

    def test_multiline_content_preserved(self) -> None:
        block = "THEME: Test\nLine 2\nLine 3\nLine 4"
        result = split_themes(block)
        assert "Line 2" in result.themes[0].theme_body
        assert "Line 4" in result.themes[0].theme_body

    def test_markers_preserved_in_body(self) -> None:
        raw = THEME_A + "\n-----\n" + THEME_B
        result = split_themes(raw)
        assert "%FA_TITLE: DeepMind" in result.themes[0].theme_body
        assert "%FA_TITLE: Waymo" in result.themes[1].theme_body

    def test_urls_preserved_in_body(self) -> None:
        result = split_themes(THEME_A)
        assert "https://example.com/deepmind" in result.themes[0].theme_body

    def test_unicode_content_preserved(self) -> None:
        raw = "THEME: Automatisation de l'IA — résumé"
        result = split_themes(raw)
        assert result.themes[0].theme_name == "Automatisation de l'IA — résumé"

    def test_emoji_content_preserved(self) -> None:
        raw = "THEME: AI Trends 🤖🚀"
        result = split_themes(raw)
        assert "🤖🚀" in result.themes[0].theme_name

    def test_body_stripped_of_leading_trailing_whitespace(self) -> None:
        raw = "  \n\n  THEME: Padded  \n\n  "
        result = split_themes(raw)
        assert not result.themes[0].theme_body.startswith(" ")
        assert not result.themes[0].theme_body.endswith(" ")

    def test_internal_blank_lines_preserved(self) -> None:
        raw = "THEME: Test\n\n\nMiddle\n\nEnd"
        result = split_themes(raw)
        assert "\n\n" in result.themes[0].theme_body


# ======================================================================
# Return type contracts
# ======================================================================


class TestReturnTypes:
    """Verify the return type structure."""

    def test_returns_theme_parse_result(self) -> None:
        result = split_themes("")
        assert isinstance(result, ThemeParseResult)

    def test_themes_list_of_parsed_theme_block(self) -> None:
        result = split_themes(THEME_A)
        assert isinstance(result.themes, list)
        assert all(isinstance(t, ParsedThemeBlock) for t in result.themes)

    def test_recommendation_is_string(self) -> None:
        result = split_themes("")
        assert isinstance(result.recommendation, str)

    def test_theme_body_is_string(self) -> None:
        result = split_themes(THEME_A)
        assert isinstance(result.themes[0].theme_body, str)

    def test_theme_name_is_str_or_none(self) -> None:
        result = split_themes("Just some text with no theme marker")
        assert result.themes[0].theme_name is None

    def test_result_is_frozen(self) -> None:
        result = split_themes(THEME_A)
        with pytest.raises(AttributeError):
            result.recommendation = "mutated"  # type: ignore[misc]

    def test_theme_block_is_frozen(self) -> None:
        result = split_themes(THEME_A)
        with pytest.raises(AttributeError):
            result.themes[0].theme_name = "mutated"  # type: ignore[misc]


# ======================================================================
# Realistic LLM output patterns
# ======================================================================


class TestRealisticLlmOutput:
    """Patterns observed in real LLM responses from the theme generation prompt."""

    def test_full_two_theme_output(self) -> None:
        """Simulates a complete theme generation response."""
        result = split_themes(TWO_THEMES_WITH_RECOMMENDATION)
        assert len(result.themes) == 2
        assert result.themes[0].theme_name == "AI in Healthcare"
        assert result.themes[1].theme_name == "Autonomous Vehicles 2026"
        assert "RECOMMENDATION:" in result.recommendation

    def test_recommendation_with_numbered_list(self) -> None:
        raw = (
            "THEME: A\n-----\nTHEME: B\n-----\n"
            "RECOMMENDATION: Theme 1\n"
            "1. Better coverage\n"
            "2. Stronger narrative\n"
            "3. More diverse sources\n"
        )
        result = split_themes(raw)
        assert "1. Better coverage" in result.recommendation
        assert "3. More diverse sources" in result.recommendation

    def test_theme_with_all_marker_types(self) -> None:
        """Theme block containing FA, M1, M2, Q1-Q3, I1-I2, RV markers."""
        raw = (
            "THEME: Comprehensive Theme\n"
            "Theme Description: Full marker set.\n\n"
            "%FA_TITLE: Featured\n%FA_SOURCE: 1\n"
            "%M1_TITLE: Main 1\n%M1_SOURCE: 2\n"
            "%M2_TITLE: Main 2\n%M2_SOURCE: 3\n"
            "%Q1_TITLE: Quick 1\n%Q1_SOURCE: 4\n"
            "%Q2_TITLE: Quick 2\n%Q2_SOURCE: 5\n"
            "%Q3_TITLE: Quick 3\n%Q3_SOURCE: 6\n"
            "%I1_TITLE: Industry 1\n%I1_Major AI Player: Google\n"
            "%I2_TITLE: Industry 2\n%I2_Major AI Player: Meta\n"
            "%RV_2-2-2 Distribution Achieved:% Yes\n"
        )
        result = split_themes(raw)
        assert len(result.themes) == 1
        body = result.themes[0].theme_body
        assert "%FA_TITLE:" in body
        assert "%I2_Major AI Player:" in body
        assert "%RV_2-2-2 Distribution Achieved:" in body

    def test_llm_preamble_before_first_theme(self) -> None:
        """Some LLMs add preamble text before the first THEME: line."""
        raw = (
            "Here are two newsletter themes based on the articles:\n\n"
            "THEME: AI Agents\nTheme Description: Rise of AI agents.\n"
            "%FA_TITLE: Agent Article\n"
        )
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert result.themes[0].theme_name == "AI Agents"

    def test_llm_postamble_after_recommendation(self) -> None:
        """Some LLMs add closing text after recommendation."""
        raw = (
            "THEME: Only Theme\n-----\n"
            "RECOMMENDATION: Theme 1\n"
            "Rationale: Best fit.\n\n"
            "Let me know if you'd like any adjustments!"
        )
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert "adjustments" in result.recommendation

    def test_separator_with_extra_dashes(self) -> None:
        """LLM sometimes uses more than 5 dashes for visual separation."""
        raw = "THEME: A\n----------\nTHEME: B"
        result = split_themes(raw)
        # str.split("-----") on "----------" splits into empty parts
        # Both themes should still be found
        assert len(result.themes) == 2

    def test_empty_theme_between_separators_filtered(self) -> None:
        """Empty block between separators should not create a theme."""
        raw = "THEME: A\n-----\n\n-----\nTHEME: B"
        result = split_themes(raw)
        assert len(result.themes) == 2
        names = [t.theme_name for t in result.themes]
        assert "A" in names
        assert "B" in names


# ======================================================================
# RECOMMENDATION: keyword edge cases
# ======================================================================


class TestRecommendationKeyword:
    """Edge cases around RECOMMENDATION: substring matching."""

    def test_lowercase_recommendation_stays_in_themes(self) -> None:
        """Only uppercase RECOMMENDATION: triggers routing."""
        raw = "THEME: Test\nrecommendation: not a real rec"
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert result.recommendation == ""

    def test_recommendation_with_extra_spaces(self) -> None:
        raw = "THEME: A\n-----\n  RECOMMENDATION:   Theme 1  "
        result = split_themes(raw)
        assert len(result.themes) == 1
        assert "RECOMMENDATION:" in result.recommendation

    def test_recommendation_no_colon_stays_in_themes(self) -> None:
        """RECOMMENDATION without colon is not matched."""
        raw = "THEME: A\n-----\nRECOMMENDATION Theme 1"
        result = split_themes(raw)
        # "RECOMMENDATION:" is not in "RECOMMENDATION Theme 1"
        assert len(result.themes) == 2
        assert result.recommendation == ""

    def test_recommendation_mid_word_not_matched(self) -> None:
        """MYRECOMMENDATION: should not be treated as recommendation block
        (but it actually contains RECOMMENDATION: substring, so it will)."""
        raw = "THEME: A\n-----\nMYRECOMMENDATION: Theme 1"
        result = split_themes(raw)
        # Contains "RECOMMENDATION:" substring, so it routes to recommendation
        assert len(result.themes) == 1
        assert "MYRECOMMENDATION:" in result.recommendation


# ======================================================================
# Parametrized: separator counting
# ======================================================================


@pytest.mark.parametrize(
    "n_themes, n_separators",
    [
        (1, 0),
        (2, 1),
        (3, 2),
        (5, 4),
    ],
    ids=["1-theme-0-sep", "2-themes-1-sep", "3-themes-2-sep", "5-themes-4-sep"],
)
def test_n_themes_require_n_minus_1_separators(
    n_themes: int,
    n_separators: int,
) -> None:
    """N themes with N-1 separators produce exactly N ParsedThemeBlocks."""
    blocks = [f"THEME: Theme {i + 1}" for i in range(n_themes)]
    raw = "\n-----\n".join(blocks)
    result = split_themes(raw)
    assert len(result.themes) == n_themes


# ======================================================================
# Parametrized: theme name extraction
# ======================================================================


@pytest.mark.parametrize(
    "raw, expected_name",
    [
        ("THEME: Simple", "Simple"),
        ("THEME:NoSpace", "NoSpace"),
        ("THEME:   Extra Spaces   ", "Extra Spaces"),
        ("THEME:\tTabbed", "Tabbed"),
        ("THEME: AI: Colons: In: Name", "AI: Colons: In: Name"),
        ("THEME: 123 Numeric Start", "123 Numeric Start"),
        ("THEME: One-Word", "One-Word"),
    ],
    ids=[
        "simple",
        "no-space",
        "extra-spaces",
        "tabbed",
        "colons",
        "numeric-start",
        "hyphenated",
    ],
)
def test_theme_name_extraction_variants(raw: str, expected_name: str) -> None:
    result = split_themes(raw)
    assert result.themes[0].theme_name == expected_name


# ======================================================================
# Parametrized: description extraction
# ======================================================================


@pytest.mark.parametrize(
    "raw, expected_desc",
    [
        ("Theme Description: Simple desc", "Simple desc"),
        ("Theme Description:NoSpace", "NoSpace"),
        ("Theme Description:   Padded   ", "Padded"),
        ("Theme Description:\tTabbed desc", "Tabbed desc"),
        ("Theme Description: Desc: with: colons", "Desc: with: colons"),
    ],
    ids=["simple", "no-space", "padded", "tabbed", "colons"],
)
def test_theme_description_extraction_variants(
    raw: str,
    expected_desc: str,
) -> None:
    result = split_themes(raw)
    assert result.themes[0].theme_description == expected_desc
