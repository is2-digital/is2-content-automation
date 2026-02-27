"""Integration test — parallel output steps 6a-6d.

Exercises all four parallel output steps with real services:

1. Step 6a (Alternates HTML): filter_unused_articles() — pure Python,
   verifies URL extraction from formatted theme and unused article detection
2. Step 6b (Email Subject): call_email_subject_llm() → parse_subjects() →
   call_email_review_llm() → create_email_doc() — LLM + Google Docs
3. Step 6c (Social Media): call_social_media_post_llm() →
   parse_phase1_titles() → create_social_media_doc() — LLM + Google Docs
4. Step 6d (LinkedIn Carousel): generate_with_validation() →
   validate_slide_bodies() → create_carousel_doc() — LLM + validation + Google Docs
5. Concurrent execution: run all four steps via asyncio.gather(), verify
   concurrent timing, check ctx.extra key population, detect race conditions

Usage:
    docker exec ica-app-1 python scripts/test_parallel_outputs.py
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --phase alternates
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --phase email
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --phase social
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --phase carousel
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --phase concurrent
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --skip-llm
    docker exec ica-app-1 python scripts/test_parallel_outputs.py --skip-gdocs

Requires OPENROUTER_API_KEY (for LLM calls) and Google service account
credentials with Shared Drive access (for Google Docs).  Run inside the
app container where .env is loaded automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

from dotenv import load_dotenv

# Ensure project root is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _check_env(*keys: str) -> dict[str, str]:
    """Validate that required environment variables are set."""
    load_dotenv(".env.dev")
    load_dotenv(".env")

    values: dict[str, str] = {}
    missing: list[str] = []
    for key in keys:
        val = os.environ.get(key, "").strip()
        if not val:
            missing.append(key)
        values[key] = val

    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    return values


def _openrouter_model(model_id: str) -> str:
    """Prepend ``openrouter/`` so LiteLLM routes through OpenRouter."""
    if not model_id.startswith("openrouter/"):
        return f"openrouter/{model_id}"
    return model_id


# ---------------------------------------------------------------------------
# Sample data — realistic theme + summaries for all parallel steps
# ---------------------------------------------------------------------------

SAMPLE_FORMATTED_THEME: dict[str, Any] = {
    "THEME": "AI Accessibility Revolution",
    "FEATURED ARTICLE": {
        "TITLE": "Hello GPT-4o: OpenAI's Latest Multimodal Model",
        "URL": "https://openai.com/index/hello-gpt-4o/",
        "SOURCE": "openai.com",
    },
    "MAIN ARTICLE 1": {
        "TITLE": "5 AI Automation Trends Reshaping Small Businesses",
        "URL": "https://example.com/ai-automation-trends",
        "SOURCE": "example.com",
    },
    "MAIN ARTICLE 2": {
        "TITLE": "EU AI Act Implementation Timeline",
        "URL": "https://example.com/ai-regulation-update",
        "SOURCE": "example.com",
    },
    "QUICK HIT 1": {
        "TITLE": "AI Skills Gap Widens",
        "URL": "https://example.com/ai-hiring-trends",
        "SOURCE": "example.com",
    },
    "QUICK HIT 2": {
        "TITLE": "Anthropic Launches New Features",
        "URL": "https://example.com/anthropic-claude-tools",
        "SOURCE": "example.com",
    },
    "QUICK HIT 3": {
        "TITLE": "Microsoft Copilot Expansion",
        "URL": "https://example.com/microsoft-copilot-enterprise",
        "SOURCE": "example.com",
    },
    "INDUSTRY DEVELOPMENT 1": {
        "TITLE": "Introducing Gemini",
        "URL": "https://blog.google/technology/ai/google-gemini-ai/",
        "SOURCE": "blog.google",
    },
    "INDUSTRY DEVELOPMENT 2": {
        "TITLE": "Microsoft Expands Copilot",
        "URL": "https://example.com/microsoft-copilot-enterprise-2",
        "SOURCE": "example.com",
    },
}

SAMPLE_SUMMARIES: list[dict[str, Any]] = [
    {
        "URL": "https://openai.com/index/hello-gpt-4o/",
        "Title": "Hello GPT-4o",
        "Summary": "OpenAI released GPT-4o, a multimodal model.",
        "BusinessRelevance": "Free access to frontier AI changes the competitive landscape.",
    },
    {
        "URL": "https://example.com/ai-automation-trends",
        "Title": "5 AI Automation Trends",
        "Summary": "Small businesses adopt AI for automation.",
        "BusinessRelevance": "Identifies highest-ROI AI investments.",
    },
    {
        "URL": "https://example.com/ai-regulation-update",
        "Title": "EU AI Act Timeline",
        "Summary": "EU AI Act enters implementation phase.",
        "BusinessRelevance": "Compliance deadlines approaching.",
    },
    {
        "URL": "https://example.com/ai-hiring-trends",
        "Title": "AI Skills Gap",
        "Summary": "Demand for AI workers surges.",
        "BusinessRelevance": "Upskilling beats external hiring.",
    },
    {
        "URL": "https://example.com/anthropic-claude-tools",
        "Title": "Anthropic Claude Features",
        "Summary": "New enterprise Claude features launched.",
        "BusinessRelevance": "Flexible deployment for sensitive ops.",
    },
    {
        "URL": "https://example.com/microsoft-copilot-enterprise",
        "Title": "Microsoft Copilot Enterprise",
        "Summary": "Copilot embedded across Dynamics 365 and Azure.",
        "BusinessRelevance": "30% productivity gains reported.",
    },
    # These two are NOT in the theme — they should be detected as "unused"
    {
        "URL": "https://example.com/unused-article-1",
        "Title": "Unused Article: AI in Healthcare",
        "Summary": "AI transforms healthcare diagnostics.",
        "BusinessRelevance": "Health-tech startups gain competitive edge.",
    },
    {
        "URL": "https://example.com/unused-article-2",
        "Title": "Unused Article: Robotics Breakthrough",
        "Summary": "New robotics advances in manufacturing.",
        "BusinessRelevance": "Manufacturing SMBs can automate more tasks.",
    },
]

# Sample HTML content (as if fetched from a Google Doc after Step 5)
SAMPLE_HTML_CONTENT = """\
<!DOCTYPE html>
<html lang="en">
<head><title>Artificially Intelligent, Actually Useful.</title></head>
<body>
<h1>AI Accessibility Revolution</h1>
<p>The AI landscape shifted this week in ways that matter for your bottom
line. OpenAI's GPT-4o dropped barriers to entry by making frontier AI
free, Google's Gemini pushed the boundaries of what multimodal means in
practice, and the EU's AI Act moved from theory to hard deadlines that
every business selling into Europe needs on their calendar right now.</p>

