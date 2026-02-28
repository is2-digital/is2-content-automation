"""Tests for ica.prompts.social_media."""

from __future__ import annotations

from typing import ClassVar

from ica.llm_configs import get_process_prompts
from ica.prompts.social_media import (
    build_social_media_caption_prompt,
    build_social_media_post_prompt,
    build_social_media_regeneration_prompt,
)

# Load prompts from JSON config (same source the builder functions use).
_POST_SYSTEM, _POST_INSTRUCTION = get_process_prompts("social-media-post")
_CAPTION_SYSTEM, _CAPTION_INSTRUCTION = get_process_prompts("social-media-caption")
_REGEN_SYSTEM, _REGEN_INSTRUCTION = get_process_prompts("social-media-regeneration")


# ===========================================================================
# Phase 1 — Social media post (graphics-only) system prompt
# ===========================================================================


class TestSocialMediaPostSystemPrompt:
    """Verify the Phase 1 system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        from ica.llm_configs.loader import get_system_prompt

        assert _POST_SYSTEM == get_system_prompt()

    def test_contains_zero_hallucination(self):
        assert "ZERO HALLUCINATION" in _POST_SYSTEM

    def test_contains_headless_api(self):
        assert "HEADLESS API" in _POST_SYSTEM

    def test_is_string(self):
        assert isinstance(_POST_SYSTEM, str)

    def test_not_empty(self):
        assert len(_POST_SYSTEM) > 100


class TestSocialMediaPostUserPrompt:
    """Verify the Phase 1 user prompt template."""

    def test_contains_newsletter_placeholder(self):
        assert "{newsletter_content}" in _POST_INSTRUCTION

    def test_contains_theme_placeholder(self):
        assert "{formatted_theme}" in _POST_INSTRUCTION

    def test_contains_slack_optimized_structure(self):
        assert "Slack-optimized" in _POST_INSTRUCTION

    def test_contains_dyk_output_format(self):
        assert "DYK #1" in _POST_INSTRUCTION

    def test_contains_it_output_format(self):
        assert "IT #1" in _POST_INSTRUCTION

    def test_contains_output_protocol(self):
        assert "Do NOT include captions" in _POST_INSTRUCTION
        assert "Do NOT include" in _POST_INSTRUCTION


# ===========================================================================
# Phase 2 — Caption generation system prompt
# ===========================================================================


class TestSocialMediaCaptionSystemPrompt:
    """Verify the Phase 2 caption system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        from ica.llm_configs.loader import get_system_prompt

        assert _CAPTION_SYSTEM == get_system_prompt()

    def test_contains_zero_hallucination(self):
        assert "ZERO HALLUCINATION" in _CAPTION_SYSTEM

    def test_contains_headless_api(self):
        assert "HEADLESS API" in _CAPTION_SYSTEM

    def test_is_string(self):
        assert isinstance(_CAPTION_SYSTEM, str)

    def test_not_empty(self):
        assert len(_CAPTION_SYSTEM) > 100


class TestSocialMediaCaptionUserPrompt:
    """Verify the Phase 2 caption user prompt template."""

    def test_contains_posts_placeholder(self):
        assert "{posts_json}" in _CAPTION_INSTRUCTION

    def test_contains_all_article_placeholders(self):
        assert "{featured_article}" in _CAPTION_INSTRUCTION
        assert "{main_article_1}" in _CAPTION_INSTRUCTION
        assert "{main_article_2}" in _CAPTION_INSTRUCTION
        assert "{quick_hit_1}" in _CAPTION_INSTRUCTION
        assert "{quick_hit_2}" in _CAPTION_INSTRUCTION
        assert "{quick_hit_3}" in _CAPTION_INSTRUCTION
        assert "{industry_news_1}" in _CAPTION_INSTRUCTION
        assert "{industry_news_2}" in _CAPTION_INSTRUCTION

    def test_contains_caption_protocol(self):
        assert "Caption_Protocol" in _CAPTION_INSTRUCTION

    def test_contains_slack_optimized(self):
        assert "Slack-optimized" in _CAPTION_INSTRUCTION


# ===========================================================================
# Caption regeneration prompts
# ===========================================================================


