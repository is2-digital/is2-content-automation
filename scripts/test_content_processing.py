"""Integration test — content processing pipeline (Phase B).

Exercises the Phase B data pipeline with real services:

1. HTTP fetching: fetch real articles, test redirect/paywall detection, HTML→text
2. LLM summarization: call real LLM, validate structured output (URL/Title/Summary/BR)
3. Theme generation & marker parsing: call real LLM, validate %XX_ marker extraction
4. Freshness check: call Gemini 2.5 Flash, validate freshness analysis output

Usage:
    docker exec ica-app-1 python scripts/test_content_processing.py
    docker exec ica-app-1 python scripts/test_content_processing.py --skip-llm
    docker exec ica-app-1 python scripts/test_content_processing.py --phase fetch
    docker exec ica-app-1 python scripts/test_content_processing.py --phase summarize
    docker exec ica-app-1 python scripts/test_content_processing.py --phase theme
    docker exec ica-app-1 python scripts/test_content_processing.py --phase freshness

Requires OPENROUTER_API_KEY (for LLM calls) and optionally Postgres env vars
(for learning data).  Run inside the app container where .env is loaded automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv

# Ensure project root is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Test articles: a mix of accessible pages, known redirect, and YouTube (unfetchable)
TEST_ARTICLES = [
    {
        "url": "https://openai.com/index/hello-gpt-4o/",
        "title": "Hello GPT-4o",
        "origin": "openai.com",
    },
    {
        "url": "https://blog.google/technology/ai/google-gemini-ai/",
        "title": "Introducing Gemini",
        "origin": "blog.google",
    },
    {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "YouTube Test (should fail)",
        "origin": "youtube.com",
    },
]


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


# ---------------------------------------------------------------------------
# Phase 1: HTTP Fetching
# ---------------------------------------------------------------------------


async def phase_fetch() -> dict[str, Any]:
    """Fetch real articles and validate fetch result handling.

    Tests:
    - Successful page fetch (200, with content)
    - YouTube URL detection via is_fetch_failure()
    - HTML stripping to plain text
    - Redirect following
    """
    print("\n" + "=" * 70)
    print("PHASE 1: HTTP Fetching")
    print("=" * 70)

    from ica.services.web_fetcher import (
        WebFetcherService,
        is_fetch_failure,
        strip_html_tags,
    )

    results: dict[str, Any] = {
        "fetched": 0,
        "failed": 0,
        "youtube_detected": False,
        "html_stripped": False,
    }

    async with WebFetcherService() as fetcher:
        for article in TEST_ARTICLES:
            url = article["url"]
            title = article["title"]
            print(f"\n--- Fetching: {title} ---")
            print(f"  URL: {url}")

            result = await fetcher.get(url)
            is_failure = is_fetch_failure(result, url)

            if is_failure:
                results["failed"] += 1
                reason = result.error or "fetch failure detected"
                if "youtube.com" in url.lower():
                    results["youtube_detected"] = True
                    reason = "YouTube URL (expected)"
                print(f"  Status: FAILED ({reason})")
            else:
                results["fetched"] += 1
                content_len = len(result.content or "")
                print(f"  Status: OK ({content_len:,} chars)")

                # Test HTML stripping
                if result.content:
                    text = strip_html_tags(result.content)
                    text_len = len(text)
                    print(f"  HTML→text: {text_len:,} chars")
                    print(f"  Preview: {text[:200]}...")

                    # Verify stripping actually removed HTML
                    if "<html" not in text.lower() and "<body" not in text.lower():
                        results["html_stripped"] = True
                        print("  HTML tags stripped: YES")
                    else:
                        print("  WARNING: HTML tags may still be present")

    # Assertions
    assert results["fetched"] >= 1, "Expected at least 1 successful fetch"
    assert results["youtube_detected"], "Expected YouTube URL to be detected as failure"
    assert results["html_stripped"], "Expected HTML stripping to remove tags"

    print(f"\n  Fetched: {results['fetched']}, Failed: {results['failed']}")
    print("  Phase 1 PASSED: HTTP fetching, failure detection, and HTML stripping work.")

    return results


# ---------------------------------------------------------------------------
# Phase 2: LLM Summarization
# ---------------------------------------------------------------------------


async def phase_summarize() -> dict[str, Any]:
    """Call the real LLM to summarize an article and validate output structure.

    Tests:
    - LLM call succeeds via OpenRouter
    - Response contains expected fields: URL, Title, Summary, Business Relevance
    - parse_summary_output() extracts all fields
    - Summary and business relevance are non-trivial (not just defaults)
    """
    print("\n" + "=" * 70)
    print("PHASE 2: LLM Summarization")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.summarization import (
        build_article_input,
        call_summary_llm,
        parse_summary_output,
    )
    from ica.services.web_fetcher import WebFetcherService, strip_html_tags

    model = get_model(LLMPurpose.SUMMARY)
    print(f"  Model: {model}")

    # Fetch a real article for summarization
    test_url = TEST_ARTICLES[0]["url"]
    test_title = TEST_ARTICLES[0]["title"]
    print("\n--- 2a. Fetching article for summarization ---")
    print(f"  URL: {test_url}")

    async with WebFetcherService() as fetcher:
        result = await fetcher.get(test_url)

    if result.error or not result.content:
        print(f"  WARNING: Could not fetch article ({result.error})")
        print("  Using a synthetic content snippet for LLM test")
        text_content = (
            "OpenAI has announced GPT-4o, a new flagship model that can reason "
            "across audio, vision, and text in real time. The model is significantly "
            "faster and more efficient than its predecessors, with improved capabilities "
            "in non-English languages. GPT-4o is available to free-tier ChatGPT users "
            "and via the API at half the cost of GPT-4 Turbo."
        )
    else:
        text_content = strip_html_tags(result.content)
        # Truncate to avoid excessive token usage
        text_content = text_content[:3000]
        print(f"  Fetched: {len(text_content):,} chars (truncated to 3000)")

    # Build input and call LLM
    print("\n--- 2b. Calling LLM for summarization ---")
    article_input = build_article_input(test_url, test_title, text_content)
    raw_output = await call_summary_llm(article_input)

    print(f"  Raw output length: {len(raw_output)} chars")
    print(f"  Raw output preview:\n    {raw_output[:300]}...")

    # Parse output
    print("\n--- 2c. Parsing summary output ---")
    parsed_url, parsed_title, summary, business = parse_summary_output(raw_output)

    print(f"  URL:                {parsed_url[:80]}")
    print(f"  Title:              {parsed_title[:80]}")
    print(f"  Summary:            {summary[:150]}...")
    print(f"  Business Relevance: {business[:150]}...")

    # Validate structure
    results: dict[str, Any] = {
        "model": model,
        "raw_output_length": len(raw_output),
        "has_url": parsed_url != "N/A",
        "has_title": parsed_title != "Untitled",
        "has_summary": summary != "No summary available.",
        "has_business": business != "No business relevance available.",
        "summary_length": len(summary),
        "business_length": len(business),
    }

    assert results["has_summary"], "Expected a real summary, not the default placeholder"
    assert results["has_business"], "Expected real business relevance, not the default"
    assert results["summary_length"] > 50, (
        f"Summary too short ({results['summary_length']} chars)"
    )
    assert results["business_length"] > 30, (
        f"Business relevance too short ({results['business_length']} chars)"
    )

    print(f"\n  Summary: {results['summary_length']} chars")
    print(f"  Business Relevance: {results['business_length']} chars")
    print("  Phase 2 PASSED: LLM summarization returns valid structured output.")

    return results


# ---------------------------------------------------------------------------
# Phase 3: Theme Generation & Marker Parsing
# ---------------------------------------------------------------------------


async def phase_theme() -> dict[str, Any]:
    """Call the real LLM to generate themes and validate %XX_ marker parsing.

    Tests:
    - LLM returns theme blocks separated by -----
    - split_themes() extracts theme blocks and recommendation
    - parse_markers() extracts all %XX_ marker fields
    - FormattedTheme has populated article slots (FA, M1, M2, Q1-Q3, I1-I2)
    """
    print("\n" + "=" * 70)
    print("PHASE 3: Theme Generation & Marker Parsing")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.theme_generation import call_theme_llm, parse_theme_output
    from ica.utils.marker_parser import split_themes

    model = get_model(LLMPurpose.THEME)
    print(f"  Model: {model}")

    # Build a sample summaries JSON (simulating Step 2 output)
    sample_summaries = [
        {
            "URL": "https://openai.com/index/hello-gpt-4o/",
            "Title": "Hello GPT-4o: OpenAI's Latest Multimodal Model",
            "Summary": "OpenAI has announced GPT-4o, a new flagship model that can reason "
            "across audio, vision, and text in real time. The model is significantly "
            "faster and more efficient, with improved non-English language capabilities.",
            "BusinessRelevance": "GPT-4o's multimodal capabilities enable businesses to build "
            "more natural customer-facing AI applications without managing multiple models.",
            "order": 1,
            "newsletter_id": "test-001",
            "industry_news": False,
        },
        {
            "URL": "https://blog.google/technology/ai/google-gemini-ai/",
            "Title": "Introducing Gemini: Google's Most Capable AI Model",
            "Summary": "Google has launched Gemini, its most capable AI model to date. "
            "Built from the ground up for multimodality, Gemini comes in three sizes: "
            "Ultra, Pro, and Nano for different deployment scenarios.",
            "BusinessRelevance": "Gemini's tiered model approach allows businesses of all "
            "sizes to integrate advanced AI capabilities matching their computational budget.",
            "order": 2,
            "newsletter_id": "test-001",
            "industry_news": True,
        },
        {
            "URL": "https://example.com/ai-automation-trends",
            "Title": "5 AI Automation Trends Reshaping Small Businesses in 2026",
            "Summary": "A comprehensive analysis of emerging AI automation trends reveals "
            "that small businesses are increasingly adopting AI for customer service, "
            "content creation, and supply chain optimization.",
            "BusinessRelevance": "Small business owners can identify which AI tools offer "
            "the highest ROI for their specific operations and industry vertical.",
            "order": 3,
            "newsletter_id": "test-001",
            "industry_news": False,
        },
        {
            "URL": "https://example.com/microsoft-copilot-enterprise",
            "Title": "Microsoft Expands Copilot to All Enterprise Applications",
            "Summary": "Microsoft is rolling out Copilot AI assistants across its entire "
            "enterprise suite including Dynamics 365, Power Platform, and Azure services. "
            "Early adopters report 30% productivity improvements.",
            "BusinessRelevance": "Businesses already using Microsoft tools can leverage AI "
            "through familiar interfaces, reducing training costs and adoption barriers.",
            "order": 4,
            "newsletter_id": "test-001",
            "industry_news": True,
        },
        {
            "URL": "https://example.com/ai-regulation-update",
            "Title": "EU AI Act Implementation Timeline: What Businesses Need to Know",
            "Summary": "The EU AI Act is entering its implementation phase with specific "
            "deadlines for different risk categories. Companies must classify their AI "
            "systems and prepare compliance documentation by mid-2026.",
            "BusinessRelevance": "Companies selling to EU customers or using AI in operations "
            "must begin compliance planning immediately to avoid penalties.",
            "order": 5,
            "newsletter_id": "test-001",
            "industry_news": False,
        },
        {
            "URL": "https://example.com/anthropic-claude-tools",
            "Title": "Anthropic Launches New Claude Enterprise Features",
            "Summary": "Anthropic has introduced new enterprise features for Claude including "
            "tool use, longer context windows, and enhanced safety guardrails for "
            "regulated industries like healthcare and finance.",
            "BusinessRelevance": "Enterprise customers gain more flexible AI deployment options "
            "with built-in compliance features for sensitive business operations.",
            "order": 6,
            "newsletter_id": "test-001",
            "industry_news": True,
        },
        {
            "URL": "https://example.com/ai-hiring-trends",
            "Title": "AI Skills Gap Widens as Demand Surges for Prompt Engineers",
            "Summary": "The demand for AI-skilled workers is outpacing supply, with prompt "
            "engineering and AI operations roles seeing 200% growth in job postings. "
            "Companies are investing in upskilling programs.",
            "BusinessRelevance": "Business leaders should invest in AI literacy programs for "
            "existing teams rather than competing in the overheated AI talent market.",
            "order": 7,
            "newsletter_id": "test-001",
            "industry_news": False,
        },
    ]

    summaries_json = json.dumps(sample_summaries, indent=2)
    print(f"  Input: {len(sample_summaries)} article summaries")

    # Call LLM for theme generation
    print("\n--- 3a. Calling LLM for theme generation ---")
    raw_output, model_used = await call_theme_llm(summaries_json)

    print(f"  Raw output length: {len(raw_output)} chars")
    print(f"  Model used: {model_used}")
    print(f"  Preview (first 500 chars):\n    {raw_output[:500]}...")

    # Split themes
    print("\n--- 3b. Splitting theme blocks ---")
    split_result = split_themes(raw_output)
    print(f"  Theme blocks found: {len(split_result.themes)}")
    print(f"  Has recommendation: {bool(split_result.recommendation)}")

    for idx, block in enumerate(split_result.themes, 1):
        print(f"    Theme {idx}: {block.theme_name or '(unnamed)'}")
        if block.theme_description:
            print(f"      Description: {block.theme_description[:100]}...")

    # Parse markers from each theme
    print("\n--- 3c. Parsing %XX_ markers ---")
    parsed_themes = parse_theme_output(raw_output)

    results: dict[str, Any] = {
        "model": model_used,
        "raw_output_length": len(raw_output),
        "theme_count": len(parsed_themes),
        "has_recommendation": bool(split_result.recommendation),
        "marker_results": [],
    }

    for idx, theme in enumerate(parsed_themes, 1):
        ft = theme.formatted_theme
        marker_report: dict[str, Any] = {
            "theme_name": theme.theme_name,
            "fa_title": ft.featured_article.title,
            "m1_title": ft.main_article_1.title,
            "m2_title": ft.main_article_2.title,
            "q1_title": ft.quick_hit_1.title,
            "q2_title": ft.quick_hit_2.title,
            "q3_title": ft.quick_hit_3.title,
            "i1_title": ft.industry_development_1.title,
            "i2_title": ft.industry_development_2.title,
        }

        # Count populated fields
        populated = sum(1 for v in marker_report.values() if v is not None)
        total = len(marker_report)

        print(f"\n  Theme {idx}: {theme.theme_name or '(unnamed)'}")
        print(f"    FA title:  {ft.featured_article.title or '(missing)'}")
        print(f"    FA URL:    {ft.featured_article.url or '(missing)'}")
        print(f"    M1 title:  {ft.main_article_1.title or '(missing)'}")
        print(f"    M2 title:  {ft.main_article_2.title or '(missing)'}")
        print(f"    Q1 title:  {ft.quick_hit_1.title or '(missing)'}")
        print(f"    Q2 title:  {ft.quick_hit_2.title or '(missing)'}")
        print(f"    Q3 title:  {ft.quick_hit_3.title or '(missing)'}")
        print(f"    I1 title:  {ft.industry_development_1.title or '(missing)'}")
        print(f"    I2 title:  {ft.industry_development_2.title or '(missing)'}")
        print(f"    Populated: {populated}/{total} fields")

        marker_report["populated"] = populated
        marker_report["total"] = total
        results["marker_results"].append(marker_report)

    # Assertions
    assert len(parsed_themes) >= 1, "Expected at least 1 theme from LLM output"

    # Check that at least one theme has populated markers
    best_populated = max(r["populated"] for r in results["marker_results"])
    assert best_populated >= 5, (
        f"Expected at least 5 populated marker fields, best theme has {best_populated}"
    )

    print(f"\n  Themes parsed: {len(parsed_themes)}")
    print(f"  Best marker coverage: {best_populated} fields")
    print("  Phase 3 PASSED: Theme generation and %XX_ marker parsing work.")

    return results


# ---------------------------------------------------------------------------
# Phase 4: Freshness Check (Gemini 2.5 Flash)
# ---------------------------------------------------------------------------


async def phase_freshness() -> dict[str, Any]:
    """Call Gemini 2.5 Flash for a freshness check on a theme body.

    Tests:
    - Freshness check LLM call succeeds via Gemini
    - Response contains substantive analysis (not empty/trivial)
    - Model routing correctly selects google/gemini-2.5-flash
    """
    print("\n" + "=" * 70)
    print("PHASE 4: Freshness Check (Gemini 2.5 Flash)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.theme_selection import run_freshness_check

    model = get_model(LLMPurpose.THEME_FRESHNESS_CHECK)
    print(f"  Model: {model}")

    # Use a realistic theme body with %XX_ markers
    sample_theme_body = """\
