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
                "Quick Highlights",
                f"Bullet {i + 1}",
                count_chars(bullet),
                150,
                190,
            )
            if err:
                errors.append(err)
    return errors


def _strip_subheading(text: str) -> str:
    """Remove a ``## ...`` subheading line from section content."""
    return re.sub(r"^##\s+.*$", "", text, count=1, flags=re.MULTILINE).strip()


def _extract_cta(text: str) -> tuple[str, str]:
    """Find the CTA line (contains ``→``) and return ``(cta, text_without_cta)``.

    Returns ``("", text)`` if no CTA line is found.
    """
    match = re.search(r"^.*→.*$", text, re.MULTILINE)
    if not match:
        return "", text
    cta = match.group(0)
    return cta, text.replace(cta, "").strip()


def _split_paragraphs(text: str) -> list[str]:
    """Split text on blank lines, returning non-empty trimmed paragraphs."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _strip_source_links(text: str) -> str:
    """Remove markdown source-link lines containing ``→`` (e.g. ``[Read more →](url)``)."""
    return re.sub(r"^\[.*→\]\(.*?\)$", "", text, flags=re.MULTILINE).strip()


def _find_callout(paras: list[str]) -> str:
    """Find the callout paragraph (bold label pattern like ``**Label:**`` text).

    Matches the n8n regex ``/^(\\*\\*|\\*)[^*]+:\\1/`` — a paragraph that starts
    with ``**`` or ``*``, followed by non-asterisk text and a colon, closed by the
    same delimiter.
    """
    pattern = re.compile(r"^(\*\*|\*)[^*]+:\1")
    return next((p for p in paras if pattern.match(p)), "")


def validate_featured_article(raw: str) -> list[CharacterCountError]:
    """Validate Featured Article section: P1 (300-400), P2 (300-400), Key Insight (300-370).

    Matches the n8n logic:
    1. Extract the FEATURED ARTICLE section.
    2. Strip the ``## ...`` subheading line.
    3. Find and remove the CTA line (contains ``→``).
    4. Split remaining text into paragraphs on blank lines.
    5. P1 = first paragraph, P2 = second paragraph.
    6. Key Insight = first paragraph starting with ``**``.
    """
    featured = extract_section(raw, "FEATURED ARTICLE")
    body = _strip_subheading(featured)
    _cta, body_no_cta = _extract_cta(body)
    paras = _split_paragraphs(body_no_cta)

    p1 = paras[0] if len(paras) > 0 else ""
    p2 = paras[1] if len(paras) > 1 else ""
    insight = next((p for p in paras if p.startswith("**")), "")

    errors: list[CharacterCountError] = []
    for field, text, lo, hi in [
        ("Paragraph 1", p1, 300, 400),
        ("Paragraph 2", p2, 300, 400),
        ("Key Insight paragraph", insight, 300, 370),
    ]:
        err = _range_check("Featured Article", field, count_chars(text), lo, hi)
        if err:
            errors.append(err)
    return errors


def validate_main_articles(raw: str) -> list[CharacterCountError]:
    """Validate Main Article 1 and 2 sections.

    For each article (ported from n8n ``parseMain``):
    1. Extract the ``MAIN ARTICLE N`` section.
    2. Strip the ``## ...`` subheading line.
    3. Remove source-link lines (``[text →](url)``).
    4. Split remaining text into paragraphs on blank lines.
    5. Callout = first paragraph matching bold-label pattern (``**Label:**``).
    6. Content = first paragraph that is NOT the callout.

    Ranges:
    - Callout Paragraph: 180–250 characters.
    - Content Paragraph: max 750 characters (no minimum).
    """
    errors: list[CharacterCountError] = []
    for index in (1, 2):
        section = extract_section(raw, f"MAIN ARTICLE {index}")
        body = _strip_subheading(section)
        body = _strip_source_links(body)
        paras = _split_paragraphs(body)

        callout = _find_callout(paras)
        content = (
            next((p for p in paras if p != callout), "")
            if callout
            else (paras[0] if paras else "")
        )

        section_name = f"Main Article {index}"

        err = _range_check(section_name, "Callout Paragraph", count_chars(callout), 180, 250)
        if err:
            errors.append(err)

        err = _range_check(section_name, "Content Paragraph", count_chars(content), 0, 750)
        if err:
            errors.append(err)

    return errors


def validate_character_counts(raw: str) -> list[CharacterCountError]:
    """Run all character-count validations on markdown content.

    Returns the combined error list across all sections.
    """
    errors: list[CharacterCountError] = []
    errors.extend(validate_quick_highlights(raw))
    errors.extend(validate_featured_article(raw))
    errors.extend(validate_main_articles(raw))
    # Future tasks will add: Industry Developments, Footer
    return errors
