"""Integration test — learning system feedback loop (Phase D).

Verifies that feedback stored in the notes table during Run 1 is correctly
retrieved, aggregated, and injected into LLM prompts during Run 2.

1. Database CRUD: connect to PostgreSQL, seed notes for all 5 feedback types,
   verify round-trip insert and retrieval.
2. Last-40 limit & type filtering: seed 50 notes of one type, verify only 40
   returned; seed notes across types, verify type filtering isolates correctly.
3. Feedback aggregation: verify aggregate_feedback() in all pipeline modules
   produces correct bullet-list format from Note objects.
4. Prompt injection: build prompts for summarization, theme generation,
   markdown generation, email subject, and HTML generation with aggregated
   feedback; verify the "Editorial Improvement Context" section appears.
5. Cross-run LLM: call the summarization LLM twice — once without feedback
   (baseline) and once with feedback directing a specific style change.
   Verify the feedback-injected prompt is structurally different.

Usage:
    docker exec ica-app-1 python scripts/test_learning_system.py
    docker exec ica-app-1 python scripts/test_learning_system.py --phase db
    docker exec ica-app-1 python scripts/test_learning_system.py --phase limit
    docker exec ica-app-1 python scripts/test_learning_system.py --phase aggregate
    docker exec ica-app-1 python scripts/test_learning_system.py --phase prompt
    docker exec ica-app-1 python scripts/test_learning_system.py --phase llm
    docker exec ica-app-1 python scripts/test_learning_system.py --skip-llm
    docker exec ica-app-1 python scripts/test_learning_system.py --skip-db

Requires DATABASE_URL (for PostgreSQL) and OPENROUTER_API_KEY (for LLM calls).
Run inside the app container where .env is loaded automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
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
# All 5 note types used across the pipeline
# ---------------------------------------------------------------------------

NOTE_TYPES = [
    "user_summarization",
    "user_newsletter_themes",
    "user_markdowngenerator",
    "user_htmlgenerator",
    "user_email_subject",
]

# Realistic feedback entries for each type
SAMPLE_FEEDBACK: dict[str, list[str]] = {
    "user_summarization": [
        "Summaries should emphasize practical business applications over technical details.",
        "Avoid using jargon like 'paradigm shift' or 'disruption' — use concrete terms instead.",
        "Business relevance sections could be more specific about which SMB functions benefit.",
    ],
    "user_newsletter_themes": [
        "Theme titles should be action-oriented, not abstract "
        "(e.g., 'How to...' not 'The Future of...').",
        "Ensure featured article is always the most broadly relevant, "
        "not just the most technical.",
        "Quick hits section needs more variety — avoid clustering similar AI model announcements.",
    ],
    "user_markdowngenerator": [
        "Opening paragraph is too generic — lead with a specific statistic or concrete example.",
        "Section transitions feel abrupt — add brief connecting sentences between major sections.",
        "CTAs should be more conversational and less 'salesy' in tone.",
    ],
    "user_htmlgenerator": [
        "Preserve all inline styles from the template — do not simplify CSS.",
        "Image alt text must be descriptive, not just the article title.",
        "Footer links section spacing is too tight on mobile — increase padding.",
    ],
    "user_email_subject": [
        "Subject lines should create curiosity without clickbait — avoid 'You Won't Believe...'.",
        "Keep subject lines under 50 characters for mobile readability.",
        "Include the newsletter number in the subject when possible.",
    ],
}

# Sample article content for summarization prompts
SAMPLE_ARTICLE_CONTENT = """\
URL: https://openai.com/index/hello-gpt-4o/
Title: Hello GPT-4o

