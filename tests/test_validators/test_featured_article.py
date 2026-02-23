"""Tests for Featured Article character counting validation.

Covers:
- Subheading stripping (## lines)
- CTA line detection and removal (lines containing →)
- Paragraph splitting on blank lines
- P1 (300-400 chars) and P2 (300-400 chars) validation
- Key Insight paragraph detection (starts with **) and validation (300-370 chars)
- Delta calculation for out-of-range values
- Edge cases: missing section, missing paragraphs, no CTA, no insight
"""

from __future__ import annotations

import pytest

from ica.validators.character_count import (
    CharacterCountError,
    _extract_cta,
    _split_paragraphs,
    _strip_subheading,
    validate_character_counts,
    validate_featured_article,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(length: int, char: str = "x") -> str:
    """Create a string of exactly *length* characters."""
    return char * length


def _make_featured(
    *,
    p1_len: int = 350,
    p2_len: int = 350,
    insight_len: int = 335,
    subheading: str = "## [AI Changes Everything](https://example.com)",
    cta: str = "Read more →",
    insight_prefix: str = "**Key Insight:** ",
) -> str:
    """Build a full markdown document with a FEATURED ARTICLE section.

    The insight_prefix is counted toward the total insight paragraph length,
    so the filler text is ``insight_len - len(insight_prefix)`` characters.
    """
    prefix_len = len(insight_prefix)
    filler = max(0, insight_len - prefix_len)
    parts = [
        "# INTRODUCTION\nSome intro.\n",
        "# FEATURED ARTICLE",
    ]
    if subheading:
        parts.append(subheading)
    parts.append("")  # blank line after subheading
    parts.append(_text(p1_len))
    parts.append("")
    parts.append(_text(p2_len))
    parts.append("")
    parts.append(f"{insight_prefix}{_text(filler)}")
    parts.append("")
    if cta:
        parts.append(cta)
    parts.append("")
    parts.append("# MAIN ARTICLE 1\nSome main text.\n")
    return "\n".join(parts)


# ===========================================================================
# _strip_subheading
# ===========================================================================


class TestStripSubheading:
    """Test the ``_strip_subheading`` helper."""

    def test_removes_h2_line(self) -> None:
        text = "## [Title](https://example.com)\nParagraph text."
        assert _strip_subheading(text) == "Paragraph text."

    def test_preserves_text_without_subheading(self) -> None:
        text = "Just a paragraph."
        assert _strip_subheading(text) == "Just a paragraph."

    def test_removes_only_first_h2(self) -> None:
        text = "## First heading\n\n## Second heading\nContent."
        result = _strip_subheading(text)
        assert "## Second heading" in result
        assert "## First heading" not in result

    def test_handles_empty_string(self) -> None:
        assert _strip_subheading("") == ""

    def test_h2_with_various_spacing(self) -> None:
        text = "##   Lots of spaces  \nContent follows."
        assert _strip_subheading(text) == "Content follows."


# ===========================================================================
# _extract_cta
# ===========================================================================


class TestExtractCta:
    """Test the ``_extract_cta`` helper."""

    def test_finds_arrow_line(self) -> None:
        text = "Paragraph 1.\n\nRead more →\n\nParagraph 2."
        cta, remaining = _extract_cta(text)
        assert cta == "Read more →"
        assert "Read more →" not in remaining

    def test_no_arrow_returns_original(self) -> None:
        text = "Paragraph 1.\n\nParagraph 2."
        cta, remaining = _extract_cta(text)
        assert cta == ""
        assert remaining == text

    def test_link_with_arrow(self) -> None:
        text = "Content.\n\n[Dive in →](https://example.com)\n\nMore."
        cta, remaining = _extract_cta(text)
        assert "→" in cta
        assert "→" not in remaining

    def test_empty_string(self) -> None:
        cta, remaining = _extract_cta("")
        assert cta == ""
        assert remaining == ""

    def test_arrow_in_middle_of_line(self) -> None:
        text = "Some text → and more text"
        cta, remaining = _extract_cta(text)
        assert cta == "Some text → and more text"


# ===========================================================================
# _split_paragraphs
# ===========================================================================


class TestSplitParagraphs:
    """Test the ``_split_paragraphs`` helper."""

    def test_splits_on_blank_lines(self) -> None:
        text = "Para one.\n\nPara two.\n\nPara three."
        assert _split_paragraphs(text) == ["Para one.", "Para two.", "Para three."]

    def test_filters_empty_paragraphs(self) -> None:
        text = "Para one.\n\n\n\nPara two."
        assert _split_paragraphs(text) == ["Para one.", "Para two."]

    def test_trims_whitespace(self) -> None:
        text = "  Para one.  \n\n  Para two.  "
        assert _split_paragraphs(text) == ["Para one.", "Para two."]

    def test_empty_string(self) -> None:
        assert _split_paragraphs("") == []

    def test_single_paragraph(self) -> None:
        assert _split_paragraphs("Just one.") == ["Just one."]

    def test_blank_lines_with_whitespace(self) -> None:
        text = "A.\n   \nB."
        assert _split_paragraphs(text) == ["A.", "B."]


# ===========================================================================
# validate_featured_article – valid content
# ===========================================================================


class TestValidateFeaturedArticleValid:
    """Cases where all paragraphs are within range → no errors."""

    def test_all_within_range(self) -> None:
        raw = _make_featured(p1_len=350, p2_len=350, insight_len=335)
        errors = validate_featured_article(raw)
        assert errors == []

    def test_at_lower_bounds(self) -> None:
        raw = _make_featured(p1_len=300, p2_len=300, insight_len=300)
        errors = validate_featured_article(raw)
        assert errors == []

    def test_at_upper_bounds(self) -> None:
        raw = _make_featured(p1_len=400, p2_len=400, insight_len=370)
        errors = validate_featured_article(raw)
        assert errors == []

    def test_mixed_bounds(self) -> None:
        raw = _make_featured(p1_len=300, p2_len=400, insight_len=370)
        errors = validate_featured_article(raw)
        assert errors == []


# ===========================================================================
# validate_featured_article – P1 errors
# ===========================================================================


class TestValidateFeaturedArticleP1:
    """Paragraph 1 character count errors (300-400 range)."""

    def test_p1_too_short(self) -> None:
        raw = _make_featured(p1_len=250)
        errors = validate_featured_article(raw)
        p1_errors = [e for e in errors if e.field == "Paragraph 1"]
        assert len(p1_errors) == 1
        assert p1_errors[0].current == 250
        assert p1_errors[0].target_min == 300
        assert p1_errors[0].target_max == 400
        assert p1_errors[0].delta == -50  # 250 - 300

    def test_p1_too_long(self) -> None:
        raw = _make_featured(p1_len=450)
        errors = validate_featured_article(raw)
        p1_errors = [e for e in errors if e.field == "Paragraph 1"]
        assert len(p1_errors) == 1
        assert p1_errors[0].current == 450
        assert p1_errors[0].delta == 50  # 450 - 400

    def test_p1_at_299_just_under(self) -> None:
        raw = _make_featured(p1_len=299)
        errors = validate_featured_article(raw)
        p1_errors = [e for e in errors if e.field == "Paragraph 1"]
        assert len(p1_errors) == 1
        assert p1_errors[0].delta == -1

    def test_p1_at_401_just_over(self) -> None:
        raw = _make_featured(p1_len=401)
        errors = validate_featured_article(raw)
        p1_errors = [e for e in errors if e.field == "Paragraph 1"]
        assert len(p1_errors) == 1
        assert p1_errors[0].delta == 1


# ===========================================================================
# validate_featured_article – P2 errors
# ===========================================================================


class TestValidateFeaturedArticleP2:
    """Paragraph 2 character count errors (300-400 range)."""

    def test_p2_too_short(self) -> None:
        raw = _make_featured(p2_len=200)
        errors = validate_featured_article(raw)
        p2_errors = [e for e in errors if e.field == "Paragraph 2"]
        assert len(p2_errors) == 1
        assert p2_errors[0].current == 200
        assert p2_errors[0].delta == -100

    def test_p2_too_long(self) -> None:
        raw = _make_featured(p2_len=500)
        errors = validate_featured_article(raw)
        p2_errors = [e for e in errors if e.field == "Paragraph 2"]
        assert len(p2_errors) == 1
        assert p2_errors[0].current == 500
        assert p2_errors[0].delta == 100

    def test_p2_at_boundary(self) -> None:
        """P2 at exactly 300 → valid."""
        raw = _make_featured(p2_len=300)
        errors = validate_featured_article(raw)
        p2_errors = [e for e in errors if e.field == "Paragraph 2"]
        assert len(p2_errors) == 0


# ===========================================================================
# validate_featured_article – Key Insight errors
# ===========================================================================


class TestValidateFeaturedArticleKeyInsight:
    """Key Insight paragraph errors (300-370 range)."""

    def test_insight_too_short(self) -> None:
        raw = _make_featured(insight_len=250)
        errors = validate_featured_article(raw)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 1
        assert insight_errors[0].current == 250
        assert insight_errors[0].delta == -50

    def test_insight_too_long(self) -> None:
        raw = _make_featured(insight_len=400)
        errors = validate_featured_article(raw)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 1
        assert insight_errors[0].current == 400
        assert insight_errors[0].delta == 30  # 400 - 370

    def test_insight_at_lower_bound(self) -> None:
        raw = _make_featured(insight_len=300)
        errors = validate_featured_article(raw)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 0

    def test_insight_at_upper_bound(self) -> None:
        raw = _make_featured(insight_len=370)
        errors = validate_featured_article(raw)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 0

    def test_insight_at_299(self) -> None:
        raw = _make_featured(insight_len=299)
        errors = validate_featured_article(raw)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 1
        assert insight_errors[0].delta == -1

    def test_insight_at_371(self) -> None:
        raw = _make_featured(insight_len=371)
        errors = validate_featured_article(raw)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 1
        assert insight_errors[0].delta == 1


# ===========================================================================
# validate_featured_article – multiple errors
# ===========================================================================


class TestValidateFeaturedArticleMultipleErrors:
    """Cases where multiple fields are out of range simultaneously."""

    def test_all_three_too_short(self) -> None:
        raw = _make_featured(p1_len=100, p2_len=100, insight_len=100)
        errors = validate_featured_article(raw)
        assert len(errors) == 3
        fields = {e.field for e in errors}
        assert fields == {"Paragraph 1", "Paragraph 2", "Key Insight paragraph"}

    def test_all_three_too_long(self) -> None:
        raw = _make_featured(p1_len=500, p2_len=500, insight_len=500)
        errors = validate_featured_article(raw)
        assert len(errors) == 3

    def test_p1_and_insight_out_but_p2_ok(self) -> None:
        raw = _make_featured(p1_len=200, p2_len=350, insight_len=400)
        errors = validate_featured_article(raw)
        assert len(errors) == 2
        fields = {e.field for e in errors}
        assert "Paragraph 1" in fields
        assert "Key Insight paragraph" in fields
        assert "Paragraph 2" not in fields


# ===========================================================================
# validate_featured_article – error metadata
# ===========================================================================


class TestValidateFeaturedArticleErrorMetadata:
    """Verify section name and error format string output."""

    def test_section_is_featured_article(self) -> None:
        raw = _make_featured(p1_len=100)
        errors = validate_featured_article(raw)
        assert all(e.section == "Featured Article" for e in errors)

    def test_format_string_too_short(self) -> None:
        raw = _make_featured(p1_len=280)
        errors = validate_featured_article(raw)
        p1 = next(e for e in errors if e.field == "Paragraph 1")
        formatted = p1.format()
        assert "Featured Article" in formatted
        assert "Paragraph 1" in formatted
        assert "current=280" in formatted
        assert "target=300–400" in formatted
        assert "delta=-20" in formatted

    def test_format_string_too_long(self) -> None:
        raw = _make_featured(p1_len=420)
        errors = validate_featured_article(raw)
        p1 = next(e for e in errors if e.field == "Paragraph 1")
        formatted = p1.format()
        assert "delta=+20" in formatted


# ===========================================================================
# validate_featured_article – edge cases
# ===========================================================================


class TestValidateFeaturedArticleEdgeCases:
    """Edge cases and structural variations."""

    def test_missing_section_returns_three_errors(self) -> None:
        """When FEATURED ARTICLE section is absent, all three fields are empty → 3 errors."""
        raw = "# QUICK HIGHLIGHTS\nSome bullets.\n# MAIN ARTICLE 1\nText.\n"
        errors = validate_featured_article(raw)
        assert len(errors) == 3
        for e in errors:
            assert e.current == 0

    def test_no_cta_line(self) -> None:
        """Section without a CTA (no →) still works."""
        raw = _make_featured(cta="")
        errors = validate_featured_article(raw)
        assert errors == []

    def test_no_subheading(self) -> None:
        """Section without a ## subheading line still works."""
        raw = _make_featured(subheading="")
        errors = validate_featured_article(raw)
        assert errors == []

    def test_no_insight_prefix(self) -> None:
        """When no paragraph starts with **, Key Insight is empty → error."""
        featured = (
            "# FEATURED ARTICLE\n"
            "## [Title](https://example.com)\n\n"
            f"{_text(350)}\n\n"
            f"{_text(350)}\n\n"
            f"No bold prefix here: {_text(300)}\n\n"
            "Read more →\n"
        )
        errors = validate_featured_article(featured)
        insight_errors = [e for e in errors if e.field == "Key Insight paragraph"]
        assert len(insight_errors) == 1
        assert insight_errors[0].current == 0  # empty string, no ** paragraph found

    def test_only_one_paragraph(self) -> None:
        """Section with only one paragraph → P2 and Key Insight produce errors."""
        featured = (
            "# FEATURED ARTICLE\n"
            f"{_text(350)}\n"
            "# MAIN ARTICLE 1\nText.\n"
        )
        errors = validate_featured_article(featured)
        fields = {e.field for e in errors}
        assert "Paragraph 2" in fields
        assert "Key Insight paragraph" in fields

    def test_empty_raw_string(self) -> None:
        """Empty markdown → section not found → all errors with current=0."""
        errors = validate_featured_article("")
        assert len(errors) == 3
        assert all(e.current == 0 for e in errors)

    def test_italic_heading_variant(self) -> None:
        """Heading with ``# *FEATURED ARTICLE*`` (italic asterisks) is also found."""
        raw = (
            "# *FEATURED ARTICLE*\n"
            f"{_text(350)}\n\n"
            f"{_text(350)}\n\n"
            f"**Key Insight:** {_text(335 - 17)}\n\n"
            "Read more →\n"
            "# *MAIN ARTICLE 1*\nText.\n"
        )
        errors = validate_featured_article(raw)
        assert errors == []


# ===========================================================================
# validate_featured_article – CTA handling
# ===========================================================================


class TestValidateFeaturedArticleCta:
    """CTA line removal should not affect paragraph counting."""

    def test_cta_is_excluded_from_paragraphs(self) -> None:
        """CTA line should not be counted as a paragraph."""
        featured = (
            "# FEATURED ARTICLE\n"
            f"{_text(350)}\n\n"
            f"{_text(350)}\n\n"
            f"**Insight:** {_text(335 - 12)}\n\n"
            "Read more →\n"
            "# MAIN ARTICLE 1\nText.\n"
        )
        errors = validate_featured_article(featured)
        assert errors == []

    def test_link_cta_with_arrow(self) -> None:
        """CTA as a markdown link with → is still removed."""
        featured = (
            "# FEATURED ARTICLE\n"
            f"{_text(350)}\n\n"
            f"{_text(350)}\n\n"
            f"**Take:** {_text(335 - 10)}\n\n"
            "[Dive in →](https://example.com)\n"
            "# MAIN ARTICLE 1\nText.\n"
        )
        errors = validate_featured_article(featured)
        assert errors == []


# ===========================================================================
# validate_character_counts integration
# ===========================================================================


class TestValidateCharacterCountsIncludesFeatured:
    """Verify that validate_character_counts includes Featured Article checks."""

    def test_featured_errors_in_combined(self) -> None:
        raw = _make_featured(p1_len=100, p2_len=100, insight_len=100)
        errors = validate_character_counts(raw)
        featured_errors = [e for e in errors if e.section == "Featured Article"]
        assert len(featured_errors) == 3

    def test_valid_featured_no_errors_in_combined(self) -> None:
        raw = _make_featured(p1_len=350, p2_len=350, insight_len=335)
        errors = validate_character_counts(raw)
        featured_errors = [e for e in errors if e.section == "Featured Article"]
        assert len(featured_errors) == 0


# ===========================================================================
# Parametrized delta tests
# ===========================================================================


class TestFeaturedArticleDeltaAccuracy:
    """Parametrized tests verifying exact delta values for all three fields."""

    @pytest.mark.parametrize(
        "p1_len,expected_delta",
        [
            (100, -200),   # 100 - 300
            (299, -1),     # 299 - 300
            (401, 1),      # 401 - 400
            (500, 100),    # 500 - 400
        ],
    )
    def test_p1_delta(self, p1_len: int, expected_delta: int) -> None:
        raw = _make_featured(p1_len=p1_len)
        errors = validate_featured_article(raw)
        p1 = next(e for e in errors if e.field == "Paragraph 1")
        assert p1.delta == expected_delta

    @pytest.mark.parametrize(
        "p2_len,expected_delta",
        [
            (150, -150),
            (299, -1),
            (401, 1),
            (600, 200),
        ],
    )
    def test_p2_delta(self, p2_len: int, expected_delta: int) -> None:
        raw = _make_featured(p2_len=p2_len)
        errors = validate_featured_article(raw)
        p2 = next(e for e in errors if e.field == "Paragraph 2")
        assert p2.delta == expected_delta

    @pytest.mark.parametrize(
        "insight_len,expected_delta",
        [
            (100, -200),
            (299, -1),
            (371, 1),
            (500, 130),
        ],
    )
    def test_insight_delta(self, insight_len: int, expected_delta: int) -> None:
        raw = _make_featured(insight_len=insight_len)
        errors = validate_featured_article(raw)
        insight = next(e for e in errors if e.field == "Key Insight paragraph")
        assert insight.delta == expected_delta
