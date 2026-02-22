"""Theme generation prompt template — Step 3 of the newsletter pipeline.

Ported from the n8n "Generate Data using LLM" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/theme_generation_subworkflow.json``.

The LLM generates two candidate newsletter themes from a JSON array of
article summaries.  Each theme assigns articles to structured slots
(Featured Article, Main Articles, Quick Hits, Industry Developments) using
``%XX_`` markers, verifies content distribution requirements (2-2-2 balance,
source mix), and ends with a recommendation for which theme to use.

Model: ``LLM_THEME_MODEL`` (``anthropic/claude-sonnet-4.5`` via OpenRouter).
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

THEME_GENERATION_SYSTEM_PROMPT = """\
You are a professional AI research editor and content analyst. Your task is \
to process the summaries of articles that may be provided in **JSON** format.

Start by reviewing the article summaries, reading "Title", "Summary", \
"BusinessRelevance", "Order" fields for each item in json

Based on that data create a and output viable two themes that meet all \
content distribution and source mix requirements and specifications listed next.


Follow these protocols EXACTLY:

---

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT generate or infer missing details.
2. Use ONLY provided data in the json format.
3. If in the json source, items have field "industry_news" equal to "true" \
use that items to fill \
%I1_TITLE,%I1_SOURCE,%I1_ORIGIN,%I1_URL,%I1_Major AI Player and \
%I2_TITLE,%I2_SOURCE,%I2_ORIGIN,%I2_URL,%I2_Major AI Player as instructed \
below\
"""

THEME_GENERATION_USER_PROMPT = """\
{feedback_section}\

---


## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points or colon) in \
this format for each created theme, do not duplicate titles for themes, do \
not rename THEME: subjects

THEME: [theme main title]
Theme Description: [1\u20133 sentence factual summary following core narrative]

Articles that fit.
FEATURED ARTICLE:
%FA_TITLE: [Pick best suitable title of an article from the json source]
%FA_SOURCE: [Print here order number from json file for this item]
%FA_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%FA_URL: [Print here url from json file for this item]
%FA_CATEGORY: [Make and print category for this item using related summary]
%FA_WHY FEATURED:[Shortly explain why you have picked this title]

%M1_TITLE: [Pick best suitable title of an article from the json source]
%M1_SOURCE: [Print here order number from json file for this item]
%M1_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%M1_URL: [Print here url from json file for this item];
%M1_CATEGORY: [Make and print category for this item using related summary]
%M1_RATIONALE: [Make and print a rationale description]

%M2_TITLE: [Pick best suitable title of an article from the json source]
%M2_SOURCE: [Print here order number from json file for this item]
%M2_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%M2_URL: [Print here url from json file for this item]
%M2_CATEGORY: [Make and print category for this item using related summary]
%M2_RATIONALE: [Make and print a rationale description]

%Q1_TITLE: [Pick best suitable title of an article from the json source]
%Q1_SOURCE: [Print here order number from json file for this item]
%Q1_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%Q1_URL: [Print here url from json file for this item]
%Q1_CATEGORY: [Make and print category for this item using related summary]

%Q2_TITLE: [Pick best suitable title of an article from the json source]
%Q2_SOURCE: [Print here order number from json file for this item]
%Q2_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%Q2_URL: [Print here url from json file for this item]
%Q2_CATEGORY: [Make and print category for this item using related summary]

%Q3_TITLE: [Pick best suitable title of an article from the json source]
%Q3_SOURCE: [Print here order number from json file for this item]
%Q3_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%Q3_URL: [Print here url from json file for this item]
%Q3_CATEGORY: [Make and print category for this item using related summary]

%I1_TITLE: [Pick best suitable title of an article from the json source]
%I1_SOURCE: [Print here order number from json file for this item]
%I1_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%I1_URL: [Print here url from json file for this item]
%I1_Major AI Player: [List Major AI Player for this article]

%I2_TITLE: [Pick best suitable title of an article from the json source]
%I2_SOURCE: [Print here order number from json file for this item]
%I2_ORIGIN: [Print here name of author of this summary, take it from \
different sources or url]
%I2_URL: [Print here url from json file for this item]
%I2_Major AI Player: [List Major AI Player for this article]

2-2-2 Distribution:
%222_tactical:% ([Include order number from the json source, in this format \
Source number]) [Create a short 1-3 word representation if the title or \
article from the json source as for tactical theme], ([Include order number \
from the json source, in this format Source number]) [Create a short 1-3 \
word representation if the title or article from the json source as for \
tactical theme]
%222_educational:% ([Include order number from the json source, in this \
format Source number]) [Create a short 1-3 word representation if the title \
or article from the json source as for educational theme], ([Include order \
number from the json source, in this format Source number]) [Create a short \
1-3 word representation if the title or article from the json source as for \
educational theme]
%222_forward-thinking:% ([Include order number from the json source, in \
this format Source number]) [Create a short 1-3 word representation if the \
title or article from the json source as for forward thinking], ([Include \
order number from the json source, in this format Source number]) [Create a \
short 1-3 word representation if the title or article from the json source \
as for forward thinking]

Source mix:
%SM_smaller_publisher:% [print here at least one and maximum 2, small \
publisher names related to the author of of the summary and Source number \
from JSON related to that item]
%SM_major_ai_player_coverage:% [Create a short 1-3 word representation if \
the title of an article from the json source] (Source number)

REQUIREMENTS VERIFIED,
%RV_2-2-2 Distribution Achieved:% [Create a short 1-3 word representation \
if the title of an article from the json source and add source[order number] \
for 2 tactical subjects], [Create a short 1-3 word representation if the \
title of an article from the json source and add Source number for 2 \
educational subjects], [Create a short 1-3 word representation if the title \
of an article from the json source and add Source number for 2 \
forward-thinking subjects]
%RV_Source mix:% ([Include order number from the json source, in this format \
Source number]) [Create a short 1-3 word representation if the title of an \
article from the json source]
%RV_Technical complexity:% ([Include order number from the json source, in \
this format Source number]) [Create a short 1-3 word representation if the \
title of an article from the json source]
%RV_Major AI player coverage:% ([Include order number from the json source, \
in this format Source number]) [Create a short 1-3 word representation if \
the title of an article from the json source]

Put a separator string "-----" after each created theme.

As the final output, after generated themes, create a recomendation you \
theme to pick and use in this format.

RECOMMENDATION: Theme [Put generated theme number] - [the theme name, \
generated above what you are recomend to use]

Rationale:

[Using ordered list, output the name of the section from the theme, that \
you recommend, and shortly explain why, make ~5 section recommendations]

[Describe using text only, 3-4 sentences, why we should pick this theme]


---

Input:
{summaries_json}\
"""


def build_theme_generation_prompt(
    summaries_json: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the theme generation LLM call.

    Args:
        summaries_json: JSON string of the article summaries array.  Each
            element should contain at minimum ``Title``, ``Summary``,
            ``BusinessRelevance``, and ``Order`` fields.
        aggregated_feedback: Optional bullet-point list of prior editorial
            feedback entries from the ``newsletter_themes_user_feedback``
            table (last 40 entries).  When provided (non-empty), the
            *Editorial Improvement Context* section is injected into the
            user prompt.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = THEME_GENERATION_USER_PROMPT.format(
        feedback_section=feedback_section,
        summaries_json=summaries_json,
    )

    return THEME_GENERATION_SYSTEM_PROMPT, user_prompt
