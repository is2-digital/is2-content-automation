"""Tests for Quick Highlights character counting validation.

Covers:
- Section extraction from markdown
- Bullet extraction (• and - prefixes)
- Character counting per bullet
- Delta calculation for 150-190 char range
- Edge cases (missing section, wrong bullet count, empty content)
"""

from __future__ import annotations

import pytest

from ica.validators.character_count import (
    CharacterCountError,
    _extract_bullets,
    _range_check,
    count_chars,
    extract_section,
    validate_quick_highlights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bullet(length: int, char: str = "x") -> str:
    """Create a bullet string of exactly *length* characters."""
    return char * length


def _make_quick_highlights(*bullet_lengths: int, prefix: str = "• ") -> str:
    """Build a full markdown document with a QUICK HIGHLIGHTS section."""
    bullets = "\n".join(f"{prefix}{_make_bullet(n)}" for n in bullet_lengths)
    return f"# QUICK HIGHLIGHTS\n{bullets}\n"


def _make_full_doc(*bullet_lengths: int) -> str:
    """Build markdown with Quick Highlights embedded between other sections."""
    bullets = "\n".join(f"• {_make_bullet(n)}" for n in bullet_lengths)
    return (
        "# INTRODUCTION\nSome intro text.\n\n"
        f"# QUICK HIGHLIGHTS\n{bullets}\n\n"
        "# FEATURED ARTICLE\nSome article text.\n"
    )


# ===========================================================================
# extract_section
# ===========================================================================


class TestExtractSection:
    """Test the extract_section helper for QUICK HIGHLIGHTS."""

    def test_extracts_basic_section(self) -> None:
        raw = "# QUICK HIGHLIGHTS\nBullet content here\n"
        assert extract_section(raw, "QUICK HIGHLIGHTS") == "Bullet content here"

    def test_extracts_between_sections(self) -> None:
        raw = (
            "# INTRO\nIntro text\n"
            "# QUICK HIGHLIGHTS\nBullet 1\nBullet 2\n"
            "# NEXT SECTION\nNext text\n"
        )
        result = extract_section(raw, "QUICK HIGHLIGHTS")
        assert result == "Bullet 1\nBullet 2"

    def test_case_insensitive(self) -> None:
        raw = "# Quick Highlights\nContent\n"
        assert extract_section(raw, "QUICK HIGHLIGHTS") == "Content"

    def test_with_bold_markers(self) -> None:
        raw = "# *QUICK HIGHLIGHTS*\nContent\n"
        assert extract_section(raw, "QUICK HIGHLIGHTS") == "Content"

    def test_returns_empty_for_missing_section(self) -> None:
        raw = "# INTRODUCTION\nSome text\n"
        assert extract_section(raw, "QUICK HIGHLIGHTS") == ""

    def test_returns_empty_for_empty_input(self) -> None:
        assert extract_section("", "QUICK HIGHLIGHTS") == ""

    def test_trims_whitespace(self) -> None:
        raw = "# QUICK HIGHLIGHTS\n  \n  Content  \n  \n"
        result = extract_section(raw, "QUICK HIGHLIGHTS")
        assert result == "Content"

    def test_multiline_content(self) -> None:
        raw = "# QUICK HIGHLIGHTS\n• Line 1\n• Line 2\n• Line 3\n"
        result = extract_section(raw, "QUICK HIGHLIGHTS")
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_section_at_end_of_document(self) -> None:
        raw = "# INTRO\nText\n# QUICK HIGHLIGHTS\nFinal content"
        assert extract_section(raw, "QUICK HIGHLIGHTS") == "Final content"

    def test_extra_spaces_around_heading(self) -> None:
        raw = "#   QUICK HIGHLIGHTS  \nContent\n"
        assert extract_section(raw, "QUICK HIGHLIGHTS") == "Content"


# ===========================================================================
# _extract_bullets
# ===========================================================================


class TestExtractBullets:
    """Test bullet extraction from section content."""

    def test_bullet_dot_prefix(self) -> None:
        text = "• First bullet\n• Second bullet\n• Third bullet"
        assert _extract_bullets(text) == ["First bullet", "Second bullet", "Third bullet"]

    def test_dash_prefix(self) -> None:
        text = "- First bullet\n- Second bullet\n- Third bullet"
        assert _extract_bullets(text) == ["First bullet", "Second bullet", "Third bullet"]

    def test_mixed_prefixes(self) -> None:
        text = "• First bullet\n- Second bullet\n• Third bullet"
        assert _extract_bullets(text) == ["First bullet", "Second bullet", "Third bullet"]

    def test_ignores_non_bullet_lines(self) -> None:
        text = "Some header text\n• Bullet one\nNot a bullet\n• Bullet two"
        assert _extract_bullets(text) == ["Bullet one", "Bullet two"]

    def test_strips_whitespace(self) -> None:
        text = "•  Padded bullet  \n- Another padded  "
        assert _extract_bullets(text) == ["Padded bullet", "Another padded"]

    def test_empty_input(self) -> None:
        assert _extract_bullets("") == []

    def test_no_bullets(self) -> None:
        text = "Just plain text\nAnother line"
        assert _extract_bullets(text) == []

    def test_bullet_with_bold_text(self) -> None:
        text = "• **Bold** text in bullet"
        assert _extract_bullets(text) == ["**Bold** text in bullet"]

    def test_single_bullet(self) -> None:
        text = "• Only one"
        assert _extract_bullets(text) == ["Only one"]

    def test_four_bullets(self) -> None:
        text = "• A\n• B\n• C\n• D"
        assert _extract_bullets(text) == ["A", "B", "C", "D"]


# ===========================================================================
# count_chars
# ===========================================================================


class TestCountChars:
    """Test the character counting helper."""

    def test_normal_string(self) -> None:
        assert count_chars("hello") == 5

    def test_empty_string(self) -> None:
        assert count_chars("") == 0

    def test_none(self) -> None:
        assert count_chars(None) == 0

    def test_string_with_spaces(self) -> None:
        assert count_chars("a b c") == 5

    def test_string_with_bold_markdown(self) -> None:
        assert count_chars("**bold**") == 8


# ===========================================================================
# _range_check
# ===========================================================================


class TestRangeCheck:
    """Test the range check error generator for 150-190 range."""

    def test_within_range_returns_none(self) -> None:
        assert _range_check("S", "F", 170, 150, 190) is None

    def test_at_lower_bound(self) -> None:
        assert _range_check("S", "F", 150, 150, 190) is None

    def test_at_upper_bound(self) -> None:
        assert _range_check("S", "F", 190, 150, 190) is None

    def test_below_range(self) -> None:
        err = _range_check("Quick Highlights", "Bullet 1", 120, 150, 190)
        assert err is not None
        assert err.section == "Quick Highlights"
        assert err.field == "Bullet 1"
        assert err.current == 120
        assert err.target_min == 150
        assert err.target_max == 190
        assert err.delta == -30  # 120 - 150

    def test_above_range(self) -> None:
        err = _range_check("Quick Highlights", "Bullet 2", 210, 150, 190)
        assert err is not None
        assert err.current == 210
        assert err.delta == 20  # 210 - 190

    def test_one_below_min(self) -> None:
        err = _range_check("S", "F", 149, 150, 190)
        assert err is not None
        assert err.delta == -1

    def test_one_above_max(self) -> None:
        err = _range_check("S", "F", 191, 150, 190)
        assert err is not None
        assert err.delta == 1

    def test_zero_current(self) -> None:
        err = _range_check("S", "F", 0, 150, 190)
        assert err is not None
        assert err.delta == -150


# ===========================================================================
# CharacterCountError.format
# ===========================================================================


class TestCharacterCountErrorFormat:
    """Test the n8n-compatible error string format."""

    def test_below_range_format(self) -> None:
        err = CharacterCountError("Quick Highlights", "Bullet 1", 120, 150, 190, -30)
        assert err.format() == (
            "Quick Highlights – Bullet 1 – current=120 – target=150–190 – delta=-30"
        )

    def test_above_range_format(self) -> None:
        err = CharacterCountError("Quick Highlights", "Bullet 2", 210, 150, 190, 20)
        assert err.format() == (
            "Quick Highlights – Bullet 2 – current=210 – target=150–190 – delta=+20"
        )

    def test_frozen_dataclass(self) -> None:
        err = CharacterCountError("S", "F", 100, 150, 190, -50)
        with pytest.raises(AttributeError):
            err.current = 200  # type: ignore[misc]


# ===========================================================================
# validate_quick_highlights — happy paths
# ===========================================================================


class TestValidateQuickHighlightsValid:
    """Test cases where all 3 bullets are within 150-190 chars."""

    def test_all_at_minimum(self) -> None:
        raw = _make_quick_highlights(150, 150, 150)
        assert validate_quick_highlights(raw) == []

    def test_all_at_maximum(self) -> None:
        raw = _make_quick_highlights(190, 190, 190)
        assert validate_quick_highlights(raw) == []

    def test_all_at_midpoint(self) -> None:
        raw = _make_quick_highlights(170, 170, 170)
        assert validate_quick_highlights(raw) == []

    def test_varied_valid_lengths(self) -> None:
        raw = _make_quick_highlights(155, 175, 185)
        assert validate_quick_highlights(raw) == []

    def test_dash_bullets(self) -> None:
        raw = _make_quick_highlights(170, 170, 170, prefix="- ")
        assert validate_quick_highlights(raw) == []

    def test_embedded_between_sections(self) -> None:
        raw = _make_full_doc(165, 170, 180)
        assert validate_quick_highlights(raw) == []


# ===========================================================================
# validate_quick_highlights — error paths
# ===========================================================================


class TestValidateQuickHighlightsErrors:
    """Test cases where bullets violate the 150-190 char range."""

    def test_first_bullet_too_short(self) -> None:
        raw = _make_quick_highlights(100, 170, 170)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 1
        assert errors[0].field == "Bullet 1"
        assert errors[0].current == 100
        assert errors[0].delta == -50  # 100 - 150

    def test_second_bullet_too_long(self) -> None:
        raw = _make_quick_highlights(170, 220, 170)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 1
        assert errors[0].field == "Bullet 2"
        assert errors[0].current == 220
        assert errors[0].delta == 30  # 220 - 190

    def test_third_bullet_too_short(self) -> None:
        raw = _make_quick_highlights(170, 170, 130)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 1
        assert errors[0].field == "Bullet 3"
        assert errors[0].delta == -20  # 130 - 150

    def test_all_bullets_too_short(self) -> None:
        raw = _make_quick_highlights(100, 110, 120)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 3
        assert [e.field for e in errors] == ["Bullet 1", "Bullet 2", "Bullet 3"]
        assert errors[0].delta == -50
        assert errors[1].delta == -40
        assert errors[2].delta == -30

    def test_all_bullets_too_long(self) -> None:
        raw = _make_quick_highlights(200, 210, 250)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 3
        assert errors[0].delta == 10  # 200 - 190
        assert errors[1].delta == 20  # 210 - 190
        assert errors[2].delta == 60  # 250 - 190

    def test_mixed_errors(self) -> None:
        raw = _make_quick_highlights(100, 170, 250)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 2
        assert errors[0].field == "Bullet 1"
        assert errors[0].delta == -50
        assert errors[1].field == "Bullet 3"
        assert errors[1].delta == 60

    def test_one_char_below_min(self) -> None:
        raw = _make_quick_highlights(149, 170, 170)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 1
        assert errors[0].delta == -1

    def test_one_char_above_max(self) -> None:
        raw = _make_quick_highlights(170, 170, 191)
        errors = validate_quick_highlights(raw)
        assert len(errors) == 1
        assert errors[0].delta == 1

    def test_error_section_name(self) -> None:
        raw = _make_quick_highlights(100, 170, 170)
        errors = validate_quick_highlights(raw)
        assert errors[0].section == "Quick Highlights"

    def test_error_target_range(self) -> None:
        raw = _make_quick_highlights(100, 170, 170)
        errors = validate_quick_highlights(raw)
        assert errors[0].target_min == 150
        assert errors[0].target_max == 190


# ===========================================================================
# validate_quick_highlights — skip cases (wrong bullet count)
# ===========================================================================


class TestValidateQuickHighlightsSkip:
    """Cases where validation is skipped (not exactly 3 bullets)."""

    def test_no_bullets(self) -> None:
        raw = "# QUICK HIGHLIGHTS\nJust plain text, no bullets.\n"
        assert validate_quick_highlights(raw) == []

    def test_one_bullet(self) -> None:
        raw = _make_quick_highlights(100)
        assert validate_quick_highlights(raw) == []

    def test_two_bullets(self) -> None:
        raw = _make_quick_highlights(100, 100)
        assert validate_quick_highlights(raw) == []

    def test_four_bullets(self) -> None:
        raw = _make_quick_highlights(100, 100, 100, 100)
        assert validate_quick_highlights(raw) == []

    def test_missing_section(self) -> None:
        raw = "# INTRODUCTION\nSome text\n# FEATURED ARTICLE\nMore text\n"
        assert validate_quick_highlights(raw) == []

    def test_empty_input(self) -> None:
        assert validate_quick_highlights("") == []

    def test_empty_section(self) -> None:
        raw = "# QUICK HIGHLIGHTS\n\n# NEXT SECTION\nText\n"
        assert validate_quick_highlights(raw) == []


# ===========================================================================
# Delta calculation accuracy (parametrized)
# ===========================================================================


class TestDeltaCalculation:
    """Verify delta = current - boundary for various lengths."""

    @pytest.mark.parametrize(
        "length, expected_delta",
        [
            (0, -150),
            (50, -100),
            (100, -50),
            (149, -1),
            (150, None),  # valid, no error
            (170, None),  # valid, no error
            (190, None),  # valid, no error
            (191, 1),
            (200, 10),
            (250, 60),
            (500, 310),
        ],
    )
    def test_delta_for_single_bullet(
        self,
        length: int,
        expected_delta: int | None,
    ) -> None:
        raw = _make_quick_highlights(length, 170, 170)
        errors = validate_quick_highlights(raw)
        bullet_1_errors = [e for e in errors if e.field == "Bullet 1"]
        if expected_delta is None:
            assert bullet_1_errors == []
        else:
            assert len(bullet_1_errors) == 1
            assert bullet_1_errors[0].delta == expected_delta

    @pytest.mark.parametrize(
        "length, expected_delta",
        [
            (1, -149),
            (149, -1),
            (191, 1),
            (300, 110),
        ],
    )
    def test_delta_for_third_bullet(
        self,
        length: int,
        expected_delta: int,
    ) -> None:
        raw = _make_quick_highlights(170, 170, length)
        errors = validate_quick_highlights(raw)
        bullet_3_errors = [e for e in errors if e.field == "Bullet 3"]
        assert len(bullet_3_errors) == 1
        assert bullet_3_errors[0].delta == expected_delta

    def test_zero_length_bullet_stripped_by_section_extraction(self) -> None:
        """A 0-length bullet becomes just '•' after section trim, losing
        the space needed for prefix matching.  This matches n8n JS behavior:
        the bullet is not detected, leaving only 2 bullets → validation skipped.
        """
        raw = _make_quick_highlights(170, 170, 0)
        assert validate_quick_highlights(raw) == []
