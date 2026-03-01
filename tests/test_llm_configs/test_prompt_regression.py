"""Regression tests for prompt configuration.

Asserts that ``build_summarization_prompt()`` and ``build_email_subject_prompt()``
produce string-identical output compared to the current XML-tagged JSON configs.

These tests guard against accidental prompt drift when editing JSON config files.
"""

from __future__ import annotations

import pytest

from ica.llm_configs import loader
from ica.llm_configs.loader import _cache, get_system_prompt

# ---------------------------------------------------------------------------
# Reference constants (current XML-tagged prompt configs)
# ---------------------------------------------------------------------------

# -- Summarization ----------------------------------------------------------

_REF_SUMMARIZATION_INSTRUCTION = (
    "<Task_Context>\n"
    "Analyze the provided article data (which includes the URL, Title, and Body)"
    " and generate a structured summary for the iS2 Digital newsletter. \n"
    "</Task_Context>\n"
    "\n"
    "<Input_Data>\n"
    "{article_content}\n"
    "</Input_Data>\n"
    "\n"
    "<Constraint_Rules>\n"
    "1. SUMMARY: 3-4 sentences. Focus on factual content, technical details,"
    " and key findings.\n"
    "2. BUSINESS_RELEVANCE: 2-3 sentences. Explain strategic relevance for"
    " SMB professionals and operations.\n"
    '3. INTEGRITY: No external research. Use ONLY the provided data.'
    ' If content is inaccessible, output "DATA_INCOMPLETE".\n'
    "4. VOICE: Use the declarative patterns defined in your Master System"
    " Instruction. Describe reality directly without hedging.\n"
    "</Constraint_Rules>\n"
    "\n"
    "<Output_Schema>\n"
    "URL: [Extract URL from input]\n"
    "Title: [Extract Title from input]\n"
    "Summary: [Insert 3-4 sentence factual summary]\n"
    "Business Relevance: [Insert 2-3 sentence business relevance commentary]\n"
    "</Output_Schema>\n"
    "\n"
    "<Feedback_Adjustment>\n"
    "{feedback_section}\n"
    "</Feedback_Adjustment>\n"
    "\n"
    "Generate the structured summary now."
)

_SUMMARIZATION_FEEDBACK_TEMPLATE = """\

## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and summarization style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""

# -- Email subject ----------------------------------------------------------

_REF_EMAIL_SUBJECT_INSTRUCTION = (
    "<Task_Context>\n"
    "You are a high-authority B2B editor. Generate 10 definitive email subject"
    " lines for the iS2 newsletter that reflect Kevin's declarative, no-fluff"
    " persona.\n"
    "</Task_Context>\n"
    "\n"
    "<Kevin_Voice_Rules>\n"
    "1. NO HYPERBOLE: Ban words like 'Revolutionizing', 'Unlocking',"
    " 'The Future of', or 'Exciting'.\n"
    "2. DECLARATIVE: Use Pattern A logic: '[Reality] isn't [misconception]."
    " It's [insight].' or similar punchy statements.\n"
    "3. DRY PRECISION: Focus on operational reality or a striking data point"
    " from the text.\n"
    "4. ZERO EMOJIS: Never use emojis or hashtags.\n"
    "</Kevin_Voice_Rules>\n"
    "\n"
    "<Technical_Constraints>\n"
    "1. LENGTH: Strictly 7 words or fewer per subject line.\n"
    "2. SOURCE: Base all subjects on {newsletter_text}.\n"
    "3. REVISION: Apply {feedback_section} to refine the tone or focus.\n"
    "</Technical_Constraints>\n"
    "\n"
    "<Output_Format_MANDATORY>\n"
    "Return clean plain text. No markdown formatting, no colons in headers.\n"
    "The ---- delimiter between subjects is mandatory for downstream parsing.\n"
    "\n"
    "Subject_1: [Subject Text]\n"
    "----\n"
    "Subject_2: [Subject Text]\n"
    "----\n"
    "(Repeat through Subject_10)\n"
    "\n"
    "RECOMMENDATION: Subject [Number] - [Subject Text]\n"
    "[Brief 1-sentence explanation of why this fits the Kevin persona best.]\n"
    "\n"
    "Example (2 of 10 shown):\n"
    "Subject_1: AI Agents Replace Dashboards Not People\n"
    "----\n"
    "Subject_2: Your Competitor Already Automated This\n"
    "----\n"
    "</Output_Format_MANDATORY>"
)

_EMAIL_SUBJECT_FEEDBACK_TEMPLATE = """\


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
    loader._system_prompt_cache = None


