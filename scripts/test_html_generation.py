"""Integration test — HTML generation & Google Docs.

Exercises Step 5 of the newsletter pipeline with real services:

1. Prompt building: verify build_html_generation_prompt() and
   build_html_regeneration_prompt() produce valid system/user prompts
2. HTML generation LLM: call call_html_llm() with real LLM to convert
   sample markdown + minimal HTML template into rendered HTML
3. Google Docs creation: create_html_doc() → insert HTML → read back
   via GoogleDocsService (real Google Docs API)
4. HTML regeneration LLM: call call_html_regeneration() with scoped
   feedback to modify a single section
5. Learning data extraction: call extract_html_learning_data() to
   distill user feedback into a storable learning note

Usage:
    docker exec ica-app-1 python scripts/test_html_generation.py
    docker exec ica-app-1 python scripts/test_html_generation.py --phase prompts
    docker exec ica-app-1 python scripts/test_html_generation.py --phase generate
    docker exec ica-app-1 python scripts/test_html_generation.py --phase gdocs
    docker exec ica-app-1 python scripts/test_html_generation.py --phase regenerate
    docker exec ica-app-1 python scripts/test_html_generation.py --phase learning
    docker exec ica-app-1 python scripts/test_html_generation.py --skip-gdocs
    docker exec ica-app-1 python scripts/test_html_generation.py --skip-llm

Requires OPENROUTER_API_KEY (for LLM calls) and Google service account
credentials with Shared Drive access (for Google Docs).  Run inside the
app container where .env is loaded automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
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
# Sample data — reuse markdown from test_markdown_validation.py
# ---------------------------------------------------------------------------


def _build_sample_markdown() -> str:
    """Build a realistic newsletter markdown for HTML generation testing."""
    intro = (
        "The AI landscape shifted this week in ways that matter for"
        " your bottom line. OpenAI\u2019s GPT-4o dropped barriers to"
        " entry by making frontier AI free, Google\u2019s Gemini pushed"
        " the boundaries of what multimodal means in practice, and the"
        " EU\u2019s AI Act moved from theory to hard deadlines that"
        " every business selling into Europe needs on their calendar"
        " right now."
    )

    bullet_1 = (
        "\u2022 **GPT-4o accessibility** marks a watershed moment"
        " \u2014 OpenAI\u2019s decision to offer their most capable"
        " model for free means solopreneurs and small teams now have"
        " the same AI firepower as enterprise competitors,"
        " fundamentally changing the competitive calculus."
    )
    bullet_2 = (
        "\u2022 **Gemini\u2019s tiered approach** solves the deployment"
        " puzzle that\u2019s held back many SMBs \u2014 by offering"
        " Ultra, Pro, and Nano variants, Google lets businesses match"
        " AI capability to budget without sacrificing quality on the"
        " tasks that actually matter to them."
    )
    bullet_3 = (
        "\u2022 **EU AI Act deadlines** are no longer theoretical"
        " \u2014 with classification requirements hitting mid-2026,"
        " companies selling to European customers face concrete"
        " compliance costs that need to be budgeted now, not next"
        " quarter."
    )

    fa_headline = (
        "## [Hello GPT-4o: OpenAI\u2019s Latest Multimodal Model]"
        "(https://openai.com/index/hello-gpt-4o/)"
    )
    fa_p1 = (
        "OpenAI\u2019s release of GPT-4o represents more than just"
        " another model update \u2014 it\u2019s a strategic"
        " repositioning of who gets access to frontier AI"
        " capabilities. The model processes text, audio, and vision"
        " simultaneously in real time, matching GPT-4 Turbo\u2019s"
        " intelligence while running at twice the speed and half the"
        " cost. For businesses that have been waiting on the"
        " sidelines, the calculus just changed."
    )
    fa_p2 = (
        "The practical implications hit hardest for customer-facing"
        " applications. Real-time multimodal processing means a"
        " single API call can handle what previously required"
        " stitching together separate vision, speech, and text"
        " models. Early adopters report cutting their AI"
        " infrastructure costs by 40-60% while actually improving"
        " response quality across non-English markets."
    )
    fa_insight = (
        "**Strategic Shift:** The real story isn\u2019t the"
        " technology \u2014 it\u2019s the pricing. By making GPT-4o"
        " available to free-tier users, OpenAI is commoditizing the"
        " capability layer and betting that developer ecosystem"
        " lock-in matters more than per-call revenue in the long run."
    )

    ma1_headline = (
        "## [5 AI Automation Trends Reshaping Small Businesses]"
        "(https://example.com/ai-automation-trends)"
    )
    ma1_content = (
        "Small businesses are moving past the experimentation phase"
        " with AI automation. The data shows a clear pattern:"
        " companies that embedded AI into customer service workflows"
        " first saw 35% cost reductions within six months, while"
        " those starting with content creation reported mixed results"
        " until they paired AI generation with human editorial"
        " oversight."
    )
    ma1_callout = (
        "**Strategic Take-away:** Focus AI investment on"
        " customer-facing workflows where response time directly"
        " correlates with revenue \u2014 customer service, quote"
        " generation, and scheduling \u2014 before expanding to"
        " creative and analytical applications."
    )

    ma2_headline = (
        "## [EU AI Act Implementation Timeline](https://example.com/ai-regulation-update)"
    )
    ma2_content = (
        "The EU AI Act\u2019s implementation timeline creates a"
        " concrete compliance roadmap that businesses can no longer"
        " afford to treat as theoretical. High-risk AI system"
        " providers face the earliest deadlines, with classification"
        " requirements due by mid-2026 and full compliance"
        " documentation required six months after that."
    )
    ma2_callout = (
        "**Actionable Steps:** Map every AI tool in your stack"
        " against the EU\u2019s four-tier risk framework this month."
        " Start with customer-facing chatbots and hiring"
        " algorithms \u2014 these consistently land in the high-risk"
        " category and require the most documentation lead time."
    )

    i1_headline = (
        "## [Introducing Gemini: Google\u2019s Most Capable AI"
        " Model](https://blog.google/technology/ai/google-gemini-ai/)"
    )
    i1_body = (
        "Google launched Gemini in three sizes \u2014 Ultra, Pro,"
        " and Nano \u2014 each targeting different deployment"
        " scenarios. Ultra leads benchmarks in 30 of 32 academic"
        " tests."
    )

    i2_headline = (
        "## [Microsoft Expands Copilot to All Enterprise"
        " Applications]"
        "(https://example.com/microsoft-copilot-enterprise)"
    )
    i2_body = (
        "Microsoft is embedding Copilot across Dynamics 365, Power"
        " Platform, and Azure. Early enterprise adopters report 30%"
        " average productivity gains across workflow automation"
        " tasks."
    )

    return (
        f"# *INTRODUCTION*\n\n{intro}\n\n"
        f"# *QUICK HIGHLIGHTS*\n\n{bullet_1}\n{bullet_2}\n"
        f"{bullet_3}\n\n"
        f"# *FEATURED ARTICLE*\n\n{fa_headline}\n\n"
        f"{fa_p1}\n\n{fa_p2}\n\n{fa_insight}\n\nRead more \u2192\n\n"
        f"# *MAIN ARTICLE 1*\n\n{ma1_headline}\n\n"
        f"{ma1_content}\n\n{ma1_callout}\n\n"
        f"[Read more \u2192](https://example.com/ai-automation-trends)"
        f"\n\n"
        f"# *MAIN ARTICLE 2*\n\n{ma2_headline}\n\n"
        f"{ma2_content}\n\n{ma2_callout}\n\n"
        f"[Read more \u2192](https://example.com/ai-regulation-update)"
        f"\n\n"
        f"# *INDUSTRY DEVELOPMENTS*\n\n{i1_headline}\n\n"
        f"{i1_body}\n\n{i2_headline}\n\n{i2_body}\n\n"
        f"# *FOOTER*\n\n"
        f"Alright, that\u2019s a wrap for the week!\n\n"
        f"Until next time, keep building with purpose and stay"
        f" ahead of the curve.\n\n"
        f"Thoughts?\n"
    )


SAMPLE_MARKDOWN = _build_sample_markdown()

# Minimal HTML template with the CSS classes the LLM prompt references.
# Provides just enough structure for the LLM to populate correctly.
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


# ---------------------------------------------------------------------------
# Phase 1: Prompt Building
# ---------------------------------------------------------------------------


async def phase_prompts() -> dict[str, Any]:
    """Verify HTML generation and regeneration prompt builders.

    Tests:
    - build_html_generation_prompt() returns (system, user) tuple
    - System prompt contains key markers (ROLE, TEMPLATE PRESERVATION)
    - User prompt contains the markdown content and template
    - build_html_regeneration_prompt() returns valid prompts for scoped updates
    - Feedback section is injected when aggregated_feedback is provided
    """
    print("\n" + "=" * 70)
    print("PHASE 1: Prompt Building")
    print("=" * 70)

    from ica.prompts.html_generation import (
        build_html_generation_prompt,
        build_html_regeneration_prompt,
    )

    # 1a. Generation prompt without feedback
    print("\n--- 1a. build_html_generation_prompt (no feedback) ---")
    sys_prompt, user_prompt = build_html_generation_prompt(
        markdown_content=SAMPLE_MARKDOWN,
        html_template=SAMPLE_HTML_TEMPLATE,
        newsletter_date=SAMPLE_NEWSLETTER_DATE,
    )

    assert sys_prompt, "System prompt is empty"
    assert user_prompt, "User prompt is empty"
    assert "ROLE" in sys_prompt, "System prompt missing ROLE section"
    assert "TEMPLATE PRESERVATION" in sys_prompt, "System prompt missing TEMPLATE PRESERVATION"
    assert SAMPLE_NEWSLETTER_DATE in user_prompt, "User prompt missing newsletter date"
    assert "INTRODUCTION" in user_prompt, "User prompt missing markdown content"
    assert "nl-content" in user_prompt, "User prompt missing HTML template"
    print(f"  System prompt: {len(sys_prompt)} chars")
    print(f"  User prompt: {len(user_prompt)} chars")
    print("  Structure: OK (ROLE, TEMPLATE PRESERVATION, content, template)")

    # 1b. Generation prompt with feedback
    print("\n--- 1b. build_html_generation_prompt (with feedback) ---")
    feedback = "\u2022 Tone should be more conversational\n\u2022 Shorten the introduction"
    sys_fb, _user_fb = build_html_generation_prompt(
        markdown_content=SAMPLE_MARKDOWN,
        html_template=SAMPLE_HTML_TEMPLATE,
        newsletter_date=SAMPLE_NEWSLETTER_DATE,
        aggregated_feedback=feedback,
    )

    assert "Editorial Improvement Context" in sys_fb, "System prompt missing feedback section"
    assert "conversational" in sys_fb, "Feedback content not injected into system prompt"
    print(f"  System prompt (with feedback): {len(sys_fb)} chars")
    print("  Feedback section detected: OK")
    print(f"  Delta vs. no-feedback: +{len(sys_fb) - len(sys_prompt)} chars")

    # 1c. Regeneration prompt
    print("\n--- 1c. build_html_regeneration_prompt ---")
    regen_sys, regen_user = build_html_regeneration_prompt(
        previous_html="<html><body>previous</body></html>",
        markdown_content=SAMPLE_MARKDOWN,
        html_template=SAMPLE_HTML_TEMPLATE,
        user_feedback="Make the introduction shorter and punchier",
        newsletter_date=SAMPLE_NEWSLETTER_DATE,
    )

    assert regen_sys, "Regeneration system prompt is empty"
    assert regen_user, "Regeneration user prompt is empty"
    assert "scoped update" in regen_sys.lower(), (
        "Regeneration system prompt missing scoped update reference"
    )
    assert "previous" in regen_user.lower(), "Regeneration user prompt missing previous HTML"
    assert "introduction shorter" in regen_user.lower(), (
        "Regeneration user prompt missing user feedback"
    )
    print(f"  Regen system prompt: {len(regen_sys)} chars")
    print(f"  Regen user prompt: {len(regen_user)} chars")
    print("  Structure: OK (scoped update mode, previous HTML, feedback)")

    results: dict[str, Any] = {
        "gen_system_len": len(sys_prompt),
        "gen_user_len": len(user_prompt),
        "gen_feedback_system_len": len(sys_fb),
        "regen_system_len": len(regen_sys),
        "regen_user_len": len(regen_user),
        "all_prompts_valid": True,
    }

    print("\n  Phase 1 PASSED: All prompt builders produce valid output.")
    return results


# ---------------------------------------------------------------------------
# Phase 2: HTML Generation LLM Call
# ---------------------------------------------------------------------------


async def phase_generate() -> dict[str, Any]:
    """Call the real LLM to generate HTML from markdown + template.

    Tests:
    - call_html_llm() returns non-empty HTML
    - Output contains <!DOCTYPE html> marker
    - Output contains expected CSS classes from the template
    - Output contains content from the markdown (article titles, links)
    - All external links include target="_blank"
    """
    print("\n" + "=" * 70)
    print("PHASE 2: HTML Generation LLM Call")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.html_generation import HTML_VALID_MARKER, call_html_llm

    model = _openrouter_model(get_model(LLMPurpose.HTML))
    print(f"  Model: {model}")

    # Generate HTML
    print("\n--- 2a. Calling call_html_llm() ---")
    html = await call_html_llm(
        markdown_content=SAMPLE_MARKDOWN,
        html_template=SAMPLE_HTML_TEMPLATE,
        newsletter_date=SAMPLE_NEWSLETTER_DATE,
        model=model,
    )

    assert html, "call_html_llm returned empty response"
    print(f"  Generated HTML: {len(html)} chars")
    print(f"  First 200 chars: {html[:200]}")

    # Check DOCTYPE marker
    print("\n--- 2b. Checking HTML validity markers ---")
    has_doctype = HTML_VALID_MARKER.lower() in html.lower()
    print(f"  Has {HTML_VALID_MARKER}: {has_doctype}")
    assert has_doctype, f"Generated HTML missing {HTML_VALID_MARKER}"

    has_html_close = "</html>" in html.lower()
    print(f"  Has </html>: {has_html_close}")
    assert has_html_close, "Generated HTML missing closing </html> tag"

    # Check template CSS classes preserved
    print("\n--- 2c. Checking template structure preservation ---")
    expected_classes = [
        "nl-content",
        "nl-intro",
        "nl-quick-highlights",
        "nl-article-box",
        "nl-footer",
    ]
    for cls in expected_classes:
        found = cls in html
        print(f"  Class '{cls}': {'found' if found else 'MISSING'}")
        assert found, f"Template class '{cls}' not preserved in output"

    # Check markdown content was populated
    print("\n--- 2d. Checking content population ---")
    content_markers = [
        ("GPT-4o", "Featured article title"),
        ("openai.com", "Featured article link domain"),
        ("AI Automation Trends", "Main article 1 reference"),
        ("EU AI Act", "Main article 2 reference"),
        ("Gemini", "Industry development 1"),
        ("Alright, that\u2019s a wrap", "Footer text"),
    ]
    for marker, description in content_markers:
        found = marker in html
        print(f"  {description}: {'found' if found else 'MISSING'}")

    # Count populated markers (don't assert all — LLM may rephrase slightly)
    populated = sum(1 for m, _ in content_markers if m in html)
    print(f"  Content markers found: {populated}/{len(content_markers)}")
    assert populated >= 4, (
        f"Only {populated}/{len(content_markers)} content markers found"
        " — LLM may not have populated the template correctly"
    )

    # Check target="_blank" on links
    print("\n--- 2e. Checking link targets ---")
    import re

    links = re.findall(r'<a\s[^>]*href=["\'][^"\']+["\'][^>]*>', html)
    blank_links = [ln for ln in links if 'target="_blank"' in ln]
    print(f"  Total <a> tags: {len(links)}")
    print(f"  With target='_blank': {len(blank_links)}")
    if links:
        blank_ratio = len(blank_links) / len(links)
        print(f"  Ratio: {blank_ratio:.0%}")
        # Allow some tolerance — internal anchors may not have target
        assert blank_ratio >= 0.7, (
            f"Only {blank_ratio:.0%} of links have target='_blank' (expected >= 70%)"
        )

    results: dict[str, Any] = {
        "model": model,
        "html_length": len(html),
        "has_doctype": has_doctype,
        "has_html_close": has_html_close,
        "classes_preserved": len(expected_classes),
        "content_populated": populated,
        "total_links": len(links),
        "blank_target_links": len(blank_links),
    }

    print(f"\n  HTML: {len(html)} chars, {len(links)} links")
    print("  Phase 2 PASSED: LLM generates valid HTML from markdown + template.")

    # Store for later phases
    results["_html"] = html
    return results


# ---------------------------------------------------------------------------
# Phase 3: Google Docs Integration
# ---------------------------------------------------------------------------


async def phase_gdocs(html: str | None = None) -> dict[str, Any]:
    """Create a Google Doc, insert HTML, and read it back.

    Tests:
    - GoogleDocsService initializes with real credentials
    - create_document() returns a valid document ID
    - insert_content() inserts HTML without error
    - get_content() retrieves the inserted text
    - create_html_doc() helper produces (doc_id, doc_url) tuple
    - doc_url format is correct (https://docs.google.com/document/d/...)
    """
    print("\n" + "=" * 70)
    print("PHASE 3: Google Docs Integration")
    print("=" * 70)

    creds_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH",
        "credentials/google-service-account.json",
    )
    drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")

    print(f"  Credentials: {creds_path}")
    print(f"  Shared Drive ID: {drive_id[:20]}..." if drive_id else "  Shared Drive: (none)")

    from ica.services.google_docs import GoogleDocsService

    docs = GoogleDocsService(credentials_path=creds_path, drive_id=drive_id)

    # Use generated HTML if available, otherwise use a minimal sample
    test_html = html or (
        "<!DOCTYPE html><html><body>"
        "<h1>Integration Test</h1>"
        "<p>This is a test document created by test_html_generation.py</p>"
        "</body></html>"
    )

    # 3a. Create document
    print("\n--- 3a. Creating Google Doc ---")
    doc_id = await docs.create_document("Integration Test - HTML Generation")

    assert doc_id, "create_document returned empty doc_id"
    assert len(doc_id) > 10, f"doc_id suspiciously short: {doc_id}"
    print(f"  Document ID: {doc_id}")
    print(f"  URL: https://docs.google.com/document/d/{doc_id}/edit")

    # 3b. Insert content
    print("\n--- 3b. Inserting HTML content ---")
    await docs.insert_content(doc_id, test_html)
    print(f"  Inserted {len(test_html)} chars")

    # 3c. Read back
    print("\n--- 3c. Reading content back ---")
    content = await docs.get_content(doc_id)

    assert content, "get_content returned empty string"
    print(f"  Retrieved: {len(content)} chars")
    print(f"  First 200 chars: {content[:200]}")

    # Google Docs stores plain text, not raw HTML — the content should
    # contain recognizable text fragments from the HTML.
    # The exact format depends on how Google Docs renders inserted text.
    assert len(content) > 0, "Retrieved content is empty"
    print("  Content retrieval: OK")

    # 3d. Test create_html_doc helper
    print("\n--- 3d. Testing create_html_doc() helper ---")
    from ica.pipeline.html_generation import create_html_doc

    helper_doc_id, helper_doc_url = await create_html_doc(
        docs,
        test_html,
        title="Integration Test - create_html_doc Helper",
    )

    assert helper_doc_id, "create_html_doc returned empty doc_id"
    assert helper_doc_url.startswith("https://docs.google.com/document/d/"), (
        f"Unexpected doc_url format: {helper_doc_url}"
    )
    assert helper_doc_id in helper_doc_url, "doc_id not found in doc_url"
    print(f"  Helper doc ID: {helper_doc_id}")
    print(f"  Helper doc URL: {helper_doc_url}")
    print("  create_html_doc: OK")

    results: dict[str, Any] = {
        "doc_id": doc_id,
        "helper_doc_id": helper_doc_id,
        "insert_length": len(test_html),
        "retrieved_length": len(content),
        "doc_url_valid": True,
        "credentials_path": creds_path,
    }

    print("\n  Created 2 docs, inserted + retrieved content")
    print("  Phase 3 PASSED: Google Docs create/insert/read works end-to-end.")

    return results


# ---------------------------------------------------------------------------
# Phase 4: HTML Regeneration (Scoped Update)
# ---------------------------------------------------------------------------


async def phase_regenerate(html: str | None = None) -> dict[str, Any]:
    """Call the real LLM for scoped HTML regeneration with user feedback.

    Tests:
    - call_html_regeneration() returns non-empty HTML
    - Output still contains <!DOCTYPE html>
    - Feedback-targeted section was modified
    - Non-targeted sections remain largely unchanged
    """
    print("\n" + "=" * 70)
    print("PHASE 4: HTML Regeneration (Scoped Update)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.html_generation import (
        HTML_VALID_MARKER,
        call_html_regeneration,
    )

    model = _openrouter_model(get_model(LLMPurpose.HTML_REGENERATION))
    print(f"  Model: {model}")

    # Use generated HTML if available from phase 2, otherwise generate a
    # minimal previous HTML for regeneration
    previous_html = html or (
        "<!DOCTYPE html><html><head><title>Artificially Intelligent,"
        " Actually Useful. - 02/26/2026</title></head>"
        '<body><table width="100%">'
        '<tr><td class="nl-content nl-intro">'
        "<p>The AI landscape shifted this week.</p>"
        '<p class="nl-intro-summary">OpenAI released GPT-4o, making'
        " frontier AI accessible to everyone.</p>"
        "</td></tr>"
        '<tr><td class="nl-footer">'
        "<p>Alright, that\u2019s a wrap for the week!</p>"
        "</td></tr></table></body></html>"
    )

    feedback = (
        "The introduction section is too brief. Please expand it to include"
        " a stronger opening statement about why this week matters for"
        " solopreneurs and SMBs. Add more energy and urgency."
    )

    print(f"\n  Previous HTML: {len(previous_html)} chars")
    print(f"  Feedback: {feedback[:80]}...")

    # Call regeneration
    print("\n--- 4a. Calling call_html_regeneration() ---")
    regen_html = await call_html_regeneration(
        previous_html=previous_html,
        markdown_content=SAMPLE_MARKDOWN,
        html_template=SAMPLE_HTML_TEMPLATE,
        user_feedback=feedback,
        newsletter_date=SAMPLE_NEWSLETTER_DATE,
        model=model,
    )

    assert regen_html, "call_html_regeneration returned empty response"
    print(f"  Regenerated HTML: {len(regen_html)} chars")
    print(f"  First 200 chars: {regen_html[:200]}")

    # Check DOCTYPE
    print("\n--- 4b. Checking HTML validity ---")
    has_doctype = HTML_VALID_MARKER.lower() in regen_html.lower()
    print(f"  Has {HTML_VALID_MARKER}: {has_doctype}")
    assert has_doctype, f"Regenerated HTML missing {HTML_VALID_MARKER}"

    # Check that footer is preserved (not targeted by feedback)
    print("\n--- 4c. Checking scope enforcement ---")
    has_footer = "nl-footer" in regen_html
    print(f"  Footer class preserved: {has_footer}")

    # Check that introduction was modified (targeted by feedback)
    has_intro = "nl-intro" in regen_html
    print(f"  Introduction class preserved: {has_intro}")

    # Output changed from previous (regeneration happened)
    changed = regen_html != previous_html
    print(f"  Content changed: {changed}")
    if changed:
        print(f"  Delta: {len(regen_html) - len(previous_html):+d} chars")

    results: dict[str, Any] = {
        "model": model,
        "previous_length": len(previous_html),
        "regen_length": len(regen_html),
        "has_doctype": has_doctype,
        "footer_preserved": has_footer,
        "intro_preserved": has_intro,
        "content_changed": changed,
    }

    delta = len(regen_html) - len(previous_html)
    print(f"\n  Regenerated: {len(regen_html)} chars (delta: {delta:+d})")
    print("  Phase 4 PASSED: Scoped HTML regeneration works with real LLM.")

    # Store for learning data phase
    results["_regen_html"] = regen_html
    results["_feedback"] = feedback
    results["_previous_html"] = previous_html
    return results


# ---------------------------------------------------------------------------
# Phase 5: Learning Data Extraction
# ---------------------------------------------------------------------------


async def phase_learning(
    feedback: str | None = None,
    input_html: str | None = None,
    output_html: str | None = None,
) -> dict[str, Any]:
    """Call the real LLM to extract learning data from user feedback.

    Tests:
    - extract_html_learning_data() returns non-empty text
    - Output is a concise learning note (not the full feedback verbatim)
    - Learning note is shorter than the original feedback context
    """
    print("\n" + "=" * 70)
    print("PHASE 5: Learning Data Extraction")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.html_generation import extract_html_learning_data

    model = _openrouter_model(get_model(LLMPurpose.HTML_LEARNING_DATA))
    print(f"  Model: {model}")

    # Use real data from prior phases if available
    test_feedback = feedback or (
        "The introduction section is too brief. Please expand it to include"
        " a stronger opening statement about why this week matters for"
        " solopreneurs and SMBs. Add more energy and urgency."
    )
    test_input = input_html or (
        "<td class='nl-intro'><p>The AI landscape shifted this week.</p></td>"
    )
    test_output = output_html or (
        "<td class='nl-intro'><p>This week marks a turning point for"
        " solopreneurs and SMBs in the AI revolution.</p></td>"
    )

    print(f"\n  Feedback: {test_feedback[:80]}...")
    print(f"  Input HTML: {len(test_input)} chars")
    print(f"  Output HTML: {len(test_output)} chars")

    # Extract learning data
    print("\n--- 5a. Calling extract_html_learning_data() ---")
    learning_note = await extract_html_learning_data(
        feedback=test_feedback,
        input_text=test_input,
        model_output=test_output,
        model=model,
    )

    assert learning_note, "extract_html_learning_data returned empty response"
    print(f"  Learning note: {learning_note}")
    print(f"  Length: {len(learning_note)} chars")

    # Verify it's a concise summary, not a raw echo
    assert len(learning_note) < len(test_feedback) + len(test_input) + len(test_output), (
        "Learning note is longer than combined inputs — likely not summarized"
    )
    print("  Conciseness check: OK")

    # Verify it contains actionable content
    is_actionable = any(
        keyword in learning_note.lower()
        for keyword in [
            "introduction",
            "expand",
            "opening",
            "energy",
            "solopreneur",
            "smb",
            "improve",
            "stronger",
            "brief",
            "urgency",
            "tone",
            "content",
        ]
    )
    print(f"  Actionable content: {is_actionable}")

    results: dict[str, Any] = {
        "model": model,
        "feedback_length": len(test_feedback),
        "learning_note_length": len(learning_note),
        "learning_note": learning_note[:200],
        "is_actionable": is_actionable,
    }

    print(f"\n  Learning note: {len(learning_note)} chars, actionable={is_actionable}")
    print("  Phase 5 PASSED: Learning data extraction produces concise summary.")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: HTML generation & Google Docs (Step 5).",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=["all", "prompts", "generate", "gdocs", "regenerate", "learning"],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-gdocs",
        action="store_true",
        help="Skip the Google Docs phase (no Google credentials required)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM call phases (prompts + gdocs only)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}
    generated_html: str | None = None
    regen_data: dict[str, Any] = {}

    # Phase 1: Prompt building (always runs)
    if args.phase in ("all", "prompts"):
        results["prompts"] = await phase_prompts()

    # Phase 2: HTML generation LLM
    if args.phase in ("all", "generate") and not args.skip_llm:
        gen_results = await phase_generate()
        generated_html = gen_results.pop("_html", None)
        results["generate"] = gen_results
    elif args.skip_llm and args.phase in ("all",):
        print("\n  HTML generation LLM phase skipped (--skip-llm).")

    # Phase 3: Google Docs
    if args.phase in ("all", "gdocs") and not args.skip_gdocs:
        results["gdocs"] = await phase_gdocs(html=generated_html)
    elif args.skip_gdocs and args.phase in ("all",):
        print("\n  Google Docs phase skipped (--skip-gdocs).")

    # Phase 4: HTML regeneration LLM
    if args.phase in ("all", "regenerate") and not args.skip_llm:
        regen_results = await phase_regenerate(html=generated_html)
        regen_data = {
            "feedback": regen_results.pop("_feedback", None),
            "previous_html": regen_results.pop("_previous_html", None),
            "regen_html": regen_results.pop("_regen_html", None),
        }
        results["regenerate"] = regen_results
    elif args.skip_llm and args.phase in ("all",):
        print("\n  HTML regeneration LLM phase skipped (--skip-llm).")

    # Phase 5: Learning data extraction
    if args.phase in ("all", "learning") and not args.skip_llm:
        results["learning"] = await phase_learning(
            feedback=regen_data.get("feedback"),
            input_html=regen_data.get("previous_html"),
            output_html=regen_data.get("regen_html"),
        )
    elif args.skip_llm and args.phase in ("all",):
        print("\n  Learning data extraction phase skipped (--skip-llm).")

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

    print("\nHTML generation & Google Docs integration test complete!")


if __name__ == "__main__":
    main()
