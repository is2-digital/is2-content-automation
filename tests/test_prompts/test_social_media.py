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
    """Verify the Phase 1 system prompt contains all required sections."""

    def test_contains_graphics_only_instruction(self):
        assert "graphics-only social media posts" in _POST_SYSTEM

    def test_contains_phase_1_label(self):
        assert "Phase 1" in _POST_SYSTEM

    def test_contains_12_posts_instruction(self):
        assert "12 posts" in _POST_SYSTEM
        assert "6 DYK + 6 IT" in _POST_SYSTEM

    def test_contains_no_captions_instruction(self):
        assert "no captions yet" in _POST_SYSTEM

    # --- IS2 service areas ---

    def test_contains_custom_software(self):
        assert "Custom Software Development" in _POST_SYSTEM

    def test_contains_ai_implementation(self):
        assert "AI Implementation" in _POST_SYSTEM

    def test_contains_digital_transformation(self):
        assert "Digital Transformation" in _POST_SYSTEM

    def test_contains_legacy_modernization(self):
        assert "Legacy Modernization" in _POST_SYSTEM

    # --- Graphic limits ---

    def test_contains_65_word_limit(self):
        assert "65 words" in _POST_SYSTEM

    def test_contains_360_char_limit(self):
        assert "360 characters" in _POST_SYSTEM

    # --- Content source rules ---

    def test_contains_no_external_sources(self):
        assert "Do NOT fetch external sources" in _POST_SYSTEM

    def test_contains_no_alternate_articles(self):
        assert "Do NOT introduce alternate articles" in _POST_SYSTEM

    # --- Article coverage ---

    def test_contains_8_articles_list(self):
        assert "Featured Article" in _POST_SYSTEM
        assert "Main Article 1" in _POST_SYSTEM
        assert "Main Article 2" in _POST_SYSTEM
        assert "Quick Hit 1" in _POST_SYSTEM
        assert "Quick Hit 2" in _POST_SYSTEM
        assert "Quick Hit 3" in _POST_SYSTEM
        assert "Industry News 1" in _POST_SYSTEM
        assert "Industry News 2" in _POST_SYSTEM

    def test_contains_coverage_rule(self):
        assert "must appear at least once" in _POST_SYSTEM

    # --- Post type requirements ---

    def test_contains_dyk_requirements(self):
        assert "DID YOU KNOW (DYK)" in _POST_SYSTEM
        assert "Did You Know?" in _POST_SYSTEM

    def test_contains_it_requirements(self):
        assert "INSIDE TIP (IT)" in _POST_SYSTEM
        assert "*Inside Tip:*" in _POST_SYSTEM

    # --- Content selection rules ---

    def test_contains_prioritize_rules(self):
        assert "PRIORITIZE content that" in _POST_SYSTEM

    def test_contains_exclude_rules(self):
        assert "EXCLUDE content that" in _POST_SYSTEM

    # --- Language and tone ---

    def test_contains_voice_rules(self):
        assert "Conversational authority" in _POST_SYSTEM

    def test_contains_qualified_phrasing(self):
        assert "qualified phrasing" in _POST_SYSTEM

    # --- Quality bar ---

    def test_contains_quality_bar(self):
        assert "INTERNAL QUALITY BAR" in _POST_SYSTEM
        assert "3.8" in _POST_SYSTEM

    def test_contains_scoring_criteria(self):
        assert "Business relevance (35%)" in _POST_SYSTEM
        assert "Surprise paired with specificity (25%)" in _POST_SYSTEM
        assert "IS2 service alignment (25%)" in _POST_SYSTEM
        assert "Engagement potential (15%)" in _POST_SYSTEM

    def test_contains_do_not_show_scores(self):
        assert "DO NOT SHOW SCORES" in _POST_SYSTEM


class TestSocialMediaPostUserPrompt:
    """Verify the Phase 1 user prompt template."""

    def test_contains_newsletter_placeholder(self):
        assert "{newsletter_content}" in _POST_INSTRUCTION

    def test_contains_theme_placeholder(self):
        assert "{formatted_theme}" in _POST_INSTRUCTION

    def test_contains_slack_format_instruction(self):
        assert "SLACK OPTIMIZED" in _POST_INSTRUCTION

    def test_contains_dyk_output_format(self):
        assert "DYK #1" in _POST_INSTRUCTION

    def test_contains_it_output_format(self):
        assert "IT #1" in _POST_INSTRUCTION

    def test_contains_final_hard_stops(self):
        assert "No captions" in _POST_INSTRUCTION
        assert "No explanations" in _POST_INSTRUCTION


