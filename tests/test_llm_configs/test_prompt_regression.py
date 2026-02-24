"""Regression tests for pilot prompt migration.

Asserts that ``build_summarization_prompt()`` and ``build_email_subject_prompt()``
produce string-identical output compared to the original hardcoded versions
(pre-migration commit 646f1ec).

These tests guard against accidental prompt drift when editing JSON config files.
"""

from __future__ import annotations

import pytest

from ica.llm_configs.loader import _cache

# ---------------------------------------------------------------------------
# Original hardcoded constants (verbatim from commit 646f1ec)
# ---------------------------------------------------------------------------

# -- Summarization ----------------------------------------------------------

_ORIG_SUMMARIZATION_SYSTEM_PROMPT = """\
You are a professional AI research editor and content analyst. Your task is \
to process news or blog articles that may be provided in HTML, Markdown, or \
plain text format according to strict editorial and data integrity standards.

Follow these protocols EXACTLY:

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.

## Article Summary Standards
Summary Specifications:
- 3-4 sentences per article
- Focus strictly on factual content, key findings, and main conclusions
- Avoid editorial opinions or speculative tone
- Include specific statistics, methodologies, or technical details when mentioned

Business Relevance Specifications:
- 2-3 sentences per article
- Explain the broad business or strategic relevance across industries
- Consider an audience of solopreneurs and SMB professionals (without naming them)
- Emphasize practical implications for decision-making, operations, or strategy
- Avoid technical or industry-specific jargon

## Data Integrity Standards
- Extract only verified information directly from the article
- Quote or cite exact statistics or claims when possible
- Flag unverifiable data explicitly (e.g., "Statistic requires verification")
- Do NOT fabricate, infer, or supplement from external knowledge
- Well-established general knowledge does NOT require verification\
"""

_ORIG_SUMMARIZATION_USER_PROMPT = """\
{feedback_section}\

## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points) in this format:

URL: [article URL]
Title: [article title]
Summary: [3-4 sentence factual summary following Article Summary Standards]
Business Relevance: [2-3 sentence business relevance commentary following \
the same standards]

Now process the following content accordingly. The input may be HTML, \
Markdown, or plain text — automatically detect the format. If the content \
cannot be fully accessed, follow the Accuracy Control Protocol.

Keep the output format consistent as plain text and not JSON object.

Input:
{article_content}\
"""

_ORIG_SUMMARIZATION_FEEDBACK_TEMPLATE = """\

## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and summarization style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""

# -- Email subject ----------------------------------------------------------

_ORIG_EMAIL_SUBJECT_SYSTEM_PROMPT = """\
You are a professional AI research editor and content analyst. Your task is \
to process the email newsletter in text format.

Start by reviewing the newsletter text, \
based on that data create up to 10 definitive email subjects that will be \
used for this newsletter.

Follow these protocols EXACTLY:

---

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Make those subject relevant to the newsletter text and be trending, \
and represent the newsletter content.
3. Make subjects short and maximum is 7 words.
4. Be creative.\
"""

_ORIG_EMAIL_SUBJECT_USER_PROMPT = """\
{feedback_section}\


## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points or colon) \
in this format for each created subject, do not duplicate.

Subject_[number]: [Text subject]

Put a separator string "-----" after each created subject.

As the final output, after generated subjects, create a recommendation \
to pick best subject and explain why, use in this format.

RECOMMENDATION: Subject [Put generated subject number] - \
[the subject text, generated above what you recommend to use]

---

Input:
{newsletter_text}\
"""

_ORIG_EMAIL_SUBJECT_FEEDBACK_TEMPLATE = """\


## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and theme style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_loader_cache() -> None:
    """Ensure JSON config is freshly loaded for each test."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Summarization regression tests
# ---------------------------------------------------------------------------


class TestSummarizationPromptRegression:
    """Assert JSON-loaded summarization prompts match original hardcoded versions."""

    SAMPLE_ARTICLE = (
        "https://example.com/article "
        "AI Revolution in SMB "
        "<p>Article body about AI in small business...</p>"
    )
    SAMPLE_FEEDBACK = "- Use shorter sentences\n- Avoid jargon"

    def test_system_prompt_matches_original(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        system, _ = build_summarization_prompt(self.SAMPLE_ARTICLE)
        assert system == _ORIG_SUMMARIZATION_SYSTEM_PROMPT

    def test_user_prompt_without_feedback_matches_original(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        _, user = build_summarization_prompt(self.SAMPLE_ARTICLE)
        expected = _ORIG_SUMMARIZATION_USER_PROMPT.format(
            feedback_section="",
            article_content=self.SAMPLE_ARTICLE,
        )
        assert user == expected

    def test_user_prompt_with_feedback_matches_original(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        _, user = build_summarization_prompt(self.SAMPLE_ARTICLE, self.SAMPLE_FEEDBACK)
        feedback_section = _ORIG_SUMMARIZATION_FEEDBACK_TEMPLATE.format(
            aggregated_feedback=self.SAMPLE_FEEDBACK.strip(),
        )
        expected = _ORIG_SUMMARIZATION_USER_PROMPT.format(
            feedback_section=feedback_section,
            article_content=self.SAMPLE_ARTICLE,
        )
        assert user == expected

    def test_system_prompt_length_unchanged(self) -> None:
        """Guard against truncation or whitespace drift."""
        from ica.prompts.summarization import build_summarization_prompt

        system, _ = build_summarization_prompt(self.SAMPLE_ARTICLE)
        assert len(system) == 1427

    def test_instruction_template_length_unchanged(self) -> None:
        """Guard against truncation or whitespace drift in the raw template."""
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("summarization")
        assert len(instruction) == 643


# ---------------------------------------------------------------------------
# Email subject regression tests
# ---------------------------------------------------------------------------


class TestEmailSubjectPromptRegression:
    """Assert JSON-loaded email-subject prompts match original hardcoded versions."""

    SAMPLE_NEWSLETTER = (
        "This week in AI: New breakthroughs in language models. "
        "GPT-5 rumors surface. Anthropic launches new features."
    )
    SAMPLE_FEEDBACK = "- Make subjects punchier\n- Focus on AI trends"

    def test_system_prompt_matches_original(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        system, _ = build_email_subject_prompt(self.SAMPLE_NEWSLETTER)
        assert system == _ORIG_EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_user_prompt_without_feedback_matches_original(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        _, user = build_email_subject_prompt(self.SAMPLE_NEWSLETTER)
        expected = _ORIG_EMAIL_SUBJECT_USER_PROMPT.format(
            feedback_section="",
            newsletter_text=self.SAMPLE_NEWSLETTER,
        )
        assert user == expected

    def test_user_prompt_with_feedback_matches_original(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        _, user = build_email_subject_prompt(self.SAMPLE_NEWSLETTER, self.SAMPLE_FEEDBACK)
        feedback_section = _ORIG_EMAIL_SUBJECT_FEEDBACK_TEMPLATE.format(
            aggregated_feedback=self.SAMPLE_FEEDBACK.strip(),
        )
        expected = _ORIG_EMAIL_SUBJECT_USER_PROMPT.format(
            feedback_section=feedback_section,
            newsletter_text=self.SAMPLE_NEWSLETTER,
        )
        assert user == expected

    def test_system_prompt_length_unchanged(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        system, _ = build_email_subject_prompt(self.SAMPLE_NEWSLETTER)
        assert len(system) == 558

    def test_instruction_template_length_unchanged(self) -> None:
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("email-subject")
        assert len(instruction) == 553


# ---------------------------------------------------------------------------
# Cross-process: JSON templates match raw constants
# ---------------------------------------------------------------------------


class TestRawTemplateRegression:
    """Verify that the raw JSON prompt templates match the original constants.

    These tests compare the templates *before* any .format() substitution,
    catching whitespace drift that might not surface in formatted output tests.
    """

    def test_summarization_system_raw(self) -> None:
        from ica.llm_configs import get_process_prompts

        system, _ = get_process_prompts("summarization")
        assert system == _ORIG_SUMMARIZATION_SYSTEM_PROMPT

    def test_summarization_instruction_raw(self) -> None:
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("summarization")
        assert instruction == _ORIG_SUMMARIZATION_USER_PROMPT

    def test_email_subject_system_raw(self) -> None:
        from ica.llm_configs import get_process_prompts

        system, _ = get_process_prompts("email-subject")
        assert system == _ORIG_EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_email_subject_instruction_raw(self) -> None:
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("email-subject")
        assert instruction == _ORIG_EMAIL_SUBJECT_USER_PROMPT
