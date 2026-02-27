"""Conditional output router for human-in-the-loop approval flows.

Determines whether to use original or regenerated content based on:
- User's form selection (switch_value from Slack sendAndWait)
- Content validity check (e.g., hasIntroduction header present)
- Feedback processing status

This is a direct port of the n8n "Conditional output" Code node used in
summarization, markdown generation, HTML generation, and other subworkflows.
See PRD Section 9.8 and project-details.md Section 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UserChoice(StrEnum):
    """Possible user selections from the Slack sendAndWait form."""

    YES = "yes"
    PROVIDE_FEEDBACK = "provide feedback"
    RESTART = "restart chat"


@dataclass(frozen=True)
class RouterResult:
    """Output of the conditional output router.

    Attributes:
        text: The content to display or pass to the next pipeline step.
        feedback: The content to store for learning / feedback injection.
    """

    text: str
    feedback: str


def normalize_switch_value(raw: str | None) -> UserChoice | None:
    """Normalize a raw Slack form value to a :class:`UserChoice`.

    Args:
        raw: The raw string from the Slack form field, or ``None``.

    Returns:
        The matching :class:`UserChoice`, or ``None`` if *raw* is ``None``,
        empty, or does not match any known choice.
    """
    if raw is None:
        return None

    cleaned = raw.strip().lower()
    if not cleaned:
        return None

    for choice in UserChoice:
        if cleaned == choice.value:
            return choice

    return None


def conditional_output_router(
    switch_value: str | None,
    original_text: str,
    re_generated_text: str | None = None,
    content_valid: bool = True,
) -> RouterResult:
    """Route between original and regenerated content.

    Mirrors the n8n "Conditional output" Code node logic:

    1. If *switch_value* is an unrecognized value (not yes/feedback/restart
       and not None), use *original_text*.
    2. Otherwise prefer *re_generated_text* when available, falling back to
       *original_text*.
    3. If *re_generated_text* exists but *content_valid* is ``False``,
       revert to *original_text* and store the invalid regen as feedback.
    4. If *switch_value* is ``"restart chat"``, store current text as feedback.

    Args:
        switch_value: Raw user choice from Slack form (``None`` on first pass).
        original_text: The initially generated content (always available).
        re_generated_text: Content regenerated from feedback, or ``None``.
        content_valid: Whether *re_generated_text* passes validity checks
            (e.g., required header present). Ignored when *re_generated_text*
            is ``None``. Defaults to ``True``.

    Returns:
        A :class:`RouterResult` with the selected *text* and *feedback*.
    """
    choice = normalize_switch_value(switch_value)

    # Step 1: Select base text.
    # Unknown switch values (not None, not a recognized choice) → original.
    if switch_value is not None and choice is None:
        text = original_text
    else:
        # Prefer regenerated when available.
        text = re_generated_text if re_generated_text is not None else original_text

    # Step 2: Content validity override.
    # If regenerated text exists but failed validation, revert and store
    # the invalid output as feedback for the next attempt.
    if re_generated_text is not None and not content_valid:
        feedback = re_generated_text
        text = original_text
    else:
        feedback = text

    # Step 3: Restart override.
    # On restart, the current text becomes the feedback seed.
    if choice is UserChoice.RESTART:
        feedback = text

    return RouterResult(text=text, feedback=feedback)