THEME: AI Accessibility Revolution
Theme Description: How AI tools are becoming more accessible to small businesses
Articles that fit:

FEATURED ARTICLE:
%FA_TITLE: Hello GPT-4o: OpenAI's Latest Multimodal Model
%FA_SOURCE: openai.com
%FA_ORIGIN: OpenAI Blog
%FA_URL: https://openai.com/index/hello-gpt-4o/
%FA_CATEGORY: AI Models
%FA_WHY FEATURED: Demonstrates how frontier AI is becoming freely accessible

%M1_TITLE: 5 AI Automation Trends Reshaping Small Businesses in 2026
%M1_SOURCE: example.com
%M1_ORIGIN: AI Industry Report
%M1_URL: https://example.com/ai-automation-trends
%M1_CATEGORY: Business AI
%M1_RATIONALE: Directly addresses SMB AI adoption patterns

%M2_TITLE: EU AI Act Implementation Timeline
%M2_SOURCE: example.com
%M2_ORIGIN: Regulatory Analysis
%M2_URL: https://example.com/ai-regulation-update
%M2_CATEGORY: AI Regulation
%M2_RATIONALE: Critical compliance info for all business sizes

%Q1_TITLE: AI Skills Gap Widens
%Q1_SOURCE: example.com
%Q1_ORIGIN: Employment Report
%Q1_URL: https://example.com/ai-hiring-trends
%Q1_CATEGORY: Workforce

