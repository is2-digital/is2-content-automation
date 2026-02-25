"""Tests for Main Article 1 and 2 character counting validation.

Covers:
- Subheading stripping (## lines)
- Source link removal (lines matching [text →](url))
- Paragraph splitting on blank lines
- Callout paragraph detection (bold label pattern **Label:** or *Label:*) and validation (180-250 chars)
- Content paragraph detection (first non-callout paragraph) and validation (max 750 chars)
- Both MAIN ARTICLE 1 and MAIN ARTICLE 2 sections
- Delta calculation for out-of-range values
- Edge cases: missing section, missing paragraphs, no callout, no content
"""

from __future__ import annotations

import pytest

from ica.validators.character_count import (
    CharacterCountError,
    _find_callout,
    _strip_source_links,
    validate_character_counts,
    validate_main_articles,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(length: int, char: str = "x") -> str:
    """Create a string of exactly *length* characters."""
    return char * length


def _make_main_article(
    *,
    index: int = 1,
    callout_len: int = 215,
    content_len: int = 500,
    subheading: str = "## [Article Title Here](https://example.com)",
    source_link: str = "[Source →](https://example.com/source)",
    callout_prefix: str = "**Strategic Take:** ",
) -> str:
    """Build a full markdown document with a MAIN ARTICLE section.

    The callout_prefix is counted toward the total callout paragraph length,
    so the filler text is ``callout_len - len(callout_prefix)`` characters.
    """
    prefix_len = len(callout_prefix)
    filler = max(0, callout_len - prefix_len)
    parts = [
        "# INTRODUCTION\nSome intro.\n",
        "# FEATURED ARTICLE\nFeatured content.\n",
        f"# MAIN ARTICLE {index}",
    ]
    if subheading:
        parts.append(subheading)
    parts.append("")  # blank line after subheading
    parts.append(_text(content_len))
    parts.append("")
    parts.append(f"{callout_prefix}{_text(filler)}")
    parts.append("")
    if source_link:
        parts.append(source_link)
    parts.append("")
    # Add the next section to terminate extraction
    next_section = index + 1 if index == 1 else 3
    if index == 1:
        parts.append(f"# MAIN ARTICLE 2\nNext section.\n")
    else:
        parts.append("# INDUSTRY DEVELOPMENTS\nNext section.\n")
    return "\n".join(parts)


def _make_both_main_articles(
    *,
    callout1_len: int = 215,
    content1_len: int = 500,
    callout2_len: int = 215,
    content2_len: int = 500,
    callout_prefix: str = "**Strategic Take:** ",
) -> str:
    """Build a markdown document with both MAIN ARTICLE 1 and 2."""
    prefix_len = len(callout_prefix)
    filler1 = max(0, callout1_len - prefix_len)
    filler2 = max(0, callout2_len - prefix_len)
    return "\n".join(
        [
            "# INTRODUCTION\nSome intro.\n",
            "# FEATURED ARTICLE\nFeatured content.\n",
            "# MAIN ARTICLE 1",
            "## [First Article](https://example.com/1)",
            "",
            _text(content1_len),
            "",
            f"{callout_prefix}{_text(filler1)}",
            "",
            "[Source →](https://example.com/1)",
            "",
            "# MAIN ARTICLE 2",
            "## [Second Article](https://example.com/2)",
            "",
            _text(content2_len),
            "",
            f"{callout_prefix}{_text(filler2)}",
            "",
            "[Source →](https://example.com/2)",
            "",
            "# INDUSTRY DEVELOPMENTS\nNext section.\n",
        ]
    )


# ===========================================================================
# _strip_source_links
# ===========================================================================


class TestStripSourceLinks:
    """Test the ``_strip_source_links`` helper."""

    def test_removes_source_link_line(self) -> None:
        text = "Paragraph text.\n\n[Read more →](https://example.com)\n\nMore text."
        result = _strip_source_links(text)
        assert "[Read more →]" not in result
        assert "Paragraph text." in result
        assert "More text." in result

    def test_preserves_text_without_source_link(self) -> None:
        text = "Just a paragraph."
        assert _strip_source_links(text) == "Just a paragraph."

    def test_handles_empty_string(self) -> None:
        assert _strip_source_links("") == ""

    def test_removes_multiple_source_links(self) -> None:
        text = "[First →](https://a.com)\nContent.\n[Second →](https://b.com)"
        result = _strip_source_links(text)
        assert "→" not in result
        assert "Content." in result

    def test_preserves_inline_links_without_arrow(self) -> None:
        text = "[Normal link](https://example.com)\nContent."
        result = _strip_source_links(text)
        assert "[Normal link]" in result

    def test_preserves_arrow_not_in_link(self) -> None:
        text = "Some text with → arrow but not a link."
        result = _strip_source_links(text)
        assert "→" in result


# ===========================================================================
# _find_callout
# ===========================================================================


class TestFindCallout:
    """Test the ``_find_callout`` helper."""

    def test_finds_double_bold_callout(self) -> None:
        paras = ["Content paragraph.", "**Strategic Take:** Some insight here."]
        assert _find_callout(paras) == "**Strategic Take:** Some insight here."

    def test_finds_single_italic_callout(self) -> None:
        paras = ["Content paragraph.", "*Key Point:* Some insight here."]
        assert _find_callout(paras) == "*Key Point:* Some insight here."

    def test_returns_first_matching_callout(self) -> None:
        paras = ["**First:** One.", "**Second:** Two."]
        assert _find_callout(paras) == "**First:** One."

    def test_returns_empty_when_no_callout(self) -> None:
        paras = ["Normal paragraph.", "Another normal one."]
        assert _find_callout(paras) == ""

    def test_returns_empty_for_empty_list(self) -> None:
        assert _find_callout([]) == ""

    def test_no_match_for_bold_without_colon(self) -> None:
        paras = ["**Bold text** without a colon after it."]
        assert _find_callout(paras) == ""

    def test_matches_callout_with_long_label(self) -> None:
        paras = ["**Strategic Take-away for Leaders:** Details here."]
        assert _find_callout(paras) == "**Strategic Take-away for Leaders:** Details here."


# ===========================================================================
# validate_main_articles – valid content (single article)
# ===========================================================================


class TestValidateMainArticlesValid:
    """Cases where callout and content are within range → no errors for that article."""

    def test_article_1_all_within_range(self) -> None:
        raw = _make_main_article(index=1, callout_len=215, content_len=500)
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_article_2_all_within_range(self) -> None:
        raw = _make_main_article(index=2, callout_len=215, content_len=500)
        errors = validate_main_articles(raw)
        a2_errors = [e for e in errors if e.section == "Main Article 2"]
        assert a2_errors == []

    def test_callout_at_lower_bound_180(self) -> None:
        raw = _make_main_article(callout_len=180, content_len=500)
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_callout_at_upper_bound_250(self) -> None:
        raw = _make_main_article(callout_len=250, content_len=500)
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_content_at_exactly_750(self) -> None:
        raw = _make_main_article(callout_len=215, content_len=750)
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_content_at_1_char(self) -> None:
        """Content has no minimum, so even 1 char is valid."""
        raw = _make_main_article(callout_len=215, content_len=1)
        errors = validate_main_articles(raw)
        content_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        ]
        assert content_errors == []


