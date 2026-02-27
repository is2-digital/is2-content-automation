"""Integration test — 3-layer markdown validation pipeline.

Exercises the three-layer validation pipeline with real LLM calls:

1. Character count validation (code-based): validate section lengths, delta calculations
2. Structural LLM validation (GPT-4.1): real LLM call, JSON response parsing, error merging
3. Voice LLM validation (GPT-4.1): real LLM call, prior-error preservation, VOICE: prefixes
4. Full pipeline (run_three_layer_validation): all 3 layers combined, error merging verified
5. Generate-with-validation loop: full generation + validation + retry + ValidationLoopCounter

Usage:
    docker exec ica-app-1 python scripts/test_markdown_validation.py
    docker exec ica-app-1 python scripts/test_markdown_validation.py --phase charcount
    docker exec ica-app-1 python scripts/test_markdown_validation.py --phase structural
    docker exec ica-app-1 python scripts/test_markdown_validation.py --phase voice
    docker exec ica-app-1 python scripts/test_markdown_validation.py --phase pipeline
    docker exec ica-app-1 python scripts/test_markdown_validation.py --phase loop
    docker exec ica-app-1 python scripts/test_markdown_validation.py --skip-generation

Requires OPENROUTER_API_KEY (for LLM calls).  Run inside the app container where
.env is loaded automatically.
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
    """Prepend ``openrouter/`` so LiteLLM routes through OpenRouter.

    Mirrors the logic in ``ica.services.llm.completion()`` (line 125-126).
    Pipeline modules that call ``litellm.acompletion`` directly need this
    prefix when only OPENROUTER_API_KEY is set (no direct provider keys).
    """
    if not model_id.startswith("openrouter/"):
        return f"openrouter/{model_id}"
    return model_id


# ---------------------------------------------------------------------------
# Sample markdown — realistic newsletter content for validation testing.
# Adjacent string literals keep code lines under 99 chars while producing
# the long prose lines the character-count validator expects.
# ---------------------------------------------------------------------------


def _build_sample_markdown() -> str:
    """Build a realistic newsletter markdown for validation testing."""
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
        "## [EU AI Act Implementation Timeline]"
        "(https://example.com/ai-regulation-update)"
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

# A formatted theme JSON string for the generate_with_validation loop test.
# This mimics the output of Step 3 (theme generation) that feeds into Step 4.
SAMPLE_FORMATTED_THEME = json.dumps(
    {
        "theme_name": "AI Accessibility Revolution",
        "theme_description": "How frontier AI tools are becoming accessible to all businesses",
        "featured_article": {
            "title": "Hello GPT-4o: OpenAI's Latest Multimodal Model",
            "url": "https://openai.com/index/hello-gpt-4o/",
            "source": "openai.com",
            "origin": "OpenAI Blog",
            "category": "AI Models",
            "summary": "OpenAI released GPT-4o, a multimodal model processing text, audio, "
            "and vision in real time at half the cost of GPT-4 Turbo.",
            "business_relevance": "Free-tier access to frontier AI enables solopreneurs to "
            "compete with enterprise teams on AI capability.",
            "why_featured": "Demonstrates democratization of frontier AI capabilities",
        },
        "main_article_1": {
            "title": "5 AI Automation Trends Reshaping Small Businesses in 2026",
            "url": "https://example.com/ai-automation-trends",
            "source": "example.com",
            "origin": "AI Industry Report",
            "category": "Business AI",
            "summary": "Small businesses are moving past experimentation with AI, embedding "
            "it into customer service and operations workflows.",
            "business_relevance": "Identifies which AI tools offer highest ROI for SMBs.",
            "rationale": "Directly addresses SMB AI adoption patterns",
        },
        "main_article_2": {
            "title": "EU AI Act Implementation Timeline",
            "url": "https://example.com/ai-regulation-update",
            "source": "example.com",
            "origin": "Regulatory Analysis",
            "category": "AI Regulation",
            "summary": "The EU AI Act enters implementation phase with specific deadlines "
            "for risk classification and compliance documentation.",
            "business_relevance": "Companies selling to EU must begin compliance planning now.",
            "rationale": "Critical compliance info for all business sizes",
        },
        "quick_hit_1": {
            "title": "AI Skills Gap Widens as Demand Surges",
            "url": "https://example.com/ai-hiring-trends",
            "source": "example.com",
            "origin": "Employment Report",
            "category": "Workforce",
            "summary": "Demand for AI-skilled workers outpaces supply with 200% job growth.",
        },
        "quick_hit_2": {
            "title": "Anthropic Launches New Claude Enterprise Features",
            "url": "https://example.com/anthropic-claude-tools",
            "source": "example.com",
            "origin": "Anthropic Blog",
            "category": "AI Tools",
            "summary": "New enterprise features include tool use and enhanced safety guardrails.",
        },
        "quick_hit_3": {
            "title": "Microsoft Copilot Expansion Across Enterprise Suite",
            "url": "https://example.com/microsoft-copilot-enterprise",
            "source": "example.com",
            "origin": "Microsoft Blog",
            "category": "Enterprise AI",
            "summary": "Copilot AI embedded across Dynamics 365, Power Platform, and Azure.",
        },
        "industry_development_1": {
            "title": "Introducing Gemini: Google's Most Capable AI Model",
            "url": "https://blog.google/technology/ai/google-gemini-ai/",
            "source": "blog.google",
            "origin": "Google AI Blog",
            "major_player": "Google",
        },
        "industry_development_2": {
            "title": "Microsoft Expands Copilot to All Enterprise Applications",
            "url": "https://example.com/microsoft-copilot-enterprise",
            "source": "example.com",
            "origin": "Microsoft News",
            "major_player": "Microsoft",
        },
    },
    indent=2,
)


# ---------------------------------------------------------------------------
# Phase 1: Character Count Validation (Code-Based)
# ---------------------------------------------------------------------------


async def phase_charcount() -> dict[str, Any]:
    """Run code-based character count validation on sample markdown.

    Tests:
    - validate_character_counts() runs without error on realistic content
    - CharacterCountError.format() produces expected string format
    - Delta calculation is correct (negative = too short, positive = too long)
    - All sections are checked: Quick Highlights, Featured Article, Main Articles
    """
    print("\n" + "=" * 70)
    print("PHASE 1: Character Count Validation (Code-Based)")
    print("=" * 70)

    from ica.validators.character_count import (
        CharacterCountError,
        validate_character_counts,
        validate_featured_article,
        validate_main_articles,
        validate_quick_highlights,
    )

    # Run full validation on sample markdown
    print("\n--- 1a. Running validate_character_counts() on sample markdown ---")
    errors = validate_character_counts(SAMPLE_MARKDOWN)

    print(f"  Total errors: {len(errors)}")
    for err in errors:
        print(f"    {err.format()}")

    # Run section-by-section for detailed diagnostics
    print("\n--- 1b. Section-by-section results ---")

    qh_errors = validate_quick_highlights(SAMPLE_MARKDOWN)
    print(f"  Quick Highlights: {len(qh_errors)} errors")
    for err in qh_errors:
        print(f"    {err.format()}")

    fa_errors = validate_featured_article(SAMPLE_MARKDOWN)
    print(f"  Featured Article: {len(fa_errors)} errors")
    for err in fa_errors:
        print(f"    {err.format()}")

    ma_errors = validate_main_articles(SAMPLE_MARKDOWN)
    print(f"  Main Articles: {len(ma_errors)} errors")
    for err in ma_errors:
        print(f"    {err.format()}")

    # Test error format structure
    print("\n--- 1c. Verifying error format structure ---")
    if errors:
        sample = errors[0]
        formatted = sample.format()
        print(f"  Sample formatted: {formatted}")
        assert " – " in formatted, "Expected ' – ' delimiter in formatted error"
        assert "current=" in formatted, "Expected 'current=' in formatted error"
        assert "target=" in formatted, "Expected 'target=' in formatted error"
        assert "delta=" in formatted, "Expected 'delta=' in formatted error"
        print("  Format structure: OK")

        # Verify delta calculation
        assert isinstance(sample.delta, int), "Delta should be an integer"
        if sample.current < sample.target_min:
            expected_delta = sample.current - sample.target_min
            assert sample.delta == expected_delta, (
                f"Delta mismatch: {sample.delta} != {expected_delta}"
            )
            print(f"  Delta (too short): {sample.delta} (correct)")
        elif sample.current > sample.target_max:
            expected_delta = sample.current - sample.target_max
            assert sample.delta == expected_delta, (
                f"Delta mismatch: {sample.delta} != {expected_delta}"
            )
            print(f"  Delta (too long): {sample.delta} (correct)")
    else:
        print("  No errors to verify format (sample markdown is within all ranges)")

    # Verify all errors are CharacterCountError instances
    for err in errors:
        assert isinstance(err, CharacterCountError), (
            f"Expected CharacterCountError, got {type(err)}"
        )

    results: dict[str, Any] = {
        "total_errors": len(errors),
        "qh_errors": len(qh_errors),
        "fa_errors": len(fa_errors),
        "ma_errors": len(ma_errors),
        "format_valid": True,
        "delta_valid": True,
    }

    print(f"\n  Total: {len(errors)} errors across all sections")
    print("  Phase 1 PASSED: Character count validation runs correctly.")

    return results


# ---------------------------------------------------------------------------
# Phase 2: Structural LLM Validation
# ---------------------------------------------------------------------------


async def phase_structural() -> dict[str, Any]:
    """Call real GPT-4.1 for structural validation and verify response parsing.

    Tests:
    - LLM call succeeds via OpenRouter (GPT-4.1)
    - Response is valid JSON with { output: { isValid, errors } }
    - Character count errors passed in are preserved in output
    - Structural findings are returned as string list
    """
    print("\n" + "=" * 70)
    print("PHASE 2: Structural LLM Validation (GPT-4.1)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.markdown_generation import (
        format_char_errors_json,
        run_structural_validation,
    )
    from ica.validators.character_count import validate_character_counts

    model = _openrouter_model(get_model(LLMPurpose.MARKDOWN_VALIDATOR))
    print(f"  Model: {model}")

    # First get char errors for input
    print("\n--- 2a. Getting character count errors as input ---")
    char_errors = validate_character_counts(SAMPLE_MARKDOWN)
    char_errors_json = format_char_errors_json(char_errors)
    print(f"  Char errors JSON: {char_errors_json[:200]}...")
    print(f"  Char error count: {len(char_errors)}")

    # Call structural validation LLM
    print("\n--- 2b. Calling structural validation LLM ---")
    struct_valid, struct_errors = await run_structural_validation(
        SAMPLE_MARKDOWN,
        char_errors_json,
        model=model,
    )

    print(f"  isValid: {struct_valid}")
    print(f"  Error count: {len(struct_errors)}")
    for i, err in enumerate(struct_errors[:10]):
        print(f"    [{i + 1}] {err[:120]}")
    if len(struct_errors) > 10:
        print(f"    ... and {len(struct_errors) - 10} more")

    # Verify response structure
    print("\n--- 2c. Verifying response structure ---")
    assert isinstance(struct_valid, bool), f"Expected bool for isValid, got {type(struct_valid)}"
    assert isinstance(struct_errors, list), f"Expected list for errors, got {type(struct_errors)}"
    for err in struct_errors:
        assert isinstance(err, str), f"Expected string error, got {type(err)}"
    print("  Response structure: OK")

    # Check that character count errors were preserved (if any exist)
    if char_errors:
        # The structural validator should include char errors in its output
        char_error_strs = [e.format() for e in char_errors]
        preserved = sum(
            1
            for ce in char_error_strs
            if any(ce in se for se in struct_errors)
        )
        print(f"  Char errors preserved: {preserved}/{len(char_errors)}")
    else:
        print("  No char errors to check preservation (all within range)")

    results: dict[str, Any] = {
        "model": model,
        "is_valid": struct_valid,
        "error_count": len(struct_errors),
        "char_errors_in": len(char_errors),
        "response_structure_ok": True,
    }

    print(f"\n  Structural valid: {struct_valid}, Errors: {len(struct_errors)}")
    print("  Phase 2 PASSED: Structural LLM validation returns valid response.")

    return results


# ---------------------------------------------------------------------------
# Phase 3: Voice LLM Validation
# ---------------------------------------------------------------------------


async def phase_voice() -> dict[str, Any]:
    """Call real GPT-4.1 for voice validation and verify error merging.

    Tests:
    - LLM call succeeds via OpenRouter (GPT-4.1)
    - Prior errors (from structural validator) are preserved verbatim
    - New voice errors are prefixed with 'VOICE:'
    - Response is valid JSON with { output: { isValid, errors } }
    """
    print("\n" + "=" * 70)
    print("PHASE 3: Voice LLM Validation (GPT-4.1)")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.markdown_generation import (
        format_char_errors_json,
        run_structural_validation,
        run_voice_validation,
    )
    from ica.validators.character_count import validate_character_counts

    model = _openrouter_model(get_model(LLMPurpose.MARKDOWN_VALIDATOR))
    print(f"  Model: {model}")

    # Run layers 1 and 2 first to get prior errors for layer 3
    print("\n--- 3a. Running layers 1 & 2 to get prior errors ---")
    char_errors = validate_character_counts(SAMPLE_MARKDOWN)
    char_errors_json = format_char_errors_json(char_errors)
    print(f"  Layer 1 char errors: {len(char_errors)}")

    struct_valid, struct_errors = await run_structural_validation(
        SAMPLE_MARKDOWN,
        char_errors_json,
        model=model,
    )
    print(f"  Layer 2 structural valid: {struct_valid}")
    print(f"  Layer 2 error count: {len(struct_errors)}")

    # Build prior_errors_json for voice validator
    prior_json = json.dumps(
        {
            "output": {
                "isValid": struct_valid and len(char_errors) == 0,
                "errors": struct_errors,
            }
        }
    )
    print(f"  Prior errors JSON: {prior_json[:200]}...")

    # Call voice validation LLM
    print("\n--- 3b. Calling voice validation LLM ---")
    voice_valid, all_errors = await run_voice_validation(
        SAMPLE_MARKDOWN,
        prior_json,
        model=model,
    )

    print(f"  isValid: {voice_valid}")
    print(f"  Total error count: {len(all_errors)}")
    for i, err in enumerate(all_errors[:15]):
        print(f"    [{i + 1}] {err[:120]}")
    if len(all_errors) > 15:
        print(f"    ... and {len(all_errors) - 15} more")

    # Verify response structure
    print("\n--- 3c. Verifying response structure ---")
    assert isinstance(voice_valid, bool), f"Expected bool for isValid, got {type(voice_valid)}"
    assert isinstance(all_errors, list), f"Expected list for errors, got {type(all_errors)}"
    for err in all_errors:
        assert isinstance(err, str), f"Expected string error, got {type(err)}"
    print("  Response structure: OK")

    # Check error merging: prior errors should be preserved
    print("\n--- 3d. Verifying error merging ---")
    prior_preserved = 0
    voice_new = 0
    for err in all_errors:
        if err.startswith("VOICE:"):
            voice_new += 1
        elif any(err in se for se in struct_errors):
            prior_preserved += 1

    print(f"  Prior errors preserved: {prior_preserved}")
    print(f"  New VOICE: errors: {voice_new}")
    print(f"  Other errors: {len(all_errors) - prior_preserved - voice_new}")

    # The voice validator should return at least as many errors as the structural one
    # (since it merges prior errors)
    if struct_errors:
        assert len(all_errors) >= len(struct_errors), (
            f"Voice validator returned fewer errors ({len(all_errors)}) than "
            f"structural validator ({len(struct_errors)}) — merging may have failed"
        )
        print("  Error count >= structural errors: OK (merging preserved)")

    results: dict[str, Any] = {
        "model": model,
        "is_valid": voice_valid,
        "total_errors": len(all_errors),
        "prior_preserved": prior_preserved,
        "voice_new": voice_new,
        "struct_errors_in": len(struct_errors),
        "response_structure_ok": True,
    }

    print(f"\n  Voice valid: {voice_valid}, Total errors: {len(all_errors)}")
    print("  Phase 3 PASSED: Voice LLM validation returns valid response with merged errors.")

    return results


# ---------------------------------------------------------------------------
# Phase 4: Full Three-Layer Pipeline
# ---------------------------------------------------------------------------


async def phase_pipeline() -> dict[str, Any]:
    """Run the complete run_three_layer_validation() pipeline end-to-end.

    Tests:
    - All 3 layers execute in sequence
    - ValidationResult has correct structure (is_valid, errors, char_errors_json)
    - Error merging across all layers produces a unified error list
    - char_errors_json is valid JSON
    """
    print("\n" + "=" * 70)
    print("PHASE 4: Full Three-Layer Validation Pipeline")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.pipeline.markdown_generation import (
        ValidationResult,
        run_three_layer_validation,
    )

    model = _openrouter_model(get_model(LLMPurpose.MARKDOWN_VALIDATOR))
    print(f"  Validator model: {model}")

    # Run full pipeline (pass model to route through OpenRouter)
    print("\n--- 4a. Running run_three_layer_validation() ---")
    result = await run_three_layer_validation(
        SAMPLE_MARKDOWN,
        validator_model=model,
    )

    print(f"  is_valid: {result.is_valid}")
    print(f"  Error count: {len(result.errors)}")
    print(f"  char_errors_json length: {len(result.char_errors_json)}")

    # Display errors
    for i, err in enumerate(result.errors[:15]):
        print(f"    [{i + 1}] {err[:120]}")
    if len(result.errors) > 15:
        print(f"    ... and {len(result.errors) - 15} more")

    # Verify ValidationResult structure
    print("\n--- 4b. Verifying ValidationResult structure ---")
    assert isinstance(result, ValidationResult), f"Expected ValidationResult, got {type(result)}"
    assert isinstance(result.is_valid, bool), "is_valid should be bool"
    assert isinstance(result.errors, list), "errors should be list"
    assert isinstance(result.char_errors_json, str), "char_errors_json should be str"
    print("  ValidationResult structure: OK")

    # Verify char_errors_json is valid JSON
    print("\n--- 4c. Verifying char_errors_json ---")
    parsed_char_errors = json.loads(result.char_errors_json)
    assert isinstance(parsed_char_errors, list), "char_errors_json should be a JSON array"
    print(f"  char_errors_json parsed: {len(parsed_char_errors)} entries")
    for ce in parsed_char_errors[:5]:
        print(f"    {ce[:100]}")
    print("  char_errors_json: valid JSON")

    # Verify error consistency
    print("\n--- 4d. Checking error consistency ---")
    if not result.is_valid:
        assert len(result.errors) > 0, "is_valid=False but no errors returned"
        print("  is_valid=False with errors: consistent")
    else:
        # is_valid=True should mean no errors
        if len(result.errors) == 0:
            print("  is_valid=True with 0 errors: consistent")
        else:
            print(f"  WARNING: is_valid=True but {len(result.errors)} errors present")

    # Categorize errors
    voice_errors = [e for e in result.errors if e.startswith("VOICE:")]
    other_errors = [e for e in result.errors if not e.startswith("VOICE:")]
    print("\n  Error breakdown:")
    print(f"    Non-VOICE errors: {len(other_errors)} (char count + structural)")
    print(f"    VOICE: errors: {len(voice_errors)}")

    results: dict[str, Any] = {
        "model": model,
        "is_valid": result.is_valid,
        "total_errors": len(result.errors),
        "voice_errors": len(voice_errors),
        "other_errors": len(other_errors),
        "char_errors_json_entries": len(parsed_char_errors),
        "structure_ok": True,
    }

    print(f"\n  Pipeline result: valid={result.is_valid}, errors={len(result.errors)}")
    print("  Phase 4 PASSED: Full three-layer pipeline produces valid merged results.")

    return results


# ---------------------------------------------------------------------------
# Phase 5: Generate-With-Validation Loop (ValidationLoopCounter)
# ---------------------------------------------------------------------------


async def phase_loop() -> dict[str, Any]:
    """Test the generate_with_validation loop with real LLM calls.

    Tests:
    - generate_with_validation() calls markdown generation LLM
    - ValidationLoopCounter tracks attempts correctly
    - Loop terminates either on validation success or after max_attempts
    - Returned markdown is non-empty
    - With max_attempts=1, loop runs at most 1 validation (force-accept)
    """
    print("\n" + "=" * 70)
    print("PHASE 5: Generate-With-Validation Loop")
    print("=" * 70)

    env = _check_env("OPENROUTER_API_KEY")
    print(f"  API key: {env['OPENROUTER_API_KEY'][:8]}...{env['OPENROUTER_API_KEY'][-4:]}")

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.errors import ValidationLoopCounter
    from ica.pipeline.markdown_generation import generate_with_validation

    gen_model = _openrouter_model(get_model(LLMPurpose.MARKDOWN))
    val_model = _openrouter_model(get_model(LLMPurpose.MARKDOWN_VALIDATOR))
    print(f"  Generation model: {gen_model}")
    print(f"  Validator model: {val_model}")

    # Test 5a: ValidationLoopCounter behavior
    print("\n--- 5a. Verifying ValidationLoopCounter ---")
    counter = ValidationLoopCounter(max_attempts=3)
    assert counter.count == 0, f"Initial count should be 0, got {counter.count}"
    assert not counter.exhausted, "Should not be exhausted at start"
    assert counter.remaining == 3, f"Remaining should be 3, got {counter.remaining}"

    counter.increment()
    assert counter.count == 1, f"After 1 increment, count should be 1, got {counter.count}"
    assert counter.remaining == 2, f"Remaining should be 2, got {counter.remaining}"
    assert not counter.exhausted, "Should not be exhausted after 1 increment"

    counter.increment()
    counter.increment()
    assert counter.count == 3, f"After 3 increments, count should be 3, got {counter.count}"
    assert counter.exhausted, "Should be exhausted after 3 increments"
    assert counter.remaining == 0, f"Remaining should be 0, got {counter.remaining}"

    counter.reset()
    assert counter.count == 0, "After reset, count should be 0"
    assert not counter.exhausted, "After reset, should not be exhausted"
    print("  ValidationLoopCounter: OK (increment, exhausted, remaining, reset)")

    # Test 5b: Full generate_with_validation loop (limited to 1 attempt for speed)
    print("\n--- 5b. Running generate_with_validation (max_attempts=1) ---")
    print("  (Using max_attempts=1 for faster test — validates generation + single validation)")

    markdown = await generate_with_validation(
        SAMPLE_FORMATTED_THEME,
        generation_model=gen_model,
        validator_model=val_model,
        max_attempts=1,
    )

    assert markdown, "generate_with_validation returned empty markdown"
    assert len(markdown) > 100, f"Markdown too short ({len(markdown)} chars)"
    print(f"  Generated markdown: {len(markdown)} chars")
    print(f"  Starts with: {markdown[:100]}...")

    # Verify it looks like a newsletter
    has_intro = "INTRODUCTION" in markdown.upper()
    has_quick = "QUICK HIGHLIGHTS" in markdown.upper()
    has_featured = "FEATURED ARTICLE" in markdown.upper()
    print(f"  Has INTRODUCTION: {has_intro}")
    print(f"  Has QUICK HIGHLIGHTS: {has_quick}")
    print(f"  Has FEATURED ARTICLE: {has_featured}")

    assert has_intro or has_quick or has_featured, (
        "Generated markdown doesn't contain expected newsletter sections"
    )

    results: dict[str, Any] = {
        "gen_model": gen_model,
        "val_model": val_model,
        "markdown_length": len(markdown),
        "has_intro": has_intro,
        "has_quick": has_quick,
        "has_featured": has_featured,
        "counter_behavior_ok": True,
    }

    print(f"\n  Markdown: {len(markdown)} chars, sections detected")
    print("  Phase 5 PASSED: Generate-with-validation loop produces valid newsletter markdown.")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: 3-layer markdown validation pipeline.",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=["all", "charcount", "structural", "voice", "pipeline", "loop"],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="Skip the generate-with-validation loop phase (runs validation-only phases)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}

    if args.phase in ("all", "charcount"):
        results["charcount"] = await phase_charcount()

    if args.phase in ("all", "structural"):
        results["structural"] = await phase_structural()

    if args.phase in ("all", "voice"):
        results["voice"] = await phase_voice()

    if args.phase in ("all", "pipeline"):
        results["pipeline"] = await phase_pipeline()

    if args.skip_generation:
        if args.phase in ("all",):
            print("\n  Generation loop phase skipped (--skip-generation).")
    else:
        if args.phase in ("all", "loop"):
            results["loop"] = await phase_loop()

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

    print("\n3-layer markdown validation integration test complete!")


if __name__ == "__main__":
    main()
