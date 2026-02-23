"""Tests for the conditional output router utility.

Covers all combinations of:
- User choice (None, "yes", "provide feedback", "restart chat", unknown)
- Content validity (True, False)
- Regenerated text availability (present, None)
"""

from __future__ import annotations

import pytest

from ica.utils.output_router import (
    RouterResult,
    UserChoice,
    conditional_output_router,
    normalize_switch_value,
)

ORIGINAL = "Original content from Format output node"
REGENERATED = "Regenerated content from LLM"


# ---------------------------------------------------------------------------
# normalize_switch_value
# ---------------------------------------------------------------------------


class TestNormalizeSwitchValue:
    """Tests for the switch value normalizer."""

    def test_none_returns_none(self) -> None:
        assert normalize_switch_value(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_switch_value("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_switch_value("   ") is None

    def test_yes_lowercase(self) -> None:
        assert normalize_switch_value("yes") is UserChoice.YES

    def test_yes_uppercase(self) -> None:
        assert normalize_switch_value("YES") is UserChoice.YES

    def test_yes_mixed_case(self) -> None:
        assert normalize_switch_value("Yes") is UserChoice.YES

    def test_yes_with_whitespace(self) -> None:
        assert normalize_switch_value("  yes  ") is UserChoice.YES

    def test_provide_feedback_lowercase(self) -> None:
        assert normalize_switch_value("provide feedback") is UserChoice.PROVIDE_FEEDBACK

    def test_provide_feedback_mixed_case(self) -> None:
        assert normalize_switch_value("Provide Feedback") is UserChoice.PROVIDE_FEEDBACK

    def test_provide_feedback_with_whitespace(self) -> None:
        assert normalize_switch_value("  provide feedback  ") is UserChoice.PROVIDE_FEEDBACK

    def test_restart_chat_lowercase(self) -> None:
        assert normalize_switch_value("restart chat") is UserChoice.RESTART

    def test_restart_chat_mixed_case(self) -> None:
        assert normalize_switch_value("Restart Chat") is UserChoice.RESTART

    def test_restart_chat_with_whitespace(self) -> None:
        assert normalize_switch_value("  restart chat  ") is UserChoice.RESTART

    def test_unknown_value_returns_none(self) -> None:
        assert normalize_switch_value("something else") is None

    def test_partial_match_returns_none(self) -> None:
        assert normalize_switch_value("ye") is None

    def test_extra_words_returns_none(self) -> None:
        assert normalize_switch_value("yes please") is None


# ---------------------------------------------------------------------------
# RouterResult dataclass
# ---------------------------------------------------------------------------


class TestRouterResult:
    """Tests for the RouterResult dataclass."""

    def test_creation(self) -> None:
        result = RouterResult(text="hello", feedback="world")
        assert result.text == "hello"
        assert result.feedback == "world"

    def test_frozen(self) -> None:
        result = RouterResult(text="hello", feedback="world")
        with pytest.raises(AttributeError):
            result.text = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = RouterResult(text="a", feedback="b")
        b = RouterResult(text="a", feedback="b")
        assert a == b

    def test_inequality(self) -> None:
        a = RouterResult(text="a", feedback="b")
        b = RouterResult(text="a", feedback="c")
        assert a != b


# ---------------------------------------------------------------------------
# conditional_output_router — first pass (switch_value is None)
# ---------------------------------------------------------------------------


class TestFirstPass:
    """First pass through the router — no user interaction yet."""

    def test_no_regen_returns_original(self) -> None:
        result = conditional_output_router(
            switch_value=None,
            original_text=ORIGINAL,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_no_regen_explicit_none(self) -> None:
        result = conditional_output_router(
            switch_value=None,
            original_text=ORIGINAL,
            re_generated_text=None,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL


# ---------------------------------------------------------------------------
# conditional_output_router — user selects "yes"
# ---------------------------------------------------------------------------


class TestUserSelectsYes:
    """User approves content to proceed to next step."""

    def test_yes_no_regen(self) -> None:
        """First approval — no regeneration was attempted."""
        result = conditional_output_router(
            switch_value="yes",
            original_text=ORIGINAL,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_yes_with_valid_regen(self) -> None:
        """Approve after valid regeneration — use regenerated content."""
        result = conditional_output_router(
            switch_value="yes",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=True,
        )
        assert result.text == REGENERATED
        assert result.feedback == REGENERATED

    def test_yes_with_invalid_regen(self) -> None:
        """Approve but regen failed validity — revert to original."""
        result = conditional_output_router(
            switch_value="Yes",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=False,
        )
        assert result.text == ORIGINAL
        assert result.feedback == REGENERATED

    def test_yes_case_insensitive(self) -> None:
        result = conditional_output_router(
            switch_value="YES",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
        )
        assert result.text == REGENERATED

    def test_yes_with_whitespace(self) -> None:
        result = conditional_output_router(
            switch_value="  yes  ",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
        )
        assert result.text == REGENERATED


# ---------------------------------------------------------------------------
# conditional_output_router — user selects "provide feedback"
# ---------------------------------------------------------------------------


class TestUserSelectsFeedback:
    """User provides feedback for regeneration."""

    def test_feedback_no_regen(self) -> None:
        """Feedback selection with no prior regeneration."""
        result = conditional_output_router(
            switch_value="provide feedback",
            original_text=ORIGINAL,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_feedback_with_valid_regen(self) -> None:
        """Feedback after valid regeneration — use regenerated."""
        result = conditional_output_router(
            switch_value="provide feedback",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=True,
        )
        assert result.text == REGENERATED
        assert result.feedback == REGENERATED

    def test_feedback_with_invalid_regen(self) -> None:
        """Feedback after invalid regeneration — revert to original."""
        result = conditional_output_router(
            switch_value="Provide Feedback",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=False,
        )
        assert result.text == ORIGINAL
        assert result.feedback == REGENERATED

    def test_feedback_case_insensitive(self) -> None:
        result = conditional_output_router(
            switch_value="PROVIDE FEEDBACK",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
        )
        assert result.text == REGENERATED


# ---------------------------------------------------------------------------
# conditional_output_router — user selects "restart chat"
# ---------------------------------------------------------------------------


class TestUserSelectsRestart:
    """User restarts the generation from scratch."""

    def test_restart_no_regen(self) -> None:
        """Restart without prior regeneration — original becomes feedback."""
        result = conditional_output_router(
            switch_value="restart chat",
            original_text=ORIGINAL,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_restart_with_valid_regen(self) -> None:
        """Restart with valid regen — regenerated becomes text and feedback."""
        result = conditional_output_router(
            switch_value="restart chat",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=True,
        )
        # Step 1: choice is restart, which is a known choice → prefer regen
        # Step 2: content valid → feedback = text = REGENERATED
        # Step 3: restart override → feedback = text (still REGENERATED)
        assert result.text == REGENERATED
        assert result.feedback == REGENERATED

    def test_restart_with_invalid_regen(self) -> None:
        """Restart with invalid regen — revert to original, store invalid as feedback initially,
        then restart override sets feedback to text (original)."""
        result = conditional_output_router(
            switch_value="Restart Chat",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=False,
        )
        # Step 1: choice=restart (known) → prefer regen → text=REGENERATED
        # Step 2: invalid → feedback=REGENERATED, text=ORIGINAL
        # Step 3: restart override → feedback=text=ORIGINAL
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_restart_case_insensitive(self) -> None:
        result = conditional_output_router(
            switch_value="RESTART CHAT",
            original_text=ORIGINAL,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL


# ---------------------------------------------------------------------------
# conditional_output_router — unknown switch values
# ---------------------------------------------------------------------------


class TestUnknownSwitchValue:
    """Unknown/unexpected switch values always fall back to original."""

    def test_unknown_no_regen(self) -> None:
        result = conditional_output_router(
            switch_value="something unexpected",
            original_text=ORIGINAL,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_unknown_with_valid_regen(self) -> None:
        """Unknown choice with valid regen — still uses original (safe fallback)."""
        result = conditional_output_router(
            switch_value="maybe",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=True,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_unknown_with_invalid_regen(self) -> None:
        """Unknown choice with invalid regen — original text, invalid regen as feedback."""
        result = conditional_output_router(
            switch_value="nope",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
            content_valid=False,
        )
        # Step 1: unknown switch → text=ORIGINAL
        # Step 2: invalid regen → feedback=REGENERATED, text=ORIGINAL
        assert result.text == ORIGINAL
        assert result.feedback == REGENERATED

    def test_empty_string_switch(self) -> None:
        """Empty string is treated as unknown (not None)."""
        result = conditional_output_router(
            switch_value="",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
        )
        # Empty string: normalize returns None, but switch_value is not None
        # → unknown path → text=ORIGINAL
        assert result.text == ORIGINAL

    def test_whitespace_only_switch(self) -> None:
        """Whitespace-only is treated as unknown."""
        result = conditional_output_router(
            switch_value="   ",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
        )
        assert result.text == ORIGINAL


# ---------------------------------------------------------------------------
# conditional_output_router — content validity interactions
# ---------------------------------------------------------------------------


class TestContentValidity:
    """Content validity flag interactions with various user choices."""

    def test_valid_no_regen_has_no_effect(self) -> None:
        """content_valid is ignored when re_generated_text is None."""
        result = conditional_output_router(
            switch_value="yes",
            original_text=ORIGINAL,
            re_generated_text=None,
            content_valid=False,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_invalid_regen_overrides_text_selection(self) -> None:
        """Invalid regen always reverts text to original regardless of choice."""
        for choice in ["yes", "provide feedback"]:
            result = conditional_output_router(
                switch_value=choice,
                original_text=ORIGINAL,
                re_generated_text=REGENERATED,
                content_valid=False,
            )
            assert result.text == ORIGINAL, f"Failed for choice={choice}"
            assert result.feedback == REGENERATED, f"Failed for choice={choice}"

    def test_default_content_valid_is_true(self) -> None:
        """Default content_valid is True — regenerated text is used."""
        result = conditional_output_router(
            switch_value="yes",
            original_text=ORIGINAL,
            re_generated_text=REGENERATED,
        )
        assert result.text == REGENERATED


# ---------------------------------------------------------------------------
# conditional_output_router — edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_original_text(self) -> None:
        result = conditional_output_router(
            switch_value=None,
            original_text="",
        )
        assert result.text == ""
        assert result.feedback == ""

    def test_empty_regenerated_text(self) -> None:
        """Empty string is not None — it counts as regenerated text present."""
        result = conditional_output_router(
            switch_value="yes",
            original_text=ORIGINAL,
            re_generated_text="",
            content_valid=True,
        )
        assert result.text == ""
        assert result.feedback == ""

    def test_original_equals_regenerated(self) -> None:
        """When both texts are identical, result is consistent."""
        result = conditional_output_router(
            switch_value="yes",
            original_text=ORIGINAL,
            re_generated_text=ORIGINAL,
            content_valid=True,
        )
        assert result.text == ORIGINAL
        assert result.feedback == ORIGINAL

    def test_multiline_content(self) -> None:
        """Router preserves multiline content without modification."""
        multi = "Line 1\nLine 2\n\nLine 4"
        result = conditional_output_router(
            switch_value="yes",
            original_text="old",
            re_generated_text=multi,
        )
        assert result.text == multi

    def test_unicode_content(self) -> None:
        """Router handles unicode content."""
        unicode_text = "AI Insights — \u2018Smart\u2019 \u201cAnalysis\u201d \u2022 Bullet"
        result = conditional_output_router(
            switch_value="yes",
            original_text="old",
            re_generated_text=unicode_text,
        )
        assert result.text == unicode_text

    def test_very_long_content(self) -> None:
        """Router handles large content strings."""
        long_text = "x" * 100_000
        result = conditional_output_router(
            switch_value="yes",
            original_text="old",
            re_generated_text=long_text,
        )
        assert len(result.text) == 100_000


# ---------------------------------------------------------------------------
# Comprehensive state matrix
# ---------------------------------------------------------------------------


class TestStateMatrix:
    """Exhaustive test of all input state combinations.

    Matrix dimensions:
    - switch_value: None, yes, provide_feedback, restart, unknown
    - re_generated_text: None, present
    - content_valid: True, False (only meaningful when regen present)
    """

    @pytest.mark.parametrize(
        ("switch_val", "regen", "valid", "expected_text", "expected_feedback"),
        [
            # switch=None (first pass)
            (None, None, True, ORIGINAL, ORIGINAL),
            (None, REGENERATED, True, REGENERATED, REGENERATED),
            (None, REGENERATED, False, ORIGINAL, REGENERATED),
            # switch=yes
            ("yes", None, True, ORIGINAL, ORIGINAL),
            ("yes", REGENERATED, True, REGENERATED, REGENERATED),
            ("yes", REGENERATED, False, ORIGINAL, REGENERATED),
            # switch=provide feedback
            ("provide feedback", None, True, ORIGINAL, ORIGINAL),
            ("provide feedback", REGENERATED, True, REGENERATED, REGENERATED),
            ("provide feedback", REGENERATED, False, ORIGINAL, REGENERATED),
            # switch=restart chat
            ("restart chat", None, True, ORIGINAL, ORIGINAL),
            ("restart chat", REGENERATED, True, REGENERATED, REGENERATED),
            ("restart chat", REGENERATED, False, ORIGINAL, ORIGINAL),
            # switch=unknown
            ("unknown", None, True, ORIGINAL, ORIGINAL),
            ("unknown", REGENERATED, True, ORIGINAL, ORIGINAL),
            ("unknown", REGENERATED, False, ORIGINAL, REGENERATED),
        ],
        ids=[
            "none-no_regen-valid",
            "none-regen-valid",
            "none-regen-invalid",
            "yes-no_regen-valid",
            "yes-regen-valid",
            "yes-regen-invalid",
            "feedback-no_regen-valid",
            "feedback-regen-valid",
            "feedback-regen-invalid",
            "restart-no_regen-valid",
            "restart-regen-valid",
            "restart-regen-invalid",
            "unknown-no_regen-valid",
            "unknown-regen-valid",
            "unknown-regen-invalid",
        ],
    )
    def test_state_combination(
        self,
        switch_val: str | None,
        regen: str | None,
        valid: bool,
        expected_text: str,
        expected_feedback: str,
    ) -> None:
        result = conditional_output_router(
            switch_value=switch_val,
            original_text=ORIGINAL,
            re_generated_text=regen,
            content_valid=valid,
        )
        assert result.text == expected_text
        assert result.feedback == expected_feedback


# ---------------------------------------------------------------------------
# UserChoice enum
# ---------------------------------------------------------------------------


class TestUserChoiceEnum:
    """Tests for the UserChoice enum."""

    def test_values(self) -> None:
        assert UserChoice.YES.value == "yes"
        assert UserChoice.PROVIDE_FEEDBACK.value == "provide feedback"
        assert UserChoice.RESTART.value == "restart chat"

    def test_is_string_subclass(self) -> None:
        assert isinstance(UserChoice.YES, str)

    def test_comparison_with_string(self) -> None:
        assert UserChoice.YES == "yes"
        assert UserChoice.PROVIDE_FEEDBACK == "provide feedback"
        assert UserChoice.RESTART == "restart chat"

    def test_member_count(self) -> None:
        assert len(UserChoice) == 3
