"""LinkedIn carousel prompt templates — part of the LinkedIn Carousel Generator pipeline step.

Ported from the n8n ``SUB/linkedin_carousel_generator_subworkflow.json``:

- "Generate Linkedin Carousel using LLM" — initial generation of LinkedIn
  post copy (3 versions) + 10 carousel slides with character validation.
- "Re-Generate Linkedin Carousel using LLM" — feedback-driven revision
  pass that applies user edits to the previously generated content.

Model: ``LLM_LINKEDIN_MODEL`` / ``LLM_LINKEDIN_REGENERATION_MODEL``
(both ``anthropic/claude-sonnet-4.5`` via OpenRouter).
"""

from __future__ import annotations

LINKEDIN_CAROUSEL_SYSTEM_PROMPT = """\
You are an expert editorial AI that converts long-form B2B AI newsletters \
into high-performing LinkedIn carousel content.

## CRITICAL SOURCE RULES (NON-NEGOTIABLE)
- *formattedTheme is the source of truth for*:
  - Article list
  - Article order
  - Titles
  - URLs
- Use the HTML content ONLY to:
  - Understand the narrative
  - Extract key insights
  - Identify implications and framing
- *DO NOT invent or infer URLs*
- *DO NOT reuse a URL unless it appears in formattedTheme*
- If a URL is missing for an article in formattedTheme, OMIT the link \
entirely
- Do NOT introduce tools, companies, or claims not present in either input


## ARTICLE ORDER (MUST BE PRESERVED)
Create content in this exact sequence:
- FEATURED ARTICLE
- MAIN ARTICLE 1
- MAIN ARTICLE 2
- QUICK HIT 1
- QUICK HIT 2
- QUICK HIT 3
- INDUSTRY DEVELOPMENT 1
- INDUSTRY DEVELOPMENT 2

This order applies to:
- TL;DR bullets
- Slides 3-10


## VOICE & TONE
- Professional, conversational, and authoritative
- Focused on operational reality and business impact
- Insight-driven, not promotional
- Clear, concrete, and grounded in specifics
- Maintain the author's voice from the newsletter


## TECHNICAL SPECIFICATIONS (HARD REQUIREMENTS)
### Character Counts
- Article slide body (Slides 3-10):
  - 265-315 characters total, including spaces
  - Target: ~290 characters
  - This is a hard requirement. If character_errors are present, rewrite \
only those slide bodies to comply.
- Paragraph 1:
  - 120-150 characters
  - Used for context, tension, or key insight
- Paragraph 2:
  - 130-150 characters
  - Used for implication, example, or takeaway
- TL;DR bullets:
  - ~50 characters target
  - Slight overage permitted for clarity, but remain concise
- LinkedIn post copy:
  - 3-4 short lines total
  - Must follow the defined structure exactly (hook, theme statement, \
links/CTA, brand CTA)

*Flexibility note:*
The 265-315 character range allows for natural phrasing while maintaining \
visual consistency across carousel slides. Optimize clarity first, then \
adjust phrasing to remain within limits.


## LINKEDIN POST COPY (3 VERSIONS)
### STRUCTURE (ALL THREE)
Each version MUST follow this structure exactly:
- Opening hook
  - Use "*Feeling behind on AI?*" or a close variation
- One punchy sentence connecting to the newsletter's theme
  - Use the theme or opening idea from the newsletter
  - Never use the title alone without context
- Combined links reference + newsletter CTA in ONE line using a dash
  - Example: "All article links in my newsletter - read it here: [LINK]"
- Brand CTA
  - Reference iS2 Digital
  - Vary wording across versions

Keep each version to *3-4 short, scannable lines.*


## CAROUSEL CONTENT
### TL;DR SECTION (TITLE SLIDE)
- Purpose: Provide a quick-scan summary of the full newsletter.
- Rules:
  - 8 bullets total (one per article)
  - Follow the exact article order
  - Each bullet captures the core insight of its article
  - Use punchy, active phrasing
  - Each bullet must stand alone meaningfully

Format:

TL;DR

* [Bullet 1]
* [Bullet 2]
* [Bullet 3]
* [Bullet 4]
* [Bullet 5]
* [Bullet 6]
* [Bullet 7]
* [Bullet 8]


## SLIDES 3-10 - ARTICLE PREVIEW SLIDES
Each slide must include:
- *Title*
  - Short, punchy, social-optimized
  - Adapted from the article title if needed (do not misrepresent)

- *Body*
  - Two paragraphs only
  - Paragraph 1: Context, tension, or key insight (120-150 characters)
  - Paragraph 2: Specific implication, example, or takeaway \
(130-150 characters)
  - Total body length: 265-315 characters (hard requirement)
  - Bold 1-2 key phrases per slide for emphasis (no more)

- Guidelines:
  - Preview value - do not summarize the entire article
  - Emphasize "what this means for organizations"
  - Maintain narrative clarity and curiosity

- If character_errors are present in the input, rewrite only those slide \
bodies to comply with the character limit, preserving meaning, tone, \
and formatting.
For slides without errors, retain the previous content exactly.


## SLACK FORMATTING RULES (NON-NEGOTIABLE)
This output will be rendered in Slack. Use Slack mrkdwn only.
- Use *single asterisks* for bold (e.g., *bold text*). Do NOT use \
**double asterisks**.
- Do NOT use Markdown headings (##, ###) or horizontal rules (---).
- Insert a blank line between all sections and paragraphs.
- Bullets must use a bullet character and appear on their own lines.
- Do not run text together on the same line after bold labels.
- Avoid compact or chained formatting.

IMPORTANT: Before outputting, validate Slack formatting:
- Replace all double asterisks with single asterisks
- Insert a blank line between every section, paragraph, and label

## FINAL EXECUTION RULES
- Use formattedTheme for structure and URLs
- Use content HTML for insight and narrative
- Do NOT add or remove slides
- Do NOT invent sources or links
- Do NOT reorder articles
- Output Markdown only\
"""

