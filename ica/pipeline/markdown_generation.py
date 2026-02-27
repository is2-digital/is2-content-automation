"""Markdown generation pipeline — Step 4 of the newsletter pipeline.

Ports the n8n ``markdown_generator_subworkflow.json``:

1. Extract ``formatted_theme`` from pipeline context (Step 3 output).
2. Fetch learning data (last 40 entries, ``type='user_markdowngenerator'``).
3. Aggregate feedback into prompt-injectable string.
4. Call LLM with the ~4 000-word markdown generation prompt.

**Three-layer validation** (up to 3 attempts):
- Layer 1: Character count validation (code-based) via
  :mod:`ica.validators.character_count`.
- Layer 2: Structural validation (LLM, ``openai/gpt-4.1``) via
  :mod:`ica.prompts.markdown_structural_validation`.
- Layer 3: Voice validation (LLM, ``openai/gpt-4.1``) via
  :mod:`ica.prompts.markdown_voice_validation`.
- Errors merged; fed back to LLM if invalid and under 3 attempts.
  After 3 attempts the output is force-accepted.

**User review**: Share in Slack, collect approval/feedback.  On approval,
create Google Doc with markdown, share link.  Store feedback in ``notes``
table (``type='user_markdowngenerator'``).

Output: Google Doc document ID (``markdown_doc_id``).

See APPLICATION.md Section 2.5, PRD Section 3.4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose, get_model
from ica.db.crud import add_note
from ica.db.models import Note
from ica.errors import ValidationLoopCounter
from ica.prompts.learning_data_extraction import build_learning_data_extraction_prompt
from ica.prompts.markdown_generation import (
    build_markdown_generation_prompt,
    build_markdown_regeneration_prompt,
)
from ica.prompts.markdown_structural_validation import (
    build_structural_validation_prompt,
)
from ica.prompts.markdown_voice_validation import build_voice_validation_prompt
from ica.utils.output_router import (
    UserChoice,
    conditional_output_router,
    normalize_switch_value,
)
from ica.validators.character_count import (
    CharacterCountError,
    validate_character_counts,
)

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class SlackMarkdownReview(Protocol):
    """Slack interactions for the markdown review loop.

    Ports three n8n Slack nodes:

    - "Share markdown" → :meth:`send_channel_message`
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


class GoogleDocsWriter(Protocol):
    """Protocol for creating and populating a Google Doc."""

    async def create_document(self, title: str) -> str:
        """Create a new Google Doc and return its document ID."""
        ...

    async def insert_content(self, document_id: str, text: str) -> None:
        """Insert text content into the Google Doc."""
        ...


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkdownGenerationResult:
    """Final output of the markdown generation pipeline step.

    Attributes:
        markdown: The approved newsletter markdown text.
        markdown_doc_id: Google Doc document ID containing the markdown.
        doc_url: Google Docs URL for the created document.
        model: The LLM model identifier used for generation.
    """

    markdown: str
    markdown_doc_id: str
    doc_url: str
    model: str


@dataclass(frozen=True)
class ValidationResult:
    """Combined result from all three validation layers.

    Attributes:
        is_valid: ``True`` when no errors were found.
        errors: Merged error list from all three layers.
        char_errors_json: JSON string of character-count errors (for
            injection into the structural validation prompt).
    """

    is_valid: bool
    errors: list[str]
    char_errors_json: str


# ---------------------------------------------------------------------------
# Constants — Slack form config
# ---------------------------------------------------------------------------

MARKDOWN_REVIEW_HEADER = "# *INTRODUCTION*"
"""Expected header in generated markdown; used for content validity check."""

NEXT_STEPS_FIELD_LABEL = "Ready to proceed to next step ?"
NEXT_STEPS_OPTIONS: list[str] = ["Yes", "Provide Feedback", "Restart Chat"]
NEXT_STEPS_BUTTON_LABEL = "Proceed to Next Steps"
NEXT_STEPS_FORM_TITLE = "Proceed to next step"
NEXT_STEPS_FORM_DESCRIPTION = "Markdown newsletter has been generated and validated."
NEXT_STEPS_MESSAGE = "*Newsletter markdown has been generated and validated.*"

FEEDBACK_MESSAGE = "*Please provide feedback to improve the newsletter markdown*"
FEEDBACK_BUTTON_LABEL = "Add feedback"
FEEDBACK_FORM_TITLE = "Feedback Form"
FEEDBACK_FORM_DESCRIPTION = "Please provide feedback to improve newsletter markdown"

GOOGLE_DOC_TITLE = "Newsletter Markdown"
"""Default title for the Google Doc created on approval."""


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


