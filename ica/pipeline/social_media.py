"""Social media generator pipeline — Step 6c of the newsletter pipeline (parallel).

Ports the n8n ``social_media_generator_subworkflow.json``:

**Phase 1 — Post Concept Generation:**
1. Fetch HTML document content from Google Docs.
2. Call LLM (``anthropic/claude-sonnet-4.5``) with social media prompt to generate
   12 graphics-only posts — 6 DYK + 6 IT.
3. Share posts in Slack.
4. User approves or requests regeneration.
5. User selects which posts to develop.

**Phase 2 — Caption Generation:**
1. Parse selected posts, resolve source URLs from ``formatted_theme``.
2. Call LLM with social media caption prompt to generate captions (150-300 chars).
3. Share captions in Slack for review.
4. Feedback loop: Yes / Provide Feedback / Restart.
5. Final post selection for artifact.
6. Create Google Doc with final posts.

See APPLICATION.md Section 2.9, PRD Section 3.8.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

import litellm

from ica.config.llm_config import LLMPurpose, get_model
from ica.prompts.social_media import (
    build_social_media_caption_prompt,
    build_social_media_post_prompt,
    build_social_media_regeneration_prompt,
)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class SlackSocialMediaReview(Protocol):
    """Slack interactions for the social media generator.

    Ports multiple n8n Slack nodes:

    - "User approval" → :meth:`send_and_wait` (Phase 1 approval)
    - "Send a message" → :meth:`send_channel_message` (share posts/captions)
    - "Next steps" → :meth:`send_and_wait_form` (Phase 1 proceed/regenerate)
    - "Next steps selection" → :meth:`send_and_wait_form` (Phase 2 feedback)
    - "Send message and wait for response" → :meth:`send_and_wait_form` (selection)
    - "Feedback form" → :meth:`send_and_wait_freetext`
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
class ParsedPost:
    """A single social media post parsed from LLM output.

    Attributes:
        title: Full title like ``"DYK #1 — Headline"``.
        post_type: ``"DYK"`` or ``"IT"``.
        number: Post number (1-6).
        headline: The headline text after the dash.
        source: Source article name.
        source_url: Source URL resolved from ``formatted_theme``.
        graphic_info: Word/character count info string.
        emphasis: Emphasis recommendation text.
        graphic_text: Full graphic text content.
    """

    title: str
    post_type: str
    number: int
    headline: str
    source: str
    source_url: str
    graphic_info: str
    emphasis: str
    graphic_text: str


