"""Email subject & preview generator pipeline — Step 6b of the newsletter pipeline (parallel).

Ports the n8n ``email_subject_and_preview_subworkflow.json``:

1. Fetch the HTML newsletter document from Google Docs and strip HTML tags.
2. Fetch learning data (last 40 entries, ``type='user_email_subject'``).
3. Call LLM (``anthropic/claude-sonnet-4.5``) with the email subject prompt to
   generate up to 10 subject line options with a recommendation.
4. Parse subjects from the raw LLM output.
5. Share subjects in Slack, present radio-button selection form.
6. On feedback → extract learning data → store in ``notes`` table → loop back.
7. On subject selection → call LLM for email review generation.
8. Share review in Slack → approval form (Approve / Reset All / Add feedback).
9. On approval → create Google Doc with subject + review → share link in Slack.

Existing assets: ``prompts/email_subject.py``, ``prompts/email_review.py``,
``prompts/learning_data_extraction.py``.

See APPLICATION.md Section 2.8, PRD Section 3.7.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose, get_model
from ica.db.crud import add_note, get_recent_notes
from ica.db.models import Note
from ica.prompts.email_review import build_email_review_prompt
from ica.prompts.email_subject import build_email_subject_prompt
from ica.prompts.learning_data_extraction import build_learning_data_extraction_prompt


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class SlackEmailSubjectReview(Protocol):
    """Slack interactions for the email subject & preview pipeline.

    Ports multiple n8n Slack nodes:

    - "Output Generated Newsletter Subjects" → :meth:`send_channel_message`
    - "Select subjects or submit feedback" → :meth:`send_and_wait_form`
    - "Output Selected Review" → :meth:`send_channel_message`
    - "Approve or Submit Feedback" → :meth:`send_and_wait_form`
    - "Send a message" → :meth:`send_channel_message` (doc link)
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
class ParsedSubject:
    """A single parsed email subject from the LLM output.

    Attributes:
        subject: The subject line text.
        subject_id: The numeric identifier (e.g. ``"1"``).
        subject_body: The raw block text from the LLM output.
    """

    subject: str
    subject_id: str
    subject_body: str


@dataclass(frozen=True)
class EmailSubjectResult:
    """Final output of the email subject & preview pipeline step.

    Attributes:
        selected_subject: The user-selected email subject text.
        review_text: The generated email review / preview text.
        doc_id: Google Doc document ID containing subject + review.
        doc_url: Google Docs URL for the created document.
        model: The LLM model identifier used for subject generation.
    """

    selected_subject: str
    review_text: str
    doc_id: str
    doc_url: str
    model: str


# ---------------------------------------------------------------------------
# Constants — Slack form config
# ---------------------------------------------------------------------------

SUBJECT_SELECTION_FIELD_LABEL = "Newsletter Subject or Feedback"
"""Field label for the subject selection radio group."""

FEEDBACK_FIELD_LABEL = "Editor Feedback for AI"
"""Field label for the optional feedback textarea."""

SUBJECT_SELECTION_BUTTON_LABEL = "Select  Subject or Submit Feedback"
"""Button label matching n8n sendAndWait node."""

SUBJECT_SELECTION_FORM_TITLE = "Proceed to next step"
SUBJECT_SELECTION_FORM_DESCRIPTION = "All Subjecsts have been successfully created."
SUBJECT_SELECTION_MESSAGE = (
    "*Please select whitch subject you'd like to develop, "
    "or let me know if you'd like to explore other thematic angles.*"
)

REVIEW_APPROVAL_FIELD_LABEL = "Approve or Feedback"
"""Field label for the review approval radio group."""

REVIEW_NOTES_FIELD_LABEL = "Editor Notes"
"""Field label for the review feedback textarea."""

REVIEW_APPROVAL_BUTTON_LABEL = "Approve Review or Submit Feedback"
REVIEW_APPROVAL_FORM_TITLE = "Proceed to next step"
REVIEW_APPROVAL_FORM_DESCRIPTION = "The Review has been successfully created."
REVIEW_APPROVAL_MESSAGE = "*The Review has been successfully created.*"

REVIEW_APPROVAL_OPTIONS: list[str] = [
    "Approve review and continue",
    "Reset All (Generate Subjects and Review Again)",
    "Add a feedback",
]

