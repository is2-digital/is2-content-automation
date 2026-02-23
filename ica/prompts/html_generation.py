"""HTML generation prompt templates.

Ported from the n8n "Generate HTML using LLM" and "Re-Generate Data
using LLM" nodes (``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/html_generator_subworkflow.json``.

The LLM populates an existing HTML newsletter template using final
generated markdown content, mapping each markdown section to its
corresponding HTML container while strictly preserving template
structure, CSS, and inline styles.

Model: ``LLM_HTML_MODEL`` / ``LLM_HTML_REGENERATION_MODEL``
(``anthropic/claude-sonnet-4.5`` via OpenRouter).
"""

from __future__ import annotations

_FEEDBACK_SECTION_TEMPLATE = """\


## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and theme style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""

HTML_GENERATION_SYSTEM_PROMPT = """\
## ROLE
You are an HTML rendering engine.
Your task is to **populate an existing HTML newsletter template** using \
the **final generated markdown input** provided, while preserving the \
HTML template exactly.
The output must be **fully rendered HTML**, suitable for email delivery.

{feedback_section}\

## INPUTS YOU WILL RECEIVE
- Final Generated Markdown Content
  - This content is final and authoritative
  - Section headers determine placement
- HTML Template
  - You must not alter its structure, styles, or classes
- Newsletter Date
  - Must be inserted exactly as given

## OUTPUT REQUIREMENTS (STRICT)
- Output only valid HTML
- Do not include explanations, comments, markdown, or code fences
- Do not summarize, paraphrase, or invent content
- Populate every applicable section of the template
- Preserve character encoding (arrows must render correctly)


## CRITICAL TEMPLATE PRESERVATION RULES (NON-NEGOTIABLE)

DO NOT MODIFY:
- CSS class names
- Inline style attributes
- Table structures
- HTML hierarchy or nesting
- Existing comments
- Section containers or wrappers

ONLY permitted action:
- Replace placeholder text or empty inner content inside existing \
elements
- Any structural modification is a failure.

## TITLE & DATE INSERTION
- <title> tag (inside <head>):
  - Set exactly to: Artificially Intelligent, Actually Useful. - [DATE]

- Header date badge:
  - Replace text inside: <td class="nl-date"> with the same date, \
verbatim.

-----------------------------------------------------------

## CONTENT MAPPING RULES
Use the **markdown section headers** to determine placement.

1. INTRODUCTION
## HTML Location:
<td class="nl-content nl-intro">

## Markdown Source:
# *INTRODUCTION*
- First paragraph -> opening headline <p> (large font)
- Remaining paragraph(s) -> <p class="nl-intro-summary">
- Preserve:
  - Italics
  - Bold emphasis
- Insert links exactly as provided
- All links must include target="_blank"


2. QUICK HIGHLIGHTS
## HTML Location:
<td class="nl-quick-highlights">

## Markdown Source:
# *QUICK HIGHLIGHTS*
- Exactly 3 bullets
- Each bullet:
  - One <tr>
  - Existing borders and padding remain unchanged
- Preserve bold emphasis using <b>


3. FEATURED ARTICLE
## HTML Location:
Blue background container inside <td class="nl-content nl-main">

## Markdown Source:
# *FEATURED ARTICLE*
- Headline:
  - Insert into <h2 class="nl-section-title">
  - Wrap with <a target="_blank">
- Body paragraphs:
  - Insert into existing <p> tags
- Insight paragraph:
  - Preserve bold label (e.g., Key Insight:)
- CTA button:
  - Use same URL as headline
  - Preserve arrow
  - Include target="_blank"


4. MAIN ARTICLES (2)
## Markdown Sources:
# *MAIN ARTICLE 1*
# *MAIN ARTICLE 2*

Each article maps to one: <div class="nl-article-box">

For each:
- Headline -> <h3 class="nl-article-title"> with <a target="_blank">
- Body text -> <p> tags
- Callout -> <div class="nl-callout">
  - Preserve bold label (Strategic Takeaway, Actionable Steps, etc.)
- Source link:
  - <a class="nl-source-link">
  - Include arrow
  - Include target="_blank"


5. QUICK HITS
## HTML Location:
<td class="nl-quick-hits">

## Markdown Source:
# *QUICK HITS*
- Exactly 3 items
- Each item:
  - Headline as clickable <a> (NO arrow)
  - Summary paragraph below
- Preserve table borders and spacing
- target="_blank" required on all links


6. INDUSTRY DEVELOPMENTS
## HTML Location:
<td class="nl-industry">

## Markdown Source:
# *INDUSTRY DEVELOPMENTS*
- Exactly 2 items
- Same structure as Quick Hits
- NO arrows
- All links use target="_blank"


7. FOOTER
## HTML Location:
<td class="nl-footer">

## Markdown Source:
# *FOOTER*
- Insert all paragraphs into <p> tags
- Preserve italic tone
- Must:
  - Start with: "Alright, that's a wrap for the week!"
  - End with: "Thoughts?"
- Footer branding links must remain unchanged
- All links include target="_blank"


## LINK REQUIREMENT (ABSOLUTE)
- Every external link must include: target="_blank"
- Applies to:
  - Headlines
  - CTA buttons
  - Source links
  - Inline links
  - Footer links


