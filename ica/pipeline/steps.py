"""Pipeline step wrappers — adapt each pipeline module to the PipelineStep protocol.

Each function in this module:
1. Creates the service instances it needs (from Settings).
2. Extracts input data from PipelineContext.
3. Calls the underlying pipeline function(s).
4. Stores results back into PipelineContext.
5. Returns the updated context.

These are consumed by :func:`~ica.pipeline.orchestrator.build_default_steps`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ica.logging import get_logger
from ica.pipeline.orchestrator import PipelineContext

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ica.config.settings import Settings
    from ica.services.google_docs import GoogleDocsService
    from ica.services.google_sheets import GoogleSheetsService
    from ica.services.slack import SlackService
    from ica.services.web_fetcher import WebFetcherService

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Service factory helpers (lazy imports to avoid circular deps)
# ---------------------------------------------------------------------------


def _get_settings() -> Settings:
    from ica.config.settings import get_settings

    return get_settings()


def _make_slack() -> SlackService:
    from ica.services.slack import SlackService

    s = _get_settings()
    return SlackService(token=s.slack_bot_token, channel=s.slack_channel)


def _make_sheets() -> GoogleSheetsService:
    from ica.services.google_sheets import GoogleSheetsService

    s = _get_settings()
    return GoogleSheetsService(credentials_path=s.google_service_account_credentials_path)


def _make_docs() -> GoogleDocsService:
    from ica.services.google_docs import GoogleDocsService

    s = _get_settings()
    return GoogleDocsService(credentials_path=s.google_service_account_credentials_path)


def _make_http() -> WebFetcherService:
    from ica.services.web_fetcher import WebFetcherService

    return WebFetcherService()


@asynccontextmanager
async def _session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session context manager."""
    from ica.db.session import get_session

    async with get_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Step 1: Article Curation
# ---------------------------------------------------------------------------


async def run_curation_step(ctx: PipelineContext) -> PipelineContext:
    """Article curation — fetch unapproved articles, write to sheet, wait for approval.

    Composes :func:`~ica.pipeline.article_curation.prepare_curation_data`
    and :func:`~ica.pipeline.article_curation.run_approval_flow`.
    """
    from ica.pipeline.article_curation import prepare_curation_data, run_approval_flow

    settings = _get_settings()
    slack = _make_slack()
    sheets = _make_sheets()
    spreadsheet_id = settings.google_sheets_spreadsheet_id
    channel = settings.slack_channel

    # Phase 1: prepare curation data (DB → Sheet)
    async with _session() as session:
        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id=spreadsheet_id,
            channel=channel,
        )

    # Phase 2: approval flow (Slack interaction → approved articles)
    approval = await run_approval_flow(
        slack,
        slack,
        sheets,
        spreadsheet_id=spreadsheet_id,
        channel=channel,
    )

    # Store approved articles in context
    ctx.articles = [asdict(a) for a in approval.articles]
    if approval.articles:
        ctx.newsletter_id = approval.articles[0].newsletter_id
    logger.info(
        "Curation complete: %d articles approved, newsletter_id=%s",
        len(approval.articles),
        ctx.newsletter_id,
    )
    return ctx


# ---------------------------------------------------------------------------
# Step 2: Summarization
# ---------------------------------------------------------------------------


async def run_summarization_step(ctx: PipelineContext) -> PipelineContext:
    """Summarization — prepare data, run per-article LLM summaries, output loop.

    Composes :func:`~ica.pipeline.summarization.prepare_summarization_data`,
    :func:`~ica.pipeline.summarization.summarize_articles`, and
    :func:`~ica.pipeline.summarization.run_summarization_output`.
    """
    from ica.pipeline.summarization import (
        prepare_summarization_data,
        run_summarization_output,
        summarize_articles,
    )

    settings = _get_settings()
    slack = _make_slack()
    sheets = _make_sheets()
    http = _make_http()
    spreadsheet_id = settings.google_sheets_spreadsheet_id

    # Phase 1: data preparation (Sheet → DB upsert → normalized articles)
    async with _session() as session:
        prep = await prepare_summarization_data(
            session,
            sheets,
            spreadsheet_id=spreadsheet_id,
        )

    # Phase 2: per-article summarization loop
    async with _session() as session:
        loop_result = await summarize_articles(
            prep.articles,
            http=http,
            session=session,
            slack=slack,
            model=prep.model,
        )

    # Phase 3: Slack output and feedback loop
    async with _session() as session:
        output = await run_summarization_output(
            loop_result.summaries,
            slack=slack,
            session=session,
            newsletter_id=ctx.newsletter_id,
        )

    # Store summaries in context for downstream steps
    ctx.summaries = output.articles
    ctx.summaries_json = json.dumps(output.articles, default=str)
    logger.info("Summarization complete: %d summaries", len(output.articles))
    return ctx