GOOGLE_DOC_TITLE = "Email-subject-preview"
"""Default title for the Google Doc created for email subject + review output."""

SUBJECTS_HEADER = "*Newsletter Text Subjects: *"
"""Slack Block Kit header for the subjects display."""

REVIEW_HEADER = "*Newsletter AI Review*"
"""Slack Block Kit header for the review display."""


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------


def strip_html_to_text(html: str) -> str:
    """Strip HTML tags from content, returning plain text.

    Ports the n8n "Process Input" Code node which:
    1. Removes ``<style>`` and ``<script>`` blocks
    2. Strips remaining HTML tags
    3. Cleans up whitespace and decodes ``&nbsp;``

    Args:
        html: Raw HTML content from Google Docs.

    Returns:
        Plain text with HTML stripped.
    """
    text = html
    # 1. Strip <style> and <script> blocks
    text = re.sub(r"<(style|script)[^>]*>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE)
    # 2. Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # 3. Clean up whitespace and decode basic entities
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Feedback aggregation
# ---------------------------------------------------------------------------


def aggregate_feedback(notes: list[Note]) -> str | None:
    """Convert Note rows into a bullet-point string for prompt injection.

    Mirrors the n8n "Process User Feedback" Code node pattern.

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
# LLM calls — subject generation
# ---------------------------------------------------------------------------


async def call_email_subject_llm(
    newsletter_text: str,
    *,
    aggregated_feedback: str | None = None,
    model: str | None = None,
) -> str:
    """Call the LLM to generate email subject lines.

    Args:
        newsletter_text: Plain-text newsletter content (HTML stripped).
        aggregated_feedback: Optional aggregated learning data.
        model: Override model identifier.

    Returns:
        The raw LLM response text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.EMAIL_SUBJECT)
    system_prompt, user_prompt = build_email_subject_prompt(
        newsletter_text=newsletter_text,
        aggregated_feedback=aggregated_feedback,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content  # type: ignore[union-attr]
    if not content or not content.strip():
        raise RuntimeError("LLM returned an empty response for email subject generation")

    return content.strip()


# ---------------------------------------------------------------------------
# Subject parsing
# ---------------------------------------------------------------------------


def parse_subjects(raw_output: str) -> tuple[list[ParsedSubject], str]:
    """Parse LLM output into individual subjects and recommendation.

    Ports the n8n "Prepare AI generated subjects" Code node:
    - Split on ``-----`` delimiter
    - Blocks containing ``RECOMMENDATION:`` go to recommendation
    - Other blocks extract ``Subject_N: text`` patterns

    Args:
        raw_output: The raw text from the LLM.

    Returns:
        A ``(subjects, recommendation)`` tuple. ``recommendation`` is the
        combined recommendation text, or empty string if none found.
    """
    parts = [p.strip() for p in raw_output.split("-----") if p.strip()]

    recommendation_parts = [p for p in parts if "RECOMMENDATION:" in p]
    subject_parts = [p for p in parts if "RECOMMENDATION:" not in p]

    recommendation = "\n".join(recommendation_parts)

    subjects: list[ParsedSubject] = []
    for block in subject_parts:
        # Extract "Subject_N: text"
        subject_match = re.search(r"Subject_[0-9]*:\s*(.+)", block, re.IGNORECASE)
        subject_text = subject_match.group(1).strip() if subject_match else None

        # Extract the number from "Subject_N"
        id_match = re.search(r"Subject_([0-9]*)", block, re.IGNORECASE)
        subject_id = id_match.group(1).strip() if id_match else None

        if subject_text and subject_id:
            subjects.append(
                ParsedSubject(
                    subject=subject_text,
                    subject_id=subject_id,
                    subject_body=block,
                )
            )

    return subjects, recommendation


# ---------------------------------------------------------------------------
# Slack formatting — subjects
# ---------------------------------------------------------------------------


def format_recommendation(text: str) -> str:
    """Apply Slack mrkdwn bold to recommendation keywords.

    Ports the n8n ``formatRecommendation()`` helper in "Format output" Code node.

    Args:
        text: Raw recommendation text from the LLM.

    Returns:
        Text with RECOMMENDATION/Explanation/EXPLANATION bolded.
    """
    result = str(text or "")
    result = result.replace("RECOMMENDATION:", "*RECOMMENDATION:*")
    result = result.replace("Explanation:", "*Explanation:*")
    result = result.replace("EXPLANATION:", "*EXPLANATION:*")
    return result


def build_subjects_slack_blocks(
    subjects: list[ParsedSubject],
    recommendation: str,
) -> list[dict[str, object]]:
    """Build Slack Block Kit blocks for displaying generated subjects.

    Ports the n8n "Format output" Code node.

    Args:
        subjects: Parsed subject list.
        recommendation: Recommendation text from the LLM.

    Returns:
        Slack Block Kit blocks list.
    """
    blocks: list[dict[str, object]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"\n{SUBJECTS_HEADER}\n",
            },
        },
        {"type": "divider"},
    ]

    for i, s in enumerate(subjects):
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*SUBJECT {i + 1}:* {s.subject}\n",
                },
            }
        )
        blocks.append({"type": "divider"})

    if recommendation:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"\n{format_recommendation(recommendation)}\n",
                },
            }
        )

    return blocks