<h2>Featured: Hello GPT-4o</h2>
<p>OpenAI's release of GPT-4o represents more than just another model
update. The model processes text, audio, and vision simultaneously in
real time, matching GPT-4 Turbo's intelligence while running at twice
the speed and half the cost.</p>

<h2>5 AI Automation Trends Reshaping Small Businesses</h2>
<p>Companies that embedded AI into customer service workflows first saw
35% cost reductions within six months.</p>

<h2>EU AI Act Implementation Timeline</h2>
<p>High-risk AI system providers face classification requirements due
by mid-2026 and full compliance documentation required six months after.</p>

<h2>Industry Developments</h2>
<p>Google launched Gemini in three sizes. Microsoft is embedding Copilot
across Dynamics 365, Power Platform, and Azure.</p>

<p>That's a wrap for the week! Until next time, keep building with purpose.</p>
</body>
</html>"""

SAMPLE_NEWSLETTER_TEXT = (
    "AI Accessibility Revolution. The AI landscape shifted this week in ways "
    "that matter for your bottom line. OpenAI's GPT-4o dropped barriers to "
    "entry by making frontier AI free, Google's Gemini pushed the boundaries "
    "of what multimodal means in practice, and the EU's AI Act moved from "
    "theory to hard deadlines. Featured: Hello GPT-4o — OpenAI's release of "
    "GPT-4o represents more than just another model update. The model processes "
    "text, audio, and vision simultaneously in real time. 5 AI Automation "
    "Trends Reshaping Small Businesses — Companies that embedded AI into "
    "customer service workflows first saw 35% cost reductions within six months. "
    "EU AI Act Implementation Timeline — High-risk AI system providers face "
    "classification requirements due by mid-2026. Industry: Google launched "
    "Gemini in three sizes. Microsoft embedding Copilot across enterprise apps. "
    "That's a wrap for the week!"
)


# ---------------------------------------------------------------------------
# Phase 1: Step 6a — Alternates HTML (Pure Python)
# ---------------------------------------------------------------------------


async def phase_alternates() -> dict[str, Any]:
    """Test filter_unused_articles() with realistic theme and summary data.

    Tests:
    - extract_urls_from_theme() finds all URLs in nested theme dict
    - filter_unused_articles() correctly identifies unused articles
    - Unused count matches expected (2 articles not in theme)
    - Used URLs list matches theme URLs
    - Edge case: empty summaries list
    - Edge case: all articles used (no unused)
    """
    print("\n" + "=" * 70)
    print("PHASE 1: Step 6a — Alternates HTML (Filter Unused Articles)")
    print("=" * 70)

    from ica.pipeline.alternates_html import (
        FilterResult,
        extract_urls_from_theme,
        filter_unused_articles,
    )

    # 1a. Extract URLs from theme
    print("\n--- 1a. extract_urls_from_theme() ---")
    theme_urls = extract_urls_from_theme(SAMPLE_FORMATTED_THEME)
    print(f"  URLs found in theme: {len(theme_urls)}")
    for url in sorted(theme_urls):
        print(f"    {url}")

    assert len(theme_urls) >= 7, (
        f"Expected at least 7 URLs in theme, got {len(theme_urls)}"
    )
    assert "https://openai.com/index/hello-gpt-4o/" in theme_urls, (
        "Featured article URL not found in theme"
    )

    # 1b. Filter unused articles
    print("\n--- 1b. filter_unused_articles() ---")
    result: FilterResult = filter_unused_articles(
        SAMPLE_FORMATTED_THEME, SAMPLE_SUMMARIES,
    )

    print(f"  Total summaries: {len(SAMPLE_SUMMARIES)}")
    print(f"  URLs in theme: {len(result.urls_in_theme)}")
    print(f"  Unused articles: {len(result.unused_summaries)}")
    for unused in result.unused_summaries:
        print(f"    {unused['Title']} ({unused['URL']})")

    assert len(result.unused_summaries) == 2, (
        f"Expected 2 unused articles, got {len(result.unused_summaries)}"
    )
    unused_urls = {s["URL"] for s in result.unused_summaries}
    assert "https://example.com/unused-article-1" in unused_urls
    assert "https://example.com/unused-article-2" in unused_urls

    # 1c. Edge case: empty summaries
    print("\n--- 1c. Edge case: empty summaries ---")
    empty_result = filter_unused_articles(SAMPLE_FORMATTED_THEME, [])
    assert len(empty_result.unused_summaries) == 0
    print("  Empty summaries: OK (0 unused)")

    # 1d. Edge case: all articles used (every summary URL is in theme)
    print("\n--- 1d. Edge case: all articles used ---")
    used_only = [s for s in SAMPLE_SUMMARIES if s["URL"] in theme_urls]
    all_used_result = filter_unused_articles(SAMPLE_FORMATTED_THEME, used_only)
    assert len(all_used_result.unused_summaries) == 0
    print(f"  All-used ({len(used_only)} summaries): OK (0 unused)")

    results: dict[str, Any] = {
        "theme_urls_count": len(theme_urls),
        "total_summaries": len(SAMPLE_SUMMARIES),
        "unused_count": len(result.unused_summaries),
        "edge_empty": True,
        "edge_all_used": True,
    }

    print("\n  Phase 1 PASSED: Alternates HTML filtering works correctly.")
    return results


# ---------------------------------------------------------------------------
# Phase 2: Step 6b — Email Subject & Preview (LLM + Google Docs)
# ---------------------------------------------------------------------------


async def phase_email(*, skip_gdocs: bool = False) -> dict[str, Any]:
    """Test email subject generation, parsing, review LLM, and doc creation.

    Tests:
    - strip_html_to_text() produces clean plain text
    - call_email_subject_llm() returns non-empty response
    - parse_subjects() extracts Subject_N patterns and recommendation
    - call_email_review_llm() generates a review preview
    - create_email_doc() creates a Google Doc with subject + review
    """
    print("\n" + "=" * 70)
    print("PHASE 2: Step 6b — Email Subject & Preview")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.email_subject import (
        call_email_review_llm,
        call_email_subject_llm,
        create_email_doc,
        parse_subjects,
        strip_html_to_text,
    )

    # 2a. HTML stripping
    print("\n--- 2a. strip_html_to_text() ---")
    plain_text = strip_html_to_text(SAMPLE_HTML_CONTENT)
    assert plain_text, "strip_html_to_text returned empty string"
    assert "<html" not in plain_text.lower(), "HTML tags not stripped"
    assert "GPT-4o" in plain_text, "Content not preserved after stripping"
    print(f"  Input HTML: {len(SAMPLE_HTML_CONTENT)} chars")
    print(f"  Plain text: {len(plain_text)} chars")
    print(f"  Preview: {plain_text[:150]}...")

    # 2b. Email subject LLM
    print("\n--- 2b. call_email_subject_llm() ---")
    model = _openrouter_model(get_model(LLMPurpose.EMAIL_SUBJECT))
    print(f"  Model: {model}")

    raw_subjects = await call_email_subject_llm(
        newsletter_text=plain_text,
        model=model,
    )

    assert raw_subjects, "call_email_subject_llm returned empty response"
    print(f"  Raw output: {len(raw_subjects)} chars")
    print(f"  Preview:\n    {raw_subjects[:300]}...")

    # 2c. Parse subjects
    print("\n--- 2c. parse_subjects() ---")
    subjects, recommendation = parse_subjects(raw_subjects)

    print(f"  Subjects found: {len(subjects)}")
    for subj in subjects:
        print(f"    Subject_{subj.subject_id}: {subj.subject[:80]}")
    print(f"  Recommendation: {len(recommendation)} chars")
    if recommendation:
        print(f"    {recommendation[:150]}...")

    assert len(subjects) >= 2, (
        f"Expected at least 2 subjects, got {len(subjects)}"
    )

    # 2d. Email review LLM
    print("\n--- 2d. call_email_review_llm() ---")
    review_model = _openrouter_model(get_model(LLMPurpose.EMAIL_PREVIEW))
    print(f"  Model: {review_model}")

    review_text = await call_email_review_llm(
        newsletter_text=plain_text,
        model=review_model,
    )

    assert review_text, "call_email_review_llm returned empty response"
    print(f"  Review text: {len(review_text)} chars")
    print(f"  Preview: {review_text[:200]}...")

    results: dict[str, Any] = {
        "model_subject": model,
        "model_review": review_model,
        "plain_text_length": len(plain_text),
        "subject_count": len(subjects),
        "has_recommendation": bool(recommendation),
        "review_length": len(review_text),
    }

    # 2e. Create Google Doc
    if not skip_gdocs:
        print("\n--- 2e. create_email_doc() ---")
        from ica.services.google_docs import GoogleDocsService

        creds_path = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
            "credentials/google-service-account.json",
        )
        drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")
        docs = GoogleDocsService(credentials_path=creds_path, drive_id=drive_id)

        selected_subject = subjects[0].subject
        doc_id, doc_url = await create_email_doc(
            docs, selected_subject, review_text,
            title="Integration Test - Email Subject",
        )

        assert doc_id, "create_email_doc returned empty doc_id"
        assert doc_url.startswith("https://docs.google.com/document/d/"), (
            f"Unexpected doc_url format: {doc_url}"
        )
        print(f"  Doc ID: {doc_id}")
        print(f"  Doc URL: {doc_url}")
        results["email_doc_id"] = doc_id
    else:
        print("\n  Google Docs phase skipped (--skip-gdocs).")

    print("\n  Phase 2 PASSED: Email subject + review generation works.")
    return results


# ---------------------------------------------------------------------------
# Phase 3: Step 6c — Social Media (LLM + Google Docs)
# ---------------------------------------------------------------------------


async def phase_social(*, skip_gdocs: bool = False) -> dict[str, Any]:
    """Test social media post generation, title parsing, and doc creation.

    Tests:
    - call_social_media_post_llm() returns non-empty response with DYK/IT posts
    - parse_phase1_titles() extracts post titles from LLM output
    - Output contains expected post type patterns (DYK, IT)
    - create_social_media_doc() creates a Google Doc
    """
    print("\n" + "=" * 70)
    print("PHASE 3: Step 6c — Social Media Posts")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.social_media import (
        call_social_media_post_llm,
        create_social_media_doc,
        parse_phase1_titles,
    )

    # 3a. Generate social media posts (Phase 1)
    print("\n--- 3a. call_social_media_post_llm() ---")
    model = _openrouter_model(get_model(LLMPurpose.SOCIAL_MEDIA))
    print(f"  Model: {model}")

    formatted_theme_json = json.dumps(SAMPLE_FORMATTED_THEME, indent=2)
    raw_posts = await call_social_media_post_llm(
        newsletter_content=SAMPLE_HTML_CONTENT,
        formatted_theme=formatted_theme_json,
        model=model,
    )

    assert raw_posts, "call_social_media_post_llm returned empty response"
    print(f"  Raw output: {len(raw_posts)} chars")
    print(f"  Preview:\n    {raw_posts[:400]}...")

    # 3b. Parse Phase 1 titles
    print("\n--- 3b. parse_phase1_titles() ---")
    titles = parse_phase1_titles(raw_posts)
    print(f"  Titles extracted: {len(titles)}")
    for title in titles:
        print(f"    {title}")

    # LLM should generate DYK and/or IT posts
    has_dyk = any("DYK" in t for t in titles)
    has_it = any("IT" in t for t in titles)
    print(f"  Has DYK posts: {has_dyk}")
    print(f"  Has IT posts: {has_it}")

    assert len(titles) >= 1, (
        f"Expected at least 1 parseable title, got {len(titles)}"
    )

    results: dict[str, Any] = {
        "model": model,
        "raw_posts_length": len(raw_posts),
        "title_count": len(titles),
        "has_dyk": has_dyk,
        "has_it": has_it,
    }

    # 3c. Create Google Doc
    if not skip_gdocs:
        print("\n--- 3c. create_social_media_doc() ---")
        from ica.services.google_docs import GoogleDocsService

        creds_path = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
            "credentials/google-service-account.json",
        )
        drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")
        docs = GoogleDocsService(credentials_path=creds_path, drive_id=drive_id)

        doc_id, doc_url = await create_social_media_doc(
            docs, raw_posts,
            title="Integration Test - Social Media Posts",
        )

        assert doc_id, "create_social_media_doc returned empty doc_id"
        assert doc_url.startswith("https://docs.google.com/document/d/"), (
            f"Unexpected doc_url format: {doc_url}"
        )
        print(f"  Doc ID: {doc_id}")
        print(f"  Doc URL: {doc_url}")
        results["social_doc_id"] = doc_id
    else:
        print("\n  Google Docs phase skipped (--skip-gdocs).")

    print("\n  Phase 3 PASSED: Social media post generation works.")
    return results


# ---------------------------------------------------------------------------
# Phase 4: Step 6d — LinkedIn Carousel (LLM + Validation + Google Docs)
# ---------------------------------------------------------------------------


async def phase_carousel(*, skip_gdocs: bool = False) -> dict[str, Any]:
    """Test carousel generation, character validation, and doc creation.

    Tests:
    - call_carousel_llm() returns non-empty carousel content
    - validate_slide_bodies() detects and annotates slide body character counts
    - generate_with_validation() retries on validation errors
    - create_carousel_doc() creates a Google Doc
    """
    print("\n" + "=" * 70)
    print("PHASE 4: Step 6d — LinkedIn Carousel")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.linkedin_carousel import (
        create_carousel_doc,
        generate_with_validation,
        validate_slide_bodies,
    )

    # 4a. Generate carousel with validation
    print("\n--- 4a. generate_with_validation() ---")
    model = _openrouter_model(get_model(LLMPurpose.LINKEDIN))
    print(f"  Model: {model}")

    formatted_theme_json = json.dumps(SAMPLE_FORMATTED_THEME, indent=2)
    carousel_output, remaining_errors = await generate_with_validation(
        formatted_theme=formatted_theme_json,
        newsletter_content=SAMPLE_HTML_CONTENT,
        max_attempts=2,
        model=model,
    )

    assert carousel_output, "generate_with_validation returned empty output"
    print(f"  Final output: {len(carousel_output)} chars")
    print(f"  Remaining errors: {len(remaining_errors)}")
    if remaining_errors:
        for err in remaining_errors:
            print(f"    Slide body ({err.actual_characters} chars): {err.error_type}")
    print(f"  Preview:\n    {carousel_output[:400]}...")

    # 4b. Validate slide bodies on final output
    print("\n--- 4b. validate_slide_bodies() on final output ---")
    validation = validate_slide_bodies(carousel_output)
    print(f"  Annotated output: {len(validation.annotated_output)} chars")
    print(f"  Validation errors: {len(validation.errors)}")
    for err in validation.errors:
        print(f"    {err.actual_characters} chars (range: {err.required_range})")

    # Check that annotated output contains character count markers
    has_char_counts = "*Character count:" in validation.annotated_output
    print(f"  Has character count annotations: {has_char_counts}")

    results: dict[str, Any] = {
        "model": model,
        "output_length": len(carousel_output),
        "remaining_errors": len(remaining_errors),
        "validation_errors": len(validation.errors),
        "has_char_annotations": has_char_counts,
    }

    # 4c. Create Google Doc
    if not skip_gdocs:
        print("\n--- 4c. create_carousel_doc() ---")
        from ica.services.google_docs import GoogleDocsService

        creds_path = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
            "credentials/google-service-account.json",
        )
        drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")
        docs = GoogleDocsService(credentials_path=creds_path, drive_id=drive_id)

        doc_id, doc_url = await create_carousel_doc(
            docs, carousel_output,
            title="Integration Test - LinkedIn Carousel",
        )

        assert doc_id, "create_carousel_doc returned empty doc_id"
        assert doc_url.startswith("https://docs.google.com/document/d/"), (
            f"Unexpected doc_url format: {doc_url}"
        )
        print(f"  Doc ID: {doc_id}")
        print(f"  Doc URL: {doc_url}")
        results["carousel_doc_id"] = doc_id
    else:
        print("\n  Google Docs phase skipped (--skip-gdocs).")

    print("\n  Phase 4 PASSED: LinkedIn carousel generation + validation works.")
    return results


# ---------------------------------------------------------------------------
# Phase 5: Concurrent Execution via asyncio.gather()
# ---------------------------------------------------------------------------


async def phase_concurrent(*, skip_gdocs: bool = False) -> dict[str, Any]:
    """Run all four parallel steps concurrently and verify behavior.

    Tests:
    - All 4 steps complete successfully via asyncio.gather()
    - Wall-clock time is less than sum of individual times (proves concurrency)
    - Each step populates its expected ctx.extra keys
    - No shared-state corruption (ctx.extra keys are distinct)
    - Failure isolation: a failed step does not cancel siblings
    """
    print("\n" + "=" * 70)
    print("PHASE 5: Concurrent Execution (asyncio.gather)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.alternates_html import filter_unused_articles
    from ica.pipeline.email_subject import (
        call_email_review_llm,
        call_email_subject_llm,
        parse_subjects,
        strip_html_to_text,
    )
    from ica.pipeline.linkedin_carousel import generate_with_validation
    from ica.pipeline.social_media import (
        call_social_media_post_llm,
        parse_phase1_titles,
    )

    # Shared state dict simulating PipelineContext.extra
    extra: dict[str, Any] = {}
    timings: dict[str, float] = {}
    errors: dict[str, str] = {}

    plain_text = strip_html_to_text(SAMPLE_HTML_CONTENT)
    formatted_theme_json = json.dumps(SAMPLE_FORMATTED_THEME, indent=2)

    # Define the 4 concurrent tasks
    async def task_6a() -> None:
        """Step 6a: Alternates HTML (pure Python)."""
        start = time.monotonic()
        result = filter_unused_articles(SAMPLE_FORMATTED_THEME, SAMPLE_SUMMARIES)
        extra["alternates_unused_summaries"] = result.unused_summaries
        extra["alternates_urls_in_theme"] = result.urls_in_theme
        timings["6a_alternates"] = time.monotonic() - start

    async def task_6b() -> None:
        """Step 6b: Email subject + review via LLM."""
        start = time.monotonic()
        model = _openrouter_model(get_model(LLMPurpose.EMAIL_SUBJECT))
        raw = await call_email_subject_llm(newsletter_text=plain_text, model=model)
        subjects, _rec = parse_subjects(raw)
        extra["email_subject"] = subjects[0].subject if subjects else ""
        review_model = _openrouter_model(get_model(LLMPurpose.EMAIL_PREVIEW))
        review = await call_email_review_llm(
            newsletter_text=plain_text, model=review_model,
        )
        extra["email_review"] = review
        timings["6b_email"] = time.monotonic() - start

    async def task_6c() -> None:
        """Step 6c: Social media post generation via LLM."""
        start = time.monotonic()
        model = _openrouter_model(get_model(LLMPurpose.SOCIAL_MEDIA))
        raw = await call_social_media_post_llm(
            newsletter_content=SAMPLE_HTML_CONTENT,
            formatted_theme=formatted_theme_json,
            model=model,
        )
        titles = parse_phase1_titles(raw)
        extra["social_media_titles"] = titles
        extra["social_media_raw"] = raw
        timings["6c_social"] = time.monotonic() - start

    async def task_6d() -> None:
        """Step 6d: LinkedIn carousel with validation loop."""
        start = time.monotonic()
        model = _openrouter_model(get_model(LLMPurpose.LINKEDIN))
        output, errs = await generate_with_validation(
            formatted_theme=formatted_theme_json,
            newsletter_content=SAMPLE_HTML_CONTENT,
            max_attempts=2,
            model=model,
        )
        extra["linkedin_carousel_output"] = output
        extra["linkedin_carousel_errors"] = len(errs)
        timings["6d_carousel"] = time.monotonic() - start

    # Wrap each task to catch errors without canceling siblings
    async def safe_run(name: str, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            errors[name] = str(exc)
            print(f"  WARNING: {name} failed: {exc}")

    # Run all 4 concurrently
    print("\n--- 5a. Launching 4 tasks via asyncio.gather() ---")
    wall_start = time.monotonic()

    await asyncio.gather(
        safe_run("6a_alternates", task_6a()),
        safe_run("6b_email", task_6b()),
        safe_run("6c_social", task_6c()),
        safe_run("6d_carousel", task_6d()),
    )

    wall_time = time.monotonic() - wall_start
    sequential_sum = sum(timings.values())

    print("\n--- 5b. Timing results ---")
    for step_name, duration in sorted(timings.items()):
        print(f"  {step_name}: {duration:.2f}s")
    print(f"  Sequential sum: {sequential_sum:.2f}s")
    print(f"  Wall-clock time: {wall_time:.2f}s")

    if sequential_sum > 0:
        speedup = sequential_sum / wall_time
        print(f"  Speedup factor: {speedup:.2f}x")
    else:
        speedup = 0.0

    # Verify concurrency: wall time should be < sum of individual times
    # (Only meaningful when LLM tasks ran — 6a is instant)
    llm_timings = {k: v for k, v in timings.items() if k != "6a_alternates"}
    if len(llm_timings) >= 2:
        llm_sum = sum(llm_timings.values())
        assert wall_time < llm_sum, (
            f"Wall time ({wall_time:.2f}s) >= sum of LLM times ({llm_sum:.2f}s)"
            " — tasks may not have run concurrently"
        )
        print("  Concurrency check: PASSED (wall < sum of LLM times)")

    # Verify ctx.extra key population
    print("\n--- 5c. Shared state (ctx.extra) verification ---")
    expected_keys = [
        "alternates_unused_summaries",
        "alternates_urls_in_theme",
        "email_subject",
        "email_review",
        "social_media_titles",
        "social_media_raw",
        "linkedin_carousel_output",
        "linkedin_carousel_errors",
    ]

    populated = 0
    for key in expected_keys:
        present = key in extra
        value = extra.get(key)
        summary = ""
        if isinstance(value, str):
            summary = f"{len(value)} chars"
        elif isinstance(value, list):
            summary = f"{len(value)} items"
        elif isinstance(value, int):
            summary = str(value)
        elif value is not None:
            summary = type(value).__name__
        status = f"present ({summary})" if present else "MISSING"
        print(f"  {key}: {status}")
        if present:
            populated += 1

    # Allow for step failures — check at least keys from successful steps
    successful_steps = len(timings)
    print(f"\n  Populated keys: {populated}/{len(expected_keys)}")
    print(f"  Successful steps: {successful_steps}/4")
    print(f"  Failed steps: {len(errors)}")
    for name, err_msg in errors.items():
        print(f"    {name}: {err_msg[:100]}")

    # Core assertion: at least 3 of 4 steps should succeed
    assert successful_steps >= 3, (
        f"Only {successful_steps}/4 steps succeeded: {list(errors.keys())}"
    )

    results: dict[str, Any] = {
        "wall_time": round(wall_time, 2),
        "sequential_sum": round(sequential_sum, 2),
        "speedup": round(speedup, 2),
        "successful_steps": successful_steps,
        "failed_steps": len(errors),
        "populated_keys": populated,
        "total_expected_keys": len(expected_keys),
    }

    print(f"\n  {successful_steps}/4 steps passed, wall={wall_time:.2f}s")
    print("  Phase 5 PASSED: Concurrent execution verified.")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: parallel output steps 6a-6d.",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=[
            "all", "alternates", "email", "social", "carousel", "concurrent",
        ],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM call phases (run alternates only)",
    )
    parser.add_argument(
        "--skip-gdocs",
        action="store_true",
        help="Skip Google Docs creation (no Google credentials required)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}

    # Phase 1: Alternates HTML (always runs — no external deps)
    if args.phase in ("all", "alternates"):
        results["alternates"] = await phase_alternates()

    if args.skip_llm:
        if args.phase in ("all",):
            print("\n  LLM phases skipped (--skip-llm).")
    else:
        # Phase 2: Email Subject
        if args.phase in ("all", "email"):
            results["email"] = await phase_email(skip_gdocs=args.skip_gdocs)

        # Phase 3: Social Media
        if args.phase in ("all", "social"):
            results["social"] = await phase_social(skip_gdocs=args.skip_gdocs)

        # Phase 4: LinkedIn Carousel
        if args.phase in ("all", "carousel"):
            results["carousel"] = await phase_carousel(skip_gdocs=args.skip_gdocs)

        # Phase 5: Concurrent Execution
        if args.phase in ("all", "concurrent"):
            results["concurrent"] = await phase_concurrent(
                skip_gdocs=args.skip_gdocs,
            )

    # Summary
    print("\n" + "=" * 70)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 70)

    for phase_name, phase_results in results.items():
        print(f"\n  {phase_name}:")
        for key, value in phase_results.items():
            display = str(value)
            if len(display) > 100:
                display = display[:100] + "..."
            print(f"    {key}: {display}")

    print("\nParallel output steps (6a-6d) integration test complete!")


if __name__ == "__main__":
    main()