@dataclass(frozen=True)
class SocialMediaResult:
    """Final output of the social media generator pipeline step.

    Attributes:
        doc_id: Google Doc document ID containing the final posts.
        doc_url: Google Docs URL for the created document.
        final_content: The final combined post content text.
        model: The LLM model identifier used for post generation.
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
    "*Fetched final HTML newsletter. Are we good to proceed to social media content generation ?*"
)

# Phase 1 — post generation next steps
PHASE1_NEXT_STEPS_FIELD = "Proceed to Next steps"
PHASE1_NEXT_STEPS_OPTIONS: list[str] = ["Yes", "Regenerate"]
PHASE1_NEXT_STEPS_MESSAGE = "*Social media posts generated*"
PHASE1_BUTTON_LABEL = "Proceed to Next Steps"
PHASE1_FORM_TITLE = "Proceed to Next Steps"
PHASE1_FORM_DESCRIPTION = "Social media posts generated"

# Phase 1 — post selection
POST_SELECTION_FIELD = "Select DYK & IT Posts for Captioning"
POST_SELECTION_MESSAGE = "*Please select the posts you'd like to develop*"
POST_SELECTION_BUTTON = "Select Posts"
POST_SELECTION_FORM_TITLE = "Proceed to next step"
POST_SELECTION_FORM_DESCRIPTION = "Select the posts you'd like to develop"

# Phase 2 — caption review next steps
PHASE2_NEXT_STEPS_FIELD = "Ready to proceed to next step ?"
PHASE2_NEXT_STEPS_OPTIONS: list[str] = ["Yes", "Provide Feedback", "Restart Chat"]
PHASE2_NEXT_STEPS_MESSAGE = "*Social media posts generated*"
PHASE2_BUTTON_LABEL = "Proceed to Next Steps"
PHASE2_FORM_TITLE = "Proceed to next step"
PHASE2_FORM_DESCRIPTION = "Social media posts generated"

# Phase 2 — feedback
FEEDBACK_MESSAGE = "*Please provide feedback to improve social media posts content*"
FEEDBACK_BUTTON_LABEL = "Add feedback"
FEEDBACK_FORM_TITLE = "Feedback Form"
FEEDBACK_FORM_DESCRIPTION = "Please provide feedback to improve social media posts content"

# Final selection
FINAL_SELECTION_FIELD = "Select DYK & IT Posts to create final artifact"
FINAL_SELECTION_MESSAGE = (
    "*Please select the posts you'd like to add to final social media artifact*"
)
FINAL_SELECTION_BUTTON = "Select Posts"
FINAL_SELECTION_FORM_TITLE = "Proceed to next step"
FINAL_SELECTION_FORM_DESCRIPTION = "Select the posts you'd like to add to social media artifact"

GOOGLE_DOC_TITLE = "Social-media-posts"
"""Default title for the Google Doc created for social media output."""


# ---------------------------------------------------------------------------
# Post parsing — Phase 1 output
# ---------------------------------------------------------------------------

# Regex for Phase 1 titles: *DYK #1 — Headline*  or  *IT #3 — Headline*
_PHASE1_TITLE_RE = re.compile(r"\*(DYK|IT) #(\d+)\s*[—–-]\s*(.+?)\*")

# Regex for Phase 2 titles: *DYK #1:* *Headline*  or  *IT #3:* *Headline*
_PHASE2_TITLE_RE = re.compile(r"\*(DYK|IT) #(\d+):?\*\s*\*(.+?)\*")


def parse_phase1_titles(raw_text: str) -> list[str]:
    """Extract post titles from Phase 1 LLM output for selection form.

    Returns a list of strings like ``["DYK #1 — Headline", ...]``.
    """
    titles: list[str] = []
    for match in _PHASE1_TITLE_RE.finditer(raw_text):
        post_type, number, headline = match.group(1), match.group(2), match.group(3)
        titles.append(f"{post_type} #{number} — {headline}")
    return titles


def parse_phase2_titles(raw_text: str) -> list[str]:
    """Extract post titles from Phase 2 caption LLM output for final selection.

    Returns a list of strings like ``["DYK #1 — Headline", ...]``.
    """
    titles: list[str] = []
    for match in _PHASE2_TITLE_RE.finditer(raw_text):
        post_type, number, headline = match.group(1), match.group(2), match.group(3)
        titles.append(f"{post_type} #{number} — {headline}")
    return titles


def get_source_url(source_name: str, formatted_theme: dict[str, object]) -> str:
    """Resolve a source article name to its URL from formatted_theme.

    Mirrors the n8n ``getSourceUrl`` helper in the "Fetch selected posts"
    Code node. Prioritizes key-name match over source-number match.

    Args:
        source_name: Source string from the post (e.g. "Main Article 1").
        formatted_theme: The formatted theme dict with article metadata.

    Returns:
        The URL string, or ``""`` if not found.
    """
    if not source_name:
        return ""

    source_key = source_name.split(" - ")[0].strip()
    # Try to extract a source number
    number_match = re.search(r"\d+", source_name)
    source_number = number_match.group(0) if number_match else None

    # Pass 1: Try key-name match (highest priority)
    for key, item in formatted_theme.items():
        if not isinstance(item, dict):
            continue
        if key.upper() == source_key.upper():
            return str(item.get("URL", ""))

    # Pass 2: Try source-number match (fallback)
    if source_number:
        for key, item in formatted_theme.items():
            if not isinstance(item, dict):
                continue
            if item.get("Source") == source_number:
                return str(item.get("URL", ""))

    return ""


def parse_phase1_posts(
    raw_text: str,
    selected_titles: list[str],
    formatted_theme: dict[str, object],
) -> list[ParsedPost]:
    """Parse Phase 1 LLM output into structured post objects.

    Ports the n8n "Fetch selected posts" Code node: splits the raw text
    on the separator, filters by selected titles, extracts fields via
    regex, and resolves source URLs from formatted_theme.

    Args:
        raw_text: Full Phase 1 LLM output text.
        selected_titles: List of selected title strings.
        formatted_theme: Theme dict for URL resolution.

    Returns:
        List of :class:`ParsedPost` objects for selected posts.
    """
    # Split on separator line (n8n uses '–––––––––––––––––')
    blocks = re.split(r"[–—-]{5,}", raw_text)
    blocks = [b.strip() for b in blocks if b.strip()]

    posts: list[ParsedPost] = []
    for block in blocks:
        # Match title
        title_match = _PHASE1_TITLE_RE.search(block)
        if not title_match:
            continue

        post_type = title_match.group(1)
        number = int(title_match.group(2))
        headline = title_match.group(3)
        title = f"{post_type} #{number} — {headline}"

        if title not in selected_titles:
            continue

        # Extract fields
        source_match = re.search(r"\*Source\*:\s*(.+)", block)
        source = source_match.group(1).strip() if source_match else ""

        graphic_match = re.search(r"\*Graphic Component\*\s*\((.+?)\)", block)
        graphic_info = graphic_match.group(1).strip() if graphic_match else ""

        emphasis_match = re.search(r"\*Emphasis Recommendation\*:\s*(.+)", block)
        emphasis = emphasis_match.group(1).strip() if emphasis_match else ""

        # Graphic text: everything after the emphasis line (or after graphic info)
        graphic_text = ""
        graphic_text_match = re.search(
            r"(Did You Know\?|Inside Tip:|\*Inside Tip:\*)([\s\S]+)", block
        )
        if graphic_text_match:
            graphic_text = graphic_text_match.group(0).strip()

        source_url = get_source_url(source, formatted_theme)

        posts.append(
            ParsedPost(
                title=title,
                post_type=post_type,
                number=number,
                headline=headline,
                source=source,
                source_url=source_url,
                graphic_info=graphic_info,
                emphasis=emphasis,
                graphic_text=graphic_text,
            )
        )

    return posts


def filter_final_posts(
    raw_captions: str,
    selected_titles: list[str],
) -> str:
    """Filter caption output to only include selected posts, combined into a blob.

    Ports the n8n "Fetch final content" Code node: splits on ``---``,
    matches titles, and joins selected posts.

    Args:
        raw_captions: Full caption LLM output text.
        selected_titles: List of selected title strings for final artifact.

    Returns:
        Combined text blob of selected posts joined by separators.
    """
    blocks = raw_captions.split("---")
    blocks = [b.strip() for b in blocks if b.strip()]

    selected_blocks: list[str] = []
    for block in blocks:
        # Try Phase 2 title format first: *DYK #1:* *Headline*
        title_match = _PHASE2_TITLE_RE.search(block)
        if title_match:
            post_type = title_match.group(1)
            number = title_match.group(2)
            headline = title_match.group(3)
            identifier = f"{post_type} #{number} — {headline}"
            if identifier in selected_titles:
                selected_blocks.append(block)
                continue

        # Fall back to Phase 1 title format: *DYK #1 — Headline*
        title_match = _PHASE1_TITLE_RE.search(block)
        if title_match:
            post_type = title_match.group(1)
            number = title_match.group(2)
            headline = title_match.group(3)
            identifier = f"{post_type} #{number} — {headline}"
            if identifier in selected_titles:
                selected_blocks.append(block)

    return "\n\n---\n\n".join(selected_blocks)


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------


def build_phase1_next_steps_form() -> list[dict[str, object]]:
    """Build the Phase 1 next-steps form (Yes / Regenerate).

    Ports the n8n "Next steps" Slack sendAndWait form.
    """
    return [
        {
            "fieldLabel": PHASE1_NEXT_STEPS_FIELD,
            "fieldType": "dropdown",
            "fieldOptions": {
                "values": [{"option": opt} for opt in PHASE1_NEXT_STEPS_OPTIONS],
            },
            "requiredField": True,
        },
    ]


def build_post_selection_form(titles: list[str]) -> list[dict[str, object]]:
    """Build a checkbox selection form for posts.

    Ports the n8n "Fetch Options" Code node that builds the selection form.

    Args:
        titles: List of post title strings to offer as options.

    Returns:
        JSON-serialisable form field list for Slack sendAndWait.
    """
    return [
        {
            "fieldLabel": POST_SELECTION_FIELD,
            "fieldType": "checkbox",
            "fieldOptions": {
                "values": [{"option": t} for t in titles],
            },
        },
    ]


def build_phase2_next_steps_form() -> list[dict[str, object]]:
    """Build the Phase 2 next-steps form (Yes / Provide Feedback / Restart Chat).

    Ports the n8n "Next steps selection" Slack sendAndWait form.
    """
    return [
        {
            "fieldLabel": PHASE2_NEXT_STEPS_FIELD,
            "fieldType": "dropdown",
            "fieldOptions": {
                "values": [{"option": opt} for opt in PHASE2_NEXT_STEPS_OPTIONS],
            },
            "requiredField": True,
        },
    ]


def build_final_selection_form(titles: list[str]) -> list[dict[str, object]]:
    """Build a checkbox selection form for final artifact posts.

    Ports the n8n "Fetch Final Options" Code node.

    Args:
        titles: List of post title strings from caption output.

    Returns:
        JSON-serialisable form field list for Slack sendAndWait.
    """
    return [
        {
            "fieldLabel": FINAL_SELECTION_FIELD,
            "fieldType": "checkbox",
            "fieldOptions": {
                "values": [{"option": t} for t in titles],
            },
        },
    ]


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


async def call_social_media_post_llm(
    newsletter_content: str,
    formatted_theme: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to generate 12 graphics-only social media posts (Phase 1).

    Args:
        newsletter_content: The full HTML newsletter content.
        formatted_theme: The formatted theme JSON string.
        model: Override model identifier.

    Returns:
        The raw LLM response text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.SOCIAL_MEDIA)
    system_prompt, user_prompt = build_social_media_post_prompt(
        newsletter_content=newsletter_content,
        formatted_theme=formatted_theme,
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
        raise RuntimeError("LLM returned an empty response for social media post generation")

    return content.strip()


async def call_caption_llm(
    posts: list[ParsedPost],
    formatted_theme: dict[str, object],
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to generate captions for selected posts (Phase 2).

    Args:
        posts: List of selected parsed posts.
        formatted_theme: The formatted theme dict for newsletter context.
        model: Override model identifier.

    Returns:
        The raw LLM response text with captions.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.SOCIAL_POST_CAPTION)

    # Build posts JSON array
    posts_json = json.dumps(
        [
            {
                "title": p.title,
                "originalHeadline": p.headline,
                "source": p.source,
                "sourceUrl": p.source_url,
                "graphicComponentInfo": p.graphic_info,
                "emphasis": p.emphasis,
                "graphicText": p.graphic_text,
            }
            for p in posts
        ],
        indent=2,
    )

    # Extract article context from formatted_theme
    def _get_article(key: str) -> str:
        val = formatted_theme.get(key)
        return json.dumps(val) if val else "{}"

    system_prompt, user_prompt = build_social_media_caption_prompt(
        posts_json=posts_json,
        featured_article=_get_article("FEATURED ARTICLE"),
        main_article_1=_get_article("MAIN ARTICLE 1"),
        main_article_2=_get_article("MAIN ARTICLE 2"),
        quick_hit_1=_get_article("QUICK HIT 1"),
        quick_hit_2=_get_article("QUICK HIT 2"),
        quick_hit_3=_get_article("QUICK HIT 3"),
        industry_news_1=_get_article("INDUSTRY DEVELOPMENT 1"),
        industry_news_2=_get_article("INDUSTRY DEVELOPMENT 2"),
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
        raise RuntimeError("LLM returned an empty response for social media caption generation")

    return content.strip()


async def call_caption_regeneration_llm(
    feedback_text: str,
    previous_captions: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to regenerate captions based on user feedback.

    Args:
        feedback_text: The user's free-text feedback.
        previous_captions: The previously generated captions.
        model: Override model identifier.

    Returns:
        The regenerated caption text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.SOCIAL_MEDIA_REGENERATION)
    system_prompt, user_prompt = build_social_media_regeneration_prompt(
        feedback_text=feedback_text,
        previous_captions=previous_captions,
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
        raise RuntimeError("LLM returned an empty response for social media caption regeneration")

    return content.strip()


# ---------------------------------------------------------------------------
# Google Doc creation
# ---------------------------------------------------------------------------


async def create_social_media_doc(
    docs: GoogleDocsService,
    content: str,
    *,
    title: str = GOOGLE_DOC_TITLE,
) -> tuple[str, str]:
    """Create a Google Doc with the final social media post content.

    Args:
        docs: Google Docs service.
        content: The final combined post text.
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