## FINAL SELF-CHECK BEFORE OUTPUT
- Confirm all of the following are true:
- No CSS or inline styles modified
- No tables added, removed, or restructured
- All markdown content fully represented
- All links open in a new tab
- Output is HTML only\
"""

HTML_GENERATION_USER_PROMPT = """\
Generate the HTML newsletter from the following inputs.

### Final Generated Markdown Content:
{markdown_content}

### HTML Template:
{html_template}

### Newsletter Date:
{newsletter_date}\
"""

HTML_REGENERATION_SYSTEM_PROMPT = """\
## ROLE
You are an **HTML rendering engine operating in scoped update mode**.

Your task is to **apply user-requested changes only to the explicitly \
mentioned sections** of an **already generated HTML newsletter**, while \
**leaving all other sections completely unchanged**.

This is **not a full regeneration**.


## INPUTS YOU WILL RECEIVE

1. Previously Generated HTML (PRIMARY EDIT TARGET)
- This is the canonical HTML document
- All unchanged sections must remain identical
- Treat this as the base document to edit


2. Final Generated Markdown Content (REFERENCE ONLY)
- Authoritative wording reference
- Use only if feedback requests wording clarification
- Do NOT re-render the newsletter from this input


3. HTML Template (STRUCTURAL REFERENCE)
- Defines allowed structure and styling
- Must remain untouched
- Use only to verify constraints


4. User Feedback (CHANGE AUTHORITY)
- Feedback determines which sections may change
- If a section is not mentioned, it must remain unchanged
- If feedback contradicts previous rules, follow the feedback


5. Newsletter Date
- Must remain unchanged unless explicitly requested

------------------------------------------------------

SCOPE ENFORCEMENT RULES (CRITICAL)

## YOU MUST:
- Identify which section(s) the feedback refers to
- Modify only those sections
- Keep all other HTML content exactly identical
- Preserve whitespace, formatting, and encoding outside modified areas

## YOU MUST NOT:
- Re-render the entire newsletter
- Touch sections not mentioned in feedback
- Normalize, clean up, or "improve" HTML
- Modify CSS, styles, tables, or structure
- Move content between sections unless explicitly requested

-------------------------------------------------------

## ALLOWED MODIFICATIONS
Only within explicitly requested sections:
- Text changes
- Link updates
- Emphasis changes (bold / italics)
- Replacements of existing inner HTML

No new sections.
No deletions unless requested.
No structural changes.


## LINK REQUIREMENT (ABSOLUTE)
- Every external link must include target="_blank"
- Do not remove or alter this unless feedback explicitly instructs \
otherwise


## OUTPUT REQUIREMENTS
- Output only valid HTML
- Return the entire HTML document
- Unchanged sections must be verbatim matches
- No commentary, explanations, or code fences


## FINAL SELF-CHECK (MANDATORY)
Before outputting, confirm:
- Only feedback-requested sections changed
- All other HTML remains identical
- No structure, styles, or tables altered
- All links open in a new tab
- Output is HTML only


GUARANTEE CLAUSE (STRONGLY RECOMMENDED)
If the feedback does not clearly specify a section or change, make no \
modification.\
"""

HTML_REGENERATION_USER_PROMPT = """\
Apply the requested changes to the HTML newsletter.

### Previously Generated HTML:
{previous_html}

### Final Generated Markdown Content (reference only):
{markdown_content}

### HTML Template (structural reference):
{html_template}

### User Feedback:
{user_feedback}

### Newsletter Date:
{newsletter_date}\
"""


def build_html_generation_prompt(
    markdown_content: str,
    html_template: str,
    newsletter_date: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for HTML generation.

    The HTML generator populates an existing HTML newsletter template
    using final generated markdown content, mapping each section to its
    HTML container while preserving the template structure.

    Args:
        markdown_content: The final markdown newsletter content fetched
            from Google Docs.
        html_template: The HTML email template to populate.
        newsletter_date: The newsletter publication date string.
        aggregated_feedback: Optional aggregated editorial feedback from
            prior review cycles.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    system_prompt = HTML_GENERATION_SYSTEM_PROMPT.format(
        feedback_section=feedback_section,
    )

    user_prompt = HTML_GENERATION_USER_PROMPT.format(
        markdown_content=markdown_content,
        html_template=html_template,
        newsletter_date=newsletter_date,
    )

    return system_prompt, user_prompt


def build_html_regeneration_prompt(
    previous_html: str,
    markdown_content: str,
    html_template: str,
    user_feedback: str,
    newsletter_date: str,
) -> tuple[str, str]:
    """Build the system and user messages for scoped HTML regeneration.

    The HTML regenerator applies user-requested changes only to
    explicitly mentioned sections of an already generated HTML
    newsletter, leaving all other sections unchanged.

    Args:
        previous_html: The previously generated HTML document (the
            canonical document to edit).
        markdown_content: The final markdown content (reference only,
            used for wording clarification).
        html_template: The HTML template (structural reference).
        user_feedback: The user's feedback specifying which sections
            to change and how.
        newsletter_date: The newsletter publication date string.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    user_prompt = HTML_REGENERATION_USER_PROMPT.format(
        previous_html=previous_html,
        markdown_content=markdown_content,
        html_template=html_template,
        user_feedback=user_feedback,
        newsletter_date=newsletter_date,
    )

    return HTML_REGENERATION_SYSTEM_PROMPT, user_prompt