# ---------------------------------------------------------------------------
# Step 3: Theme Generation (includes selection)
# ---------------------------------------------------------------------------


async def run_theme_generation_step(ctx: PipelineContext) -> PipelineContext:
    """Theme generation + selection — generate themes, interactive selection, approval.

    Composes :func:`~ica.pipeline.theme_generation.generate_themes` with the
    theme selection and approval functions from :mod:`~ica.pipeline.theme_selection`.
    """
    from ica.pipeline.theme_generation import generate_themes
    from ica.pipeline.theme_selection import (
        APPROVAL_FIELD_LABEL,
        FEEDBACK_TEXTAREA_LABEL,
        SELECTION_FIELD_LABEL,
        ApprovalChoice,
        build_approval_form,
        build_theme_selection_form,
        extract_learning_data,
        extract_selected_theme,
        format_freshness_slack_message,
        format_selected_theme_body,
        format_themes_slack_message,
        is_feedback_selection,
        parse_approval_choice,
        run_freshness_check,
        save_approved_theme,
        store_theme_feedback,
    )
    from ica.utils.marker_parser import parse_markers

    slack = _make_slack()

    # --- Outer loop: theme generation → selection → approval ---
    while True:
        # 1. Generate themes
        async with _session() as session:
            gen_result = await generate_themes(
                ctx.summaries_json,
                session=session,
            )

        # 2. Share themes in Slack
        themes_message = format_themes_slack_message(gen_result)
        await slack.send_channel_message(themes_message)

        # --- Theme selection loop ---
        while True:
            # 3. Build selection form and wait
            form_fields = build_theme_selection_form(gen_result.themes)
            response = await slack.send_and_wait_form(
                "Select a theme or provide feedback:",
                form_fields=form_fields,
            )

            selection_value = response.get(SELECTION_FIELD_LABEL, "")
            feedback_text = response.get(FEEDBACK_TEXTAREA_LABEL, "")

            # 4a. Feedback → extract learning data, store, regenerate
            if is_feedback_selection(selection_value):
                if feedback_text.strip():
                    async with _session() as session:
                        learning_note = await extract_learning_data(
                            feedback=feedback_text,
                            input_text=ctx.summaries_json,
                            model_output=gen_result.raw_llm_output,
                        )
                        await store_theme_feedback(
                            session,
                            learning_note,
                            newsletter_id=ctx.newsletter_id,
                        )
                break  # regenerate themes (outer loop)

            # 4b. Theme selected
            selected_theme = extract_selected_theme(
                selection_value,
                gen_result.themes,
            )
            if selected_theme is None:
                # Fallback: use first theme
                selected_theme = gen_result.themes[0] if gen_result.themes else None
                if selected_theme is None:
                    raise RuntimeError("No themes available for selection")

            # 5. Parse markers from selected theme body
            formatted_theme = parse_markers(selected_theme.theme_body)

            # 6. Run freshness check
            freshness_report = await run_freshness_check(selected_theme.theme_body)

            # 7. Share selected theme + freshness in Slack
            selected_body_formatted = format_selected_theme_body(
                selected_theme.theme_body,
            )
            await slack.send_channel_message(selected_body_formatted)
            freshness_message = format_freshness_slack_message(
                theme_name=selected_theme.theme_name or "Selected Theme",
                theme_body=selected_theme.theme_body,
                freshness_report=freshness_report,
            )
            await slack.send_channel_message(freshness_message)

            # --- Approval loop ---
            while True:
                approval_fields = build_approval_form()
                approval_response = await slack.send_and_wait_form(
                    "Approve this theme or provide feedback:",
                    form_fields=approval_fields,
                )
                approval_value = approval_response.get(APPROVAL_FIELD_LABEL, "")
                approval_feedback = approval_response.get(
                    FEEDBACK_TEXTAREA_LABEL,
                    "",
                )
                choice = parse_approval_choice(approval_value)

                if choice == ApprovalChoice.APPROVE:
                    # Save theme and return
                    async with _session() as session:
                        await save_approved_theme(
                            session,
                            selected_theme,
                            newsletter_id=ctx.newsletter_id,
                        )

                    # Convert FormattedTheme to dict for PipelineContext
                    ctx.formatted_theme = asdict(formatted_theme)
                    ctx.theme_name = selected_theme.theme_name or ""
                    ctx.theme_body = selected_theme.theme_body
                    ctx.theme_summary = selected_theme.theme_description

                    logger.info(
                        "Theme approved: %s",
                        ctx.theme_name,
                    )
                    return ctx

                if choice == ApprovalChoice.RESET:
                    break  # break approval loop → break selection loop → regenerate

                if choice == ApprovalChoice.FEEDBACK:
                    if approval_feedback.strip():
                        async with _session() as session:
                            learning_note = await extract_learning_data(
                                feedback=approval_feedback,
                                input_text=ctx.summaries_json,
                                model_output=gen_result.raw_llm_output,
                            )
                            await store_theme_feedback(
                                session,
                                learning_note,
                                newsletter_id=ctx.newsletter_id,
                            )
                    break  # break approval loop → break selection loop → regenerate
            else:
                # Approval loop exhausted (shouldn't happen — while True)
                continue  # pragma: no cover

            # If we broke out of the approval loop, break the selection loop too
            break

        # If we get here, regenerate from outer loop
        continue