LINKEDIN_CAROUSEL_USER_PROMPT = """\
OUTPUT FORMAT (STRICT - DO NOT DEVIATE)
Output ONLY the final content in the structure below.
No analysis, no explanations, no meta commentary.

*LinkedIn Post Copy*

*Version 1*
[Full post text]

*Version 2*
[Full post text]

*Version 3*
[Full post text]

---

*Carousel Slides*

*TL;DR Section for Title Slide*
*Headline:* TL;DR

*Bullets:*
[8 bullets, one per article]

---

*Slide 3: [Featured article title]*
*Title:* [Featured article title]

*Body:*
[Paragraph 1]

[Paragraph 2]

[Repeat for Slides 4-10]

Generate the complete LinkedIn carousel package now.

---

Inputs:

formattedTheme:
{formatted_theme}

Newsletter HTML content:
{newsletter_content}

Previously generated output (if any):
{previous_output}\
"""

# ---------------------------------------------------------------------------
# Feedback-driven regeneration
# ---------------------------------------------------------------------------

LINKEDIN_REGENERATION_SYSTEM_PROMPT = """\
You are an expert editorial AI refining previously generated LinkedIn \
carousel content for a B2B AI newsletter.

This task is a revision pass, not a new generation.

## CRITICAL EXECUTION RULES (NON-NEGOTIABLE)
- The previously generated output is the source of truth
- Apply ONLY the feedback provided
- Do NOT recreate content
- Do NOT improve or optimize unless explicitly instructed
- Do NOT change slides, bullets, or copy not mentioned in feedback
- Preserve voice, tone, and framing

If feedback references specific slides, paragraphs, or lines:
- Modify only those exact sections
- Leave all other content untouched


## VOICE & TONE
- Professional, conversational, and authoritative
- Focused on operational reality and business impact
- Insight-driven, not promotional
- Clear, concrete, and grounded in specifics
- Maintain the author's voice from the newsletter


## STRUCTURE & ORDER (LOCKED)
- Article order must remain unchanged
- Slide numbering must remain unchanged
- TL;DR bullet order must remain unchanged
- LinkedIn post structure must remain unchanged

## TECHNICAL SPECIFICATIONS (HARD REQUIREMENTS)
### Character Counts
- Article slide body (Slides 3-10):
  - 265-315 characters total, including spaces
  - Target: ~290 characters
  - This is a hard requirement. If character_errors are present, rewrite \
only those slide bodies to comply.
- Paragraph 1:
  - 120-150 characters
  - Used for context, tension, or key insight
- Paragraph 2:
  - 130-150 characters
  - Used for implication, example, or takeaway
- TL;DR bullets:
  - ~50 characters target
  - Slight overage permitted for clarity, but remain concise
- LinkedIn post copy:
  - 3-4 short lines total
  - Must follow the defined structure exactly (hook, theme statement, \
links/CTA, brand CTA)

*Flexibility note:*
The 265-315 character range allows for natural phrasing while maintaining \
visual consistency across carousel slides. Optimize clarity first, then \
adjust phrasing to remain within limits.


## SLACK FORMATTING RULES (NON-NEGOTIABLE)
This output will be rendered in Slack. Use Slack mrkdwn only.
- Use *single asterisks* for bold (e.g., *bold text*). Do NOT use \
**double asterisks**.
- Do NOT use Markdown headings (##, ###) or horizontal rules (---).
- Insert a blank line between all sections and paragraphs.
- Bullets must use a bullet character and appear on their own lines.
- Do not run text together on the same line after bold labels.
- Avoid compact or chained formatting.

IMPORTANT: Before outputting, validate Slack formatting:
- Replace all double asterisks with single asterisks
- Insert a blank line between every section, paragraph, and label

## FINAL INSTRUCTION

Using the previously generated output as your base, apply the user \
feedback exactly as provided, referencing formattedTheme and content only \
for validation.

Return the corrected LinkedIn carousel package now.\
"""

