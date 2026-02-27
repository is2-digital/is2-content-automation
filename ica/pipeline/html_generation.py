"""HTML generation pipeline — Step 5 of the newsletter pipeline.

Ports the n8n ``html_generator_subworkflow.json``:

1. Fetch markdown content from Google Docs (``markdown_doc_id`` from Step 4).
2. Call LLM (``anthropic/claude-sonnet-4.5``) with the HTML generation prompt
   to populate an email-ready HTML template from the markdown.
3. Create a Google Doc with the generated HTML.
4. Share preview in Slack for approval.

**Feedback loop**: feedback → scoped regeneration (only mentioned sections) →
learning data extraction → store in ``notes`` table
(``type='user_htmlgenerator'``).

Output: Google Doc document ID (``html_doc_id``).

See APPLICATION.md Section 2.6, PRD Section 3.5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose, get_model
from ica.db.crud import add_note, get_recent_notes
from ica.db.models import Note
from ica.prompts.html_generation import (
    build_html_generation_prompt,
    build_html_regeneration_prompt,
)
from ica.prompts.learning_data_extraction import build_learning_data_extraction_prompt
from ica.utils.output_router import (
    UserChoice,
    conditional_output_router,
    normalize_switch_value,
)

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class SlackHtmlReview(Protocol):
    """Slack interactions for the HTML review loop.

    Ports three n8n Slack nodes:

    - "Share Generated HTML" → :meth:`send_channel_message`
    - "Next steps selection" → :meth:`send_and_wait_form`
    - "Feedback form" → :meth:`send_and_wait_freetext`
    """

    async def send_channel_message(
        self,
        text: str,
        *,
        blocks: list[dict[str, object]] | None = None,
    ) -> None:
        """Send a message to the Slack channel (``chat.postMessage``)."""
        ...

    async def send_and_wait_form(
        self,
        message: str,
        *,
        form_fields: list[dict[str, object]],
        button_label: str = "Proceed to Next Steps",
        form_title: str = "Proceed to next step",
        form_description: str = "",
    ) -> dict[str, str]:
        """Send a form and wait for user response."""
        ...

    async def send_and_wait_freetext(
        self,
        message: str,
        *,
        button_label: str = "Add feedback",
        form_title: str = "Feedback Form",
        form_description: str = "",
    ) -> str:
        """Send a free-text form and wait for user response."""
        ...


class GoogleDocsService(Protocol):
    """Protocol for Google Docs read/write operations."""

    async def create_document(self, title: str) -> str:
        """Create a new Google Doc and return its document ID."""
        ...

    async def insert_content(self, document_id: str, text: str) -> None:
        """Insert text content into the Google Doc."""
        ...

    async def get_content(self, document_id: str) -> str:
        """Fetch the plain-text content of a Google Doc."""
        ...


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HtmlGenerationResult:
    """Final output of the HTML generation pipeline step.

    Attributes:
        html: The approved HTML newsletter text.
        html_doc_id: Google Doc document ID containing the HTML.
        doc_url: Google Docs URL for the created document.
        model: The LLM model identifier used for generation.
    """

    html: str
    html_doc_id: str
    doc_url: str
    model: str


# ---------------------------------------------------------------------------
# Constants — Slack form config
# ---------------------------------------------------------------------------

HTML_VALID_MARKER = "<!DOCTYPE html>"
"""Expected marker in generated HTML; used for content validity check."""

NEXT_STEPS_FIELD_LABEL = "Ready to proceed to next step ?"
NEXT_STEPS_OPTIONS: list[str] = ["Yes", "Provide Feedback"]
NEXT_STEPS_BUTTON_LABEL = "Proceed to Next Steps"
NEXT_STEPS_FORM_TITLE = "Proceed to next step"
NEXT_STEPS_FORM_DESCRIPTION = "HTML newsletter has been generated."
NEXT_STEPS_MESSAGE = (
    "*Newsletter HTML has been generated.* Review the Google Doc and click to proceed when done."
)

FEEDBACK_MESSAGE = "*Please provide feedback to improve generated HTML content*"
FEEDBACK_BUTTON_LABEL = "Add feedback"
FEEDBACK_FORM_TITLE = "Feedback Form"
FEEDBACK_FORM_DESCRIPTION = "Please provide feedback to improve generated HTML content"

GOOGLE_DOC_TITLE = "Newsletter HTML"
"""Default title for the Google Doc created for HTML output."""

APPROVAL_MESSAGE = "*Newsletter HTML Approved, moving to next steps*"
"""Slack notification sent when user approves the HTML."""


# ---------------------------------------------------------------------------
# Feedback aggregation
# ---------------------------------------------------------------------------


def aggregate_feedback(notes: list[Note]) -> str | None:
    """Convert Note rows into a bullet-point string for prompt injection.

    Mirrors the n8n "Aggregate Feedback" Code node pattern.

    Args:
        notes: Recent feedback rows from the ``notes`` table.

    Returns:
        A newline-separated bullet list, or ``None`` if no feedback exists.
    """
    if not notes:
        return None
    lines = [f"\u2022 {row.feedback_text}" for row in notes if row.feedback_text]
    return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# LLM calls — generation
# ---------------------------------------------------------------------------


async def call_html_llm(
    markdown_content: str,
    html_template: str,
    newsletter_date: str,
    *,
    aggregated_feedback: str | None = None,
    model: str | None = None,
) -> str:
    """Call the LLM to generate the HTML newsletter from markdown + template.

    Args:
        markdown_content: The approved newsletter markdown content.
        html_template: The HTML email template to populate.
        newsletter_date: The newsletter publication date string.
        aggregated_feedback: Optional aggregated learning data.
        model: Override model identifier.

    Returns:
        The raw LLM response text (generated HTML).

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.HTML)
    system_prompt, user_prompt = build_html_generation_prompt(
        markdown_content=markdown_content,
        html_template=html_template,
        newsletter_date=newsletter_date,
        aggregated_feedback=aggregated_feedback,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content: str | None = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("LLM returned an empty response for HTML generation")

    return content.strip()


async def call_html_regeneration(
    previous_html: str,
    markdown_content: str,
    html_template: str,
    user_feedback: str,
    newsletter_date: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM for scoped HTML regeneration based on user feedback.

    Only modifies sections explicitly mentioned in the feedback,
    leaving all other sections unchanged.

    Args:
        previous_html: The previously generated HTML document.
        markdown_content: The markdown content (reference only).
        html_template: The HTML template (structural reference).
        user_feedback: The user's feedback text.
        newsletter_date: The newsletter publication date string.
        model: Override model identifier.

    Returns:
        The regenerated HTML text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.HTML_REGENERATION)
    system_prompt, user_prompt = build_html_regeneration_prompt(
        previous_html=previous_html,
        markdown_content=markdown_content,
        html_template=html_template,
        user_feedback=user_feedback,
        newsletter_date=newsletter_date,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content: str | None = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("LLM returned an empty response for HTML regeneration")

    return content.strip()


# ---------------------------------------------------------------------------
# Learning data extraction
# ---------------------------------------------------------------------------


async def extract_html_learning_data(
    feedback: str,
    input_text: str,
    model_output: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to extract learning data from user feedback.

    Ports the n8n "Learning data extractor" node in the HTML
    generator subworkflow.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        input_text: The current HTML content (as context).
        model_output: The regenerated HTML text.
        model: Override model identifier.

    Returns:
        Extracted ``learning_feedback`` text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.HTML_LEARNING_DATA)
    system_prompt, user_prompt = build_learning_data_extraction_prompt(
        feedback=feedback,
        input_text=input_text,
        model_output=model_output,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content: str | None = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("LLM returned an empty response for learning data extraction")

    text = content.strip()

    # Try to parse JSON and extract the learning_feedback field.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "learning_feedback" in data:
            return str(data["learning_feedback"])
    except (json.JSONDecodeError, TypeError):
        pass

    return text


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------


def build_next_steps_form() -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for next-steps selection.

    Presents a required dropdown with options: Yes / Provide Feedback.

    Returns:
        JSON-serialisable form field list for Slack sendAndWait.
    """
    return [
        {
            "fieldLabel": NEXT_STEPS_FIELD_LABEL,
            "fieldType": "dropdown",
            "fieldOptions": {
                "values": [{"option": opt} for opt in NEXT_STEPS_OPTIONS],
            },
            "requiredField": True,
        },
    ]


def parse_next_steps_response(response: dict[str, str]) -> UserChoice | None:
    """Parse the user's selection from the next-steps form response.

    Args:
        response: The raw Slack form response dict mapping field labels
            to selected values.

    Returns:
        The user's choice, or ``None`` if the value is unrecognized.
    """
    value = response.get(NEXT_STEPS_FIELD_LABEL, "")
    return normalize_switch_value(value)


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


async def store_html_feedback(
    session: AsyncSession,
    feedback_text: str,
    *,
    newsletter_id: str | None = None,
) -> None:
    """Store processed learning feedback in the ``notes`` table.

    Inserts with ``type='user_htmlgenerator'``.

    Args:
        session: Active async database session.
        feedback_text: The processed learning note.
        newsletter_id: Optional newsletter association.
    """
    await add_note(
        session,
        "user_htmlgenerator",
        feedback_text,
        newsletter_id=newsletter_id,
    )


# ---------------------------------------------------------------------------
# Google Doc creation
# ---------------------------------------------------------------------------


async def create_html_doc(
    docs: GoogleDocsService,
    html: str,
    *,
    title: str = GOOGLE_DOC_TITLE,
) -> tuple[str, str]:
    """Create a Google Doc with the generated HTML content.

    Args:
        docs: Google Docs service.
        html: The generated HTML newsletter.
        title: Document title.

    Returns:
        ``(doc_id, doc_url)`` tuple.
    """
    doc_id = await docs.create_document(title)
    await docs.insert_content(doc_id, html)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return doc_id, doc_url


# ---------------------------------------------------------------------------
# Main orchestration — generation, output sharing, and feedback loop
# ---------------------------------------------------------------------------


async def run_html_generation(
    markdown_content: str,
    html_template: str,
    newsletter_date: str,
    *,
    slack: SlackHtmlReview,
    docs: GoogleDocsService | None = None,
    session: AsyncSession | None = None,
    newsletter_id: str | None = None,
) -> HtmlGenerationResult:
    """Run the full HTML generation pipeline step.

    Orchestrates PRD Section 3.5:

    1. Fetch learning data (last 40 entries, ``type='user_htmlgenerator'``).
    2. Aggregate feedback into prompt-injectable string.
    3. Call LLM to generate HTML from markdown + template.
    4. Create Google Doc with HTML output.
    5. Share preview link in Slack.
    6. Send next-steps form (Yes / Provide Feedback).
    7. **Yes** → notify approval, return result.
    8. **Provide Feedback** → collect feedback → scoped regeneration →
       extract learning data → store in ``notes`` → update doc → re-share.

    Args:
        markdown_content: The approved newsletter markdown content
            (fetched from Google Docs in the caller).
        html_template: The HTML email template to populate.
        newsletter_date: The newsletter publication date string.
        slack: Slack interaction handler.
        docs: Google Docs service for creating/updating the output document.
        session: Optional async database session for storing learning data.
        newsletter_id: Optional newsletter association.

    Returns:
        :class:`HtmlGenerationResult` with the final HTML, doc ID,
        URL, and model identifier.
    """
    model_id = get_model(LLMPurpose.HTML)
    form_fields = build_next_steps_form()

    # Step 1: Fetch learning data
    aggregated_feedback: str | None = None
    if session is not None:
        notes = await get_recent_notes(session, "user_htmlgenerator")
        aggregated_feedback = aggregate_feedback(notes)

    # Step 2: Generate HTML via LLM
    html = await call_html_llm(
        markdown_content,
        html_template,
        newsletter_date,
        aggregated_feedback=aggregated_feedback,
    )

    # Step 3: Create Google Doc with HTML
    doc_id = ""
    doc_url = ""
    if docs is not None:
        doc_id, doc_url = await create_html_doc(docs, html)

    # Step 4: Enter review loop
    original_html = html
    regenerated_html: str | None = None
    switch_value: str | None = None

    while True:
        # Route content via conditional output router
        route = conditional_output_router(
            switch_value=switch_value,
            original_text=original_html,
            re_generated_text=regenerated_html,
            content_valid=(
                HTML_VALID_MARKER.lower() in regenerated_html.lower()
                if regenerated_html is not None
                else True
            ),
        )
        current_html = route.text

        # Share Google Doc link in Slack
        share_message = NEXT_STEPS_MESSAGE
        if doc_url:
            share_message = (
                f"*Newsletter HTML has been generated.* "
                f"Review here and click to proceed when done: {doc_url}"
            )
        await slack.send_channel_message(share_message)

        # Send next-steps form and wait for response
        response = await slack.send_and_wait_form(
            share_message,
            form_fields=form_fields,
            button_label=NEXT_STEPS_BUTTON_LABEL,
            form_title=NEXT_STEPS_FORM_TITLE,
            form_description=NEXT_STEPS_FORM_DESCRIPTION,
        )

        choice = parse_next_steps_response(response)
        switch_value = response.get(NEXT_STEPS_FIELD_LABEL, "")

        if choice == UserChoice.YES:
            # Notify approval
            await slack.send_channel_message(APPROVAL_MESSAGE)

            return HtmlGenerationResult(
                html=current_html,
                html_doc_id=doc_id,
                doc_url=doc_url,
                model=model_id,
            )

        if choice == UserChoice.PROVIDE_FEEDBACK:
            # Collect feedback
            user_feedback = await slack.send_and_wait_freetext(
                FEEDBACK_MESSAGE,
                button_label=FEEDBACK_BUTTON_LABEL,
                form_title=FEEDBACK_FORM_TITLE,
                form_description=FEEDBACK_FORM_DESCRIPTION,
            )

            # Scoped regeneration via LLM
            regenerated_html = await call_html_regeneration(
                previous_html=current_html,
                markdown_content=markdown_content,
                html_template=html_template,
                user_feedback=user_feedback,
                newsletter_date=newsletter_date,
            )

            # Extract learning data
            learning_note = await extract_html_learning_data(
                feedback=user_feedback,
                input_text=current_html,
                model_output=regenerated_html,
            )

            # Store learning data
            if session is not None:
                await store_html_feedback(
                    session,
                    learning_note,
                    newsletter_id=newsletter_id,
                )

            # Update Google Doc with regenerated HTML
            if docs is not None and doc_id:
                await docs.insert_content(doc_id, regenerated_html)

            # Loop back — regenerated_html will be picked up by router
            continue

        # Unknown choice — loop back with original
        regenerated_html = None
