"""Theme Selection & Approval — second half of pipeline Step 3.

Receives :class:`ThemeGenerationResult` from :func:`generate_themes`,
formats themes for Slack display, handles the interactive selection and
approval flows, runs freshness check, and saves the approved theme to
the database.

Flow:
1. Format themes for Slack display (Block Kit).
2. Build a selection form (radio buttons: each theme + "Add Feedback").
3. Parse the user's selection response.
4. If feedback → extract learning data via LLM, store in DB, return for
   theme regeneration.
5. If theme selected → run freshness check via LLM.
6. Format selected theme + freshness report for Slack.
7. Build approval form (Approve / Reset / Feedback).
8. Approve → upsert theme in ``themes``, output result.
9. Feedback → extract learning data, store, return for regeneration.
10. Reset → signal caller to regenerate from scratch.

See PRD Section 3.3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose
from ica.db.crud import add_note, upsert_theme
from ica.pipeline.theme_generation import GeneratedTheme, ThemeGenerationResult
from ica.prompts.freshness_check import build_freshness_check_prompt
from ica.prompts.learning_data_extraction import (
    build_learning_data_extraction_prompt,
)
from ica.services.llm import completion
from ica.utils.marker_parser import FormattedTheme

# ---------------------------------------------------------------------------
# Constants — Slack form field labels and option values
# ---------------------------------------------------------------------------

SELECTION_FIELD_LABEL = "Newsletter Theme or Feedback"
FEEDBACK_TEXTAREA_LABEL = "Editor Feedback for AI"
APPROVAL_FIELD_LABEL = "Approve or Feedback"

FEEDBACK_OPTION = "Add Feedback"
APPROVE_OPTION = "Approve articles and continue"
RESET_OPTION = "Reset Articles (Generate Themes Again)"
ADD_FEEDBACK_OPTION = "Add a feedback"

THEME_OPTION_PREFIX = "THEME: "


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ApprovalChoice(StrEnum):
    """Possible user selections from the final approval form."""

    APPROVE = "approve"
    RESET = "reset"
    FEEDBACK = "feedback"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeSelectionResult:
    """Output of the theme selection and approval flow.

    Attributes:
        theme_name: Name of the approved theme.
        theme_body: Raw text of the approved theme.
        theme_summary: Description/summary of the approved theme.
        formatted_theme: Parsed article assignments for downstream steps.
        freshness_report: LLM-generated freshness check result.
        newsletter_id: Newsletter association (if set during approval).
    """

    theme_name: str
    theme_body: str
    theme_summary: str | None
    formatted_theme: FormattedTheme
    freshness_report: str
    newsletter_id: str | None = None


# ---------------------------------------------------------------------------
# Slack formatting — themes overview
# ---------------------------------------------------------------------------


def format_theme_body(theme_body: str) -> str:
    """Convert a raw theme body with ``%XX_`` markers to Slack mrkdwn.

    Mirrors the n8n "Format output" Code node ``formatTheme()`` function.
    Strips URLs, rationales, and origins; replaces markers with readable
    Slack formatting.

    Args:
        theme_body: Raw theme body text with ``%XX_`` markers.

    Returns:
        Slack-formatted text suitable for display in a Block Kit section.
    """
    t = theme_body

    # Remove URL, RATIONALE, and ORIGIN lines entirely.
    t = re.sub(r"^%[A-Za-z0-9]{2}_URL[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%[A-Za-z0-9]{2}_RATIONALE[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%[A-Za-z0-9]{2}_ORIGIN[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)

    # Featured Article
    t = re.sub(r"^%FA_TITLE:?", "\u2022 *Featured Candidate:* ", t, flags=re.MULTILINE)
    t = re.sub(r"\n%FA_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%FA_CATEGORY:?", ") - ", t)
    t = re.sub(r"\nFEATURED ARTICLE:?", "", t)
    t = re.sub(r"\n%FA_WHY FEATURED:?", " - ", t)

    # Main Articles
    t = re.sub(r"^%M1_TITLE:?", "\u2022 *Main Candidate 1:* ", t, flags=re.MULTILINE)
    t = re.sub(r"\n%M1_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%M1_CATEGORY:?", ") - ", t)
    t = re.sub(r"^%M2_TITLE:?", "\u2022 *Main Candidate 2:* ", t, flags=re.MULTILINE)
    t = re.sub(r"\n%M2_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%M2_CATEGORY:?", ") - ", t)

    # Quick Hits
    t = re.sub(
        r"^%Q1_TITLE:?",
        "\n\u2022 *Quick Hits Candidates:* \n  \u2022",
        t,
        flags=re.MULTILINE,
    )
    t = re.sub(r"\n%Q1_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%Q1_CATEGORY:?", ") - ", t)
    t = re.sub(r"^%Q2_TITLE:?", "  \u2022", t, flags=re.MULTILINE)
    t = re.sub(r"\n%Q2_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%Q2_CATEGORY:?", ") - ", t)
    t = re.sub(r"^%Q3_TITLE:?", "  \u2022", t, flags=re.MULTILINE)
    t = re.sub(r"\n%Q3_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%Q3_CATEGORY:?", ") - ", t)

    # Industry Developments
    t = re.sub(
        r"^%I1_TITLE:?",
        "\n\u2022 *Industry Candidates:* \n  \u2022",
        t,
        flags=re.MULTILINE,
    )
    t = re.sub(r"\n%I1_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%I1_Major AI Player:?", ") - ", t)
    t = re.sub(r"^%I2_TITLE:?", "  \u2022", t, flags=re.MULTILINE)
    t = re.sub(r"\n%I2_SOURCE:?", "  (Source ", t)
    t = re.sub(r"\n%I2_Major AI Player:?", ") - ", t)

    # Requirements / verification lines — strip entirely.
    t = re.sub(r"REQUIREMENTS VERIFIED[^\r\n]*\r?\n?", "", t)
    t = re.sub(r"^%RV_Major AI player coverage:[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_Technical complexity:[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_Source mix:[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_2-2-2 Distribution Achieved:[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"Source mix:", "*Source mix:* ", t)

    # Catch-all: strip any remaining %XX_ prefixes.
    t = re.sub(r"%[A-Za-z0-9]{2}_", "", t, flags=re.IGNORECASE)

    # Theme header lines.
    t = re.sub(r"^THEME[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^Theme Description:?", "*Core Narrative:*", t, flags=re.MULTILINE)
    t = re.sub(r"^Articles that fit.?", "\n*Articles that fit:*", t, flags=re.MULTILINE)

    return t


def format_recommendation(text: str) -> str:
    """Format the recommendation text for Slack display.

    Mirrors the n8n "Format output" Code node ``formatRecommendation()``
    function.

    Args:
        text: Raw recommendation text from the LLM.

    Returns:
        Slack mrkdwn-formatted recommendation.
    """
    t = str(text) if text else ""
    t = t.replace("Rationale:", "*Rationale:*")
    t = re.sub(r"(RECOMMENDATION:\s*)([^\n]+)", r"\1*\2*", t)
    t = re.sub(r"(\d+\.\s*)(.+?)(?=:\s|- )", r"\1*\2*", t)
    t = re.sub(r"%[A-Za-z0-9]{2}_", "", t, flags=re.IGNORECASE)
    t = re.sub(r"%222_", "", t, flags=re.IGNORECASE)
    return t


def format_themes_slack_message(result: ThemeGenerationResult) -> str:
    """Build a Slack message displaying all generated themes.

    Mirrors the n8n "Format output" Code node.  Produces a flat
    mrkdwn message with all themes and the recommendation, separated
    by divider lines.

    Args:
        result: The complete theme generation result.

    Returns:
        Slack mrkdwn message text.
    """
    divider = (
        "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"
    )

    parts: list[str] = ["\n* Newsletter Text Themes: *\n"]

    for idx, theme in enumerate(result.themes, start=1):
        name = theme.theme_name or f"Theme {idx}"
        body = format_theme_body(theme.theme_body)
        parts.append(f"*THEME {idx}:* *{name}*\n\n\n{body}\n\n")

    if result.recommendation:
        parts.append(f"\n{format_recommendation(result.recommendation)}\n")

    return divider.join(parts)


# ---------------------------------------------------------------------------
# Slack formatting — selected theme detail view
# ---------------------------------------------------------------------------


def format_selected_theme_body(theme_body: str) -> str:
    """Format a selected theme body for the detailed Slack view.

    Mirrors the n8n "Format output - Selected Theme" Code node's
    ``formatTheme()`` — a more detailed view that labels each article
    field individually.

    Args:
        theme_body: Raw theme body text with ``%XX_`` markers.

    Returns:
        Detailed Slack mrkdwn text showing each article's fields.
    """
    t = theme_body

    # Remove header lines.
    t = re.sub(r"^THEME[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%[A-Za-z0-9]{2}_SOURCE[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^Theme Description:[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^Articles that fit.?", "", t, flags=re.MULTILINE)

    # Featured Article
    t = re.sub(r"\n\nFEATURED ARTICLE:", "*FEATURED ARTICLE:*", t)
    t = re.sub(r"%FA_TITLE:", "*\u2022 Title:*", t)
    t = re.sub(r"%FA_ORIGIN:", "*\u2022 Source:*", t)
    t = re.sub(r"%FA_CATEGORY:", "*\u2022 Category:*", t)
    t = re.sub(r"%FA_URL:", "*\u2022 URL:*", t)
    t = re.sub(r"%FA_WHY FEATURED:", "*\u2022 Why featured:*", t)

    # Main Articles
    t = re.sub(r"^%M1_TITLE:?", "\n\n*MAIN ARTICLE 1:*  \n*\u2022 Title:*", t, flags=re.MULTILINE)
    t = re.sub(r"%M1_CATEGORY:?", "*\u2022 Category:*", t)
    t = re.sub(r"%M1_ORIGIN:", "*\u2022 Source:*", t)
    t = re.sub(r"%M1_URL:", "*\u2022 URL:*", t)
    t = re.sub(r"%M1_RATIONALE:", "*\u2022 Rationale:*", t)

    t = re.sub(r"^%M2_TITLE:?", "\n\n*MAIN ARTICLE 2:*  \n*\u2022 Title:*", t, flags=re.MULTILINE)
    t = re.sub(r"%M2_CATEGORY:?", "*\u2022 Category:*", t)
    t = re.sub(r"%M2_ORIGIN:", "*\u2022 Source:*", t)
    t = re.sub(r"%M2_URL:", "*\u2022 URL:*", t)
    t = re.sub(r"%M2_RATIONALE:", "*\u2022 Rationale:*", t)

    # Quick Hits
    for q in ("Q1", "Q2", "Q3"):
        num = q[1]
        t = re.sub(
            rf"^%{q}_TITLE:?",
            f"\n\n*QUICK HIT ARTICLE {num}:*  \n*\u2022 Title:*",
            t,
            flags=re.MULTILINE,
        )
        t = re.sub(rf"%{q}_CATEGORY:?", "*\u2022 Category:*", t)
        t = re.sub(rf"%{q}_ORIGIN:", "*\u2022 Source:*", t)
        t = re.sub(rf"%{q}_URL:", "*\u2022 URL:*", t)

    # Industry Developments
    for i in ("I1", "I2"):
        num = i[1]
        t = re.sub(
            rf"^%{i}_TITLE:?",
            f"\n\n*INDUSTRY ARTICLE {num}: *  \n*\u2022 Title:*",
            t,
            flags=re.MULTILINE,
        )
        t = re.sub(rf"%{i}_CATEGORY:?", "*\u2022 Category:*", t)
        t = re.sub(rf"%{i}_ORIGIN:", "*\u2022 Source:*", t)
        t = re.sub(rf"%{i}_URL:", "*\u2022 URL:*", t)
        t = re.sub(rf"%{i}_Major AI Player:?", "*\u2022 Major AI Player:*", t)

    # Requirements / verification lines — strip.
    t = re.sub(r"^REQUIREMENTS VERIFIED:[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_Major AI player coverage:%[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_Technical complexity:%[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_Source mix:%[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^%RV_2-2-2 Distribution Achieved:%[^\r\n]*\r?\n?", "", t, flags=re.MULTILINE)
    t = re.sub(r"Source mix:", "*Source mix:* ", t)

    # Catch-all: strip remaining markers.
    t = re.sub(r"%[A-Za-z0-9]{2}_", "", t, flags=re.IGNORECASE)

    return t


def format_freshness_slack_message(
    theme_name: str,
    theme_body: str,
    freshness_report: str,
) -> str:
    """Build a Slack message showing the selected theme and freshness report.

    Mirrors the n8n "Format output - Selected Theme" Code node.

    Args:
        theme_name: Name of the selected theme.
        theme_body: Raw theme body text.
        freshness_report: LLM-generated freshness check result.

    Returns:
        Slack mrkdwn message text.
    """
    divider = (
        "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"
    )

    parts: list[str] = [
        "\n Selected theme: \n",
        (
            f"*FINAL ARTICLE SELECTIONS:*\n"
            f"*THEME:* {theme_name}\n\n"
            f"\n{format_selected_theme_body(theme_body)}\n\n"
        ),
        "\n *AI-Generated Editorial Freshness Report* \n",
        f"\n{freshness_report}\n",
    ]

    return divider.join(parts)


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------


def build_theme_selection_form(
    themes: list[GeneratedTheme],
) -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for theme selection.

    Creates a radio-button field with one option per theme (prefixed
    with ``THEME: ``) plus an "Add Feedback" option, and a textarea
    for editor feedback.

    Mirrors the n8n "Conditional output" Code node form builder.

    Args:
        themes: The generated themes from :func:`generate_themes`.

    Returns:
        A JSON-serialisable list of form field descriptors for
        Slack sendAndWait ``defineForm: "json"``.
    """
    options: list[dict[str, str]] = [
        {"option": f"{THEME_OPTION_PREFIX}{theme.theme_name or f'Theme {idx}'}"}
        for idx, theme in enumerate(themes, start=1)
    ]
    options.append({"option": FEEDBACK_OPTION})

    return [
        {
            "fieldLabel": SELECTION_FIELD_LABEL,
            "fieldType": "radio",
            "fieldOptions": {"values": options},
        },
        {
            "fieldLabel": FEEDBACK_TEXTAREA_LABEL,
            "fieldType": "textarea",
        },
    ]


