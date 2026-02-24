"""Social media prompt templates — part of the Social Media Generator pipeline step.

Ported from the n8n ``SUB/social_media_generator_subworkflow.json``:

- "Generate Social media post using LLM" — Phase 1: 12 graphics-only posts
  (6 DYK + 6 IT).
- "Generate post captions using LLM" — Phase 2: captions for user-selected
  posts.
- "Re-Generate post captions using LLM" — feedback-driven caption revision.

Model: ``LLM_SOCIAL_MEDIA_MODEL`` / ``LLM_SOCIAL_POST_CAPTION_MODEL`` /
``LLM_SOCIAL_MEDIA_REGENERATION_MODEL`` (all ``anthropic/claude-sonnet-4.5``
via OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts


def build_social_media_post_prompt(
    newsletter_content: str,
    formatted_theme: str,
) -> tuple[str, str]:
    """Build the system and user messages for the social media post LLM call.

    Loads the system and instruction prompts from the ``social-media-post``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Phase 1: generates 12 graphics-only posts (6 DYK + 6 IT) from the
    newsletter HTML content.

    Args:
        newsletter_content: The full HTML newsletter content.
        formatted_theme: The formatted theme object containing article
            metadata (titles, sources, URLs, categories).

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("social-media-post")

    user_prompt = instruction.format(
        newsletter_content=newsletter_content,
        formatted_theme=formatted_theme,
    )

    return system_prompt, user_prompt


def build_social_media_caption_prompt(
    posts_json: str,
    featured_article: str,
    main_article_1: str,
    main_article_2: str,
    quick_hit_1: str,
    quick_hit_2: str,
    quick_hit_3: str,
    industry_news_1: str,
    industry_news_2: str,
) -> tuple[str, str]:
    """Build the system and user messages for the caption generation LLM call.

    Loads the system and instruction prompts from the ``social-media-caption``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Phase 2: generates full captions for the user-selected posts from
    Phase 1.

    Args:
        posts_json: JSON-serialized array of selected posts, each with
            title, originalHeadline, source, sourceUrl,
            graphicComponentInfo, emphasis, graphicText.
        featured_article: JSON string for Featured Article metadata.
        main_article_1: JSON string for Main Article 1 metadata.
        main_article_2: JSON string for Main Article 2 metadata.
        quick_hit_1: JSON string for Quick Hit 1 metadata.
        quick_hit_2: JSON string for Quick Hit 2 metadata.
        quick_hit_3: JSON string for Quick Hit 3 metadata.
        industry_news_1: JSON string for Industry News 1 metadata.
        industry_news_2: JSON string for Industry News 2 metadata.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("social-media-caption")

    user_prompt = instruction.format(
        posts_json=posts_json,
        featured_article=featured_article,
        main_article_1=main_article_1,
        main_article_2=main_article_2,
        quick_hit_1=quick_hit_1,
        quick_hit_2=quick_hit_2,
        quick_hit_3=quick_hit_3,
        industry_news_1=industry_news_1,
        industry_news_2=industry_news_2,
    )

    return system_prompt, user_prompt


def build_social_media_regeneration_prompt(
    feedback_text: str,
    previous_captions: str,
) -> tuple[str, str]:
    """Build the system and user messages for caption regeneration.

    Loads the system and instruction prompts from the
    ``social-media-regeneration`` JSON config via
    :func:`~ica.llm_configs.get_process_prompts`.

    Applies user feedback to previously generated captions while
    preserving structure, sources, and URLs.

    Args:
        feedback_text: The user's free-text feedback from the Slack form.
        previous_captions: The previously generated captions output
            (used as the base for revision).

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("social-media-regeneration")

    user_prompt = instruction.format(
        feedback_text=feedback_text,
        previous_captions=previous_captions,
    )

    return system_prompt, user_prompt