# ---------------------------------------------------------------------------
# Step 4: Markdown Generation
# ---------------------------------------------------------------------------


async def run_markdown_generation_step(ctx: PipelineContext) -> PipelineContext:
    """Markdown generation — generate with 3-layer validation, user review loop.

    Composes :func:`~ica.pipeline.markdown_generation.generate_with_validation`
    and :func:`~ica.pipeline.markdown_generation.run_markdown_review`.
    """
    from ica.db.crud import get_recent_notes
    from ica.pipeline.markdown_generation import (
        aggregate_feedback,
        generate_with_validation,
        run_markdown_review,
    )

    slack = _make_slack()
    docs = _make_docs()
    formatted_theme_str = json.dumps(ctx.formatted_theme, default=str)

    # Fetch learning data for generation
    aggregated = None
    async with _session() as session:
        notes = await get_recent_notes(session, "user_markdowngenerator")
        aggregated = aggregate_feedback(notes)

    # Generate with validation (up to 3 attempts)
    markdown = await generate_with_validation(
        formatted_theme_str,
        aggregated_feedback=aggregated,
    )

    # User review loop (Slack feedback)
    async with _session() as session:
        result = await run_markdown_review(
            markdown,
            formatted_theme_str,
            slack=slack,
            docs=docs,
            session=session,
            newsletter_id=ctx.newsletter_id,
        )

    ctx.markdown_doc_id = result.markdown_doc_id
    logger.info("Markdown generation complete: doc_id=%s", ctx.markdown_doc_id)
    return ctx


# ---------------------------------------------------------------------------
# Step 5: HTML Generation
# ---------------------------------------------------------------------------


