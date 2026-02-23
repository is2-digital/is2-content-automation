"""Character count validation for newsletter markdown sections.

Ported from the n8n "Validation Character count" Code node in
markdown_generator_subworkflow.json. Performs section-by-section character
counting with delta calculations for targeted LLM corrections.

Each error includes section name, field, current count, target range,
and exact delta (negative = too short, positive = too long).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CharacterCountError:
    """A single character-count validation error."""

    section: str
    field: str
    current: int
    target_min: int
    target_max: int
    delta: int

    def format(self) -> str:
        """Format as the n8n-compatible error string.

        Matches the JS output:
          ``section – field – current=N – target=MIN–MAX – delta=D``
        """
        sign = "+" if self.delta > 0 else ""
        return (
            f"{self.section} – {self.field} – current={self.current}"
            f" – target={self.target_min}–{self.target_max}"
            f" – delta={sign}{self.delta}"
        )


def extract_section(raw: str, title: str) -> str:
    """Extract a section's content from markdown by heading title.

    Uses the regex pattern from PRD Section 9.3::

        #\\s*\\*?{SECTION_NAME}\\*?\\s*\\n(content)(?=\\n#\\s*\\*?|$)

    Returns the trimmed content, or empty string if not found.
    """
    pattern = re.compile(
        rf"#\s*\*?{re.escape(title)}\*?\s*\n([\s\S]*?)(?=\n#\s*\*?|$)",
        re.IGNORECASE,
    )
    match = pattern.search(raw)
    return match.group(1).strip() if match else ""


def count_chars(s: str | None) -> int:
    """Count characters in a string, treating None as empty."""
    return len(s or "")


def _range_check(
    section: str,
    field: str,
    current: int,
    min_val: int,
    max_val: int,
) -> CharacterCountError | None:
    """Return an error if *current* is outside [min_val, max_val]."""
    if current < min_val:
        return CharacterCountError(
            section=section,
            field=field,
            current=current,
            target_min=min_val,
            target_max=max_val,
            delta=current - min_val,
        )
    if current > max_val:
        return CharacterCountError(
            section=section,
            field=field,
            current=current,
            target_min=min_val,
            target_max=max_val,
            delta=current - max_val,
        )
    return None


def _extract_bullets(text: str) -> list[str]:
    """Extract bullet items from text, stripping ``•`` or ``-`` prefixes."""
    return [
        line.removeprefix("• ").removeprefix("- ").strip()
        for line in text.split("\n")
        if line.startswith("• ") or line.startswith("- ")
    ]


def validate_quick_highlights(raw: str) -> list[CharacterCountError]:
    """Validate Quick Highlights section: 3 bullets, 150-190 chars each.

    Matches the n8n logic:
    1. Extract the QUICK HIGHLIGHTS section.
    2. Split into bullet lines (``•`` or ``-`` prefix).
    3. Only validate if exactly 3 bullets are found.
    4. Each bullet must be 150-190 characters.
    """
    quick = extract_section(raw, "QUICK HIGHLIGHTS")
    bullets = _extract_bullets(quick)
    errors: list[CharacterCountError] = []
    if len(bullets) == 3:
        for i, bullet in enumerate(bullets):
            err = _range_check(
                "Quick Highlights", f"Bullet {i + 1}", count_chars(bullet), 150, 190,
            )
            if err:
                errors.append(err)
    return errors


def validate_character_counts(raw: str) -> list[CharacterCountError]:
    """Run all character-count validations on markdown content.

    Returns the combined error list across all sections.
    """
    errors: list[CharacterCountError] = []
    errors.extend(validate_quick_highlights(raw))
    # Future tasks will add: Featured Article, Main Articles,
    # Industry Developments, Footer
    return errors