class TestSocialMediaRegenerationSystemPrompt:
    """Verify the regeneration system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        from ica.llm_configs.loader import get_system_prompt

        assert _REGEN_SYSTEM == get_system_prompt()

    def test_contains_zero_hallucination(self):
        assert "ZERO HALLUCINATION" in _REGEN_SYSTEM

    def test_contains_headless_api(self):
        assert "HEADLESS API" in _REGEN_SYSTEM

    def test_is_string(self):
        assert isinstance(_REGEN_SYSTEM, str)

    def test_not_empty(self):
        assert len(_REGEN_SYSTEM) > 100


class TestSocialMediaRegenerationUserPrompt:
    """Verify the regeneration user prompt template."""

    def test_contains_feedback_placeholder(self):
        assert "{feedback_text}" in _REGEN_INSTRUCTION

    def test_contains_previous_captions_placeholder(self):
        assert "{previous_captions}" in _REGEN_INSTRUCTION

    def test_contains_critical_rules(self):
        assert "Critical_Rules" in _REGEN_INSTRUCTION


# ===========================================================================
# Builder functions
# ===========================================================================


class TestBuildSocialMediaPostPrompt:
    """Verify the Phase 1 builder function."""

    def test_returns_tuple(self):
        result = build_social_media_post_prompt("<html>content</html>", "theme data")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        sys_prompt, _ = build_social_media_post_prompt("content", "theme")
        assert sys_prompt == _POST_SYSTEM

    def test_user_prompt_contains_newsletter_content(self):
        _, user_prompt = build_social_media_post_prompt("<html>newsletter</html>", "theme")
        assert "<html>newsletter</html>" in user_prompt

    def test_user_prompt_contains_formatted_theme(self):
        _, user_prompt = build_social_media_post_prompt("content", "my theme data")
        assert "my theme data" in user_prompt

    def test_different_inputs_produce_different_prompts(self):
        _, prompt_a = build_social_media_post_prompt("content A", "theme A")
        _, prompt_b = build_social_media_post_prompt("content B", "theme B")
        assert prompt_a != prompt_b


class TestBuildSocialMediaCaptionPrompt:
    """Verify the Phase 2 builder function."""

    _articles: ClassVar[dict[str, str]] = {
        "posts_json": '[{"title": "test"}]',
        "featured_article": '{"title": "FA"}',
        "main_article_1": '{"title": "M1"}',
        "main_article_2": '{"title": "M2"}',
        "quick_hit_1": '{"title": "Q1"}',
        "quick_hit_2": '{"title": "Q2"}',
        "quick_hit_3": '{"title": "Q3"}',
        "industry_news_1": '{"title": "I1"}',
        "industry_news_2": '{"title": "I2"}',
    }

    def test_returns_tuple(self):
        result = build_social_media_caption_prompt(**self._articles)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        sys_prompt, _ = build_social_media_caption_prompt(**self._articles)
        assert sys_prompt == _CAPTION_SYSTEM

    def test_user_prompt_contains_posts_json(self):
        _, user_prompt = build_social_media_caption_prompt(**self._articles)
        assert '[{"title": "test"}]' in user_prompt

    def test_user_prompt_contains_all_articles(self):
        _, user_prompt = build_social_media_caption_prompt(**self._articles)
        assert '{"title": "FA"}' in user_prompt
        assert '{"title": "M1"}' in user_prompt
        assert '{"title": "M2"}' in user_prompt
        assert '{"title": "Q1"}' in user_prompt
        assert '{"title": "Q2"}' in user_prompt
        assert '{"title": "Q3"}' in user_prompt
        assert '{"title": "I1"}' in user_prompt
        assert '{"title": "I2"}' in user_prompt

    def test_different_posts_produce_different_prompts(self):
        articles_a = dict(self._articles)
        articles_b = dict(self._articles, posts_json='[{"title": "other"}]')
        _, prompt_a = build_social_media_caption_prompt(**articles_a)
        _, prompt_b = build_social_media_caption_prompt(**articles_b)
        assert prompt_a != prompt_b


class TestBuildSocialMediaRegenerationPrompt:
    """Verify the regeneration builder function."""

    def test_returns_tuple(self):
        result = build_social_media_regeneration_prompt("fix tone", "prev captions")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        sys_prompt, _ = build_social_media_regeneration_prompt("feedback", "captions")
        assert sys_prompt == _REGEN_SYSTEM

    def test_user_prompt_contains_feedback(self):
        _, user_prompt = build_social_media_regeneration_prompt("make it shorter", "old captions")
        assert "make it shorter" in user_prompt

    def test_user_prompt_contains_previous_captions(self):
        _, user_prompt = build_social_media_regeneration_prompt(
            "feedback", "previous caption text here"
        )
        assert "previous caption text here" in user_prompt

    def test_different_feedback_produces_different_prompts(self):
        _, prompt_a = build_social_media_regeneration_prompt("fix A", "captions")
        _, prompt_b = build_social_media_regeneration_prompt("fix B", "captions")
        assert prompt_a != prompt_b