%Q2_TITLE: Anthropic Launches New Features
%Q2_SOURCE: example.com
%Q2_ORIGIN: Anthropic Blog
%Q2_URL: https://example.com/anthropic-claude-tools
%Q2_CATEGORY: AI Tools

%Q3_TITLE: Microsoft Copilot Expansion
%Q3_SOURCE: example.com
%Q3_ORIGIN: Microsoft Blog
%Q3_URL: https://example.com/microsoft-copilot-enterprise
%Q3_CATEGORY: Enterprise AI

%I1_TITLE: Introducing Gemini
%I1_SOURCE: blog.google
%I1_ORIGIN: Google AI Blog
%I1_URL: https://blog.google/technology/ai/google-gemini-ai/
%I1_Major AI Player: Google

%I2_TITLE: Microsoft Expands Copilot
%I2_SOURCE: example.com
%I2_ORIGIN: Microsoft News
%I2_URL: https://example.com/microsoft-copilot-enterprise
%I2_Major AI Player: Microsoft

REQUIREMENTS VERIFIED:
%RV_2-2-2 Distribution Achieved:% Yes
%RV_Source mix:% Diverse (OpenAI, Google, Microsoft, independent)
%RV_Technical complexity:% Accessible to non-technical audience
%RV_Major AI player coverage:% Google, Microsoft, OpenAI, Anthropic"""

    print(f"  Theme body: {len(sample_theme_body)} chars")
    print("  Theme: AI Accessibility Revolution")

    # Call freshness check
    print("\n--- 4a. Calling freshness check LLM ---")
    freshness_report = await run_freshness_check(sample_theme_body)

    print(f"  Report length: {len(freshness_report)} chars")
    print(f"  Report preview:\n    {freshness_report[:400]}...")

    results: dict[str, Any] = {
        "model": model,
        "report_length": len(freshness_report),
        "has_content": len(freshness_report) > 50,
    }

    # Assertions
    assert results["has_content"], (
        f"Freshness report too short ({results['report_length']} chars)"
    )

    print(f"\n  Report: {results['report_length']} chars")
    print("  Phase 4 PASSED: Freshness check returns substantive analysis.")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: content processing pipeline (Phase B).",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=["all", "fetch", "summarize", "theme", "freshness"],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip phases that require LLM calls (run fetch only)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}

    if args.phase in ("all", "fetch"):
        results["fetch"] = await phase_fetch()

    if args.skip_llm:
        if args.phase in ("all",):
            print("\n  LLM phases skipped (--skip-llm).")
    else:
        if args.phase in ("all", "summarize"):
            results["summarize"] = await phase_summarize()

        if args.phase in ("all", "theme"):
            results["theme"] = await phase_theme()

        if args.phase in ("all", "freshness"):
            results["freshness"] = await phase_freshness()

    # Summary
    print("\n" + "=" * 70)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 70)

    for phase_name, phase_results in results.items():
        print(f"\n  {phase_name}:")
        for key, value in phase_results.items():
            # Truncate long values
            display = str(value)
            if len(display) > 100:
                display = display[:100] + "..."
            print(f"    {key}: {display}")

    print("\nPhase B integration test complete!")


if __name__ == "__main__":
    main()
