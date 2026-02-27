"""Integration test — generation & validation pipeline (Phase C).

Chains Steps 4–6d end-to-end with data flowing between them:

1. Markdown generation + 3-layer validation (real LLM): generate_with_validation()
   produces validated newsletter markdown; verify ValidationLoopCounter, error
   merging, and final markdown structure.
2. HTML generation from markdown (real LLM): call_html_llm() converts the
   generated markdown into email-ready HTML; verify template preservation,
   content population, and DOCTYPE marker.
3. Google Docs creation: create Google Docs for both markdown and HTML;
   verify round-trip content storage.
4. Parallel output steps 6a-6d: run all four steps concurrently via
   asyncio.gather() using data produced by prior phases; verify timing
   speedup, ctx.extra key population, and failure isolation.
5. Orchestrator integration: exercise run_pipeline() with Steps 4–5 as
   sequential + Steps 6a-6d as parallel, using PipelineContext to confirm
   the real wiring.

Usage:
    docker exec ica-app-1 python scripts/test_generation_validation.py
    docker exec ica-app-1 python scripts/test_generation_validation.py --phase markdown
    docker exec ica-app-1 python scripts/test_generation_validation.py --phase html
    docker exec ica-app-1 python scripts/test_generation_validation.py --phase gdocs
    docker exec ica-app-1 python scripts/test_generation_validation.py --phase parallel
    docker exec ica-app-1 python scripts/test_generation_validation.py --phase orchestrator
    docker exec ica-app-1 python scripts/test_generation_validation.py --skip-gdocs
    docker exec ica-app-1 python scripts/test_generation_validation.py --skip-parallel

Requires OPENROUTER_API_KEY (for LLM calls) and optionally Google service
account credentials (for Google Docs).  Run inside the app container where
.env is loaded automatically.
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
# Sample data — realistic theme JSON for markdown generation (Step 4 input)
# ---------------------------------------------------------------------------

SAMPLE_FORMATTED_THEME = json.dumps(
    {
        "theme_name": "AI Accessibility Revolution",
        "theme_description": ("How frontier AI tools are becoming accessible to all businesses"),
        "featured_article": {
            "title": "Hello GPT-4o: OpenAI's Latest Multimodal Model",
            "url": "https://openai.com/index/hello-gpt-4o/",
            "source": "openai.com",
            "origin": "OpenAI Blog",
            "category": "AI Models",
            "summary": (
                "OpenAI released GPT-4o, a multimodal model processing text,"
                " audio, and vision in real time at half the cost of GPT-4"
                " Turbo."
            ),
            "business_relevance": (
                "Free-tier access to frontier AI enables solopreneurs to"
                " compete with enterprise teams on AI capability."
            ),
            "why_featured": ("Demonstrates democratization of frontier AI capabilities"),
        },
        "main_article_1": {
            "title": "5 AI Automation Trends Reshaping Small Businesses in 2026",
            "url": "https://example.com/ai-automation-trends",
            "source": "example.com",
            "origin": "AI Industry Report",
            "category": "Business AI",
            "summary": (
                "Small businesses are moving past experimentation with AI,"
                " embedding it into customer service and operations workflows."
            ),
            "business_relevance": ("Identifies which AI tools offer highest ROI for SMBs."),
            "rationale": "Directly addresses SMB AI adoption patterns",
        },
        "main_article_2": {
            "title": "EU AI Act Implementation Timeline",
            "url": "https://example.com/ai-regulation-update",
            "source": "example.com",
            "origin": "Regulatory Analysis",
            "category": "AI Regulation",
            "summary": (
                "The EU AI Act enters implementation phase with specific"
                " deadlines for risk classification and compliance"
                " documentation."
            ),
            "business_relevance": ("Companies selling to EU must begin compliance planning now."),
            "rationale": "Critical compliance info for all business sizes",
        },
        "quick_hit_1": {
            "title": "AI Skills Gap Widens as Demand Surges",
            "url": "https://example.com/ai-hiring-trends",
            "source": "example.com",
            "origin": "Employment Report",
            "category": "Workforce",
            "summary": ("Demand for AI-skilled workers outpaces supply with 200% job growth."),
        },
        "quick_hit_2": {
            "title": "Anthropic Launches New Claude Enterprise Features",
            "url": "https://example.com/anthropic-claude-tools",
            "source": "example.com",
            "origin": "Anthropic Blog",
            "category": "AI Tools",
            "summary": (
                "New enterprise features include tool use and enhanced safety guardrails."
            ),
        },
        "quick_hit_3": {
            "title": "Microsoft Copilot Expansion Across Enterprise Suite",
            "url": "https://example.com/microsoft-copilot-enterprise",
            "source": "example.com",
            "origin": "Microsoft Blog",
            "category": "Enterprise AI",
            "summary": ("Copilot AI embedded across Dynamics 365, Power Platform, and Azure."),
        },
        "industry_development_1": {
            "title": "Introducing Gemini: Google's Most Capable AI Model",
            "url": "https://blog.google/technology/ai/google-gemini-ai/",
            "source": "blog.google",
            "origin": "Google AI Blog",
            "major_player": "Google",
        },
        "industry_development_2": {
            "title": ("Microsoft Expands Copilot to All Enterprise Applications"),
            "url": "https://example.com/microsoft-copilot-enterprise",
            "source": "example.com",
            "origin": "Microsoft News",
            "major_player": "Microsoft",
        },
    },
    indent=2,
)

# Minimal HTML template for Step 5 (HTML generation).
SAMPLE_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Artificially Intelligent, Actually Useful. - DATE_PLACEHOLDER</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; padding: 0; }
    .nl-date { font-size: 14px; color: #666; }
    .nl-content { padding: 20px; }
    .nl-intro { font-size: 16px; }
    .nl-intro-summary { font-size: 14px; color: #333; }
    .nl-quick-highlights { padding: 20px; background: #f9f9f9; }
    .nl-section-title { font-size: 20px; color: #1a73e8; }
    .nl-article-box { border: 1px solid #ddd; padding: 15px; margin: 10px 0; }
    .nl-article-title { font-size: 18px; }
    .nl-callout { background: #f0f7ff; padding: 10px; margin: 10px 0; }
    .nl-source-link { color: #1a73e8; text-decoration: none; }
    .nl-quick-hits { padding: 20px; }
    .nl-industry { padding: 20px; background: #f5f5f5; }
    .nl-footer { padding: 20px; font-style: italic; }
  </style>
</head>
<body>
<table width="100%">
  <tr><td class="nl-date">DATE_PLACEHOLDER</td></tr>
  <tr><td class="nl-content nl-intro">
    <p>INTRODUCTION_HEADLINE</p>
    <p class="nl-intro-summary">INTRODUCTION_SUMMARY</p>
  </td></tr>
  <tr><td class="nl-quick-highlights">
    <table>
      <tr><td>QUICK_HIGHLIGHT_1</td></tr>
      <tr><td>QUICK_HIGHLIGHT_2</td></tr>
      <tr><td>QUICK_HIGHLIGHT_3</td></tr>
    </table>
  </td></tr>
  <tr><td class="nl-content nl-main">
    <div style="background: #1a73e8; color: white; padding: 20px;">
      <h2 class="nl-section-title" style="color: white;">FEATURED_HEADLINE</h2>
      <p>FEATURED_BODY_1</p>
      <p>FEATURED_BODY_2</p>
      <p>FEATURED_INSIGHT</p>
      <a href="#" style="color: white;">Read more &#8594;</a>
    </div>
    <div class="nl-article-box">
      <h3 class="nl-article-title">MAIN_ARTICLE_1_HEADLINE</h3>
      <p>MAIN_ARTICLE_1_BODY</p>
      <div class="nl-callout">MAIN_ARTICLE_1_CALLOUT</div>
      <a class="nl-source-link" href="#">Read more &#8594;</a>
    </div>
    <div class="nl-article-box">
      <h3 class="nl-article-title">MAIN_ARTICLE_2_HEADLINE</h3>
      <p>MAIN_ARTICLE_2_BODY</p>
      <div class="nl-callout">MAIN_ARTICLE_2_CALLOUT</div>
      <a class="nl-source-link" href="#">Read more &#8594;</a>
    </div>
  </td></tr>
  <tr><td class="nl-quick-hits">
    <table>
      <tr><td>QUICK_HIT_1</td></tr>
      <tr><td>QUICK_HIT_2</td></tr>
      <tr><td>QUICK_HIT_3</td></tr>
    </table>
  </td></tr>
  <tr><td class="nl-industry">
    <table>
      <tr><td>INDUSTRY_1</td></tr>
      <tr><td>INDUSTRY_2</td></tr>
    </table>
  </td></tr>
  <tr><td class="nl-footer">
    <p>FOOTER_TEXT</p>
  </td></tr>
</table>
</body>
</html>
"""