# ===========================================================================
# Phase 2 — Caption generation system prompt
# ===========================================================================


class TestSocialMediaCaptionSystemPrompt:
    """Verify the Phase 2 caption system prompt."""

    def test_contains_authoritative_data_instruction(self):
        assert "AUTHORITATIVE" in _CAPTION_SYSTEM

    def test_contains_posts_array_primary(self):
        assert "Posts Array (PRIMARY" in _CAPTION_SYSTEM

    def test_contains_newsletter_context_only(self):
        assert "CONTEXT ONLY" in _CAPTION_SYSTEM

    # --- Data integrity ---

    def test_contains_data_integrity_rules(self):
        assert "DATA INTEGRITY RULES" in _CAPTION_SYSTEM

    def test_contains_use_verbatim(self):
        assert "VERBATIM" in _CAPTION_SYSTEM

    def test_contains_no_create_infer(self):
        assert "MUST NOT create, infer, guess" in _CAPTION_SYSTEM

    # --- Caption structure ---

    def test_contains_caption_structure(self):
        assert "CAPTION STRUCTURE" in _CAPTION_SYSTEM

    def test_contains_opening_hook_rules(self):
        assert "OPENING HOOK" in _CAPTION_SYSTEM
        assert "Under 15 words" in _CAPTION_SYSTEM

    def test_contains_body_rules(self):
        assert "BODY" in _CAPTION_SYSTEM
        assert "qualified language" in _CAPTION_SYSTEM

    def test_contains_ending_rules(self):
        assert "ENDING" in _CAPTION_SYSTEM
        assert "sourceUrl" in _CAPTION_SYSTEM

    def test_contains_hashtag_rules(self):
        assert "#iS2Digital" in _CAPTION_SYSTEM
        assert "#iS2" in _CAPTION_SYSTEM

    # --- Post-type rules ---

    def test_contains_dyk_caption_rules(self):
        assert "DYK Posts" in _CAPTION_SYSTEM

    def test_contains_it_caption_rules(self):
        assert "IT Posts" in _CAPTION_SYSTEM

    # --- Validation ---

    def test_contains_validation_self_check(self):
        assert "VALIDATION" in _CAPTION_SYSTEM
        assert "SELF-CHECK" in _CAPTION_SYSTEM

    # --- Caption length ---

    def test_contains_caption_length_constraint(self):
        assert "150-300 characters" in _CAPTION_SYSTEM


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

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in _CAPTION_INSTRUCTION

    def test_contains_slack_optimized(self):
        assert "SLACK OPTIMIZED" in _CAPTION_INSTRUCTION


# ===========================================================================
# Caption regeneration prompts
# ===========================================================================


class TestSocialMediaRegenerationSystemPrompt:
    """Verify the regeneration system prompt."""

    def test_contains_regeneration_header(self):
        assert "REGENERATION" in _REGEN_SYSTEM

    def test_contains_apply_feedback(self):
        assert "applying the feedback" in _REGEN_SYSTEM

    def test_contains_do_not_modify_rules(self):
        assert "Do NOT modify" in _REGEN_SYSTEM

    def test_contains_preserve_structure(self):
        assert "CAPTION STRUCTURE TO PRESERVE" in _REGEN_SYSTEM

    def test_contains_validation_rules(self):
        assert "VALIDATION" in _REGEN_SYSTEM

    def test_contains_caption_length(self):
        assert "150-300 characters" in _REGEN_SYSTEM

    def test_contains_no_new_facts(self):
        assert "Do NOT introduce new facts" in _REGEN_SYSTEM


class TestSocialMediaRegenerationUserPrompt:
    """Verify the regeneration user prompt template."""

    def test_contains_feedback_placeholder(self):
        assert "{feedback_text}" in _REGEN_INSTRUCTION

    def test_contains_previous_captions_placeholder(self):
        assert "{previous_captions}" in _REGEN_INSTRUCTION

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in _REGEN_INSTRUCTION


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