async def call_markdown_llm(
    formatted_theme: str,
    *,
    aggregated_feedback: str | None = None,
    previous_markdown: str = "",
    validator_errors: str = "",
    model: str | None = None,
) -> str:
    """Call the LLM to generate (or regenerate) the newsletter markdown.

    Args:
        formatted_theme: JSON string of the formatted theme data.
        aggregated_feedback: Optional aggregated learning data.
        previous_markdown: Previous output (for validator-driven regen).
        validator_errors: Merged validator error string (for regen).
        model: Override model identifier.

    Returns:
        The raw LLM response text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.MARKDOWN)
    system_prompt, user_prompt = build_markdown_generation_prompt(
        formatted_theme=formatted_theme,
        aggregated_feedback=aggregated_feedback or "",
        previous_markdown=previous_markdown,
        validator_errors=validator_errors,
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
        raise RuntimeError("LLM returned an empty response for markdown generation")

    return content.strip()


# ---------------------------------------------------------------------------
# Three-layer validation
# ---------------------------------------------------------------------------


def format_char_errors_json(errors: list[CharacterCountError]) -> str:
    """Format character-count errors as JSON for downstream LLM prompts.

    Args:
        errors: List of character-count errors from Layer 1.

    Returns:
        JSON string array of formatted error strings.
    """
    return json.dumps([e.format() for e in errors])


async def run_structural_validation(
    markdown: str,
    char_errors_json: str,
    *,
    model: str | None = None,
) -> tuple[bool, list[str]]:
    """Layer 2 — structural validation via LLM.

    Calls the structural validation LLM which checks non-numeric rules
    and merges its findings with the provided character-count errors.

    Args:
        markdown: The newsletter markdown to validate.
        char_errors_json: JSON string of character-count errors.
        model: Override model identifier.

    Returns:
        ``(is_valid, errors)`` tuple.  Errors include both character-count
        and structural findings.
    """
    model_id = model or get_model(LLMPurpose.MARKDOWN_VALIDATOR)
    system_prompt, user_prompt = build_structural_validation_prompt(
        markdown_content=markdown,
        char_errors=char_errors_json,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content: str | None = response.choices[0].message.content
    return _parse_validation_response(content or "")


async def run_voice_validation(
    markdown: str,
    prior_errors_json: str,
    *,
    model: str | None = None,
) -> tuple[bool, list[str]]:
    """Layer 3 — voice validation via LLM.

    Evaluates voice, tone, and editorial integrity, then merges any
    VOICE-prefixed errors with prior validator errors.

    Args:
        markdown: The newsletter markdown to validate.
        prior_errors_json: JSON string of prior validator output
            (structural + character-count errors).
        model: Override model identifier.

    Returns:
        ``(is_valid, errors)`` tuple.  Errors include all prior errors
        plus any new VOICE errors.
    """
    model_id = model or get_model(LLMPurpose.MARKDOWN_VALIDATOR)
    system_prompt, user_prompt = build_voice_validation_prompt(
        markdown_content=markdown,
        prior_errors_json=prior_errors_json,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content: str | None = response.choices[0].message.content
    return _parse_validation_response(content or "")


def _parse_validation_response(raw: str) -> tuple[bool, list[str]]:
    """Parse a validator LLM response into (is_valid, errors).

    Expects JSON: ``{ "output": { "isValid": bool, "errors": [...] } }``

    Falls back gracefully if the response is malformed.

    Args:
        raw: Raw LLM response text.

    Returns:
        ``(is_valid, errors)`` tuple.
    """
    text = raw.strip()
    if not text:
        return True, []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        import re

        match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if match:
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                return False, [f"Unparseable validator response: {text[:200]}"]
        else:
            return False, [f"Unparseable validator response: {text[:200]}"]

    # Navigate { "output": { "isValid": ..., "errors": [...] } }
    if isinstance(data, dict):
        output = data.get("output", data)
        if isinstance(output, dict):
            is_valid = bool(output.get("isValid", True))
            errors = output.get("errors", [])
            if isinstance(errors, list):
                return is_valid, [str(e) for e in errors]
            return is_valid, []

    return True, []


async def run_three_layer_validation(
    markdown: str,
    *,
    validator_model: str | None = None,
) -> ValidationResult:
    """Run the complete three-layer validation pipeline.

    1. Character count validation (code-based).
    2. Structural validation (LLM).
    3. Voice validation (LLM).

    Errors from all layers are merged into a single list.

    Args:
        markdown: The newsletter markdown to validate.
        validator_model: Override model for LLM validators.

    Returns:
        :class:`ValidationResult` with combined errors from all layers.
    """
    # Layer 1: Character count (code-based)
    char_errors = validate_character_counts(markdown)
    char_errors_json = format_char_errors_json(char_errors)

    # Layer 2: Structural validation (LLM)
    struct_valid, struct_errors = await run_structural_validation(
        markdown,
        char_errors_json,
        model=validator_model,
    )

    # Build prior errors JSON for voice validator
    prior_json = json.dumps(
        {
            "output": {
                "isValid": struct_valid and len(char_errors) == 0,
                "errors": struct_errors,
            }
        }
    )

    # Layer 3: Voice validation (LLM)
    voice_valid, all_errors = await run_voice_validation(
        markdown,
        prior_json,
        model=validator_model,
    )

    # Voice validator merges all prior errors, so all_errors is the final set
    is_valid = voice_valid and len(all_errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        errors=all_errors,
        char_errors_json=char_errors_json,
    )


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------


async def generate_with_validation(
    formatted_theme: str,
    *,
    aggregated_feedback: str | None = None,
    generation_model: str | None = None,
    validator_model: str | None = None,
    max_attempts: int = 3,
) -> str:
    """Generate markdown with up to *max_attempts* validation retries.

    1. Call LLM to generate markdown.
    2. Run three-layer validation.
    3. If valid or attempts exhausted → return markdown.
    4. If invalid → feed errors back to LLM and repeat.

    Args:
        formatted_theme: JSON string of the formatted theme data.
        aggregated_feedback: Optional aggregated learning data.
        generation_model: Override model for generation.
        validator_model: Override model for validation.
        max_attempts: Maximum validation attempts (default 3).

    Returns:
        The final markdown text (validated or force-accepted).
    """
    counter = ValidationLoopCounter(max_attempts=max_attempts)

    # First generation
    markdown = await call_markdown_llm(
        formatted_theme,
        aggregated_feedback=aggregated_feedback,
        model=generation_model,
    )

    while True:
        # Validate
        result = await run_three_layer_validation(
            markdown,
            validator_model=validator_model,
        )

        if result.is_valid or counter.exhausted:
            return markdown

        counter.increment()

        # Regenerate with errors
        errors_str = "\n".join(result.errors)
        markdown = await call_markdown_llm(
            formatted_theme,
            aggregated_feedback=aggregated_feedback,
            previous_markdown=markdown,
            validator_errors=errors_str,
            model=generation_model,
        )


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------


def build_next_steps_form() -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for next-steps selection.

    Presents a required dropdown with options: Yes / Provide Feedback /
    Restart Chat.

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
# LLM calls — user feedback regeneration and learning data extraction
# ---------------------------------------------------------------------------


async def call_user_feedback_regeneration(
    original_markdown: str,
    user_feedback: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to regenerate markdown based on user feedback.

    Ports the n8n "Re-Generate Data using LLM" node for user-driven
    feedback (distinct from the validator-driven regeneration loop).

    Args:
        original_markdown: The current newsletter markdown.
        user_feedback: The user's free-text feedback from Slack.
        model: Override model identifier.

    Returns:
        The regenerated markdown text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.MARKDOWN_REGENERATION)
    system_prompt, user_prompt = build_markdown_regeneration_prompt(
        original_markdown=original_markdown,
        user_feedback=user_feedback,
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
        raise RuntimeError("LLM returned an empty response for markdown regeneration")

    return content.strip()


async def extract_markdown_learning_data(
    feedback: str,
    input_text: str,
    model_output: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to extract learning data from user feedback.

    Ports the n8n "Learning data extractor" node in the markdown
    generator subworkflow.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        input_text: The formatted theme input (or current markdown).
        model_output: The regenerated markdown text.
        model: Override model identifier.

    Returns:
        Extracted ``learning_feedback`` text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.MARKDOWN_LEARNING_DATA)
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
# Database operations
# ---------------------------------------------------------------------------


async def store_markdown_feedback(
    session: AsyncSession,
    feedback_text: str,
    *,
    newsletter_id: str | None = None,
) -> None:
    """Store processed learning feedback in the ``notes`` table.

    Inserts with ``type='user_markdowngenerator'``.

    Args:
        session: Active async database session.
        feedback_text: The processed learning note.
        newsletter_id: Optional newsletter association.
    """
    await add_note(
        session,
        "user_markdowngenerator",
        feedback_text,
        newsletter_id=newsletter_id,
    )


# ---------------------------------------------------------------------------
# Google Doc creation
# ---------------------------------------------------------------------------


async def create_markdown_doc(
    docs: GoogleDocsWriter,
    markdown: str,
    *,
    title: str = GOOGLE_DOC_TITLE,
) -> tuple[str, str]:
    """Create a Google Doc with the approved markdown content.

    Args:
        docs: Google Docs writer service.
        markdown: The approved newsletter markdown.
        title: Document title.

    Returns:
        ``(doc_id, doc_url)`` tuple.
    """
    doc_id = await docs.create_document(title)
    await docs.insert_content(doc_id, markdown)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return doc_id, doc_url


# ---------------------------------------------------------------------------
# Main orchestration — output sharing and feedback loop
# ---------------------------------------------------------------------------


async def run_markdown_review(
    markdown: str,
    formatted_theme: str,
    *,
    slack: SlackMarkdownReview,
    docs: GoogleDocsWriter | None = None,
    session: AsyncSession | None = None,
    newsletter_id: str | None = None,
) -> MarkdownGenerationResult:
    """Run the markdown output sharing and user feedback loop.

    Orchestrates PRD Section 3.4 user review steps:

    1. Share generated markdown in Slack.
    2. Send next-steps form (Yes / Provide Feedback / Restart Chat).
    3. **Yes** → create Google Doc with markdown, share link, return.
    4. **Provide Feedback** → collect feedback → regenerate via LLM →
       extract learning data → store in ``notes`` → re-share (loop).
    5. **Restart Chat** → reset to original markdown → re-share (loop).

    Args:
        markdown: The validated markdown from :func:`generate_with_validation`.
        formatted_theme: The formatted theme JSON string (for context).
        slack: Slack interaction handler.
        docs: Google Docs writer for creating the output document.
        session: Optional async database session for storing learning data.
        newsletter_id: Optional newsletter association.

    Returns:
        :class:`MarkdownGenerationResult` with the final markdown, doc ID,
        URL, and model identifier.
    """
    model_id = get_model(LLMPurpose.MARKDOWN)
    form_fields = build_next_steps_form()

    original_markdown = markdown
    regenerated_markdown: str | None = None
    switch_value: str | None = None

    while True:
        # Step 1: Route content via conditional output router
        route = conditional_output_router(
            switch_value=switch_value,
            original_text=original_markdown,
            re_generated_text=regenerated_markdown,
            content_valid=(
                MARKDOWN_REVIEW_HEADER in regenerated_markdown
                if regenerated_markdown is not None
                else True
            ),
        )
        current_markdown = route.text

        # Step 2: Share in Slack channel
        await slack.send_channel_message(current_markdown)

        # Step 3: Send next-steps form and wait for response
        response = await slack.send_and_wait_form(
            NEXT_STEPS_MESSAGE,
            form_fields=form_fields,
            button_label=NEXT_STEPS_BUTTON_LABEL,
            form_title=NEXT_STEPS_FORM_TITLE,
            form_description=NEXT_STEPS_FORM_DESCRIPTION,
        )

        choice = parse_next_steps_response(response)
        switch_value = response.get(NEXT_STEPS_FIELD_LABEL, "")

        # Step 4: Route based on user selection
        if choice == UserChoice.YES:
            # Create Google Doc and return
            doc_id = ""
            doc_url = ""
            if docs is not None:
                doc_id, doc_url = await create_markdown_doc(
                    docs,
                    current_markdown,
                )
                # Notify user with doc link
                await slack.send_channel_message(
                    f"*Newsletter markdown saved to Google Docs:*\n{doc_url}"
                )

            return MarkdownGenerationResult(
                markdown=current_markdown,
                markdown_doc_id=doc_id,
                doc_url=doc_url,
                model=model_id,
            )

        if choice == UserChoice.PROVIDE_FEEDBACK:
            # Step 5a: Collect feedback
            user_feedback = await slack.send_and_wait_freetext(
                FEEDBACK_MESSAGE,
                button_label=FEEDBACK_BUTTON_LABEL,
                form_title=FEEDBACK_FORM_TITLE,
                form_description=FEEDBACK_FORM_DESCRIPTION,
            )

            # Step 5b: Regenerate via LLM
            regenerated_markdown = await call_user_feedback_regeneration(
                original_markdown=current_markdown,
                user_feedback=user_feedback,
            )

            # Step 5c: Extract learning data
            learning_note = await extract_markdown_learning_data(
                feedback=user_feedback,
                input_text=formatted_theme,
                model_output=regenerated_markdown,
            )

            # Step 5d: Store learning data
            if session is not None:
                await store_markdown_feedback(
                    session,
                    learning_note,
                    newsletter_id=newsletter_id,
                )

            # Loop back — regenerated_markdown will be picked up by router
            continue

        # Restart Chat or unrecognized — reset and loop
        regenerated_markdown = None