# ===========================================================================
# validate_main_articles – both articles valid
# ===========================================================================


class TestValidateMainArticlesBothValid:
    """Both MAIN ARTICLE 1 and 2 within range → no errors."""

    def test_both_within_range(self) -> None:
        raw = _make_both_main_articles(
            callout1_len=215,
            content1_len=500,
            callout2_len=215,
            content2_len=500,
        )
        errors = validate_main_articles(raw)
        assert errors == []

    def test_both_at_bounds(self) -> None:
        raw = _make_both_main_articles(
            callout1_len=180,
            content1_len=750,
            callout2_len=250,
            content2_len=750,
        )
        errors = validate_main_articles(raw)
        assert errors == []


# ===========================================================================
# validate_main_articles – callout errors
# ===========================================================================


class TestValidateMainArticlesCallout:
    """Callout paragraph character count errors (180-250 range)."""

    def test_callout_too_short(self) -> None:
        raw = _make_main_article(callout_len=100)
        errors = validate_main_articles(raw)
        callout_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        ]
        assert len(callout_errors) == 1
        assert callout_errors[0].current == 100
        assert callout_errors[0].target_min == 180
        assert callout_errors[0].target_max == 250
        assert callout_errors[0].delta == -80  # 100 - 180

    def test_callout_too_long(self) -> None:
        raw = _make_main_article(callout_len=300)
        errors = validate_main_articles(raw)
        callout_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        ]
        assert len(callout_errors) == 1
        assert callout_errors[0].current == 300
        assert callout_errors[0].delta == 50  # 300 - 250

    def test_callout_at_179_just_under(self) -> None:
        raw = _make_main_article(callout_len=179)
        errors = validate_main_articles(raw)
        callout_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        ]
        assert len(callout_errors) == 1
        assert callout_errors[0].delta == -1

    def test_callout_at_251_just_over(self) -> None:
        raw = _make_main_article(callout_len=251)
        errors = validate_main_articles(raw)
        callout_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        ]
        assert len(callout_errors) == 1
        assert callout_errors[0].delta == 1

    def test_article_2_callout_too_short(self) -> None:
        raw = _make_main_article(index=2, callout_len=150)
        errors = validate_main_articles(raw)
        callout_errors = [
            e for e in errors if e.section == "Main Article 2" and e.field == "Callout Paragraph"
        ]
        assert len(callout_errors) == 1
        assert callout_errors[0].current == 150
        assert callout_errors[0].delta == -30