def build_approval_form() -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for final theme approval.

    Options: Approve / Reset Articles / Add Feedback, plus a textarea.

    Mirrors the n8n "Approve or Submit Feedback" sendAndWait node.

    Returns:
        A JSON-serialisable list of form field descriptors.
    """
    return [
        {
            "fieldLabel": APPROVAL_FIELD_LABEL,
            "fieldType": "radio",
            "fieldOptions": {
                "values": [
                    {"option": APPROVE_OPTION},
                    {"option": RESET_OPTION},
                    {"option": ADD_FEEDBACK_OPTION},
                ],
            },
        },
        {
            "fieldLabel": FEEDBACK_TEXTAREA_LABEL,
            "fieldType": "textarea",
        },
    ]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def extract_selected_theme(
    selection_value: str,
    themes: list[GeneratedTheme],
) -> GeneratedTheme | None:
    """Match a Slack form selection to a :class:`GeneratedTheme`.

    The selection value is expected to be in the format
    ``"THEME: <theme_name>"`` as generated by :func:`build_theme_selection_form`.

    Matching uses case-insensitive comparison of the portion after
    the ``THEME: `` prefix against each theme's ``theme_name``.

    Args:
        selection_value: The raw value from the Slack form radio field.
        themes: The generated themes to match against.

    Returns:
        The matching :class:`GeneratedTheme`, or ``None`` if no match
        is found (e.g., user selected "Add Feedback").
    """
    if not selection_value:
        return None

    cleaned = selection_value.strip()

    # Check if the value starts with the theme prefix.
    upper = cleaned.upper()
    if not upper.startswith("THEME"):
        return None

    # Extract the theme name after "THEME: " or "THEME:" prefix.
    match = re.match(r"THEME\s*:\s*(.+)", cleaned, re.IGNORECASE)
    if not match:
        return None

    selected_name = match.group(1).strip()

    # Match against available themes (case-insensitive).
    for theme in themes:
        if theme.theme_name and theme.theme_name.strip().lower() == selected_name.lower():
            return theme

    return None


def is_feedback_selection(selection_value: str) -> bool:
    """Check whether the user selected "Add Feedback" on the selection form.

    Args:
        selection_value: The raw value from the Slack form radio field.

    Returns:
        ``True`` if the selection matches the feedback option.
    """
    if not selection_value:
        return False
    return selection_value.strip().lower() == FEEDBACK_OPTION.lower()


def parse_approval_choice(approval_value: str) -> ApprovalChoice:
    """Parse the user's selection from the approval form.

    Uses case-insensitive ``contains`` matching to mirror the n8n
    "Final Switch" node routing logic.

    Args:
        approval_value: The raw value from the Slack approval radio field.

    Returns:
        The corresponding :class:`ApprovalChoice`.

    Raises:
        ValueError: If the value does not match any known option.
    """
    if not approval_value:
        raise ValueError("Empty approval value")

    lower = approval_value.strip().lower()

    if "approve" in lower:
        return ApprovalChoice.APPROVE
    if "reset" in lower:
        return ApprovalChoice.RESET
    if "feedback" in lower:
        return ApprovalChoice.FEEDBACK

    raise ValueError(f"Unrecognized approval value: {approval_value!r}")


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


async def run_freshness_check(
    theme_body: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to check editorial freshness of a theme.

    Compares the theme against recent newsletters at
    is2digital.com/newsletters.

    Args:
        theme_body: The raw body text of the selected theme.
        model: Override model identifier. Defaults to
            ``get_model(LLMPurpose.THEME_FRESHNESS_CHECK)``.

    Returns:
        The LLM's freshness analysis text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    system_prompt, user_prompt = build_freshness_check_prompt(theme_body)

    result = await completion(
        purpose=LLMPurpose.THEME_FRESHNESS_CHECK,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        step="theme_freshness",
    )

    return result.text


async def extract_learning_data(
    feedback: str,
    input_text: str,
    model_output: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to convert raw feedback into a learning note.

    Mirrors the n8n "Learning data extractor" information-extraction
    node used across subworkflows.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        input_text: The input provided to the original LLM (e.g.,
            the summarized articles JSON).
        model_output: The LLM output the user is providing feedback on.
        model: Override model identifier. Defaults to
            ``get_model(LLMPurpose.THEME_LEARNING_DATA)``.

    Returns:
        The extracted ``learning_feedback`` text. If the LLM returns
        valid JSON with a ``learning_feedback`` key, that value is
        extracted; otherwise the raw response is returned.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    system_prompt, user_prompt = build_learning_data_extraction_prompt(
        feedback=feedback,
        input_text=input_text,
        model_output=model_output,
    )

    result = await completion(
        purpose=LLMPurpose.THEME_LEARNING_DATA,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        step="theme_learning_data",
    )

    text = result.text

    # Try to parse JSON and extract the learning_feedback field.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "learning_feedback" in data:
            return str(data["learning_feedback"])
    except (json.JSONDecodeError, TypeError):
        pass

    return text


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


async def save_approved_theme(
    session: AsyncSession,
    theme: GeneratedTheme,
    *,
    newsletter_id: str | None = None,
) -> None:
    """Save an approved theme to the ``themes`` table.

    Mirrors the n8n "Structure SQL Insert Query" + "Insert into table"
    nodes.  Uses upsert (ON CONFLICT DO UPDATE) to handle re-approvals.

    Args:
        session: Active async database session.
        theme: The approved theme to save.
        newsletter_id: Optional newsletter association.
    """
    await upsert_theme(
        session,
        theme=theme.theme_name or "",
        theme_body=theme.theme_body,
        theme_summary=theme.theme_description,
        newsletter_id=newsletter_id,
        approved=True,
    )


async def store_theme_feedback(
    session: AsyncSession,
    feedback_text: str,
    *,
    newsletter_id: str | None = None,
) -> None:
    """Store processed learning feedback in the database.

    Mirrors the n8n "Insert user feedback" Postgres node.

    Args:
        session: Active async database session.
        feedback_text: The processed learning note from
            :func:`extract_learning_data`.
        newsletter_id: Optional newsletter association.
    """
    await add_note(
        session,
        "user_newsletter_themes",
        feedback_text,
        newsletter_id=newsletter_id,
    )
