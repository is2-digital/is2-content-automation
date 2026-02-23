"""Tests for ica.utils.boolean_normalizer.normalize_boolean.

Verifies conversion of Google Sheets string values to Python booleans,
matching the n8n Field Mapping Set node expression:
    $json.approved && $json.approved.toString().toLowerCase() === 'yes'

Task: ica-dd0.1.8 — Test boolean normalizer
"""

from __future__ import annotations

import pytest

from ica.utils.boolean_normalizer import normalize_boolean


# ---------------------------------------------------------------------------
# Truthy cases — only "yes" (case-insensitive) maps to True
# ---------------------------------------------------------------------------


class TestTruthyValues:
    """Values that should normalize to True."""

    def test_lowercase_yes(self) -> None:
        assert normalize_boolean("yes") is True

    def test_uppercase_yes(self) -> None:
        assert normalize_boolean("YES") is True

    def test_titlecase_yes(self) -> None:
        assert normalize_boolean("Yes") is True

    def test_mixed_case_yes(self) -> None:
        assert normalize_boolean("yEs") is True

    def test_mixed_case_yes_variant(self) -> None:
        assert normalize_boolean("yeS") is True

    def test_yes_with_leading_whitespace(self) -> None:
        assert normalize_boolean("  yes") is True

    def test_yes_with_trailing_whitespace(self) -> None:
        assert normalize_boolean("yes  ") is True

    def test_yes_with_surrounding_whitespace(self) -> None:
        assert normalize_boolean("  yes  ") is True

    def test_yes_with_tab(self) -> None:
        assert normalize_boolean("\tyes\t") is True

    def test_bool_true(self) -> None:
        """Python bool True should pass through."""
        assert normalize_boolean(True) is True


# ---------------------------------------------------------------------------
# Falsy cases — everything else maps to False
# ---------------------------------------------------------------------------


class TestFalsyValues:
    """Values that should normalize to False."""

    def test_lowercase_no(self) -> None:
        assert normalize_boolean("no") is False

    def test_uppercase_no(self) -> None:
        assert normalize_boolean("NO") is False

    def test_titlecase_no(self) -> None:
        assert normalize_boolean("No") is False

    def test_lowercase_true_string(self) -> None:
        """The string 'true' is NOT truthy — only 'yes' is."""
        assert normalize_boolean("true") is False

    def test_uppercase_true_string(self) -> None:
        assert normalize_boolean("TRUE") is False

    def test_titlecase_true_string(self) -> None:
        assert normalize_boolean("True") is False

    def test_lowercase_false_string(self) -> None:
        assert normalize_boolean("false") is False

    def test_uppercase_false_string(self) -> None:
        assert normalize_boolean("FALSE") is False

    def test_titlecase_false_string(self) -> None:
        assert normalize_boolean("False") is False

    def test_empty_string(self) -> None:
        assert normalize_boolean("") is False

    def test_whitespace_only(self) -> None:
        assert normalize_boolean("   ") is False

    def test_none(self) -> None:
        assert normalize_boolean(None) is False

    def test_bool_false(self) -> None:
        """Python bool False should pass through."""
        assert normalize_boolean(False) is False

    def test_zero_string(self) -> None:
        assert normalize_boolean("0") is False

    def test_one_string(self) -> None:
        assert normalize_boolean("1") is False

    def test_arbitrary_string(self) -> None:
        assert normalize_boolean("maybe") is False

    def test_y_alone(self) -> None:
        """Single 'y' is not 'yes'."""
        assert normalize_boolean("y") is False

    def test_n_alone(self) -> None:
        assert normalize_boolean("n") is False

    def test_yes_with_extra_chars(self) -> None:
        """'yess' is not 'yes'."""
        assert normalize_boolean("yess") is False

    def test_yes_with_prefix(self) -> None:
        """'ayes' is not 'yes'."""
        assert normalize_boolean("ayes") is False


# ---------------------------------------------------------------------------
# Return type guarantees
# ---------------------------------------------------------------------------


class TestReturnType:
    """Ensure the return value is always a real bool, not a truthy/falsy proxy."""

    @pytest.mark.parametrize("value", ["yes", "YES", "Yes", True])
    def test_truthy_returns_exact_bool_true(self, value: str | bool) -> None:
        result = normalize_boolean(value)
        assert result is True
        assert type(result) is bool

    @pytest.mark.parametrize(
        "value",
        ["no", "NO", "true", "false", "", None, False, "0", "1", "maybe"],
    )
    def test_falsy_returns_exact_bool_false(self, value: str | bool | None) -> None:
        result = normalize_boolean(value)
        assert result is False
        assert type(result) is bool


# ---------------------------------------------------------------------------
# Parametrized matrix — matches task description exactly
# ---------------------------------------------------------------------------


class TestTaskSpecifiedValues:
    """Directly verify the values listed in the task description:
    yes, no, Yes, YES, true, false, empty string.
    """

    @pytest.mark.parametrize(
        ("input_value", "expected"),
        [
            ("yes", True),
            ("no", False),
            ("Yes", True),
            ("YES", True),
            ("true", False),
            ("false", False),
            ("", False),
        ],
        ids=["yes", "no", "Yes", "YES", "true", "false", "empty"],
    )
    def test_specified_conversions(
        self, input_value: str, expected: bool
    ) -> None:
        assert normalize_boolean(input_value) is expected