async def run_social_media_generation(
    html_doc_id: str,
    formatted_theme: dict[str, object],
    *,
    slack: SlackSocialMediaReview,
    docs: GoogleDocsService | None = None,
) -> SocialMediaResult:
    """Run the full social media generator pipeline step.

    Orchestrates PRD Section 3.8 / n8n ``social_media_generator_subworkflow``:

    1. Send Slack approval to proceed.
    2. Fetch HTML document content from Google Docs.
    3. Call LLM for Phase 1 (12 graphics-only posts).
    4. Share posts in Slack.
    5. Phase 1 next-steps (Yes/Regenerate) — regenerate loops back to step 2.
    6. Present post selection checkbox form.
    7. Parse selected posts, resolve source URLs.
    8. Call LLM for Phase 2 (captions for selected posts).
    9. Share captions in Slack.
    10. Phase 2 next-steps (Yes/Provide Feedback/Restart Chat).
    11. Present final artifact selection.
    12. Create Google Doc with final content.
    13. Share Google Doc link in Slack.

    Args:
        html_doc_id: Google Doc document ID containing the HTML newsletter.
        formatted_theme: The formatted theme dict with article metadata.
        slack: Slack interaction handler.
        docs: Google Docs service for reading/creating documents.

    Returns:
        :class:`SocialMediaResult` with the final doc ID, URL, content,
        and model identifier.
    """
    model_id = get_model(LLMPurpose.SOCIAL_MEDIA)
    formatted_theme_str = json.dumps(formatted_theme)

    # Step 1: User approval to proceed
    await slack.send_and_wait(
        SLACK_CHANNEL,
        APPROVAL_MESSAGE,
        approve_label="Yes",
    )

    # Phase 1 loop: generate posts → approve/regenerate
    while True:
        # Step 2: Fetch HTML document content
        newsletter_content = ""
        if docs is not None:
            newsletter_content = await docs.get_content(html_doc_id)

        # Step 3: Call LLM for Phase 1
        phase1_output = await call_social_media_post_llm(
            newsletter_content=newsletter_content,
            formatted_theme=formatted_theme_str,
        )

        # Step 4: Share posts in Slack
        await slack.send_channel_message(phase1_output)

        # Step 5: Phase 1 next-steps form
        form_fields = build_phase1_next_steps_form()
        response = await slack.send_and_wait_form(
            PHASE1_NEXT_STEPS_MESSAGE,
            form_fields=form_fields,
            button_label=PHASE1_BUTTON_LABEL,
            form_title=PHASE1_FORM_TITLE,
            form_description=PHASE1_FORM_DESCRIPTION,
        )

        choice = response.get(PHASE1_NEXT_STEPS_FIELD, "").strip().lower()
        if "yes" in choice:
            break
        # Otherwise "Regenerate" — loop back to re-fetch and regenerate

    # Step 6: Post selection form
    titles = parse_phase1_titles(phase1_output)
    selection_form = build_post_selection_form(titles)
    selection_response = await slack.send_and_wait_form(
        POST_SELECTION_MESSAGE,
        form_fields=selection_form,
        button_label=POST_SELECTION_BUTTON,
        form_title=POST_SELECTION_FORM_TITLE,
        form_description=POST_SELECTION_FORM_DESCRIPTION,
    )

    # Parse selected titles from response
    selected_raw = selection_response.get(POST_SELECTION_FIELD, "")
    selected_titles = _parse_checkbox_response(selected_raw)

    # Step 7: Parse selected posts
    selected_posts = parse_phase1_posts(phase1_output, selected_titles, formatted_theme)

    # Step 8: Call LLM for Phase 2 captions
    captions_output = await call_caption_llm(selected_posts, formatted_theme)

    # Phase 2 loop: share captions → feedback
    while True:
        # Step 9: Share captions in Slack
        await slack.send_channel_message(captions_output)

        # Step 10: Phase 2 next-steps form
        phase2_form = build_phase2_next_steps_form()
        phase2_response = await slack.send_and_wait_form(
            PHASE2_NEXT_STEPS_MESSAGE,
            form_fields=phase2_form,
            button_label=PHASE2_BUTTON_LABEL,
            form_title=PHASE2_FORM_TITLE,
            form_description=PHASE2_FORM_DESCRIPTION,
        )

        phase2_choice = phase2_response.get(PHASE2_NEXT_STEPS_FIELD, "").strip().lower()

        if "yes" in phase2_choice:
            break

        if "provide feedback" in phase2_choice:
            # Collect feedback
            user_feedback = await slack.send_and_wait_freetext(
                FEEDBACK_MESSAGE,
                button_label=FEEDBACK_BUTTON_LABEL,
                form_title=FEEDBACK_FORM_TITLE,
                form_description=FEEDBACK_FORM_DESCRIPTION,
            )

            # Regenerate captions
            captions_output = await call_caption_regeneration_llm(
                feedback_text=user_feedback,
                previous_captions=captions_output,
            )
            # Loop back to share regenerated captions
            continue

        if "restart" in phase2_choice:
            # Restart: re-fetch document and regenerate from Phase 2
            newsletter_content = ""
            if docs is not None:
                newsletter_content = await docs.get_content(html_doc_id)
            captions_output = await call_caption_llm(selected_posts, formatted_theme)
            continue

        # Unknown choice — loop back
        continue

    # Step 11: Final selection form
    final_titles = parse_phase2_titles(captions_output)
    final_form = build_final_selection_form(final_titles)
    final_response = await slack.send_and_wait_form(
        FINAL_SELECTION_MESSAGE,
        form_fields=final_form,
        button_label=FINAL_SELECTION_BUTTON,
        form_title=FINAL_SELECTION_FORM_TITLE,
        form_description=FINAL_SELECTION_FORM_DESCRIPTION,
    )

    final_selected_raw = final_response.get(FINAL_SELECTION_FIELD, "")
    final_selected_titles = _parse_checkbox_response(final_selected_raw)

    # Step 12: Filter and combine selected posts
    final_content = filter_final_posts(captions_output, final_selected_titles)

    # Step 13: Create Google Doc with final content
    doc_id = ""
    doc_url = ""
    if docs is not None:
        doc_id, doc_url = await create_social_media_doc(docs, final_content)

    # Step 14: Share Google Doc link in Slack
    if doc_url:
        await slack.send_channel_message(
            f"*Review Generated Social Media Posts here, moving to next steps :* \n"
            f" {doc_url}?usp=sharing"
        )

    return SocialMediaResult(
        doc_id=doc_id,
        doc_url=doc_url,
        final_content=final_content,
        model=model_id,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_checkbox_response(raw: str) -> list[str]:
    """Parse a checkbox response value into a list of selected titles.

    Slack checkbox responses may come as a comma-separated string
    or as a JSON array string. Handles both formats.

    Args:
        raw: The raw response string.

    Returns:
        List of selected title strings.
    """
    if not raw:
        return []

    # Try JSON array first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to comma-separated
    return [item.strip() for item in raw.split(",") if item.strip()]