def format_subjects_slack_message(
    subjects: list[ParsedSubject],
    recommendation: str,
) -> str:
    """Build a flattened Slack message from subjects blocks.

    Ports the message construction in n8n "Format output" Code node.

    Args:
        subjects: Parsed subject list.
        recommendation: Recommendation text from the LLM.

    Returns:
        Flattened Slack mrkdwn message string.
    """
    blocks = build_subjects_slack_blocks(subjects, recommendation)
    separator = "\n \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500 \u2500\n\n"
    parts = [
        b["text"]["text"]  # type: ignore[index]
        for b in blocks
        if "text" in b and isinstance(b["text"], dict) and "text" in b["text"]
    ]
    return separator.join(parts)


# ---------------------------------------------------------------------------
# Slack forms — subject selection
# ---------------------------------------------------------------------------


def build_subject_selection_form(
    subjects: list[ParsedSubject],
) -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for subject selection.

    Ports the n8n "Conditional output" Code node. Presents radio buttons
    with each subject and an "Add Feedback" option, plus a textarea for
    editor feedback.

    Args:
        subjects: Parsed subject list.

    Returns:
        JSON-serialisable form field list for Slack sendAndWait.
    """
    options = [{"option": f"SUBJECT {s.subject_id}: {s.subject}"} for s in subjects]
    options.append({"option": "Add Feedback"})

    return [
        {
            "fieldLabel": SUBJECT_SELECTION_FIELD_LABEL,
            "fieldType": "radio",
            "fieldOptions": {"values": options},
        },
        {
            "fieldLabel": FEEDBACK_FIELD_LABEL,
            "fieldType": "textarea",
        },
    ]


def is_subject_selection(value: str) -> bool:
    """Check if the user's selection contains a subject identifier.

    Ports the n8n "Switch" node condition:
    ``data["Newsletter Subject or Feedback"]`` contains ``"SUBJECT"``.

    Args:
        value: The raw selection value from the Slack form.

    Returns:
        ``True`` if the value contains ``SUBJECT`` (subject selected),
        ``False`` if it's a feedback selection (e.g. "Add Feedback").
    """
    return "SUBJECT" in value


def extract_selected_subject(
    selection: str,
    subjects: list[ParsedSubject],
) -> ParsedSubject | None:
    """Extract the selected subject from the radio button response.

    Ports the n8n "Format subject output" Code node which parses the
    ``SUBJECT N`` pattern and looks up the subject by index.

    Args:
        selection: The raw selection value (e.g. ``"SUBJECT 3: AI Meets..."``).
        subjects: The full list of parsed subjects.

    Returns:
        The matching :class:`ParsedSubject`, or ``None`` if not found.
    """
    match = re.search(r"SUBJECT\s+(\d+)", selection, re.IGNORECASE)
    if not match:
        return None

    subject_number = int(match.group(1))
    # n8n uses 1-based index: AllSubjects[subjectNumberID - 1]
    idx = subject_number - 1
    if 0 <= idx < len(subjects):
        return subjects[idx]

    return None


# ---------------------------------------------------------------------------
# LLM calls — email review generation
# ---------------------------------------------------------------------------


async def call_email_review_llm(
    newsletter_text: str,
    *,
    user_review_feedback: str | None = None,
    model: str | None = None,
) -> str:
    """Call the LLM to generate the email review / preview text.

    Ports the n8n "Review data extractor - Review" node.

    Args:
        newsletter_text: Plain-text newsletter content.
        user_review_feedback: Optional feedback from a prior review cycle.
        model: Override model identifier.

    Returns:
        The generated review text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.EMAIL_PREVIEW)
    system_prompt, user_prompt = build_email_review_prompt(
        newsletter_text=newsletter_text,
        user_review_feedback=user_review_feedback,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content  # type: ignore[union-attr]
    if not content or not content.strip():
        raise RuntimeError("LLM returned an empty response for email review generation")

    return content.strip()


# ---------------------------------------------------------------------------
# Slack formatting — review
# ---------------------------------------------------------------------------


def build_review_slack_blocks(review_text: str) -> list[dict[str, object]]:
    """Build Slack Block Kit blocks for displaying the email review.

    Ports the n8n "Format output - Review" Code node.

    Args:
        review_text: The generated review text from the LLM.

    Returns:
        Slack Block Kit blocks list.
    """
    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n\n\n Review: \n",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"\n{review_text}\n",
            },
        },
    ]


