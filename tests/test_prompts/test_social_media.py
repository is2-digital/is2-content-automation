"""Tests for ica.prompts.social_media."""

from __future__ import annotations

from ica.prompts.social_media import (
    SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT,
    SOCIAL_MEDIA_CAPTION_USER_PROMPT,
    SOCIAL_MEDIA_POST_SYSTEM_PROMPT,
    SOCIAL_MEDIA_POST_USER_PROMPT,
    SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT,
    SOCIAL_MEDIA_REGENERATION_USER_PROMPT,
    build_social_media_caption_prompt,
    build_social_media_post_prompt,
    build_social_media_regeneration_prompt,
)


# ===========================================================================
# Phase 1 — Social media post (graphics-only) system prompt
# ===========================================================================


class TestSocialMediaPostSystemPrompt:
    """Verify the Phase 1 system prompt contains all required sections."""

    def test_contains_graphics_only_instruction(self):
        assert "graphics-only social media posts" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_phase_1_label(self):
        assert "Phase 1" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_12_posts_instruction(self):
        assert "12 posts" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "6 DYK + 6 IT" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_no_captions_instruction(self):
        assert "no captions yet" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- IS2 service areas ---

    def test_contains_custom_software(self):
        assert "Custom Software Development" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_ai_implementation(self):
        assert "AI Implementation" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_digital_transformation(self):
        assert "Digital Transformation" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_legacy_modernization(self):
        assert "Legacy Modernization" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Graphic limits ---

    def test_contains_65_word_limit(self):
        assert "65 words" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_360_char_limit(self):
        assert "360 characters" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Content source rules ---

    def test_contains_no_external_sources(self):
        assert "Do NOT fetch external sources" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_no_alternate_articles(self):
        assert "Do NOT introduce alternate articles" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Article coverage ---

    def test_contains_8_articles_list(self):
        assert "Featured Article" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Main Article 1" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Main Article 2" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Quick Hit 1" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Quick Hit 2" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Quick Hit 3" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Industry News 1" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Industry News 2" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_coverage_rule(self):
        assert "must appear at least once" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Post type requirements ---

    def test_contains_dyk_requirements(self):
        assert "DID YOU KNOW (DYK)" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Did You Know?" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_it_requirements(self):
        assert "INSIDE TIP (IT)" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "*Inside Tip:*" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Content selection rules ---

    def test_contains_prioritize_rules(self):
        assert "PRIORITIZE content that" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_exclude_rules(self):
        assert "EXCLUDE content that" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Language and tone ---

    def test_contains_voice_rules(self):
        assert "Conversational authority" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_qualified_phrasing(self):
        assert "qualified phrasing" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    # --- Quality bar ---

    def test_contains_quality_bar(self):
        assert "INTERNAL QUALITY BAR" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "3.8" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_scoring_criteria(self):
        assert "Business relevance (35%)" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Surprise paired with specificity (25%)" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "IS2 service alignment (25%)" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT
        assert "Engagement potential (15%)" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_contains_do_not_show_scores(self):
        assert "DO NOT SHOW SCORES" in SOCIAL_MEDIA_POST_SYSTEM_PROMPT


class TestSocialMediaPostUserPrompt:
    """Verify the Phase 1 user prompt template."""

    def test_contains_newsletter_placeholder(self):
        assert "{newsletter_content}" in SOCIAL_MEDIA_POST_USER_PROMPT

    def test_contains_theme_placeholder(self):
        assert "{formatted_theme}" in SOCIAL_MEDIA_POST_USER_PROMPT

    def test_contains_slack_format_instruction(self):
        assert "SLACK OPTIMIZED" in SOCIAL_MEDIA_POST_USER_PROMPT

    def test_contains_dyk_output_format(self):
        assert "DYK #1" in SOCIAL_MEDIA_POST_USER_PROMPT

    def test_contains_it_output_format(self):
        assert "IT #1" in SOCIAL_MEDIA_POST_USER_PROMPT

    def test_contains_final_hard_stops(self):
        assert "No captions" in SOCIAL_MEDIA_POST_USER_PROMPT
        assert "No explanations" in SOCIAL_MEDIA_POST_USER_PROMPT


# ===========================================================================
# Phase 2 — Caption generation system prompt
# ===========================================================================