# ---------------------------------------------------------------------------
# Summarization regression tests
# ---------------------------------------------------------------------------


class TestSummarizationPromptRegression:
    """Assert JSON-loaded summarization prompts match reference XML-tagged versions."""

    SAMPLE_ARTICLE = (
        "https://example.com/article "
        "AI Revolution in SMB "
        "<p>Article body about AI in small business...</p>"
    )
    SAMPLE_FEEDBACK = "- Use shorter sentences\n- Avoid jargon"

    def test_system_prompt_is_shared(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        system, _ = build_summarization_prompt(self.SAMPLE_ARTICLE)
        assert system == get_system_prompt()

    def test_user_prompt_without_feedback_matches_reference(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        _, user = build_summarization_prompt(self.SAMPLE_ARTICLE)
        expected = _REF_SUMMARIZATION_INSTRUCTION.format(
            feedback_section="",
            article_content=self.SAMPLE_ARTICLE,
        )
        assert user == expected

    def test_user_prompt_with_feedback_matches_reference(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        _, user = build_summarization_prompt(self.SAMPLE_ARTICLE, self.SAMPLE_FEEDBACK)
        feedback_section = _SUMMARIZATION_FEEDBACK_TEMPLATE.format(
            aggregated_feedback=self.SAMPLE_FEEDBACK.strip(),
        )
        expected = _REF_SUMMARIZATION_INSTRUCTION.format(
            feedback_section=feedback_section,
            article_content=self.SAMPLE_ARTICLE,
        )
        assert user == expected

    def test_instruction_template_length_unchanged(self) -> None:
        """Guard against truncation or whitespace drift in the raw template."""
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("summarization")
        assert len(instruction) == 1016


# ---------------------------------------------------------------------------
# Email subject regression tests
# ---------------------------------------------------------------------------


class TestEmailSubjectPromptRegression:
    """Assert JSON-loaded email-subject prompts match reference XML-tagged versions."""

    SAMPLE_NEWSLETTER = (
        "This week in AI: New breakthroughs in language models. "
        "GPT-5 rumors surface. Anthropic launches new features."
    )
    SAMPLE_FEEDBACK = "- Make subjects punchier\n- Focus on AI trends"

    def test_system_prompt_is_shared(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        system, _ = build_email_subject_prompt(self.SAMPLE_NEWSLETTER)
        assert system == get_system_prompt()

    def test_user_prompt_without_feedback_matches_reference(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        _, user = build_email_subject_prompt(self.SAMPLE_NEWSLETTER)
        expected = _REF_EMAIL_SUBJECT_INSTRUCTION.format(
            feedback_section="",
            newsletter_text=self.SAMPLE_NEWSLETTER,
        )
        assert user == expected

    def test_user_prompt_with_feedback_matches_reference(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        _, user = build_email_subject_prompt(self.SAMPLE_NEWSLETTER, self.SAMPLE_FEEDBACK)
        feedback_section = _EMAIL_SUBJECT_FEEDBACK_TEMPLATE.format(
            aggregated_feedback=self.SAMPLE_FEEDBACK.strip(),
        )
        expected = _REF_EMAIL_SUBJECT_INSTRUCTION.format(
            feedback_section=feedback_section,
            newsletter_text=self.SAMPLE_NEWSLETTER,
        )
        assert user == expected

    def test_instruction_template_length_unchanged(self) -> None:
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("email-subject")
        assert len(instruction) == 1346


# ---------------------------------------------------------------------------
# Cross-process: JSON templates match raw constants
# ---------------------------------------------------------------------------


class TestRawTemplateRegression:
    """Verify that the raw JSON prompt templates match the reference constants.

    These tests compare the templates *before* any .format() substitution,
    catching whitespace drift that might not surface in formatted output tests.
    """

    def test_summarization_system_is_shared(self) -> None:
        from ica.llm_configs import get_process_prompts

        system, _ = get_process_prompts("summarization")
        assert system == get_system_prompt()

    def test_summarization_instruction_raw(self) -> None:
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("summarization")
        assert instruction == _REF_SUMMARIZATION_INSTRUCTION

    def test_email_subject_system_is_shared(self) -> None:
        from ica.llm_configs import get_process_prompts

        system, _ = get_process_prompts("email-subject")
        assert system == get_system_prompt()

    def test_email_subject_instruction_raw(self) -> None:
        from ica.llm_configs import get_process_prompts

        _, instruction = get_process_prompts("email-subject")
        assert instruction == _REF_EMAIL_SUBJECT_INSTRUCTION