# ===========================================================================
# validate_main_articles – content errors
# ===========================================================================


class TestValidateMainArticlesContent:
    """Content paragraph errors (max 750 chars)."""

    def test_content_too_long(self) -> None:
        raw = _make_main_article(content_len=800)
        errors = validate_main_articles(raw)
        content_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        ]
        assert len(content_errors) == 1
        assert content_errors[0].current == 800
        assert content_errors[0].delta == 50  # 800 - 750

    def test_content_at_751_just_over(self) -> None:
        raw = _make_main_article(content_len=751)
        errors = validate_main_articles(raw)
        content_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        ]
        assert len(content_errors) == 1
        assert content_errors[0].delta == 1

    def test_content_way_over(self) -> None:
        raw = _make_main_article(content_len=1200)
        errors = validate_main_articles(raw)
        content_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        ]
        assert len(content_errors) == 1
        assert content_errors[0].delta == 450  # 1200 - 750

    def test_article_2_content_too_long(self) -> None:
        raw = _make_main_article(index=2, content_len=900)
        errors = validate_main_articles(raw)
        content_errors = [
            e for e in errors if e.section == "Main Article 2" and e.field == "Content Paragraph"
        ]
        assert len(content_errors) == 1
        assert content_errors[0].current == 900
        assert content_errors[0].delta == 150


# ===========================================================================
# validate_main_articles – multiple errors
# ===========================================================================


class TestValidateMainArticlesMultipleErrors:
    """Cases where multiple fields/articles are out of range simultaneously."""

    def test_callout_and_content_both_out(self) -> None:
        raw = _make_main_article(callout_len=100, content_len=900)
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert len(a1_errors) == 2
        fields = {e.field for e in a1_errors}
        assert fields == {"Callout Paragraph", "Content Paragraph"}

    def test_both_articles_callout_too_short(self) -> None:
        raw = _make_both_main_articles(callout1_len=100, callout2_len=120)
        errors = validate_main_articles(raw)
        callout_errors = [e for e in errors if e.field == "Callout Paragraph"]
        assert len(callout_errors) == 2
        sections = {e.section for e in callout_errors}
        assert sections == {"Main Article 1", "Main Article 2"}

    def test_article_1_ok_article_2_out(self) -> None:
        raw = _make_both_main_articles(
            callout1_len=215,
            content1_len=500,
            callout2_len=100,
            content2_len=900,
        )
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        a2_errors = [e for e in errors if e.section == "Main Article 2"]
        assert len(a1_errors) == 0
        assert len(a2_errors) == 2

    def test_all_four_fields_out(self) -> None:
        raw = _make_both_main_articles(
            callout1_len=100,
            content1_len=900,
            callout2_len=300,
            content2_len=800,
        )
        errors = validate_main_articles(raw)
        assert len(errors) == 4


# ===========================================================================
# validate_main_articles – error metadata
# ===========================================================================


class TestValidateMainArticlesErrorMetadata:
    """Verify section name and error format string output."""

    def test_section_names(self) -> None:
        raw = _make_both_main_articles(callout1_len=100, callout2_len=100)
        errors = validate_main_articles(raw)
        callout_errors = [e for e in errors if e.field == "Callout Paragraph"]
        sections = [e.section for e in callout_errors]
        assert "Main Article 1" in sections
        assert "Main Article 2" in sections

    def test_format_string_callout_too_short(self) -> None:
        raw = _make_main_article(callout_len=160)
        errors = validate_main_articles(raw)
        callout = next(e for e in errors if e.field == "Callout Paragraph")
        formatted = callout.format()
        assert "Main Article 1" in formatted
        assert "Callout Paragraph" in formatted
        assert "current=160" in formatted
        assert "target=180–250" in formatted
        assert "delta=-20" in formatted

    def test_format_string_content_too_long(self) -> None:
        raw = _make_main_article(content_len=780)
        errors = validate_main_articles(raw)
        content = next(e for e in errors if e.field == "Content Paragraph")
        formatted = content.format()
        assert "Main Article 1" in formatted
        assert "Content Paragraph" in formatted
        assert "current=780" in formatted
        assert "delta=+30" in formatted


