"""Theme Generation Pipeline — Step 3 of the newsletter pipeline.

Receives summarized articles from Step 2, fetches learning data from the
``notes`` table (type ``user_newsletter_themes``), calls the LLM with the
theme generation prompt, and parses the output into structured themes.

Flow:
1. Fetch recent notes (last 40 entries) from the database.
2. Aggregate feedback into a bullet-point list for prompt injection.
3. Build system/user prompts via :func:`build_theme_generation_prompt`.
4. Call LLM via :func:`~ica.services.llm.completion`.
5. Split LLM output on ``-----`` delimiters via :func:`split_themes`.
6. Extract ``%XX_`` markers from each theme via :func:`parse_markers`.
7. Return :class:`ThemeGenerationResult` with all parsed themes.

See PRD Section 3.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose
from ica.db.crud import get_recent_notes
from ica.db.models import Note
from ica.prompts.theme_generation import build_theme_generation_prompt
from ica.services.llm import completion
from ica.utils.marker_parser import (
    FormattedTheme,
    parse_markers,
    split_themes,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratedTheme:
    """A single theme with its raw text and parsed structured data.

    Attributes:
        theme_name: Name extracted from the ``THEME:`` line.
        theme_description: Description from the ``Theme Description:`` line.
        theme_body: The raw text block for this theme.
        formatted_theme: Structured article assignments parsed from markers.
    """

    theme_name: str | None
    theme_description: str | None
    theme_body: str
    formatted_theme: FormattedTheme


@dataclass(frozen=True)
class ThemeGenerationResult:
    """Complete result of the theme generation pipeline step.

    Attributes:
        themes: List of parsed themes (typically 2).
        recommendation: The LLM's recommendation text.
        raw_llm_output: The complete raw text returned by the LLM.
        model: The model identifier used for generation.
    """

    themes: list[GeneratedTheme] = field(default_factory=list)
    recommendation: str = ""
    raw_llm_output: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# Feedback aggregation
# ---------------------------------------------------------------------------


def aggregate_feedback(
    feedback_rows: list[Note],
) -> str | None:
    """Convert feedback rows into a bullet-point string for prompt injection.

    Mirrors the n8n "Process User Feedback" Code node which aggregates
    feedback entries from the database into a single text block.

    Args:
        feedback_rows: Recent feedback rows ordered by ``created_at`` DESC
            (as returned by :func:`get_recent_notes`).

    Returns:
        A newline-separated bullet list of feedback texts, or ``None``
        if no feedback is available.
    """
    if not feedback_rows:
        return None

    lines = [f"- {row.feedback_text}" for row in feedback_rows if row.feedback_text]
    return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def call_theme_llm(
    summaries_json: str,
    aggregated_feedback: str | None = None,
    *,
    model: str | None = None,
) -> tuple[str, str]:
    """Call the LLM to generate newsletter themes.

    Args:
        summaries_json: JSON string of the article summaries array.
        aggregated_feedback: Optional aggregated feedback text.
        model: Override model identifier. Defaults to
            ``get_model(LLMPurpose.THEME)``.

    Returns:
        A ``(response_text, model_used)`` tuple.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    system_prompt, user_prompt = build_theme_generation_prompt(
        summaries_json=summaries_json,
        aggregated_feedback=aggregated_feedback,
    )

    result = await completion(
        purpose=LLMPurpose.THEME,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        step="theme_generation",
    )

    return result.text, result.model


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_theme_output(raw_output: str) -> list[GeneratedTheme]:
    """Parse raw LLM output into a list of :class:`GeneratedTheme` objects.

    Combines :func:`split_themes` (splitting on ``-----``) with
    :func:`parse_markers` (extracting ``%XX_`` markers) to produce
    fully structured theme objects.

    Args:
        raw_output: The complete text returned by the theme-generation LLM.

    Returns:
        List of :class:`GeneratedTheme` objects (one per theme block).
    """
    result = split_themes(raw_output)

    themes: list[GeneratedTheme] = []
    for block in result.themes:
        formatted = parse_markers(block.theme_body, theme_title=block.theme_name)
        themes.append(
            GeneratedTheme(
                theme_name=block.theme_name,
                theme_description=block.theme_description,
                theme_body=block.theme_body,
                formatted_theme=formatted,
            )
        )

    return themes


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def generate_themes(
    summaries_json: str,
    session: AsyncSession | None = None,
    *,
    model: str | None = None,
) -> ThemeGenerationResult:
    """Execute the full theme generation pipeline step.

    1. Fetch recent notes from the ``notes`` table (type
       ``user_newsletter_themes``).
    2. Aggregate feedback into a prompt-injectable string.
    3. Call the LLM with the theme generation prompt.
    4. Parse the LLM output into structured theme objects.

    Args:
        summaries_json: JSON string of the article summaries array.
            Each element should contain ``Title``, ``Summary``,
            ``BusinessRelevance``, and ``Order`` fields.
        session: Optional async database session.  When provided,
            learning data is fetched from the ``notes`` table.  When
            ``None``, no feedback is injected (useful for testing or
            first run).
        model: Override model identifier.

    Returns:
        A :class:`ThemeGenerationResult` with all parsed themes,
        the recommendation text, the raw LLM output, and the model used.
    """
    # Step 1: Fetch recent feedback
    aggregated = None
    if session is not None:
        feedback_rows = await get_recent_notes(
            session,
            "user_newsletter_themes",
        )
        aggregated = aggregate_feedback(feedback_rows)

    # Step 2-3: Build prompt and call LLM
    raw_output, model_used = await call_theme_llm(
        summaries_json=summaries_json,
        aggregated_feedback=aggregated,
        model=model,
    )

    # Step 4: Parse into structured themes
    themes = parse_theme_output(raw_output)

    # Extract recommendation from the split result
    split_result = split_themes(raw_output)

    return ThemeGenerationResult(
        themes=themes,
        recommendation=split_result.recommendation,
        raw_llm_output=raw_output,
        model=model_used,
    )
