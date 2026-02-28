"""LinkedIn carousel generator pipeline — Step 6d of the newsletter pipeline (parallel).

Ports the n8n ``linkedin_carousel_generator_subworkflow.json``:

1. Send Slack approval to proceed.
2. Fetch HTML document content from Google Docs.
3. Call LLM (``anthropic/claude-sonnet-4.5``) with linkedin_carousel prompt
   for carousel slide generation (post copy + 10 slides).
4. **Character validation** (code-based, per slide body):
   - Slide body total: 265-315 characters
   - Parsed via ``*Body:*`` markers in the LLM output.
5. If validation fails, regenerate with error details (up to 2 attempts).
6. Share validated output in Slack for approval.
7. Feedback loop: Yes / Provide Feedback / Regenerate.
8. Create Google Doc with final content.
9. Share Google Doc link in Slack.

**No database writes** — matches the n8n workflow which has no Postgres nodes.

See APPLICATION.md Section 2.10, PRD Section 3.9.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from ica.config.llm_config import LLMPurpose, get_model
from ica.services.llm import completion
from ica.prompts.linkedin_carousel import (
    build_linkedin_carousel_prompt,
    build_linkedin_regeneration_prompt,
)

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class SlackLinkedInReview(Protocol):
    """Slack interactions for the LinkedIn carousel generator.

    Ports multiple n8n Slack nodes:

    - "User approval" → :meth:`send_and_wait` (initial proceed)
    - "Send a message" → :meth:`send_channel_message` (share content)
    - "Next steps" → :meth:`send_and_wait_form` (Yes/Regenerate/Feedback)
    - "Send message and wait for response" → :meth:`send_and_wait_freetext`
    """

    async def send_and_wait(
        self,
        channel: str,
        text: str,
        *,
        approve_label: str = "Yes",
    ) -> str:
        """Send an approval button and block until the user responds."""
        ...

    async def send_channel_message(
        self,
        text: str,
        *,
        blocks: list[dict[str, object]] | None = None,
    ) -> None:
        """Send a message to the Slack channel."""
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
class SlideError:
    """A character-count validation error for a single slide body.

    Matches the error format from the n8n "Code in JavaScript" validation node.
    """

    slide_body: str
    actual_characters: int
    required_range: str = "265-315"
    error_type: str = "CHARACTER_LIMIT_VIOLATION"
    severity: str = "ERROR"
    instruction: str = (
        "Rewrite the slide body to be 265-315 characters total "
        "while preserving meaning, tone, and structure."
    )

    def to_dict(self) -> dict[str, object]:
        """Serialize for injection into the LLM prompt."""
        return {
            "slide_body": self.slide_body,
            "type": self.error_type,
            "severity": self.severity,
            "actualCharacters": self.actual_characters,
            "requiredRange": self.required_range,
            "instruction": self.instruction,
        }


@dataclass(frozen=True)
class ValidationResult:
    """Result of slide body character validation.

    Attributes:
        annotated_output: The LLM output with character counts appended.
        errors: List of per-slide errors (empty if all pass).
    """

    annotated_output: str
    errors: list[SlideError]


@dataclass(frozen=True)
class LinkedInCarouselResult:
    """Final output of the LinkedIn carousel generator pipeline step.

    Attributes:
        doc_id: Google Doc document ID containing the final carousel content.
        doc_url: Google Docs URL for the created document.
        final_content: The final carousel text (post copy + slides).
        model: The LLM model identifier used for generation.
    """

    doc_id: str
    doc_url: str
    final_content: str
    model: str


# ---------------------------------------------------------------------------
# Constants — Slack messages and form config
# ---------------------------------------------------------------------------

SLACK_CHANNEL = "#n8n-is2"

APPROVAL_MESSAGE = (
    "*Fetched final HTML newsletter. Are we good to proceed to Linkedin Posts generation ?*"
)

# Next steps form
NEXT_STEPS_FIELD = "Proceed to Next steps"
NEXT_STEPS_OPTIONS: list[str] = ["Yes", "Regenerate", "Provide Feedback"]
NEXT_STEPS_MESSAGE = "*Linkedin posts generated*"
NEXT_STEPS_BUTTON_LABEL = "Proceed to Next Steps"
NEXT_STEPS_FORM_TITLE = "Proceed to Next Steps"
NEXT_STEPS_FORM_DESCRIPTION = "Linkedin posts generated"

# Feedback form
FEEDBACK_MESSAGE = "*Please provide feedback to improve LinkedIn posts content*"
FEEDBACK_BUTTON_LABEL = "Add feedback"
FEEDBACK_FORM_TITLE = "Feedback Form"
FEEDBACK_FORM_DESCRIPTION = "Please provide feedback to improve Linkedin posts content"

GOOGLE_DOC_TITLE = "Linkedin-posts"
"""Default title for the Google Doc created for carousel output."""

# Character validation constants
MIN_CHARS = 265
MAX_CHARS = 315
MAX_VALIDATION_ATTEMPTS = 2
"""Maximum automatic retry attempts for character validation."""


# ---------------------------------------------------------------------------
# Character validation
# ---------------------------------------------------------------------------

# Regex to extract slide body blocks: *Body:*\n ... until next section
_BODY_RE = re.compile(r"(\*Body:\*\n)([\s\S]*?)(?=\n\n---|\n\n\*Slide|\s*$)")


def validate_slide_bodies(raw_output: str) -> ValidationResult:
    """Validate character counts for slide body sections (Slides 3-10).

    Ports the n8n "Code in JavaScript" validation node. Parses ``*Body:*``
    markers from the LLM output, counts characters (with a -4 offset
    matching the n8n formula), and produces errors for violations.

    The output text is annotated with ``*Character count: N characters*``
    after each body block.

    Args:
        raw_output: The raw LLM output containing carousel slides.

    Returns:
        :class:`ValidationResult` with annotated output and error list.
    """
    errors: list[SlideError] = []
    annotated = raw_output

    # Process body blocks in reverse order so string replacements
    # don't shift subsequent match positions.
    matches = list(_BODY_RE.finditer(raw_output))

    for match in reversed(matches):
        body_content = match.group(2)
        cleaned_body = body_content.rstrip()

        # n8n formula: charCount = cleanedBody.length - 4
        char_count = len(cleaned_body) - 4

        if char_count < MIN_CHARS or char_count > MAX_CHARS:
            errors.append(
                SlideError(
                    slide_body=cleaned_body,
                    actual_characters=char_count,
                )
            )

        # Insert character count annotation after the body block
        annotation = f"\n*Character count:* {char_count} characters"
        insert_pos = match.end()
        annotated = annotated[:insert_pos] + annotation + annotated[insert_pos:]

    # Errors were added in reverse order; reverse back to slide order.
    errors.reverse()

    return ValidationResult(annotated_output=annotated, errors=errors)


# ---------------------------------------------------------------------------
# Form builder
# ---------------------------------------------------------------------------


def build_next_steps_form() -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for next-steps selection.

    Presents a required dropdown: Yes / Regenerate / Provide Feedback.

    Ports the n8n "Next steps" Slack sendAndWait form.
    """
    return [
        {
            "fieldLabel": NEXT_STEPS_FIELD,
            "fieldType": "dropdown",
            "fieldOptions": {
                "values": [{"option": opt} for opt in NEXT_STEPS_OPTIONS],
            },
            "requiredField": True,
        },
    ]


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