# ===========================================================================
# validate_main_articles – edge cases
# ===========================================================================


class TestValidateMainArticlesEdgeCases:
    """Edge cases and structural variations."""

    def test_missing_section_returns_callout_error(self) -> None:
        """When MAIN ARTICLE 1 section is absent, callout is empty → error."""
        raw = (
            "# QUICK HIGHLIGHTS\nSome bullets.\n# MAIN ARTICLE 2\n## [Title](https://x.com)\n\n"
            + _text(500)
            + "\n\n**Take:** "
            + _text(195)
            + "\n\n# INDUSTRY DEVELOPMENTS\nText.\n"
        )
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        a1_callout = [e for e in a1_errors if e.field == "Callout Paragraph"]
        assert len(a1_callout) == 1
        assert a1_callout[0].current == 0

    def test_no_source_link(self) -> None:
        """Section without a source link line still works."""
        raw = _make_main_article(source_link="")
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_no_subheading(self) -> None:
        """Section without a ## subheading line still works."""
        raw = _make_main_article(subheading="")
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_no_callout_found(self) -> None:
        """When no paragraph matches bold-label pattern, callout is empty → error."""
        raw = "\n".join(
            [
                "# MAIN ARTICLE 1",
                "## [Title](https://example.com)",
                "",
                _text(500),
                "",
                "No bold pattern here: " + _text(200),
                "",
                "[Source →](https://example.com)",
                "",
                "# MAIN ARTICLE 2\nText.\n",
            ]
        )
        errors = validate_main_articles(raw)
        callout_errors = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        ]
        assert len(callout_errors) == 1
        assert callout_errors[0].current == 0

    def test_empty_raw_string(self) -> None:
        """Empty markdown → sections not found → callout errors with current=0."""
        errors = validate_main_articles("")
        callout_errors = [e for e in errors if e.field == "Callout Paragraph"]
        assert len(callout_errors) == 2  # One for each article
        assert all(e.current == 0 for e in callout_errors)

    def test_italic_heading_variant(self) -> None:
        """Heading with ``# *MAIN ARTICLE 1*`` (italic asterisks) is found."""
        prefix = "**Insight:** "
        prefix_len = len(prefix)
        raw = "\n".join(
            [
                "# *MAIN ARTICLE 1*",
                "## [Title](https://example.com)",
                "",
                _text(500),
                "",
                f"{prefix}{_text(215 - prefix_len)}",
                "",
                "# *MAIN ARTICLE 2*\nText.\n",
            ]
        )
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_only_callout_no_content(self) -> None:
        """Section with only a callout paragraph → content is empty (0 chars, valid)."""
        prefix = "**Take:** "
        prefix_len = len(prefix)
        raw = "\n".join(
            [
                "# MAIN ARTICLE 1",
                "",
                f"{prefix}{_text(215 - prefix_len)}",
                "",
                "# MAIN ARTICLE 2\nText.\n",
            ]
        )
        errors = validate_main_articles(raw)
        a1_content = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        ]
        # Content is 0 chars, max 750, no error (no minimum)
        assert a1_content == []

    def test_only_content_no_callout(self) -> None:
        """Section with content but no callout → callout error, no content error."""
        raw = "\n".join(
            [
                "# MAIN ARTICLE 1",
                "",
                _text(500),
                "",
                "# MAIN ARTICLE 2\nText.\n",
            ]
        )
        errors = validate_main_articles(raw)
        a1_callout = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        ]
        a1_content = [
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        ]
        assert len(a1_callout) == 1
        assert a1_callout[0].current == 0
        assert a1_content == []


# ===========================================================================
# validate_main_articles – source link handling
# ===========================================================================