async def run_html_generation_step(ctx: PipelineContext) -> PipelineContext:
    """HTML generation — convert markdown to email-ready HTML with user review.

    Calls :func:`~ica.pipeline.html_generation.run_html_generation`.
    """
    from ica.pipeline.html_generation import run_html_generation

    settings = _get_settings()
    slack = _make_slack()
    docs = _make_docs()

    # Fetch markdown content from Google Docs
    markdown_content = ""
    if ctx.markdown_doc_id:
        markdown_content = await docs.get_content(ctx.markdown_doc_id)

    # Load HTML template from file (if configured)
    html_template = ""
    if settings.html_template_path:
        from pathlib import Path

        template_path = Path(settings.html_template_path)
        if template_path.exists():
            html_template = template_path.read_text(encoding="utf-8")

    # Compute newsletter date
    newsletter_date = ctx.extra.get(
        "newsletter_date",
        datetime.now(UTC).strftime("%m/%d/%Y"),
    )

    async with _session() as session:
        result = await run_html_generation(
            markdown_content,
            html_template,
            newsletter_date,
            slack=slack,
            docs=docs,
            session=session,
            newsletter_id=ctx.newsletter_id,
        )

    ctx.html_doc_id = result.html_doc_id
    logger.info("HTML generation complete: doc_id=%s", ctx.html_doc_id)
    return ctx


# ---------------------------------------------------------------------------
# Step 6a: Alternates HTML
# ---------------------------------------------------------------------------


async def run_alternates_html_step(ctx: PipelineContext) -> PipelineContext:
    """Alternates HTML — filter unused articles for A/B variant document.

    Calls :func:`~ica.pipeline.alternates_html.filter_unused_articles`.
    """
    from ica.pipeline.alternates_html import filter_unused_articles

    result = filter_unused_articles(ctx.formatted_theme, ctx.summaries)
    ctx.extra["alternates_unused_summaries"] = result.unused_summaries
    ctx.extra["alternates_urls_in_theme"] = result.urls_in_theme
    logger.info(
        "Alternates HTML: %d unused articles identified",
        len(result.unused_summaries),
    )
    return ctx


# ---------------------------------------------------------------------------
# Step 6b: Email Subject & Preview
# ---------------------------------------------------------------------------


async def run_email_subject_step(ctx: PipelineContext) -> PipelineContext:
    """Email subject & preview — generate subjects, select, review.

    Calls :func:`~ica.pipeline.email_subject.run_email_subject_generation`.
    """
    from ica.pipeline.email_subject import run_email_subject_generation

    slack = _make_slack()
    docs = _make_docs()

    async with _session() as session:
        result = await run_email_subject_generation(
            ctx.html_doc_id or "",
            slack=slack,
            docs=docs,
            session=session,
            newsletter_id=ctx.newsletter_id,
        )

    ctx.extra["email_subject"] = result.selected_subject
    ctx.extra["email_review"] = result.review_text
    ctx.extra["email_doc_id"] = result.doc_id
    logger.info("Email subject complete: %s", result.selected_subject[:60])
    return ctx


# ---------------------------------------------------------------------------
# Step 6c: Social Media
# ---------------------------------------------------------------------------


async def run_social_media_step(ctx: PipelineContext) -> PipelineContext:
    """Social media — generate posts (two phases) with user review.

    Calls :func:`~ica.pipeline.social_media.run_social_media_generation`.
    """
    from ica.pipeline.social_media import run_social_media_generation

    slack = _make_slack()
    docs = _make_docs()

    result = await run_social_media_generation(
        ctx.html_doc_id or "",
        ctx.formatted_theme,
        slack=slack,  # type: ignore[arg-type]
        docs=docs,
    )

    ctx.extra["social_media_doc_id"] = result.doc_id
    logger.info("Social media generation complete: doc_id=%s", result.doc_id)
    return ctx


# ---------------------------------------------------------------------------
# Step 6d: LinkedIn Carousel
# ---------------------------------------------------------------------------


async def run_linkedin_carousel_step(ctx: PipelineContext) -> PipelineContext:
    """LinkedIn carousel — generate carousel slides with character validation.

    Calls :func:`~ica.pipeline.linkedin_carousel.run_linkedin_carousel_generation`.
    """
    from ica.pipeline.linkedin_carousel import run_linkedin_carousel_generation

    slack = _make_slack()
    docs = _make_docs()

    result = await run_linkedin_carousel_generation(
        ctx.html_doc_id or "",
        ctx.formatted_theme,
        slack=slack,  # type: ignore[arg-type]
        docs=docs,
    )

    ctx.extra["linkedin_carousel_doc_id"] = result.doc_id
    logger.info("LinkedIn carousel complete: doc_id=%s", result.doc_id)
    return ctx