class TestSocialMediaCaptionSystemPrompt:
    """Verify the Phase 2 caption system prompt."""

    def test_contains_authoritative_data_instruction(self):
        assert "AUTHORITATIVE" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_posts_array_primary(self):
        assert "Posts Array (PRIMARY" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_newsletter_context_only(self):
        assert "CONTEXT ONLY" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    # --- Data integrity ---

    def test_contains_data_integrity_rules(self):
        assert "DATA INTEGRITY RULES" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_use_verbatim(self):
        assert "VERBATIM" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_no_create_infer(self):
        assert "MUST NOT create, infer, guess" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    # --- Caption structure ---

    def test_contains_caption_structure(self):
        assert "CAPTION STRUCTURE" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_opening_hook_rules(self):
        assert "OPENING HOOK" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT
        assert "Under 15 words" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_body_rules(self):
        assert "BODY" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT
        assert "qualified language" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_ending_rules(self):
        assert "ENDING" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT
        assert "sourceUrl" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_hashtag_rules(self):
        assert "#iS2Digital" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT
        assert "#iS2" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    # --- Post-type rules ---

    def test_contains_dyk_caption_rules(self):
        assert "DYK Posts" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    def test_contains_it_caption_rules(self):
        assert "IT Posts" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    # --- Validation ---

    def test_contains_validation_self_check(self):
        assert "VALIDATION" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT
        assert "SELF-CHECK" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

    # --- Caption length ---

    def test_contains_caption_length_constraint(self):
        assert "150-300 characters" in SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT


class TestSocialMediaCaptionUserPrompt:
    """Verify the Phase 2 caption user prompt template."""

    def test_contains_posts_placeholder(self):
        assert "{posts_json}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT

    def test_contains_all_article_placeholders(self):
        assert "{featured_article}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{main_article_1}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{main_article_2}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{quick_hit_1}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{quick_hit_2}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{quick_hit_3}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{industry_news_1}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT
        assert "{industry_news_2}" in SOCIAL_MEDIA_CAPTION_USER_PROMPT

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in SOCIAL_MEDIA_CAPTION_USER_PROMPT

    def test_contains_slack_optimized(self):
        assert "SLACK OPTIMIZED" in SOCIAL_MEDIA_CAPTION_USER_PROMPT


# ===========================================================================
# Caption regeneration prompts
# ===========================================================================


class TestSocialMediaRegenerationSystemPrompt:
    """Verify the regeneration system prompt."""

    def test_contains_regeneration_header(self):
        assert "REGENERATION" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_contains_apply_feedback(self):
        assert "applying the feedback" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_contains_do_not_modify_rules(self):
        assert "Do NOT modify" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_contains_preserve_structure(self):
        assert "CAPTION STRUCTURE TO PRESERVE" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_contains_validation_rules(self):
        assert "VALIDATION" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_contains_caption_length(self):
        assert "150-300 characters" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_contains_no_new_facts(self):
        assert "Do NOT introduce new facts" in SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT


class TestSocialMediaRegenerationUserPrompt:
    """Verify the regeneration user prompt template."""

    def test_contains_feedback_placeholder(self):
        assert "{feedback_text}" in SOCIAL_MEDIA_REGENERATION_USER_PROMPT

    def test_contains_previous_captions_placeholder(self):
        assert "{previous_captions}" in SOCIAL_MEDIA_REGENERATION_USER_PROMPT

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in SOCIAL_MEDIA_REGENERATION_USER_PROMPT


# ===========================================================================
# Builder functions
# ===========================================================================


class TestBuildSocialMediaPostPrompt:
    """Verify the Phase 1 builder function."""

    def test_returns_tuple(self):
        result = build_social_media_post_prompt("<html>content</html>", "theme data")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        sys_prompt, _ = build_social_media_post_prompt("content", "theme")
        assert sys_prompt is SOCIAL_MEDIA_POST_SYSTEM_PROMPT

    def test_user_prompt_contains_newsletter_content(self):
        _, user_prompt = build_social_media_post_prompt(
            "<html>newsletter</html>", "theme"
        )
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

    _articles = {
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

    def test_system_prompt_is_constant(self):
        sys_prompt, _ = build_social_media_caption_prompt(**self._articles)
        assert sys_prompt is SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT

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

    def test_system_prompt_is_constant(self):
        sys_prompt, _ = build_social_media_regeneration_prompt("feedback", "captions")
        assert sys_prompt is SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT

    def test_user_prompt_contains_feedback(self):
        _, user_prompt = build_social_media_regeneration_prompt(
            "make it shorter", "old captions"
        )
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