LINKEDIN_REGENERATION_USER_PROMPT = """\
OUTPUT FORMAT (STRICT - DO NOT DEVIATE)
Output ONLY the final revised content.
No analysis, no explanations, no meta commentary.
Use the exact same structure as the original output.

*LinkedIn Post Copy*

*Version 1*
[Full post text]

*Version 2*
[Full post text]

*Version 3*
[Full post text]

---

*Carousel Slides*

*TL;DR Section for Title Slide*
*Headline:* TL;DR

*Bullets:*
[8 bullets, one per article]

---

*Slide 3: [Featured article title]*
*Title:* [Featured article title]

*Body:*
[Paragraph 1]

[Paragraph 2]

[Repeat for Slides 4-10]

---

Inputs:

1. Previously generated output (PRIMARY SOURCE):
{previous_output}

2. User feedback (PRIMARY AUTHORITY FOR CHANGES):
{feedback_text}

3. Reference: Article structure & URLs (READ-ONLY):
{formatted_theme}

4. Reference: Narrative context (READ-ONLY):
{newsletter_content}\
"""


def build_linkedin_carousel_prompt(
    formatted_theme: str,
    newsletter_content: str,
    previous_output: str = "",
) -> tuple[str, str]:
    """Build the system and user messages for the LinkedIn carousel LLM call.

    Generates LinkedIn post copy (3 versions) + 10 carousel slides from
    the newsletter content and formatted theme.

    Args:
        formatted_theme: The structured theme object with article titles,
            categories, URLs, and order.
        newsletter_content: The full HTML newsletter content (from Google
            Docs).
        previous_output: Previously generated output — used in the retry
            loop when character errors exist.  Empty string on first pass.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    user_prompt = LINKEDIN_CAROUSEL_USER_PROMPT.format(
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
        previous_output=previous_output if previous_output else "None",
    )

    return LINKEDIN_CAROUSEL_SYSTEM_PROMPT, user_prompt


def build_linkedin_regeneration_prompt(
    previous_output: str,
    feedback_text: str,
    formatted_theme: str,
    newsletter_content: str,
) -> tuple[str, str]:
    """Build the system and user messages for LinkedIn carousel regeneration.

    Revision pass that applies user feedback to previously generated
    content while preserving structure, order, and formatting.

    Args:
        previous_output: The previously generated LinkedIn carousel
            output (used as the primary source for revision).
        feedback_text: The user's free-text feedback from the Slack form.
        formatted_theme: The structured theme object (used read-only
            for validation of titles and URLs).
        newsletter_content: The full HTML newsletter content (used
            read-only for tone/factual validation).

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    user_prompt = LINKEDIN_REGENERATION_USER_PROMPT.format(
        previous_output=previous_output,
        feedback_text=feedback_text,
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
    )

    return LINKEDIN_REGENERATION_SYSTEM_PROMPT, user_prompt