class TestValidateMainArticlesSourceLinks:
    """Source link removal should not affect paragraph counting."""

    def test_source_link_excluded_from_paragraphs(self) -> None:
        """Source link lines should be stripped before paragraph splitting."""
        prefix = "**Take:** "
        prefix_len = len(prefix)
        raw = "\n".join(
            [
                "# MAIN ARTICLE 1",
                "## [Title](https://example.com)",
                "",
                _text(500),
                "",
                f"{prefix}{_text(215 - prefix_len)}",
                "",
                "[Read the full story →](https://example.com/full)",
                "",
                "# MAIN ARTICLE 2\nNext.\n",
            ]
        )
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []

    def test_multiple_source_links_stripped(self) -> None:
        """Multiple source links are all removed."""
        prefix = "**Take:** "
        prefix_len = len(prefix)
        raw = "\n".join(
            [
                "# MAIN ARTICLE 1",
                "",
                _text(500),
                "",
                f"{prefix}{_text(215 - prefix_len)}",
                "",
                "[First →](https://a.com)",
                "[Second →](https://b.com)",
                "",
                "# MAIN ARTICLE 2\nNext.\n",
            ]
        )
        errors = validate_main_articles(raw)
        a1_errors = [e for e in errors if e.section == "Main Article 1"]
        assert a1_errors == []


# ===========================================================================
# validate_main_articles – callout pattern variations
# ===========================================================================


class TestValidateMainArticlesCalloutPatterns:
    """Test various callout pattern formats."""

    def test_double_bold_with_colon(self) -> None:
        """Standard ``**Label:** text`` pattern."""
        paras = [_text(500), f"**Strategic Take:** {_text(195)}"]
        callout = _find_callout(paras)
        assert callout.startswith("**Strategic Take:**")

    def test_single_italic_with_colon(self) -> None:
        """``*Label:* text`` pattern."""
        paras = [_text(500), f"*Key Point:* {_text(195)}"]
        callout = _find_callout(paras)
        assert callout.startswith("*Key Point:*")

    def test_bold_with_hyphenated_label(self) -> None:
        """``**Take-away:** text`` pattern."""
        paras = [_text(500), f"**Take-away:** {_text(195)}"]
        callout = _find_callout(paras)
        assert callout.startswith("**Take-away:**")

    def test_no_match_bold_without_closing(self) -> None:
        """Bold text that doesn't close with :** should NOT match."""
        paras = ["**Bold text without colon delimiter"]
        assert _find_callout(paras) == ""


# ===========================================================================
# validate_character_counts integration
# ===========================================================================


class TestValidateCharacterCountsIncludesMainArticles:
    """Verify that validate_character_counts includes Main Article checks."""

    def test_main_article_errors_in_combined(self) -> None:
        raw = _make_both_main_articles(callout1_len=100, callout2_len=100)
        errors = validate_character_counts(raw)
        main_errors = [e for e in errors if e.section.startswith("Main Article")]
        assert len(main_errors) >= 2

    def test_valid_main_articles_no_errors_in_combined(self) -> None:
        raw = _make_both_main_articles(
            callout1_len=215,
            content1_len=500,
            callout2_len=215,
            content2_len=500,
        )
        errors = validate_character_counts(raw)
        main_errors = [e for e in errors if e.section.startswith("Main Article")]
        assert main_errors == []


# ===========================================================================
# Parametrized delta tests
# ===========================================================================


class TestMainArticleDeltaAccuracy:
    """Parametrized tests verifying exact delta values."""

    @pytest.mark.parametrize(
        "callout_len,expected_delta",
        [
            (50, -130),  # 50 - 180
            (179, -1),  # 179 - 180
            (251, 1),  # 251 - 250
            (350, 100),  # 350 - 250
        ],
    )
    def test_callout_delta(self, callout_len: int, expected_delta: int) -> None:
        raw = _make_main_article(callout_len=callout_len)
        errors = validate_main_articles(raw)
        callout = next(
            e for e in errors if e.section == "Main Article 1" and e.field == "Callout Paragraph"
        )
        assert callout.delta == expected_delta

    @pytest.mark.parametrize(
        "content_len,expected_delta",
        [
            (751, 1),  # 751 - 750
            (800, 50),  # 800 - 750
            (1000, 250),  # 1000 - 750
            (1500, 750),  # 1500 - 750
        ],
    )
    def test_content_delta(self, content_len: int, expected_delta: int) -> None:
        raw = _make_main_article(content_len=content_len)
        errors = validate_main_articles(raw)
        content = next(
            e for e in errors if e.section == "Main Article 1" and e.field == "Content Paragraph"
        )
        assert content.delta == expected_delta