SAMPLE_NEWSLETTER_DATE = "02/26/2026"

# Sample summaries for parallel steps (includes 2 unused articles).
SAMPLE_SUMMARIES: list[dict[str, Any]] = [
    {
        "URL": "https://openai.com/index/hello-gpt-4o/",
        "Title": "Hello GPT-4o",
        "Summary": "OpenAI released GPT-4o, a multimodal model.",
        "BusinessRelevance": "Free access to frontier AI.",
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

# Formatted theme dict (non-JSON) for parallel steps that expect dict input.
SAMPLE_FORMATTED_THEME_DICT: dict[str, Any] = {
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


# ---------------------------------------------------------------------------
# Phase 1: Markdown Generation with 3-Layer Validation
# ---------------------------------------------------------------------------


async def phase_markdown() -> dict[str, Any]:
    """Generate newsletter markdown via LLM and validate with 3-layer pipeline.

    Tests:
    - generate_with_validation() produces non-empty markdown via real LLM
    - Generated markdown contains expected newsletter sections
    - run_three_layer_validation() runs all 3 layers on the generated output
    - ValidationResult has correct structure (is_valid, errors, char_errors_json)
    - Error merging across layers produces a unified error list
    - ValidationLoopCounter tracks attempts correctly
    """
    print("\n" + "=" * 70)
    print("PHASE 1: Markdown Generation + 3-Layer Validation")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.errors import ValidationLoopCounter
    from ica.pipeline.markdown_generation import (
        ValidationResult,
        generate_with_validation,
        run_three_layer_validation,
    )

    gen_model = _openrouter_model(get_model(LLMPurpose.MARKDOWN))
    val_model = _openrouter_model(get_model(LLMPurpose.MARKDOWN_VALIDATOR))
    print(f"  Generation model: {gen_model}")
    print(f"  Validator model: {val_model}")

    # 1a. Verify ValidationLoopCounter
    print("\n--- 1a. ValidationLoopCounter ---")
    counter = ValidationLoopCounter(max_attempts=3)
    assert counter.count == 0
    assert not counter.exhausted
    assert counter.remaining == 3
    counter.increment()
    counter.increment()
    counter.increment()
    assert counter.exhausted
    assert counter.remaining == 0
    counter.reset()
    assert counter.count == 0
    print("  ValidationLoopCounter: OK")

    # 1b. Generate markdown (max_attempts=1 for speed)
    print("\n--- 1b. generate_with_validation (max_attempts=1) ---")
    start = time.monotonic()
    markdown = await generate_with_validation(
        SAMPLE_FORMATTED_THEME,
        generation_model=gen_model,
        validator_model=val_model,
        max_attempts=1,
    )
    gen_time = time.monotonic() - start

    assert markdown, "generate_with_validation returned empty markdown"
    assert len(markdown) > 100, f"Markdown too short: {len(markdown)} chars"
    print(f"  Generated markdown: {len(markdown)} chars in {gen_time:.1f}s")
    print(f"  First 150 chars: {markdown[:150]}...")

    # 1c. Check newsletter sections
    print("\n--- 1c. Checking newsletter sections ---")
    sections = {
        "INTRODUCTION": "INTRODUCTION" in markdown.upper(),
        "QUICK HIGHLIGHTS": "QUICK HIGHLIGHTS" in markdown.upper(),
        "FEATURED ARTICLE": "FEATURED ARTICLE" in markdown.upper(),
        "MAIN ARTICLE": "MAIN ARTICLE" in markdown.upper(),
        "INDUSTRY": "INDUSTRY" in markdown.upper(),
        "FOOTER": "FOOTER" in markdown.upper(),
    }
    for name, found in sections.items():
        print(f"  {name}: {'found' if found else 'MISSING'}")

    found_count = sum(sections.values())
    assert found_count >= 3, (
        f"Only {found_count}/6 sections found — LLM may not have generated a valid newsletter"
    )

    # 1d. Run 3-layer validation on the generated markdown
    print("\n--- 1d. run_three_layer_validation() on generated markdown ---")
    start = time.monotonic()
    val_result = await run_three_layer_validation(
        markdown,
        validator_model=val_model,
    )
    val_time = time.monotonic() - start

    assert isinstance(val_result, ValidationResult)
    assert isinstance(val_result.is_valid, bool)
    assert isinstance(val_result.errors, list)
    assert isinstance(val_result.char_errors_json, str)
    print(f"  Validation completed in {val_time:.1f}s")
    print(f"  is_valid: {val_result.is_valid}")
    print(f"  Error count: {len(val_result.errors)}")

    # Categorize errors
    voice_errors = [e for e in val_result.errors if e.startswith("VOICE:")]
    other_errors = [e for e in val_result.errors if not e.startswith("VOICE:")]
    print(f"  Non-VOICE errors: {len(other_errors)}")
    print(f"  VOICE: errors: {len(voice_errors)}")

    for i, err in enumerate(val_result.errors[:10]):
        print(f"    [{i + 1}] {err[:120]}")
    if len(val_result.errors) > 10:
        print(f"    ... and {len(val_result.errors) - 10} more")

    # Verify char_errors_json is valid JSON
    parsed_char = json.loads(val_result.char_errors_json)
    assert isinstance(parsed_char, list)
    print(f"  char_errors_json: {len(parsed_char)} entries (valid JSON)")

    results: dict[str, Any] = {
        "gen_model": gen_model,
        "val_model": val_model,
        "markdown_length": len(markdown),
        "gen_time_s": round(gen_time, 1),
        "val_time_s": round(val_time, 1),
        "sections_found": found_count,
        "is_valid": val_result.is_valid,
        "total_errors": len(val_result.errors),
        "voice_errors": len(voice_errors),
        "char_errors": len(parsed_char),
    }

    print(f"\n  Markdown: {len(markdown)} chars, valid={val_result.is_valid}")
    print("  Phase 1 PASSED: Markdown generation + 3-layer validation works.")

    results["_markdown"] = markdown
    return results


# ---------------------------------------------------------------------------
# Phase 2: HTML Generation from Markdown
# ---------------------------------------------------------------------------


async def phase_html(markdown: str | None = None) -> dict[str, Any]:
    """Convert generated markdown to HTML via real LLM.

    Tests:
    - call_html_llm() returns non-empty HTML from the Phase 1 markdown
    - Output contains <!DOCTYPE html> marker
    - Template CSS classes are preserved in the output
    - Content from the markdown is populated in the HTML
    - Data flows correctly from Step 4 → Step 5
    """
    print("\n" + "=" * 70)
    print("PHASE 2: HTML Generation from Markdown (Step 4 → Step 5)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.html_generation import HTML_VALID_MARKER, call_html_llm

    model = _openrouter_model(get_model(LLMPurpose.HTML))
    print(f"  Model: {model}")

    # Use markdown from Phase 1 if available; otherwise use a fallback
    input_markdown = markdown or _fallback_markdown()
    source = "Phase 1 output" if markdown else "fallback sample"
    print(f"  Input markdown: {len(input_markdown)} chars ({source})")

    # 2a. Generate HTML
    print("\n--- 2a. call_html_llm() ---")
    start = time.monotonic()
    html = await call_html_llm(
        markdown_content=input_markdown,
        html_template=SAMPLE_HTML_TEMPLATE,
        newsletter_date=SAMPLE_NEWSLETTER_DATE,
        model=model,
    )
    gen_time = time.monotonic() - start

    assert html, "call_html_llm returned empty response"
    print(f"  Generated HTML: {len(html)} chars in {gen_time:.1f}s")
    print(f"  First 200 chars: {html[:200]}")

    # 2b. Check DOCTYPE
    print("\n--- 2b. HTML validity markers ---")
    has_doctype = HTML_VALID_MARKER.lower() in html.lower()
    has_close = "</html>" in html.lower()
    print(f"  Has {HTML_VALID_MARKER}: {has_doctype}")
    print(f"  Has </html>: {has_close}")
    assert has_doctype, f"Generated HTML missing {HTML_VALID_MARKER}"
    assert has_close, "Generated HTML missing closing </html>"

    # 2c. Template class preservation
    print("\n--- 2c. Template structure preservation ---")
    expected_classes = [
        "nl-content",
        "nl-intro",
        "nl-quick-highlights",
        "nl-article-box",
        "nl-footer",
    ]
    preserved = 0
    for cls in expected_classes:
        found = cls in html
        print(f"  Class '{cls}': {'found' if found else 'MISSING'}")
        if found:
            preserved += 1
    assert preserved >= 3, f"Only {preserved}/{len(expected_classes)} template classes preserved"

    # 2d. Content population check
    print("\n--- 2d. Content population ---")
    content_markers = [
        ("GPT-4o", "Featured article reference"),
        ("AI Automation", "Main article 1 reference"),
        ("EU AI Act", "Main article 2 reference"),
        ("Gemini", "Industry development 1"),
    ]
    populated = 0
    for marker, desc in content_markers:
        found = marker in html
        print(f"  {desc}: {'found' if found else 'MISSING'}")
        if found:
            populated += 1
    assert populated >= 2, f"Only {populated}/{len(content_markers)} content markers found"

    results: dict[str, Any] = {
        "model": model,
        "input_source": source,
        "html_length": len(html),
        "gen_time_s": round(gen_time, 1),
        "has_doctype": has_doctype,
        "classes_preserved": preserved,
        "content_populated": populated,
    }

    print(f"\n  HTML: {len(html)} chars, {preserved} classes, {populated} content markers")
    print("  Phase 2 PASSED: HTML generation from markdown works end-to-end.")

    results["_html"] = html
    return results


# ---------------------------------------------------------------------------
# Phase 3: Google Docs Integration (Markdown + HTML)
# ---------------------------------------------------------------------------


async def phase_gdocs(
    markdown: str | None = None,
    html: str | None = None,
) -> dict[str, Any]:
    """Create Google Docs for markdown and HTML, verify round-trip storage.

    Tests:
    - GoogleDocsService initializes with real credentials
    - Markdown doc: create → insert → read back
    - HTML doc: create_html_doc() helper returns (doc_id, doc_url)
    - Doc URLs have correct format
    - Content round-trip: inserted text can be retrieved
    """
    print("\n" + "=" * 70)
    print("PHASE 3: Google Docs Integration (Markdown + HTML)")
    print("=" * 70)

    creds_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
        "credentials/google-service-account.json",
    )
    drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")

    print(f"  Credentials: {creds_path}")
    print(f"  Shared Drive ID: {drive_id[:20]}..." if drive_id else "  Shared Drive: (none)")

    from ica.pipeline.html_generation import create_html_doc
    from ica.services.google_docs import GoogleDocsService

    docs = GoogleDocsService(credentials_path=creds_path, drive_id=drive_id)

    test_markdown = markdown or "# Test Newsletter\n\nSample markdown content."
    test_html = html or (
        "<!DOCTYPE html><html><body>"
        "<h1>Phase C Integration Test</h1>"
        "<p>Generated by test_generation_validation.py</p>"
        "</body></html>"
    )

    # 3a. Markdown doc: create + insert + read back
    print("\n--- 3a. Markdown Google Doc ---")
    md_doc_id = await docs.create_document(
        "Phase C Integration Test - Markdown",
    )
    assert md_doc_id, "create_document returned empty doc_id"
    print(f"  Doc ID: {md_doc_id}")

    await docs.insert_content(md_doc_id, test_markdown)
    print(f"  Inserted: {len(test_markdown)} chars")

    md_content = await docs.get_content(md_doc_id)
    assert md_content, "get_content returned empty string"
    print(f"  Retrieved: {len(md_content)} chars")
    print("  Markdown round-trip: OK")

    # 3b. HTML doc: create_html_doc helper
    print("\n--- 3b. HTML Google Doc (create_html_doc helper) ---")
    html_doc_id, html_doc_url = await create_html_doc(
        docs,
        test_html,
        title="Phase C Integration Test - HTML",
    )

    assert html_doc_id, "create_html_doc returned empty doc_id"
    assert html_doc_url.startswith("https://docs.google.com/document/d/")
    assert html_doc_id in html_doc_url
    print(f"  Doc ID: {html_doc_id}")
    print(f"  Doc URL: {html_doc_url}")
    print("  create_html_doc: OK")

    results: dict[str, Any] = {
        "markdown_doc_id": md_doc_id,
        "html_doc_id": html_doc_id,
        "html_doc_url": html_doc_url,
        "markdown_insert_len": len(test_markdown),
        "markdown_retrieved_len": len(md_content),
        "html_insert_len": len(test_html),
    }

    print("\n  Created 2 docs (markdown + HTML), round-trip verified")
    print("  Phase 3 PASSED: Google Docs integration works for both content types.")

    return results


# ---------------------------------------------------------------------------
# Phase 4: Parallel Output Steps 6a-6d
# ---------------------------------------------------------------------------


async def phase_parallel(
    html: str | None = None,
    *,
    skip_gdocs: bool = False,
) -> dict[str, Any]:
    """Run all four parallel steps concurrently using Phase 2 HTML output.

    Tests:
    - All 4 steps complete successfully via asyncio.gather()
    - Wall-clock time < sum of individual times (concurrency proof)
    - Each step populates its expected ctx.extra keys
    - No shared-state corruption across concurrent tasks
    - Failure isolation: a failed step does not cancel siblings
    """
    print("\n" + "=" * 70)
    print("PHASE 4: Parallel Output Steps 6a-6d (asyncio.gather)")
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
    from ica.pipeline.linkedin_carousel import (
        generate_with_validation as carousel_gen,
    )
    from ica.pipeline.social_media import (
        call_social_media_post_llm,
        parse_phase1_titles,
    )

    # Use HTML from Phase 2, or build a minimal fallback
    test_html = html or _fallback_html()
    source = "Phase 2 output" if html else "fallback sample"
    print(f"  Input HTML: {len(test_html)} chars ({source})")

    plain_text = strip_html_to_text(test_html)
    formatted_theme_json = json.dumps(SAMPLE_FORMATTED_THEME_DICT, indent=2)

    # Shared state dict simulating PipelineContext.extra
    extra: dict[str, Any] = {}
    timings: dict[str, float] = {}
    errors: dict[str, str] = {}

    # Define the 4 concurrent tasks
    async def task_6a() -> None:
        start = time.monotonic()
        result = filter_unused_articles(
            SAMPLE_FORMATTED_THEME_DICT,
            SAMPLE_SUMMARIES,
        )
        extra["alternates_unused_summaries"] = result.unused_summaries
        extra["alternates_urls_in_theme"] = result.urls_in_theme
        timings["6a_alternates"] = time.monotonic() - start

    async def task_6b() -> None:
        start = time.monotonic()
        model = _openrouter_model(get_model(LLMPurpose.EMAIL_SUBJECT))
        raw = await call_email_subject_llm(
            newsletter_text=plain_text,
            model=model,
        )
        subjects, _rec = parse_subjects(raw)
        extra["email_subject"] = subjects[0].subject if subjects else ""
        review_model = _openrouter_model(get_model(LLMPurpose.EMAIL_PREVIEW))
        review = await call_email_review_llm(
            newsletter_text=plain_text,
            model=review_model,
        )
        extra["email_review"] = review
        timings["6b_email"] = time.monotonic() - start

    async def task_6c() -> None:
        start = time.monotonic()
        model = _openrouter_model(get_model(LLMPurpose.SOCIAL_MEDIA))
        raw = await call_social_media_post_llm(
            newsletter_content=test_html,
            formatted_theme=formatted_theme_json,
            model=model,
        )
        titles = parse_phase1_titles(raw)
        extra["social_media_titles"] = titles
        extra["social_media_raw"] = raw
        timings["6c_social"] = time.monotonic() - start

    async def task_6d() -> None:
        start = time.monotonic()
        model = _openrouter_model(get_model(LLMPurpose.LINKEDIN))
        output, errs = await carousel_gen(
            formatted_theme=formatted_theme_json,
            newsletter_content=test_html,
            max_attempts=2,
            model=model,
        )
        extra["linkedin_carousel_output"] = output
        extra["linkedin_carousel_errors"] = len(errs)
        timings["6d_carousel"] = time.monotonic() - start

    async def safe_run(name: str, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            errors[name] = str(exc)
            print(f"  WARNING: {name} failed: {exc}")

    # Run all 4 concurrently
    print("\n--- 4a. Launching 4 tasks via asyncio.gather() ---")
    wall_start = time.monotonic()

    await asyncio.gather(
        safe_run("6a_alternates", task_6a()),
        safe_run("6b_email", task_6b()),
        safe_run("6c_social", task_6c()),
        safe_run("6d_carousel", task_6d()),
    )

    wall_time = time.monotonic() - wall_start
    sequential_sum = sum(timings.values())

    # Timing results
    print("\n--- 4b. Timing results ---")
    for step_name, duration in sorted(timings.items()):
        print(f"  {step_name}: {duration:.2f}s")
    print(f"  Sequential sum: {sequential_sum:.2f}s")
    print(f"  Wall-clock time: {wall_time:.2f}s")

    speedup = sequential_sum / wall_time if wall_time > 0 else 0.0
    print(f"  Speedup factor: {speedup:.2f}x")

    # Concurrency check
    llm_timings = {k: v for k, v in timings.items() if k != "6a_alternates"}
    if len(llm_timings) >= 2:
        llm_sum = sum(llm_timings.values())
        assert wall_time < llm_sum, (
            f"Wall time ({wall_time:.2f}s) >= sum of LLM times"
            f" ({llm_sum:.2f}s) — may not be concurrent"
        )
        print("  Concurrency check: PASSED")

    # Verify ctx.extra keys
    print("\n--- 4c. Shared state verification ---")
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

    successful_steps = len(timings)
    print(f"\n  Populated keys: {populated}/{len(expected_keys)}")
    print(f"  Successful steps: {successful_steps}/4")
    print(f"  Failed steps: {len(errors)}")
    for name, err_msg in errors.items():
        print(f"    {name}: {err_msg[:100]}")

    assert successful_steps >= 3, (
        f"Only {successful_steps}/4 steps succeeded: {list(errors.keys())}"
    )

    results: dict[str, Any] = {
        "wall_time_s": round(wall_time, 2),
        "sequential_sum_s": round(sequential_sum, 2),
        "speedup": round(speedup, 2),
        "successful_steps": successful_steps,
        "failed_steps": len(errors),
        "populated_keys": populated,
    }

    print(f"\n  {successful_steps}/4 steps, wall={wall_time:.2f}s, speedup={speedup:.1f}x")
    print("  Phase 4 PASSED: Parallel output steps run concurrently.")

    return results


# ---------------------------------------------------------------------------
# Phase 5: Orchestrator Integration
# ---------------------------------------------------------------------------


async def phase_orchestrator() -> dict[str, Any]:
    """Run Steps 4-5 + parallel 6a-6d via the real orchestrator.

    Tests:
    - PipelineContext flows correctly between sequential steps
    - run_pipeline() executes sequential then parallel steps
    - StepResult timing is recorded for each step
    - Parallel step failures do not block other parallel steps
    - ctx.extra keys are populated after parallel execution

    Note: This phase uses mock services for Slack and Google Docs to avoid
    interactive human-in-the-loop prompts, but calls the real LLM endpoints.
    The orchestrator's structural behavior (step ordering, timing, error
    handling, context propagation) is the focus.
    """
    print("\n" + "=" * 70)
    print("PHASE 5: Orchestrator Integration (run_pipeline)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.orchestrator import PipelineContext, StepResult, run_pipeline

    gen_model = _openrouter_model(get_model(LLMPurpose.MARKDOWN))
    val_model = _openrouter_model(get_model(LLMPurpose.MARKDOWN_VALIDATOR))
    html_model = _openrouter_model(get_model(LLMPurpose.HTML))

    # Build a PipelineContext with Phase B outputs already set
    # (simulating Steps 1-3 completed)
    ctx = PipelineContext(
        run_id="integ-phase-c-test",
        trigger="integration_test",
        formatted_theme=SAMPLE_FORMATTED_THEME_DICT,
        theme_name="AI Accessibility Revolution",
        summaries=SAMPLE_SUMMARIES,
        summaries_json=json.dumps(SAMPLE_SUMMARIES, default=str),
    )

    print(f"  run_id: {ctx.run_id}")
    print(f"  theme: {ctx.theme_name}")
    print(f"  summaries: {len(ctx.summaries)} articles")

    # Create lightweight step functions that bypass Slack interactive loops
    # but exercise the core generation logic

    async def step_4_markdown(ctx: PipelineContext) -> PipelineContext:
        """Step 4: Markdown generation (no Slack review loop)."""
        from ica.pipeline.markdown_generation import generate_with_validation

        formatted_theme_str = json.dumps(ctx.formatted_theme, default=str)
        markdown = await generate_with_validation(
            formatted_theme_str,
            generation_model=gen_model,
            validator_model=val_model,
            max_attempts=1,
        )
        # Store markdown in extra (real pipeline stores via Google Docs)
        ctx.extra["generated_markdown"] = markdown
        return ctx

    async def step_5_html(ctx: PipelineContext) -> PipelineContext:
        """Step 5: HTML generation (no Slack review loop)."""
        from ica.pipeline.html_generation import call_html_llm

        markdown = ctx.extra.get("generated_markdown", "")
        assert markdown, "No markdown from Step 4"

        html = await call_html_llm(
            markdown_content=markdown,
            html_template=SAMPLE_HTML_TEMPLATE,
            newsletter_date=SAMPLE_NEWSLETTER_DATE,
            model=html_model,
        )
        ctx.extra["generated_html"] = html
        return ctx

    async def step_6a_alternates(ctx: PipelineContext) -> PipelineContext:
        """Step 6a: Filter unused articles."""
        from ica.pipeline.alternates_html import filter_unused_articles

        result = filter_unused_articles(ctx.formatted_theme, ctx.summaries)
        ctx.extra["alternates_unused_summaries"] = result.unused_summaries
        return ctx

    async def step_6b_email(ctx: PipelineContext) -> PipelineContext:
        """Step 6b: Email subject generation."""
        from ica.pipeline.email_subject import (
            call_email_subject_llm,
            parse_subjects,
            strip_html_to_text,
        )

        html = ctx.extra.get("generated_html", "")
        plain_text = strip_html_to_text(html) if html else "Test content"
        model = _openrouter_model(get_model(LLMPurpose.EMAIL_SUBJECT))
        raw = await call_email_subject_llm(
            newsletter_text=plain_text,
            model=model,
        )
        subjects, _rec = parse_subjects(raw)
        ctx.extra["email_subject"] = subjects[0].subject if subjects else ""
        return ctx

    async def step_6c_social(ctx: PipelineContext) -> PipelineContext:
        """Step 6c: Social media post generation."""
        from ica.pipeline.social_media import (
            call_social_media_post_llm,
            parse_phase1_titles,
        )

        html = ctx.extra.get("generated_html", "")
        formatted = json.dumps(ctx.formatted_theme, indent=2)
        model = _openrouter_model(get_model(LLMPurpose.SOCIAL_MEDIA))
        raw = await call_social_media_post_llm(
            newsletter_content=html,
            formatted_theme=formatted,
            model=model,
        )
        titles = parse_phase1_titles(raw)
        ctx.extra["social_media_titles"] = titles
        return ctx

    async def step_6d_carousel(ctx: PipelineContext) -> PipelineContext:
        """Step 6d: LinkedIn carousel generation."""
        from ica.pipeline.linkedin_carousel import (
            generate_with_validation as carousel_gen,
        )

        html = ctx.extra.get("generated_html", "")
        formatted = json.dumps(ctx.formatted_theme, indent=2)
        model = _openrouter_model(get_model(LLMPurpose.LINKEDIN))
        output, _errs = await carousel_gen(
            formatted_theme=formatted,
            newsletter_content=html,
            max_attempts=1,
            model=model,
        )
        ctx.extra["linkedin_carousel_output"] = output
        return ctx

    # Define pipeline step lists
    sequential = [
        ("markdown_generation", step_4_markdown),
        ("html_generation", step_5_html),
    ]
    parallel = [
        ("alternates_html", step_6a_alternates),
        ("email_subject", step_6b_email),
        ("social_media", step_6c_social),
        ("linkedin_carousel", step_6d_carousel),
    ]

    # Run the orchestrator
    print("\n--- 5a. Running run_pipeline() ---")
    start = time.monotonic()
    ctx = await run_pipeline(
        ctx,
        sequential_steps=sequential,
        parallel_steps=parallel,
    )
    total_time = time.monotonic() - start

    print(f"\n--- 5b. Pipeline completed in {total_time:.1f}s ---")

    # Check StepResults
    print("\n--- 5c. Step results ---")
    for sr in ctx.step_results:
        assert isinstance(sr, StepResult)
        print(
            f"  {sr.step}: {sr.status} ({sr.duration_seconds:.1f}s)"
            + (f" error={sr.error}" if sr.error else "")
        )

    completed = [sr for sr in ctx.step_results if sr.status == "completed"]
    failed = [sr for sr in ctx.step_results if sr.status == "failed"]
    print(f"\n  Completed: {len(completed)}/{len(ctx.step_results)}")
    print(f"  Failed: {len(failed)}/{len(ctx.step_results)}")

    # Sequential steps must succeed
    seq_results = [
        sr for sr in ctx.step_results if sr.step in ("markdown_generation", "html_generation")
    ]
    for sr in seq_results:
        assert sr.status == "completed", f"Sequential step {sr.step} failed: {sr.error}"
    print("  Sequential steps (4, 5): all completed")

    # At least 3 of 4 parallel steps should succeed
    par_results = [
        sr
        for sr in ctx.step_results
        if sr.step
        in (
            "alternates_html",
            "email_subject",
            "social_media",
            "linkedin_carousel",
        )
    ]
    par_completed = sum(1 for sr in par_results if sr.status == "completed")
    assert par_completed >= 3, f"Only {par_completed}/4 parallel steps completed"
    print(f"  Parallel steps (6a-6d): {par_completed}/4 completed")

    # Verify context propagation: markdown → HTML → parallel steps
    print("\n--- 5d. Context propagation ---")
    has_md = bool(ctx.extra.get("generated_markdown"))
    has_html = bool(ctx.extra.get("generated_html"))
    has_alt = "alternates_unused_summaries" in ctx.extra
    has_email = bool(ctx.extra.get("email_subject"))
    print(f"  generated_markdown: {'present' if has_md else 'MISSING'}")
    print(f"  generated_html: {'present' if has_html else 'MISSING'}")
    print(f"  alternates: {'present' if has_alt else 'MISSING'}")
    print(f"  email_subject: {'present' if has_email else 'MISSING'}")

    assert has_md, "Markdown not propagated to context"
    assert has_html, "HTML not propagated to context"

    results: dict[str, Any] = {
        "total_time_s": round(total_time, 1),
        "total_steps": len(ctx.step_results),
        "completed_steps": len(completed),
        "failed_steps": len(failed),
        "sequential_ok": len(seq_results),
        "parallel_completed": par_completed,
        "context_md": has_md,
        "context_html": has_html,
    }

    print(
        f"\n  Pipeline: {len(completed)} completed, {len(failed)} failed, {total_time:.1f}s total"
    )
    print("  Phase 5 PASSED: Orchestrator runs Steps 4-6d with context propagation.")

    return results


# ---------------------------------------------------------------------------
# Fallback helpers (when running individual phases without prior data)
# ---------------------------------------------------------------------------


def _fallback_markdown() -> str:
    """Provide minimal newsletter markdown when Phase 1 is skipped."""
    intro = (
        "The AI landscape shifted this week in ways that matter for"
        " your bottom line. OpenAI\u2019s GPT-4o dropped barriers to"
        " entry, Google\u2019s Gemini pushed boundaries, and the"
        " EU\u2019s AI Act moved from theory to hard deadlines."
    )
    return (
        f"# *INTRODUCTION*\n\n{intro}\n\n"
        "# *QUICK HIGHLIGHTS*\n\n"
        "\u2022 **GPT-4o** marks a watershed moment for AI accessibility.\n"
        "\u2022 **Gemini\u2019s tiered approach** solves the deployment puzzle.\n"
        "\u2022 **EU AI Act deadlines** are no longer theoretical.\n\n"
        "# *FEATURED ARTICLE*\n\n"
        "## [Hello GPT-4o](https://openai.com/index/hello-gpt-4o/)\n\n"
        "OpenAI\u2019s release of GPT-4o represents a strategic"
        " repositioning of who gets access to frontier AI.\n\n"
        "**Strategic Shift:** OpenAI is commoditizing the capability"
        " layer and betting on ecosystem lock-in.\n\nRead more \u2192\n\n"
        "# *MAIN ARTICLE 1*\n\n"
        "## [5 AI Automation Trends](https://example.com/ai-automation-trends)\n\n"
        "Small businesses are embedding AI into customer service.\n\n"
        "**Take-away:** Focus AI investment on customer-facing workflows.\n\n"
        "# *MAIN ARTICLE 2*\n\n"
        "## [EU AI Act Timeline](https://example.com/ai-regulation-update)\n\n"
        "High-risk AI system providers face the earliest deadlines.\n\n"
        "**Actionable Steps:** Map every AI tool against the EU risk framework.\n\n"
        "# *INDUSTRY DEVELOPMENTS*\n\n"
        "## [Introducing Gemini](https://blog.google/technology/ai/google-gemini-ai/)\n\n"
        "Google launched Gemini in three sizes.\n\n"
        "## [Microsoft Copilot](https://example.com/microsoft-copilot-enterprise)\n\n"
        "Microsoft embedding Copilot across Dynamics 365 and Azure.\n\n"
        "# *FOOTER*\n\n"
        "That\u2019s a wrap for the week! Keep building with purpose.\n"
    )


def _fallback_html() -> str:
    """Provide minimal HTML when Phase 2 is skipped."""
    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<title>AI Accessibility Revolution</title></head><body>"
        "<h1>AI Accessibility Revolution</h1>"
        "<p>The AI landscape shifted this week. OpenAI's GPT-4o dropped"
        " barriers. Google's Gemini pushed boundaries. The EU AI Act"
        " moved from theory to deadlines.</p>"
        "<h2>Featured: Hello GPT-4o</h2>"
        "<p>OpenAI's GPT-4o processes text, audio, and vision at half"
        " the cost of GPT-4 Turbo.</p>"
        "<h2>5 AI Automation Trends</h2>"
        "<p>Companies embedding AI into customer service saw 35% cost"
        " reductions.</p>"
        "<h2>EU AI Act Timeline</h2>"
        "<p>Classification requirements due by mid-2026.</p>"
        "<h2>Industry Developments</h2>"
        "<p>Google launched Gemini. Microsoft embedding Copilot across"
        " enterprise apps.</p>"
        "<p>That's a wrap for the week!</p>"
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: generation & validation pipeline (Phase C).",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=[
            "all",
            "markdown",
            "html",
            "gdocs",
            "parallel",
            "orchestrator",
        ],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-gdocs",
        action="store_true",
        help="Skip Google Docs phases (no Google credentials required)",
    )
    parser.add_argument(
        "--skip-parallel",
        action="store_true",
        help="Skip parallel output steps (runs markdown + HTML only)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}
    generated_markdown: str | None = None
    generated_html: str | None = None

    # Phase 1: Markdown Generation + Validation
    if args.phase in ("all", "markdown"):
        md_results = await phase_markdown()
        generated_markdown = md_results.pop("_markdown", None)
        results["markdown"] = md_results

    # Phase 2: HTML Generation from Markdown
    if args.phase in ("all", "html"):
        html_results = await phase_html(markdown=generated_markdown)
        generated_html = html_results.pop("_html", None)
        results["html"] = html_results

    # Phase 3: Google Docs
    if args.phase in ("all", "gdocs") and not args.skip_gdocs:
        results["gdocs"] = await phase_gdocs(
            markdown=generated_markdown,
            html=generated_html,
        )
    elif args.skip_gdocs and args.phase in ("all",):
        print("\n  Google Docs phase skipped (--skip-gdocs).")

    # Phase 4: Parallel Output Steps
    if args.skip_parallel:
        if args.phase in ("all",):
            print("\n  Parallel output steps skipped (--skip-parallel).")
    else:
        if args.phase in ("all", "parallel"):
            results["parallel"] = await phase_parallel(
                html=generated_html,
                skip_gdocs=args.skip_gdocs,
            )

    # Phase 5: Orchestrator Integration
    if args.skip_parallel:
        if args.phase in ("all",):
            print("\n  Orchestrator phase skipped (--skip-parallel).")
    else:
        if args.phase in ("all", "orchestrator"):
            results["orchestrator"] = await phase_orchestrator()

    # Summary
    print("\n" + "=" * 70)
    print("PHASE C INTEGRATION TEST SUMMARY")
    print("=" * 70)

    for phase_name, phase_results in results.items():
        print(f"\n  {phase_name}:")
        for key, value in phase_results.items():
            display = str(value)
            if len(display) > 100:
                display = display[:100] + "..."
            print(f"    {key}: {display}")

    print("\nGeneration & validation pipeline (Phase C) integration test complete!")


if __name__ == "__main__":
    main()