async def call_carousel_llm(
    formatted_theme: str,
    newsletter_content: str,
    *,
    previous_output: str = "",
    model: str | None = None,
) -> str:
    """Call the LLM to generate LinkedIn carousel content.

    Ports the n8n "Generate Linkedin Carousel using LLM" node. On retry
    passes (when ``previous_output`` contains validation errors), the LLM
    prompt instructs rewriting only the non-compliant slide bodies.

    Args:
        formatted_theme: The formatted theme JSON string.
        newsletter_content: The full HTML newsletter content.
        previous_output: Previously generated output — used in the
            character-error retry loop. Empty on first pass.
        model: Override model identifier.

    Returns:
        The raw LLM response text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    system_prompt, user_prompt = build_linkedin_carousel_prompt(
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
        previous_output=previous_output,
    )

    result = await completion(
        purpose=LLMPurpose.LINKEDIN,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        step="linkedin_carousel",
    )

    return result.text


async def call_regeneration_llm(
    previous_output: str,
    feedback_text: str,
    formatted_theme: str,
    newsletter_content: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to regenerate carousel content based on user feedback.

    Ports the n8n "Re-Generate Linkedin Carousel using LLM" node.

    Args:
        previous_output: The previously generated carousel content.
        feedback_text: The user's free-text feedback.
        formatted_theme: The formatted theme JSON string.
        newsletter_content: The full HTML newsletter content.
        model: Override model identifier.

    Returns:
        The regenerated carousel text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    system_prompt, user_prompt = build_linkedin_regeneration_prompt(
        previous_output=previous_output,
        feedback_text=feedback_text,
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
    )

    result = await completion(
        purpose=LLMPurpose.LINKEDIN_REGENERATION,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        step="linkedin_regeneration",
    )

    return result.text


# ---------------------------------------------------------------------------
# Generation with validation loop
# ---------------------------------------------------------------------------


async def generate_with_validation(
    formatted_theme: str,
    newsletter_content: str,
    *,
    max_attempts: int = MAX_VALIDATION_ATTEMPTS,
    model: str | None = None,
) -> tuple[str, list[SlideError]]:
    """Generate carousel content and auto-retry on character validation errors.

    Ports the n8n character-validation retry loop:
    1. Call LLM → validate slide bodies.
    2. If errors: pass output + errors back to LLM for targeted rewrite.
    3. Repeat up to ``max_attempts`` times. After exhaustion, accept as-is.

    Args:
        formatted_theme: The formatted theme JSON string.
        newsletter_content: The full HTML newsletter content.
        max_attempts: Maximum validation retry attempts.
        model: Override model identifier.

    Returns:
        ``(final_output, remaining_errors)`` — the validated (or
        force-accepted) output text, and any remaining validation errors.
    """
    # First generation
    raw_output = await call_carousel_llm(
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
        model=model,
    )

    for attempt in range(max_attempts):
        result = validate_slide_bodies(raw_output)

        if not result.errors:
            return result.annotated_output, []

        # On the last attempt, force-accept (clear errors)
        if attempt == max_attempts - 1:
            return result.annotated_output, []

        # Build previous output with character errors for the retry prompt
        error_payload = json.dumps([e.to_dict() for e in result.errors], indent=2)
        previous_with_errors = f"{result.annotated_output}\n\ncharacter_errors:\n{error_payload}"

        # Retry LLM with error context
        raw_output = await call_carousel_llm(
            formatted_theme=formatted_theme,
            newsletter_content=newsletter_content,
            previous_output=previous_with_errors,
            model=model,
        )

    # Should not reach here, but handle gracefully
    result = validate_slide_bodies(raw_output)
    return result.annotated_output, list(result.errors)


# ---------------------------------------------------------------------------
# Google Doc creation
# ---------------------------------------------------------------------------


async def create_carousel_doc(
    docs: GoogleDocsService,
    content: str,
    *,
    title: str = GOOGLE_DOC_TITLE,
) -> tuple[str, str]:
    """Create a Google Doc with the final LinkedIn carousel content.

    Args:
        docs: Google Docs service.
        content: The final carousel text.
        title: Document title.

    Returns:
        ``(doc_id, doc_url)`` tuple.
    """
    doc_id = await docs.create_document(title)
    await docs.insert_content(doc_id, content)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return doc_id, doc_url


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def run_linkedin_carousel_generation(
    html_doc_id: str,
    formatted_theme: dict[str, object],
    *,
    slack: SlackLinkedInReview,
    docs: GoogleDocsService | None = None,
) -> LinkedInCarouselResult:
    """Run the full LinkedIn carousel generator pipeline step.

    Orchestrates PRD Section 3.9 / n8n ``linkedin_carousel_generator_subworkflow``:

    1. Send Slack approval to proceed.
    2. Fetch HTML document content from Google Docs.
    3. Call LLM for carousel generation + character validation retry loop.
    4. Share validated output in Slack.
    5. Present next-steps form (Yes / Regenerate / Provide Feedback).
    6. **Yes** → create Google Doc, share link, return result.
    7. **Provide Feedback** → collect feedback → regeneration LLM →
       loop back to share + next-steps.
    8. **Regenerate** → full re-generation from scratch (including
       validation loop).

    Args:
        html_doc_id: Google Doc document ID containing the HTML newsletter.
        formatted_theme: The formatted theme dict with article metadata.
        slack: Slack interaction handler.
        docs: Google Docs service for reading/creating documents.

    Returns:
        :class:`LinkedInCarouselResult` with the final doc ID, URL,
        content, and model identifier.
    """
    model_id = get_model(LLMPurpose.LINKEDIN)
    formatted_theme_str = json.dumps(formatted_theme)

    # Step 1: User approval to proceed
    await slack.send_and_wait(
        SLACK_CHANNEL,
        APPROVAL_MESSAGE,
        approve_label="Yes",
    )

    # Step 2: Fetch HTML document content
    newsletter_content = ""
    if docs is not None:
        newsletter_content = await docs.get_content(html_doc_id)

    # Step 3: Generate carousel with character validation
    validated_output, _ = await generate_with_validation(
        formatted_theme=formatted_theme_str,
        newsletter_content=newsletter_content,
    )

    # Track the current output for the feedback loop
    current_output = validated_output
    regenerated_output: str | None = None

    # Step 4: Share + feedback loop
    while True:
        # Use regenerated output if available, otherwise use validated output
        display_output = regenerated_output if regenerated_output else current_output

        # Share content in Slack
        await slack.send_channel_message(display_output)

        # Present next-steps form
        form_fields = build_next_steps_form()
        response = await slack.send_and_wait_form(
            NEXT_STEPS_MESSAGE,
            form_fields=form_fields,
            button_label=NEXT_STEPS_BUTTON_LABEL,
            form_title=NEXT_STEPS_FORM_TITLE,
            form_description=NEXT_STEPS_FORM_DESCRIPTION,
        )

        choice = response.get(NEXT_STEPS_FIELD, "").strip().lower()

        if "yes" in choice:
            # Select final output: prefer regenerated, fall back to validated
            final_output = regenerated_output if regenerated_output else current_output
            break

        if "provide feedback" in choice:
            # Collect feedback
            user_feedback = await slack.send_and_wait_freetext(
                FEEDBACK_MESSAGE,
                button_label=FEEDBACK_BUTTON_LABEL,
                form_title=FEEDBACK_FORM_TITLE,
                form_description=FEEDBACK_FORM_DESCRIPTION,
            )

            # Regenerate with feedback
            base_output = regenerated_output if regenerated_output else current_output
            regenerated_output = await call_regeneration_llm(
                previous_output=base_output,
                feedback_text=user_feedback,
                formatted_theme=formatted_theme_str,
                newsletter_content=newsletter_content,
            )
            continue

        if "regenerate" in choice:
            # Full re-generation from scratch (including validation loop)
            newsletter_content = ""
            if docs is not None:
                newsletter_content = await docs.get_content(html_doc_id)

            current_output, _ = await generate_with_validation(
                formatted_theme=formatted_theme_str,
                newsletter_content=newsletter_content,
            )
            regenerated_output = None
            continue

        # Unknown choice — loop back
        continue

    # Step 5: Create Google Doc with final content
    doc_id = ""
    doc_url = ""
    if docs is not None:
        doc_id, doc_url = await create_carousel_doc(docs, final_output)

    # Step 6: Share Google Doc link in Slack
    if doc_url:
        await slack.send_channel_message(
            f"*Review Generated Linkedin Posts here, moving to next steps :* \n"
            f" {doc_url}?usp=sharing"
        )

    return LinkedInCarouselResult(
        doc_id=doc_id,
        doc_url=doc_url,
        final_content=final_output,
        model=model_id,
    )