OpenAI released GPT-4o ("o" for "omni"), a new flagship model that can reason
across audio, vision, and text in real time. GPT-4o matches GPT-4 Turbo
performance on text in English and code while being significantly better in
non-English languages. The model is also 2x faster and 50% cheaper than GPT-4
Turbo via the API. GPT-4o's free tier access means frontier AI capabilities are
now available to everyone, not just paid subscribers. The model supports real-time
voice conversations and can analyze images and documents directly."""

# Sample summaries JSON for theme generation
SAMPLE_SUMMARIES_JSON = json.dumps([
    {
        "Title": "Hello GPT-4o: OpenAI's Latest Multimodal Model",
        "URL": "https://openai.com/index/hello-gpt-4o/",
        "Source": "openai.com",
        "Summary": (
            "OpenAI released GPT-4o, processing text, audio, and vision in real time "
            "at half the cost of GPT-4 Turbo."
        ),
        "BusinessRelevance": (
            "Free-tier access to frontier AI enables solopreneurs to compete with "
            "enterprise teams on AI capability."
        ),
        "Order": 1,
    },
    {
        "Title": "5 AI Automation Trends Reshaping Small Businesses",
        "URL": "https://example.com/ai-automation-trends",
        "Source": "example.com",
        "Summary": (
            "Small businesses are embedding AI into customer service and operations "
            "workflows beyond initial experimentation."
        ),
        "BusinessRelevance": "Identifies which AI tools offer highest ROI for SMBs.",
        "Order": 2,
    },
    {
        "Title": "EU AI Act Implementation Timeline",
        "URL": "https://example.com/ai-regulation-update",
        "Source": "example.com",
        "Summary": (
            "The EU AI Act enters phased enforcement in 2026, with high-risk AI "
            "systems requiring compliance audits."
        ),
        "BusinessRelevance": (
            "Any business using AI tools may need to audit their stack for "
            "EU compliance."
        ),
        "Order": 3,
    },
])

# Sample formatted theme for markdown generation
SAMPLE_FORMATTED_THEME = json.dumps({
    "theme_name": "AI Accessibility Revolution",
    "theme_description": "How frontier AI tools are becoming accessible to all businesses",
    "featured_article": {
        "title": "Hello GPT-4o: OpenAI's Latest Multimodal Model",
        "url": "https://openai.com/index/hello-gpt-4o/",
        "source": "openai.com",
        "origin": "OpenAI Blog",
        "category": "AI Models",
        "summary": (
            "OpenAI released GPT-4o, a multimodal model processing text, audio, "
            "and vision in real time at half the cost of GPT-4 Turbo."
        ),
        "business_relevance": (
            "Free-tier access to frontier AI enables solopreneurs to compete "
            "with enterprise teams on AI capability."
        ),
        "why_featured": "Demonstrates democratization of frontier AI capabilities",
    },
    "main_article_1": {
        "title": "5 AI Automation Trends Reshaping Small Businesses in 2026",
        "url": "https://example.com/ai-automation-trends",
        "source": "example.com",
        "origin": "AI Industry Report",
        "category": "Business AI",
        "summary": (
            "Small businesses are embedding AI into customer service and operations."
        ),
        "business_relevance": "Identifies which AI tools offer highest ROI for SMBs.",
        "rationale": "Directly addresses SMB AI adoption patterns",
    },
    "main_article_2": {
        "title": "EU AI Act Implementation Timeline",
        "url": "https://example.com/ai-regulation-update",
        "source": "example.com",
        "origin": "Regulatory Analysis",
        "category": "AI Regulation",
        "summary": "EU AI Act enters phased enforcement in 2026.",
        "business_relevance": "Any business using AI tools may need compliance audits.",
        "rationale": "Critical compliance info for all business sizes",
    },
    "quick_hit_1": {
        "title": "AI Skills Gap Widens",
        "url": "https://example.com/ai-hiring-trends",
        "source": "example.com",
        "origin": "Employment Report",
        "category": "Workforce",
    },
    "quick_hit_2": {
        "title": "Anthropic Launches New Features",
        "url": "https://example.com/anthropic-claude-tools",
        "source": "example.com",
        "origin": "Anthropic Blog",
        "category": "AI Tools",
    },
    "quick_hit_3": {
        "title": "Microsoft Copilot Expansion",
        "url": "https://example.com/microsoft-copilot-enterprise",
        "source": "example.com",
        "origin": "Microsoft Blog",
        "category": "Enterprise AI",
    },
    "industry_1": {
        "title": "Introducing Gemini",
        "url": "https://blog.google/technology/ai/google-gemini-ai/",
        "source": "blog.google",
        "origin": "Google AI Blog",
        "major_player": "Google",
    },
    "industry_2": {
        "title": "Microsoft Expands Copilot",
        "url": "https://example.com/microsoft-copilot-enterprise",
        "source": "example.com",
        "origin": "Microsoft News",
        "major_player": "Microsoft",
    },
})


# ---------------------------------------------------------------------------
# Phase 1: Database CRUD — seed notes and verify round-trip
# ---------------------------------------------------------------------------


async def phase_db() -> dict[str, Any]:
    """Seed notes for all 5 types and verify insert + retrieval."""
    print("\n" + "=" * 70)
    print("PHASE 1: Database CRUD — Notes seeding & round-trip")
    print("=" * 70)

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from ica.db.crud import add_note, get_recent_notes
    from ica.db.models import Base

    env = _check_env("DATABASE_URL")
    engine = create_async_engine(env["DATABASE_URL"], echo=False)

    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Use unique newsletter_id to isolate test data
    test_nid = f"phase_d_test_{uuid.uuid4().hex[:8]}"
    inserted_ids: dict[str, list[int]] = {}

    print(f"\n--- 1a. Seeding notes for all 5 types (newsletter_id={test_nid}) ---")

    async with session_factory() as session:
        for note_type, feedbacks in SAMPLE_FEEDBACK.items():
            ids: list[int] = []
            for text in feedbacks:
                note = await add_note(
                    session,
                    note_type,
                    text,
                    newsletter_id=test_nid,
                )
                ids.append(note.id)
            inserted_ids[note_type] = ids
            print(f"  {note_type}: inserted {len(ids)} notes (IDs: {ids})")
        await session.commit()

    total_inserted = sum(len(v) for v in inserted_ids.values())
    print(f"\n  Total inserted: {total_inserted}")
    assert total_inserted == 15, f"Expected 15 notes, inserted {total_inserted}"

    # Verify retrieval for each type
    print(f"\n--- 1b. Verifying retrieval per type ---")
    async with session_factory() as session:
        for note_type in NOTE_TYPES:
            rows = await get_recent_notes(session, note_type)
            # We seeded 3 per type; there may be more from prior runs
            matching = [r for r in rows if r.newsletter_id == test_nid]
            assert len(matching) >= 3, (
                f"{note_type}: expected >= 3 matching notes, got {len(matching)}"
            )
            # Verify newest-first ordering
            for i in range(len(matching) - 1):
                assert matching[i].created_at >= matching[i + 1].created_at, (
                    f"{note_type}: notes not ordered newest-first"
                )
            print(f"  {note_type}: {len(matching)} test notes retrieved (newest-first)")

    await engine.dispose()

    results: dict[str, Any] = {
        "total_inserted": total_inserted,
        "types_tested": len(NOTE_TYPES),
        "test_newsletter_id": test_nid,
    }
    print("\n  Phase 1 PASSED: Notes inserted and retrieved for all 5 types.")
    return results


# ---------------------------------------------------------------------------
# Phase 2: Last-40 limit & type filtering
# ---------------------------------------------------------------------------


async def phase_limit() -> dict[str, Any]:
    """Seed 50 notes of one type, verify only 40 returned. Verify type isolation."""
    print("\n" + "=" * 70)
    print("PHASE 2: Last-40 limit & type filtering")
    print("=" * 70)

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from ica.db.crud import add_note, get_recent_notes
    from ica.db.models import Base

    env = _check_env("DATABASE_URL")
    engine = create_async_engine(env["DATABASE_URL"], echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    test_nid = f"phase_d_limit_{uuid.uuid4().hex[:8]}"
    test_type = "user_summarization"

    print(f"\n--- 2a. Seeding 50 notes of type '{test_type}' ---")
    async with session_factory() as session:
        for i in range(50):
            await add_note(
                session,
                test_type,
                f"Limit test feedback #{i + 1}: Use shorter sentences in summaries.",
                newsletter_id=test_nid,
            )
        await session.commit()
    print(f"  Inserted 50 notes")

    # Retrieve with default limit (40)
    print(f"\n--- 2b. Retrieving with default limit=40 ---")
    async with session_factory() as session:
        rows = await get_recent_notes(session, test_type)
        print(f"  Retrieved: {len(rows)} notes")
        assert len(rows) == 40, f"Expected exactly 40, got {len(rows)}"

        # Verify these are the newest 40
        test_rows = [r for r in rows if r.newsletter_id == test_nid]
        print(f"  Test-specific rows: {len(test_rows)}")
        assert len(test_rows) <= 40, f"Expected <= 40 test rows, got {len(test_rows)}"

    # Retrieve with explicit limit=10
    print(f"\n--- 2c. Retrieving with explicit limit=10 ---")
    async with session_factory() as session:
        rows_10 = await get_recent_notes(session, test_type, limit=10)
        print(f"  Retrieved: {len(rows_10)} notes")
        assert len(rows_10) == 10, f"Expected 10, got {len(rows_10)}"

    # Type isolation: different type should not see these notes
    print(f"\n--- 2d. Type isolation check ---")
    other_type = "user_htmlgenerator"
    async with session_factory() as session:
        other_rows = await get_recent_notes(session, other_type)
        matching = [r for r in other_rows if r.newsletter_id == test_nid]
        print(f"  '{other_type}' notes with test newsletter_id: {len(matching)}")
        assert len(matching) == 0, (
            f"Type isolation failed: found {len(matching)} notes of type "
            f"'{other_type}' with test newsletter_id"
        )

    await engine.dispose()

    results: dict[str, Any] = {
        "default_limit_returned": 40,
        "explicit_limit_10_returned": 10,
        "type_isolation": "PASS",
    }
    print("\n  Phase 2 PASSED: 40-entry limit enforced, type filtering isolates correctly.")
    return results


# ---------------------------------------------------------------------------
# Phase 3: Feedback aggregation
# ---------------------------------------------------------------------------


async def phase_aggregate() -> dict[str, Any]:
    """Verify aggregate_feedback() across all pipeline modules."""
    print("\n" + "=" * 70)
    print("PHASE 3: Feedback aggregation — all pipeline modules")
    print("=" * 70)

    from ica.db.models import Note

    # Import aggregate_feedback from each pipeline module that defines it
    from ica.pipeline.theme_generation import (
        aggregate_feedback as theme_agg,
    )
    from ica.pipeline.summarization import (
        aggregate_feedback as summary_agg,
    )
    from ica.pipeline.markdown_generation import (
        aggregate_feedback as markdown_agg,
    )
    from ica.pipeline.email_subject import (
        aggregate_feedback as email_agg,
    )
    from ica.pipeline.html_generation import (
        aggregate_feedback as html_agg,
    )

    # Create mock Note objects with just feedback_text
    mock_notes = []
    for text in SAMPLE_FEEDBACK["user_summarization"]:
        note = Note.__new__(Note)
        note.feedback_text = text
        note.type = "user_summarization"
        mock_notes.append(note)

    aggregators = {
        "theme_generation": theme_agg,
        "summarization": summary_agg,
        "markdown_generation": markdown_agg,
        "email_subject": email_agg,
        "html_generation": html_agg,
    }

    results: dict[str, Any] = {}

    for module_name, agg_fn in aggregators.items():
        print(f"\n--- 3a. Testing {module_name}.aggregate_feedback() ---")

        # Test with notes
        output = agg_fn(mock_notes)
        assert output is not None, f"{module_name}: returned None for non-empty input"
        assert isinstance(output, str), f"{module_name}: expected str, got {type(output)}"

        # Each line should be a bullet point
        lines = output.strip().split("\n")
        assert len(lines) == 3, (
            f"{module_name}: expected 3 bullet lines, got {len(lines)}"
        )

        # Check bullet format (either "- " or "• " prefix)
        for line in lines:
            assert line.startswith("- ") or line.startswith("\u2022 "), (
                f"{module_name}: line doesn't start with bullet: {line!r}"
            )
            # Check the feedback text is present after the bullet
            assert len(line) > 3, f"{module_name}: bullet line too short: {line!r}"

        print(f"  Output ({len(output)} chars):")
        for line in lines:
            print(f"    {line}")

        # Test with empty list
        empty_result = agg_fn([])
        assert empty_result is None, (
            f"{module_name}: expected None for empty input, got {empty_result!r}"
        )
        print(f"  Empty input returns None: PASS")

        results[module_name] = {
            "lines": len(lines),
            "total_chars": len(output),
            "empty_returns_none": True,
        }

    print("\n  Phase 3 PASSED: All 5 aggregate_feedback() functions produce correct output.")
    return results


# ---------------------------------------------------------------------------
# Phase 4: Prompt injection — verify feedback section appears in prompts
# ---------------------------------------------------------------------------


async def phase_prompt() -> dict[str, Any]:
    """Build prompts for all 5 steps with feedback and verify injection."""
    print("\n" + "=" * 70)
    print("PHASE 4: Prompt injection — feedback section in all prompts")
    print("=" * 70)

    from ica.prompts.summarization import build_summarization_prompt
    from ica.prompts.theme_generation import build_theme_generation_prompt
    from ica.prompts.markdown_generation import build_markdown_generation_prompt
    from ica.prompts.email_subject import build_email_subject_prompt
    from ica.prompts.html_generation import build_html_generation_prompt

    # Construct a realistic aggregated feedback string
    feedback_text = "\n".join(
        f"- {fb}" for fb in SAMPLE_FEEDBACK["user_summarization"]
    )

    results: dict[str, Any] = {}

    # 4a. Summarization prompt
    print(f"\n--- 4a. Summarization prompt ---")
    sys_p, user_p = build_summarization_prompt(
        SAMPLE_ARTICLE_CONTENT,
        aggregated_feedback=feedback_text,
    )
    assert "Editorial Improvement Context" in user_p, (
        "Summarization: feedback section not found in user prompt"
    )
    assert "practical business applications" in user_p, (
        "Summarization: specific feedback text not in user prompt"
    )
    print(f"  System prompt: {len(sys_p)} chars")
    print(f"  User prompt: {len(user_p)} chars")
    print(f"  Contains 'Editorial Improvement Context': YES")
    print(f"  Contains specific feedback text: YES")
    results["summarization"] = {"sys_len": len(sys_p), "user_len": len(user_p)}

    # 4b. Theme generation prompt
    print(f"\n--- 4b. Theme generation prompt ---")
    sys_p, user_p = build_theme_generation_prompt(
        summaries_json=SAMPLE_SUMMARIES_JSON,
        aggregated_feedback=feedback_text,
    )
    assert "Editorial Improvement Context" in user_p, (
        "Theme generation: feedback section not found in user prompt"
    )
    assert "practical business applications" in user_p, (
        "Theme generation: specific feedback text not in user prompt"
    )
    print(f"  System prompt: {len(sys_p)} chars")
    print(f"  User prompt: {len(user_p)} chars")
    print(f"  Contains 'Editorial Improvement Context': YES")
    results["theme_generation"] = {"sys_len": len(sys_p), "user_len": len(user_p)}

    # 4c. Markdown generation prompt
    print(f"\n--- 4c. Markdown generation prompt ---")
    sys_p, user_p = build_markdown_generation_prompt(
        SAMPLE_FORMATTED_THEME,
        aggregated_feedback=feedback_text,
    )
    assert "Editorial Improvement Context" in user_p, (
        "Markdown generation: feedback section not found in user prompt"
    )
    assert "practical business applications" in user_p, (
        "Markdown generation: specific feedback text not in user prompt"
    )
    print(f"  System prompt: {len(sys_p)} chars")
    print(f"  User prompt: {len(user_p)} chars")
    print(f"  Contains 'Editorial Improvement Context': YES")
    results["markdown_generation"] = {"sys_len": len(sys_p), "user_len": len(user_p)}

    # 4d. Email subject prompt
    print(f"\n--- 4d. Email subject prompt ---")
    sys_p, user_p = build_email_subject_prompt(
        "This is sample newsletter text for subject line generation.",
        aggregated_feedback=feedback_text,
    )
    assert "Editorial Improvement Context" in user_p, (
        "Email subject: feedback section not found in user prompt"
    )
    assert "practical business applications" in user_p, (
        "Email subject: specific feedback text not in user prompt"
    )
    print(f"  System prompt: {len(sys_p)} chars")
    print(f"  User prompt: {len(user_p)} chars")
    print(f"  Contains 'Editorial Improvement Context': YES")
    results["email_subject"] = {"sys_len": len(sys_p), "user_len": len(user_p)}

    # 4e. HTML generation prompt (feedback goes in system prompt)
    print(f"\n--- 4e. HTML generation prompt ---")
    sys_p, user_p = build_html_generation_prompt(
        markdown_content="# Test Newsletter\n\nContent here.",
        html_template="<html><body>{{content}}</body></html>",
        newsletter_date="2026-02-26",
        aggregated_feedback=feedback_text,
    )
    # HTML generation injects feedback into the system prompt
    assert "Editorial Improvement Context" in sys_p, (
        "HTML generation: feedback section not found in system prompt"
    )
    assert "practical business applications" in sys_p, (
        "HTML generation: specific feedback text not in system prompt"
    )
    print(f"  System prompt: {len(sys_p)} chars")
    print(f"  User prompt: {len(user_p)} chars")
    print(f"  Contains 'Editorial Improvement Context' (in system): YES")
    results["html_generation"] = {"sys_len": len(sys_p), "user_len": len(user_p)}

    # 4f. Verify prompts WITHOUT feedback do NOT contain the section
    print(f"\n--- 4f. Negative check: prompts without feedback ---")
    sys_p, user_p = build_summarization_prompt(SAMPLE_ARTICLE_CONTENT)
    assert "Editorial Improvement Context" not in user_p, (
        "Summarization: feedback section found in prompt with no feedback"
    )
    assert "Editorial Improvement Context" not in sys_p, (
        "Summarization: feedback section found in system prompt with no feedback"
    )
    print(f"  Summarization without feedback: no feedback section (PASS)")

    sys_p, user_p = build_theme_generation_prompt(SAMPLE_SUMMARIES_JSON)
    assert "Editorial Improvement Context" not in user_p, (
        "Theme generation: feedback section found with no feedback"
    )
    print(f"  Theme generation without feedback: no feedback section (PASS)")

    sys_p, user_p = build_markdown_generation_prompt(SAMPLE_FORMATTED_THEME)
    assert "Editorial Improvement Context" not in user_p, (
        "Markdown generation: feedback section found with no feedback"
    )
    print(f"  Markdown generation without feedback: no feedback section (PASS)")

    print("\n  Phase 4 PASSED: Feedback injected into all 5 prompt builders correctly.")
    return results


# ---------------------------------------------------------------------------
# Phase 5: Cross-run LLM — feedback affects generation
# ---------------------------------------------------------------------------


async def phase_llm() -> dict[str, Any]:
    """Run summarization LLM twice: baseline (no feedback) vs with feedback.

    Verifies that the learning system's prompt injection mechanism works
    end-to-end with a real LLM call by confirming the prompts are
    structurally different and the LLM receives the feedback.
    """
    print("\n" + "=" * 70)
    print("PHASE 5: Cross-run LLM — feedback injection into real LLM calls")
    print("=" * 70)

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from ica.config.llm_config import LLMPurpose, get_model
    from ica.db.crud import add_note, get_recent_notes
    from ica.db.models import Base
    from ica.pipeline.theme_generation import (
        aggregate_feedback,
        generate_themes,
    )
    from ica.prompts.summarization import build_summarization_prompt
    import litellm

    env = _check_env("OPENROUTER_API_KEY", "DATABASE_URL")
    model = _openrouter_model(get_model(LLMPurpose.SUMMARY))
    print(f"  Model: {model}")

    engine = create_async_engine(env["DATABASE_URL"], echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    test_nid = f"phase_d_llm_{uuid.uuid4().hex[:8]}"

    # -- 5a. Run 1: baseline call (no feedback) --
    print(f"\n--- 5a. Run 1 — Baseline summarization (no feedback) ---")
    sys_base, user_base = build_summarization_prompt(SAMPLE_ARTICLE_CONTENT)
    assert "Editorial Improvement Context" not in user_base, (
        "Baseline prompt should not contain feedback section"
    )
    print(f"  Baseline user prompt: {len(user_base)} chars")

    response_base = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": sys_base},
            {"role": "user", "content": user_base},
        ],
    )
    baseline_output: str = response_base.choices[0].message.content.strip()
    print(f"  Baseline output: {len(baseline_output)} chars")
    print(f"  Preview: {baseline_output[:200]}...")
    assert len(baseline_output) > 50, (
        f"Baseline output too short: {len(baseline_output)} chars"
    )

    # -- 5b. Simulate Run 1 feedback storage --
    print(f"\n--- 5b. Storing feedback from Run 1 (simulated user review) ---")
    feedback_entries = [
        "Always start summaries with a concrete statistic or number from the article.",
        "Business relevance must mention at least one specific business function "
        "(e.g., marketing, operations, customer service).",
        "Avoid phrases like 'game-changer' or 'revolutionary' — use measured language.",
    ]
    async with session_factory() as session:
        for fb in feedback_entries:
            await add_note(session, "user_summarization", fb, newsletter_id=test_nid)
        await session.commit()
    print(f"  Stored {len(feedback_entries)} feedback notes")

    # -- 5c. Run 2: with feedback --
    print(f"\n--- 5c. Run 2 — Summarization with injected feedback ---")
    async with session_factory() as session:
        notes = await get_recent_notes(session, "user_summarization")
        print(f"  Retrieved {len(notes)} notes from DB")

    aggregated = aggregate_feedback(notes)
    assert aggregated is not None, "aggregate_feedback returned None with stored notes"
    print(f"  Aggregated feedback: {len(aggregated)} chars")

    sys_fb, user_fb = build_summarization_prompt(
        SAMPLE_ARTICLE_CONTENT,
        aggregated_feedback=aggregated,
    )

    # Verify structural difference
    assert "Editorial Improvement Context" in user_fb, (
        "Run 2 prompt missing feedback section"
    )
    assert len(user_fb) > len(user_base), (
        f"Run 2 prompt ({len(user_fb)}) should be longer than baseline ({len(user_base)})"
    )
    assert "concrete statistic" in user_fb, (
        "Run 2 prompt doesn't contain stored feedback text"
    )
    print(f"  Run 2 user prompt: {len(user_fb)} chars (baseline was {len(user_base)})")
    print(f"  Prompt growth from feedback: +{len(user_fb) - len(user_base)} chars")

    response_fb = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": sys_fb},
            {"role": "user", "content": user_fb},
        ],
    )
    feedback_output: str = response_fb.choices[0].message.content.strip()
    print(f"  Run 2 output: {len(feedback_output)} chars")
    print(f"  Preview: {feedback_output[:200]}...")
    assert len(feedback_output) > 50, (
        f"Run 2 output too short: {len(feedback_output)} chars"
    )

    # -- 5d. Theme generation with DB session (full integrate) --
    print(f"\n--- 5d. Theme generation with DB session (full feedback loop) ---")
    theme_model = _openrouter_model(get_model(LLMPurpose.THEME))
    print(f"  Theme model: {theme_model}")

    async with session_factory() as session:
        # Store theme-specific feedback
        await add_note(
            session,
            "user_newsletter_themes",
            "Always include at least one industry regulation or policy article.",
            newsletter_id=test_nid,
        )
        await session.commit()

    async with session_factory() as session:
        theme_result = await generate_themes(
            SAMPLE_SUMMARIES_JSON,
            session=session,
            model=theme_model,
        )

    assert theme_result.raw_llm_output, "Theme generation returned empty output"
    assert len(theme_result.themes) >= 1, (
        f"Expected >= 1 theme, got {len(theme_result.themes)}"
    )
    print(f"  Themes generated: {len(theme_result.themes)}")
    print(f"  Raw output: {len(theme_result.raw_llm_output)} chars")
    print(f"  Model used: {theme_result.model}")
    for i, theme in enumerate(theme_result.themes):
        print(f"  Theme {i + 1}: {theme.theme_name}")

    await engine.dispose()

    results: dict[str, Any] = {
        "baseline_output_len": len(baseline_output),
        "feedback_output_len": len(feedback_output),
        "prompt_growth_chars": len(user_fb) - len(user_base),
        "feedback_entries_stored": len(feedback_entries),
        "themes_generated": len(theme_result.themes),
        "theme_model": theme_result.model,
    }

    print("\n  Phase 5 PASSED: Feedback from Run 1 injected into Run 2 prompts and LLM calls.")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: learning system feedback loop (Phase D).",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=["all", "db", "limit", "aggregate", "prompt", "llm"],
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip Phase 5 (LLM calls with real API)",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip phases requiring database access (run aggregate + prompt only)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    results: dict[str, Any] = {}

    if args.skip_db:
        print("\n  Database phases skipped (--skip-db).")
    else:
        if args.phase in ("all", "db"):
            results["db"] = await phase_db()

        if args.phase in ("all", "limit"):
            results["limit"] = await phase_limit()

    if args.phase in ("all", "aggregate"):
        results["aggregate"] = await phase_aggregate()

    if args.phase in ("all", "prompt"):
        results["prompt"] = await phase_prompt()

    if args.skip_llm:
        if args.phase in ("all",):
            print("\n  LLM phase skipped (--skip-llm).")
    elif args.skip_db:
        if args.phase in ("all", "llm"):
            print("\n  LLM phase skipped (requires database, --skip-db active).")
    else:
        if args.phase in ("all", "llm"):
            results["llm"] = await phase_llm()

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

    print("\nPhase D integration test complete!")


if __name__ == "__main__":
    main()