def format_review_slack_message(review_text: str) -> str:
    """Build a flattened Slack message from review blocks.

    Ports the message construction in n8n "Format output - Review" Code node.

    Args:
        review_text: The generated review text.

    Returns:
        Flattened Slack mrkdwn message string.
    """
    blocks = build_review_slack_blocks(review_text)
    separator = "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"
    parts = [
        b["text"]["text"]  # type: ignore[index]
        for b in blocks
        if "text" in b and isinstance(b["text"], dict) and "text" in b["text"]
    ]
    return separator.join(parts)


# ---------------------------------------------------------------------------
# Slack forms — review approval
# ---------------------------------------------------------------------------


def build_review_approval_form() -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for review approval.

    Ports the n8n "Approve or Submit Feedback" sendAndWait node with:
    - Radio: Approve / Reset All / Add feedback
    - Textarea: Editor Notes

    Returns:
        JSON-serialisable form field list for Slack sendAndWait.
    """
    return [
        {
            "fieldLabel": REVIEW_APPROVAL_FIELD_LABEL,
            "fieldType": "radio",
            "fieldOptions": {
                "values": [{"option": opt} for opt in REVIEW_APPROVAL_OPTIONS],
            },
        },
        {
            "fieldLabel": REVIEW_NOTES_FIELD_LABEL,
            "fieldType": "textarea",
        },
    ]


def parse_review_approval(response: dict[str, str]) -> str:
    """Parse the user's choice from the review approval form.

    Ports the n8n "Final Switch" node logic — uses contains-based matching:
    - Contains ``"Approve"`` → ``"approve"``
    - Contains ``"feedback"`` (case-sensitive) → ``"feedback"``
    - Contains ``"Reset All"`` → ``"reset"``

    Args:
        response: The raw Slack form response dict.

    Returns:
        One of ``"approve"``, ``"feedback"``, ``"reset"``, or ``"unknown"``.
    """
    value = response.get(REVIEW_APPROVAL_FIELD_LABEL, "")

    # n8n "Final Switch" uses contains-based matching (caseSensitive=true)
    if "Approve" in value:
        return "approve"
    if "feedback" in value:
        return "feedback"
    if "Reset All" in value:
        return "reset"

    return "unknown"


# ---------------------------------------------------------------------------
# Learning data extraction
# ---------------------------------------------------------------------------


async def extract_email_learning_data(
    feedback: str,
    model_output: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to extract learning data from user feedback.

    Ports the n8n "Process feedback learning data using LLM" node
    in the email subject subworkflow.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        model_output: The LLM-generated output (raw subject generation text).
        model: Override model identifier.

    Returns:
        Extracted ``learning_feedback`` text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.EMAIL_SUBJECT_REGENERATION)
    system_prompt, user_prompt = build_learning_data_extraction_prompt(
        feedback=feedback,
        input_text=model_output,
        model_output=model_output,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content  # type: ignore[union-attr]
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


async def store_email_feedback(
    session: AsyncSession,
    feedback_text: str,
    *,
    newsletter_id: str | None = None,
) -> None:
    """Store processed learning feedback in the ``notes`` table.

    Inserts with ``type='user_email_subject'``.

    Args:
        session: Active async database session.
        feedback_text: The processed learning note.
        newsletter_id: Optional newsletter association.
    """
    await add_note(
        session,
        "user_email_subject",
        feedback_text,
        newsletter_id=newsletter_id,
    )


# ---------------------------------------------------------------------------
# Google Doc creation
# ---------------------------------------------------------------------------


async def create_email_doc(
    docs: GoogleDocsService,
    subject: str,
    review_text: str,
    *,
    title: str = GOOGLE_DOC_TITLE,
) -> tuple[str, str]:
    """Create a Google Doc with the selected subject + review.

    Ports the n8n "Create a document" → "Update a document" → "Send a message"
    chain.

    Args:
        docs: Google Docs service.
        subject: The selected email subject line.
        review_text: The generated email review text.
        title: Document title.

    Returns:
        ``(doc_id, doc_url)`` tuple.
    """
    doc_id = await docs.create_document(title)
    # n8n inserts two parts: "SUBJECT: {subject}" and then the review text
    content = f"SUBJECT: {subject}\n\n{review_text}"
    await docs.insert_content(doc_id, content)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return doc_id, doc_url


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def run_email_subject_generation(
    html_doc_id: str,
    *,
    slack: SlackEmailSubjectReview,
    docs: GoogleDocsService | None = None,
    session: AsyncSession | None = None,
    newsletter_id: str | None = None,
) -> EmailSubjectResult:
    """Run the full email subject & preview generation pipeline step.

    Orchestrates APPLICATION.md Section 2.8 / n8n email_subject_and_preview_subworkflow:

    **Phase 1 — Subject Generation & Selection:**
    1. Fetch HTML document from Google Docs, strip to plain text.
    2. Fetch learning data (last 40, ``type='user_email_subject'``).
    3. Generate subjects via LLM → parse → display in Slack.
    4. Subject selection form: pick a subject or provide feedback.
    5. Feedback → learning data extraction → store → regenerate (loop).
    6. Subject selected → proceed to Phase 2.

    **Phase 2 — Review Generation & Approval:**
    7. Call LLM for email review using selected subject context.
    8. Display review in Slack.
    9. Approval form: Approve / Reset All / Add feedback.
    10. Approve → create Google Doc → share link → return result.
    11. Feedback → regenerate review with feedback (loop).
    12. Reset All → loop back to Phase 1 (clear feedback, regenerate subjects).

    Args:
        html_doc_id: Google Doc document ID containing the HTML newsletter.
        slack: Slack interaction handler.
        docs: Google Docs service for reading the newsletter and creating output.
        session: Optional async database session for storing learning data.
        newsletter_id: Optional newsletter association.

    Returns:
        :class:`EmailSubjectResult` with selected subject, review text,
        doc ID, URL, and model identifier.
    """
    model_id = get_model(LLMPurpose.EMAIL_SUBJECT)

    # Step 1: Fetch HTML document and strip to plain text
    newsletter_text = ""
    if docs is not None:
        raw_html = await docs.get_content(html_doc_id)
        newsletter_text = strip_html_to_text(raw_html)

    # Outer loop: handles Reset All by restarting the entire flow
    while True:
        # Step 2: Fetch learning data
        aggregated_feedback: str | None = None
        if session is not None:
            notes = await get_recent_notes(session, "user_email_subject")
            aggregated_feedback = aggregate_feedback(notes)

        # Step 3: Generate subjects via LLM
        raw_output = await call_email_subject_llm(
            newsletter_text,
            aggregated_feedback=aggregated_feedback,
        )

        # Step 4: Parse subjects
        subjects, recommendation = parse_subjects(raw_output)

        # Step 5: Subject selection loop (handles feedback regeneration)
        fresh_feedback: str | None = None
        selected_subject: ParsedSubject | None = None

        while True:
            # Build Slack blocks and display
            header_text = "*AI Generated Newsletter Subjects for Review*"
            if fresh_feedback is not None:
                header_text = "*AI Generated Subjects for Review with User feedback*"

            message = format_subjects_slack_message(subjects, recommendation)
            blocks = build_subjects_slack_blocks(subjects, recommendation)
            await slack.send_channel_message(
                f"{header_text} {message}",
                blocks=blocks,
            )

            # Build selection form and wait for response
            form_fields = build_subject_selection_form(subjects)
            response = await slack.send_and_wait_form(
                SUBJECT_SELECTION_MESSAGE,
                form_fields=form_fields,
                button_label=SUBJECT_SELECTION_BUTTON_LABEL,
                form_title=SUBJECT_SELECTION_FORM_TITLE,
                form_description=SUBJECT_SELECTION_FORM_DESCRIPTION,
            )

            selection_value = response.get(SUBJECT_SELECTION_FIELD_LABEL, "")
            editor_feedback = response.get(FEEDBACK_FIELD_LABEL, "")

            if is_subject_selection(selection_value):
                # User selected a subject
                selected_subject = extract_selected_subject(selection_value, subjects)
                # Capture editor feedback if provided alongside selection
                if editor_feedback and editor_feedback.strip():
                    fresh_feedback = editor_feedback.strip()
                break

            # User chose "Add Feedback" — process feedback and loop
            feedback_text = editor_feedback.strip() if editor_feedback else ""

            if feedback_text:
                # Extract learning data via LLM
                learning_note = await extract_email_learning_data(
                    feedback=feedback_text,
                    model_output=raw_output,
                )

                # Store learning data
                if session is not None:
                    await store_email_feedback(
                        session,
                        learning_note,
                        newsletter_id=newsletter_id,
                    )

                fresh_feedback = feedback_text

            # Regenerate subjects with updated feedback
            if session is not None:
                notes = await get_recent_notes(session, "user_email_subject")
                aggregated_feedback = aggregate_feedback(notes)

            # Inject fresh feedback directly (matching n8n behavior)
            if fresh_feedback:
                aggregated_feedback = f"\n\u2022 {fresh_feedback}\n"

            raw_output = await call_email_subject_llm(
                newsletter_text,
                aggregated_feedback=aggregated_feedback,
            )
            subjects, recommendation = parse_subjects(raw_output)

        # Step 6: Fallback if no subject could be extracted
        if selected_subject is None and subjects:
            selected_subject = subjects[0]

        subject_text = selected_subject.subject if selected_subject else ""

        # Phase 2: Review generation and approval loop
        user_review_feedback: str | None = fresh_feedback
        reset_triggered = False

        while True:
            # Step 7: Generate review via LLM
            review_text = await call_email_review_llm(
                newsletter_text,
                user_review_feedback=user_review_feedback,
            )

            # Step 8: Display review in Slack
            review_message = format_review_slack_message(review_text)
            review_blocks = build_review_slack_blocks(review_text)
            await slack.send_channel_message(
                f"{REVIEW_HEADER} {review_message}",
                blocks=review_blocks,
            )

            # Step 9: Approval form
            approval_form = build_review_approval_form()
            approval_response = await slack.send_and_wait_form(
                REVIEW_APPROVAL_MESSAGE,
                form_fields=approval_form,
                button_label=REVIEW_APPROVAL_BUTTON_LABEL,
                form_title=REVIEW_APPROVAL_FORM_TITLE,
                form_description=REVIEW_APPROVAL_FORM_DESCRIPTION,
            )

            choice = parse_review_approval(approval_response)
            editor_notes = approval_response.get(REVIEW_NOTES_FIELD_LABEL, "")

            if choice == "approve":
                # Step 10: Create Google Doc with subject + review
                doc_id = ""
                doc_url = ""
                if docs is not None:
                    doc_id, doc_url = await create_email_doc(docs, subject_text, review_text)

                    # Share Google Doc link in Slack
                    share_message = (
                        f"*Review Email Subject & Preview text here, "
                        f"moving to next steps :* \n "
                        f"https://docs.google.com/document/d/{doc_id}/edit?usp=sharing"
                    )
                    await slack.send_channel_message(share_message)

                return EmailSubjectResult(
                    selected_subject=subject_text,
                    review_text=review_text,
                    doc_id=doc_id,
                    doc_url=doc_url,
                    model=model_id,
                )

            if choice == "feedback":
                # Step 11: Regenerate review with feedback
                user_review_feedback = editor_notes.strip() if editor_notes else None
                continue

            if choice == "reset":
                # Step 12: Reset all — go back to subject generation
                reset_triggered = True
                break

            # Unknown choice — loop back
            continue

        if reset_triggered:
            # Clear feedback and restart the outer loop
            # n8n behavior: "If the Reset was triggered - clear all feedbacks."
            continue

        # Should not reach here, but break just in case
        break  # pragma: no cover
