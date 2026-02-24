"""Tests for ica.pipeline.steps — step wrappers that wire pipeline modules to the orchestrator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.orchestrator import PipelineContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeSettings:
    """Minimal settings stand-in for tests."""

    slack_bot_token: str = "xoxb-fake"
    slack_channel: str = "C-TEST"
    google_sheets_credentials_path: str = "/tmp/sheets.json"
    google_docs_credentials_path: str = "/tmp/docs.json"
    google_sheets_spreadsheet_id: str = "sheet-123"
    html_template_path: str = ""


@pytest.fixture
def fake_settings():
    return FakeSettings()


@pytest.fixture
def mock_settings(fake_settings):
    """Patch get_settings to return our fake settings."""
    with patch("ica.pipeline.steps._get_settings", return_value=fake_settings):
        yield fake_settings


@pytest.fixture
def mock_slack():
    """A mock SlackService satisfying all Slack protocols."""
    slack = AsyncMock()
    slack.send_message = AsyncMock()
    slack.send_channel_message = AsyncMock()
    slack.send_and_wait = AsyncMock()
    slack.send_and_wait_form = AsyncMock(return_value={})
    slack.send_and_wait_freetext = AsyncMock(return_value="")
    return slack


@pytest.fixture
def mock_docs():
    """A mock GoogleDocsService."""
    docs = AsyncMock()
    docs.create_document = AsyncMock(return_value="doc-new-123")
    docs.insert_content = AsyncMock()
    docs.get_content = AsyncMock(return_value="<html>test</html>")
    return docs


class _FakeSessionCtx:
    """Fake async context manager that yields a mock session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


def _fake_session_ctx(session=None):
    """Create a fake session context manager."""
    return _FakeSessionCtx(session or AsyncMock())


# ---------------------------------------------------------------------------
# Step 6a: Alternates HTML (simplest — pure function, no services)
# ---------------------------------------------------------------------------


class TestAlternatesHtmlStep:
    @pytest.mark.asyncio
    async def test_filters_unused_articles(self, mock_settings):
        from ica.pipeline.steps import run_alternates_html_step

        ctx = PipelineContext(
            run_id="alt1",
            formatted_theme={
                "FEATURED ARTICLE": {"URL": "https://used.com/1"},
            },
            summaries=[
                {"URL": "https://used.com/1", "Title": "Used"},
                {"URL": "https://unused.com/2", "Title": "Unused"},
            ],
        )
        result = await run_alternates_html_step(ctx)
        assert len(result.extra["alternates_unused_summaries"]) == 1
        assert result.extra["alternates_unused_summaries"][0]["URL"] == "https://unused.com/2"

    @pytest.mark.asyncio
    async def test_empty_summaries(self, mock_settings):
        from ica.pipeline.steps import run_alternates_html_step

        ctx = PipelineContext(run_id="alt2", formatted_theme={}, summaries=[])
        result = await run_alternates_html_step(ctx)
        assert result.extra["alternates_unused_summaries"] == []

    @pytest.mark.asyncio
    async def test_all_used(self, mock_settings):
        from ica.pipeline.steps import run_alternates_html_step

        ctx = PipelineContext(
            run_id="alt3",
            formatted_theme={"ARTICLE": {"URL": "https://a.com"}},
            summaries=[{"URL": "https://a.com", "Title": "A"}],
        )
        result = await run_alternates_html_step(ctx)
        assert result.extra["alternates_unused_summaries"] == []
        assert "https://a.com" in result.extra["alternates_urls_in_theme"]

    @pytest.mark.asyncio
    async def test_returns_same_context(self, mock_settings):
        from ica.pipeline.steps import run_alternates_html_step

        ctx = PipelineContext(run_id="alt4", formatted_theme={}, summaries=[])
        result = await run_alternates_html_step(ctx)
        assert result is ctx


# ---------------------------------------------------------------------------
# Step 1: Curation
# ---------------------------------------------------------------------------


class TestCurationStep:
    @pytest.mark.asyncio
    async def test_wires_curation_flow(self, mock_settings, mock_slack):
        from ica.pipeline.article_curation import ApprovalResult, ApprovedArticle
        from ica.pipeline.steps import run_curation_step

        approved = [
            ApprovedArticle(
                url="https://example.com/1",
                title="Test Article",
                publish_date="02/23/2026",
                origin="google_news",
                approved=True,
                newsletter_id="NL-42",
                industry_news=False,
            ),
        ]
        approval_result = ApprovalResult(articles=approved, validation_attempts=1)

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_sheets", return_value=AsyncMock()),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.article_curation.prepare_curation_data",
                new_callable=AsyncMock,
            ) as mock_prepare,
            patch(
                "ica.pipeline.article_curation.run_approval_flow",
                new_callable=AsyncMock,
                return_value=approval_result,
            ) as mock_approval,
        ):
            ctx = PipelineContext(run_id="cur1")
            result = await run_curation_step(ctx)

        assert result.newsletter_id == "NL-42"
        assert len(result.articles) == 1
        assert result.articles[0]["url"] == "https://example.com/1"
        mock_prepare.assert_awaited_once()
        mock_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_approval(self, mock_settings, mock_slack):
        from ica.pipeline.article_curation import ApprovalResult
        from ica.pipeline.steps import run_curation_step

        approval_result = ApprovalResult(articles=[], validation_attempts=1)

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_sheets", return_value=AsyncMock()),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.article_curation.prepare_curation_data",
                new_callable=AsyncMock,
            ),
            patch(
                "ica.pipeline.article_curation.run_approval_flow",
                new_callable=AsyncMock,
                return_value=approval_result,
            ),
        ):
            ctx = PipelineContext(run_id="cur2")
            result = await run_curation_step(ctx)

        assert result.articles == []
        assert result.newsletter_id is None


# ---------------------------------------------------------------------------
# Step 2: Summarization
# ---------------------------------------------------------------------------


class TestSummarizationStep:
    @pytest.mark.asyncio
    async def test_wires_three_phases(self, mock_settings, mock_slack):
        from ica.pipeline.steps import run_summarization_step

        prep_result = MagicMock()
        prep_result.articles = []
        prep_result.model = "test-model"

        loop_result = MagicMock()
        loop_result.summaries = []
        loop_result.model = "test-model"

        output = MagicMock()
        output.articles = [{"URL": "https://a.com", "Title": "A", "Summary": "S"}]
        output.text = "formatted text"
        output.model = "test-model"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_sheets", return_value=AsyncMock()),
            patch("ica.pipeline.steps._make_http", return_value=AsyncMock()),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.summarization.prepare_summarization_data",
                new_callable=AsyncMock,
                return_value=prep_result,
            ) as mock_prep,
            patch(
                "ica.pipeline.summarization.summarize_articles",
                new_callable=AsyncMock,
                return_value=loop_result,
            ) as mock_loop,
            patch(
                "ica.pipeline.summarization.run_summarization_output",
                new_callable=AsyncMock,
                return_value=output,
            ) as mock_output,
        ):
            ctx = PipelineContext(run_id="sum1", newsletter_id="NL-1")
            result = await run_summarization_step(ctx)

        assert len(result.summaries) == 1
        assert result.summaries_json
        parsed = json.loads(result.summaries_json)
        assert len(parsed) == 1
        mock_prep.assert_awaited_once()
        mock_loop.assert_awaited_once()
        mock_output.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 4: Markdown Generation
# ---------------------------------------------------------------------------


class TestMarkdownGenerationStep:
    @pytest.mark.asyncio
    async def test_wires_generation_and_review(self, mock_settings, mock_slack, mock_docs):
        from ica.pipeline.steps import run_markdown_generation_step

        review_result = MagicMock()
        review_result.markdown = "# Newsletter"
        review_result.markdown_doc_id = "doc-md-abc"
        review_result.doc_url = "https://docs.google.com/doc-md-abc"
        review_result.model = "test-model"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.db.crud.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "ica.pipeline.markdown_generation.aggregate_feedback",
                return_value=None,
            ),
            patch(
                "ica.pipeline.markdown_generation.generate_with_validation",
                new_callable=AsyncMock,
                return_value="# Newsletter",
            ) as mock_gen,
            patch(
                "ica.pipeline.markdown_generation.run_markdown_review",
                new_callable=AsyncMock,
                return_value=review_result,
            ) as mock_review,
        ):
            ctx = PipelineContext(
                run_id="md1",
                formatted_theme={"THEME": "AI"},
                newsletter_id="NL-1",
            )
            result = await run_markdown_generation_step(ctx)

        assert result.markdown_doc_id == "doc-md-abc"
        mock_gen.assert_awaited_once()
        mock_review.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 5: HTML Generation
# ---------------------------------------------------------------------------


class TestHtmlGenerationStep:
    @pytest.mark.asyncio
    async def test_wires_html_generation(self, mock_settings, mock_slack, mock_docs):
        from ica.pipeline.steps import run_html_generation_step

        html_result = MagicMock()
        html_result.html = "<!DOCTYPE html>"
        html_result.html_doc_id = "doc-html-xyz"
        html_result.doc_url = "https://docs.google.com/doc-html-xyz"
        html_result.model = "test-model"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.html_generation.run_html_generation",
                new_callable=AsyncMock,
                return_value=html_result,
            ) as mock_gen,
        ):
            ctx = PipelineContext(
                run_id="html1",
                markdown_doc_id="doc-md-abc",
                newsletter_id="NL-1",
            )
            result = await run_html_generation_step(ctx)

        assert result.html_doc_id == "doc-html-xyz"
        mock_gen.assert_awaited_once()
        # Should have fetched markdown from docs
        mock_docs.get_content.assert_awaited_once_with("doc-md-abc")

    @pytest.mark.asyncio
    async def test_no_markdown_doc_id(self, mock_settings, mock_slack, mock_docs):
        from ica.pipeline.steps import run_html_generation_step

        html_result = MagicMock()
        html_result.html_doc_id = "doc-html-empty"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.html_generation.run_html_generation",
                new_callable=AsyncMock,
                return_value=html_result,
            ),
        ):
            ctx = PipelineContext(run_id="html2")
            result = await run_html_generation_step(ctx)

        assert result.html_doc_id == "doc-html-empty"
        mock_docs.get_content.assert_not_awaited()


# ---------------------------------------------------------------------------
# Step 6b: Email Subject
# ---------------------------------------------------------------------------


class TestEmailSubjectStep:
    @pytest.mark.asyncio
    async def test_wires_email_subject(self, mock_settings, mock_slack, mock_docs):
        from ica.pipeline.steps import run_email_subject_step

        email_result = MagicMock()
        email_result.selected_subject = "AI Revolution: What It Means"
        email_result.review_text = "Great newsletter..."
        email_result.doc_id = "doc-email-123"
        email_result.doc_url = "https://docs.google.com/doc-email-123"
        email_result.model = "test-model"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.email_subject.run_email_subject_generation",
                new_callable=AsyncMock,
                return_value=email_result,
            ) as mock_gen,
        ):
            ctx = PipelineContext(
                run_id="email1",
                html_doc_id="doc-html-abc",
                newsletter_id="NL-1",
            )
            result = await run_email_subject_step(ctx)

        assert result.extra["email_subject"] == "AI Revolution: What It Means"
        assert result.extra["email_review"] == "Great newsletter..."
        assert result.extra["email_doc_id"] == "doc-email-123"
        mock_gen.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 6c: Social Media
# ---------------------------------------------------------------------------


class TestSocialMediaStep:
    @pytest.mark.asyncio
    async def test_wires_social_media(self, mock_settings, mock_slack, mock_docs):
        from ica.pipeline.steps import run_social_media_step

        social_result = MagicMock()
        social_result.doc_id = "doc-social-123"
        social_result.doc_url = "https://docs.google.com/doc-social-123"
        social_result.final_content = "Post content"
        social_result.model = "test-model"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch(
                "ica.pipeline.social_media.run_social_media_generation",
                new_callable=AsyncMock,
                return_value=social_result,
            ) as mock_gen,
        ):
            ctx = PipelineContext(
                run_id="social1",
                html_doc_id="doc-html-abc",
                formatted_theme={"THEME": "AI"},
            )
            result = await run_social_media_step(ctx)

        assert result.extra["social_media_doc_id"] == "doc-social-123"
        mock_gen.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 6d: LinkedIn Carousel
# ---------------------------------------------------------------------------


class TestLinkedInCarouselStep:
    @pytest.mark.asyncio
    async def test_wires_linkedin_carousel(self, mock_settings, mock_slack, mock_docs):
        from ica.pipeline.steps import run_linkedin_carousel_step

        carousel_result = MagicMock()
        carousel_result.doc_id = "doc-carousel-123"
        carousel_result.doc_url = "https://docs.google.com/doc-carousel-123"
        carousel_result.final_content = "Carousel content"
        carousel_result.model = "test-model"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch(
                "ica.pipeline.linkedin_carousel.run_linkedin_carousel_generation",
                new_callable=AsyncMock,
                return_value=carousel_result,
            ) as mock_gen,
        ):
            ctx = PipelineContext(
                run_id="lin1",
                html_doc_id="doc-html-abc",
                formatted_theme={"THEME": "AI"},
            )
            result = await run_linkedin_carousel_step(ctx)

        assert result.extra["linkedin_carousel_doc_id"] == "doc-carousel-123"
        mock_gen.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 3: Theme Generation (most complex — composes generation + selection)
# ---------------------------------------------------------------------------


class TestThemeGenerationStep:
    @pytest.mark.asyncio
    async def test_approve_first_theme(self, mock_settings, mock_slack):
        """Approval on first attempt: generate -> select -> approve."""
        from ica.pipeline.theme_generation import GeneratedTheme, ThemeGenerationResult
        from ica.pipeline.theme_selection import (
            APPROVAL_FIELD_LABEL,
            APPROVE_OPTION,
            FEEDBACK_TEXTAREA_LABEL,
            SELECTION_FIELD_LABEL,
            THEME_OPTION_PREFIX,
        )
        from ica.pipeline.steps import run_theme_generation_step
        from ica.utils.marker_parser import FormattedTheme

        formatted = FormattedTheme(theme="AI Future")
        theme = GeneratedTheme(
            theme_name="AI Future",
            theme_description="About AI",
            theme_body="%FA_TITLE: Test\n%FA_URL: https://a.com",
            formatted_theme=formatted,
        )
        gen_result = ThemeGenerationResult(
            themes=[theme],
            recommendation="Use Theme 1",
            raw_llm_output="raw output",
            model="test-model",
        )

        # Selection form: select theme 1
        selection_response = {
            SELECTION_FIELD_LABEL: f"{THEME_OPTION_PREFIX}AI Future",
            FEEDBACK_TEXTAREA_LABEL: "",
        }
        # Approval form: approve
        approval_response = {
            APPROVAL_FIELD_LABEL: APPROVE_OPTION,
            FEEDBACK_TEXTAREA_LABEL: "",
        }

        mock_slack.send_and_wait_form = AsyncMock(
            side_effect=[selection_response, approval_response]
        )

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.theme_generation.generate_themes",
                new_callable=AsyncMock,
                return_value=gen_result,
            ),
            patch(
                "ica.utils.marker_parser.parse_markers",
                return_value=formatted,
            ),
            patch(
                "ica.pipeline.theme_selection.run_freshness_check",
                new_callable=AsyncMock,
                return_value="Looks fresh!",
            ),
            patch(
                "ica.pipeline.theme_selection.save_approved_theme",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            ctx = PipelineContext(
                run_id="theme1",
                summaries_json='[{"Title": "A"}]',
                newsletter_id="NL-1",
            )
            result = await run_theme_generation_step(ctx)

        assert result.theme_name == "AI Future"
        assert result.theme_body == theme.theme_body
        assert result.formatted_theme  # Not empty
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_feedback_then_approve(self, mock_settings, mock_slack):
        """Feedback on selection form -> regenerate -> then approve."""
        from ica.pipeline.theme_generation import GeneratedTheme, ThemeGenerationResult
        from ica.pipeline.theme_selection import (
            APPROVAL_FIELD_LABEL,
            APPROVE_OPTION,
            FEEDBACK_OPTION,
            FEEDBACK_TEXTAREA_LABEL,
            SELECTION_FIELD_LABEL,
            THEME_OPTION_PREFIX,
        )
        from ica.pipeline.steps import run_theme_generation_step
        from ica.utils.marker_parser import FormattedTheme

        formatted = FormattedTheme(theme="AI Future")
        theme = GeneratedTheme(
            theme_name="AI Future",
            theme_description="About AI",
            theme_body="%FA_TITLE: Test",
            formatted_theme=formatted,
        )
        gen_result = ThemeGenerationResult(
            themes=[theme],
            recommendation="Use Theme 1",
            raw_llm_output="raw",
            model="test",
        )

        call_count = 0

        async def side_effect_form(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First: feedback selection
                return {
                    SELECTION_FIELD_LABEL: FEEDBACK_OPTION,
                    FEEDBACK_TEXTAREA_LABEL: "Make it better",
                }
            if call_count == 2:
                # Second (after regeneration): select theme
                return {
                    SELECTION_FIELD_LABEL: f"{THEME_OPTION_PREFIX}AI Future",
                    FEEDBACK_TEXTAREA_LABEL: "",
                }
            # Third: approve
            return {
                APPROVAL_FIELD_LABEL: APPROVE_OPTION,
                FEEDBACK_TEXTAREA_LABEL: "",
            }

        mock_slack.send_and_wait_form = AsyncMock(side_effect=side_effect_form)

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.theme_generation.generate_themes",
                new_callable=AsyncMock,
                return_value=gen_result,
            ) as mock_gen,
            patch(
                "ica.pipeline.theme_selection.extract_learning_data",
                new_callable=AsyncMock,
                return_value="learning note",
            ),
            patch(
                "ica.pipeline.theme_selection.store_theme_feedback",
                new_callable=AsyncMock,
            ),
            patch(
                "ica.utils.marker_parser.parse_markers",
                return_value=formatted,
            ),
            patch(
                "ica.pipeline.theme_selection.run_freshness_check",
                new_callable=AsyncMock,
                return_value="Fresh!",
            ),
            patch(
                "ica.pipeline.theme_selection.save_approved_theme",
                new_callable=AsyncMock,
            ),
        ):
            ctx = PipelineContext(
                run_id="theme2",
                summaries_json="[]",
                newsletter_id="NL-1",
            )
            result = await run_theme_generation_step(ctx)

        assert result.theme_name == "AI Future"
        # generate_themes called twice (initial + after feedback)
        assert mock_gen.await_count == 2


# ---------------------------------------------------------------------------
# build_default_steps integration
# ---------------------------------------------------------------------------


class TestBuildDefaultStepsIntegration:
    def test_all_steps_are_async_functions(self):
        """Every step returned by build_default_steps is an async function."""
        import asyncio

        from ica.pipeline.orchestrator import build_default_steps

        seq, par = build_default_steps()
        for name, fn in seq + par:
            assert asyncio.iscoroutinefunction(fn), f"{name} is not async"

    def test_step_names_match_enum(self):
        from ica.pipeline.orchestrator import StepName, build_default_steps

        seq, par = build_default_steps()
        all_names = {name for name, _ in seq + par}
        enum_names = {s.value for s in StepName}
        assert all_names == enum_names

    def test_sequential_before_parallel(self):
        """Sequential steps are curation->summarization->theme->markdown->html."""
        from ica.pipeline.orchestrator import StepName, build_default_steps

        seq, par = build_default_steps()
        seq_names = [n for n, _ in seq]
        assert seq_names == [
            StepName.CURATION,
            StepName.SUMMARIZATION,
            StepName.THEME_GENERATION,
            StepName.MARKDOWN_GENERATION,
            StepName.HTML_GENERATION,
        ]


# ---------------------------------------------------------------------------
# Service factory helpers
# ---------------------------------------------------------------------------


class TestServiceFactories:
    def test_get_settings_delegates(self):
        """_get_settings calls config.settings.get_settings."""
        with patch("ica.config.settings.get_settings") as mock:
            mock.return_value = FakeSettings()
            from ica.pipeline.steps import _get_settings

            result = _get_settings()
            assert result.slack_bot_token == "xoxb-fake"

    def test_make_slack_creates_service(self, mock_settings):
        """_make_slack creates a SlackService with settings values."""
        with patch("ica.services.slack.SlackService") as MockSlack:
            from ica.pipeline.steps import _make_slack

            _make_slack()
            MockSlack.assert_called_once_with(
                token="xoxb-fake",
                channel="C-TEST",
            )

    def test_make_sheets_creates_service(self, mock_settings):
        """_make_sheets creates a GoogleSheetsService with credentials path."""
        with patch("ica.services.google_sheets.GoogleSheetsService") as MockSheets:
            from ica.pipeline.steps import _make_sheets

            _make_sheets()
            MockSheets.assert_called_once_with(
                credentials_path="/tmp/sheets.json",
            )

    def test_make_docs_creates_service(self, mock_settings):
        """_make_docs creates a GoogleDocsService with credentials path."""
        with patch("ica.services.google_docs.GoogleDocsService") as MockDocs:
            from ica.pipeline.steps import _make_docs

            _make_docs()
            MockDocs.assert_called_once_with(
                credentials_path="/tmp/docs.json",
            )

    def test_make_http_creates_service(self):
        """_make_http creates a WebFetcherService."""
        with patch("ica.services.web_fetcher.WebFetcherService") as MockHttp:
            from ica.pipeline.steps import _make_http

            _make_http()
            MockHttp.assert_called_once()


# ---------------------------------------------------------------------------
# Context propagation
# ---------------------------------------------------------------------------


class TestContextPropagation:
    @pytest.mark.asyncio
    async def test_curation_converts_articles_to_dicts(
        self, mock_settings, mock_slack,
    ):
        """Approved articles (dataclasses) are serialized to dicts in context."""
        from ica.pipeline.article_curation import ApprovalResult, ApprovedArticle
        from ica.pipeline.steps import run_curation_step

        approved = [
            ApprovedArticle(
                url="https://a.com",
                title="A",
                publish_date="02/23/2026",
                origin="test",
                approved=True,
                newsletter_id="NL-99",
                industry_news=False,
            ),
        ]
        approval_result = ApprovalResult(articles=approved, validation_attempts=1)

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_sheets", return_value=AsyncMock()),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.article_curation.prepare_curation_data",
                new_callable=AsyncMock,
            ),
            patch(
                "ica.pipeline.article_curation.run_approval_flow",
                new_callable=AsyncMock,
                return_value=approval_result,
            ),
        ):
            ctx = PipelineContext(run_id="prop1")
            result = await run_curation_step(ctx)

        assert result.newsletter_id == "NL-99"
        assert isinstance(result.articles[0], dict)
        assert result.articles[0]["newsletter_id"] == "NL-99"

    @pytest.mark.asyncio
    async def test_summarization_produces_valid_json(
        self, mock_settings, mock_slack,
    ):
        """summaries_json is valid JSON matching the articles list."""
        from ica.pipeline.steps import run_summarization_step

        output = MagicMock()
        output.articles = [{"URL": "https://a.com", "Title": "A"}]
        output.text = "text"
        output.model = "m"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_sheets", return_value=AsyncMock()),
            patch("ica.pipeline.steps._make_http", return_value=AsyncMock()),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.summarization.prepare_summarization_data",
                new_callable=AsyncMock,
                return_value=MagicMock(articles=[], model="m"),
            ),
            patch(
                "ica.pipeline.summarization.summarize_articles",
                new_callable=AsyncMock,
                return_value=MagicMock(summaries=[], model="m"),
            ),
            patch(
                "ica.pipeline.summarization.run_summarization_output",
                new_callable=AsyncMock,
                return_value=output,
            ),
        ):
            ctx = PipelineContext(run_id="prop2", newsletter_id="NL-1")
            result = await run_summarization_step(ctx)

        parsed = json.loads(result.summaries_json)
        assert parsed == [{"URL": "https://a.com", "Title": "A"}]

    @pytest.mark.asyncio
    async def test_html_step_uses_extra_newsletter_date(
        self, mock_settings, mock_slack, mock_docs,
    ):
        """HTML step reads newsletter_date from ctx.extra if available."""
        from ica.pipeline.steps import run_html_generation_step

        html_result = MagicMock()
        html_result.html_doc_id = "doc-html-dated"

        with (
            patch("ica.pipeline.steps._make_slack", return_value=mock_slack),
            patch("ica.pipeline.steps._make_docs", return_value=mock_docs),
            patch("ica.pipeline.steps._session", return_value=_fake_session_ctx()),
            patch(
                "ica.pipeline.html_generation.run_html_generation",
                new_callable=AsyncMock,
                return_value=html_result,
            ) as mock_gen,
        ):
            ctx = PipelineContext(
                run_id="html-date",
                markdown_doc_id="doc-md",
                extra={"newsletter_date": "03/01/2026"},
            )
            result = await run_html_generation_step(ctx)

        # The newsletter_date should have been passed to run_html_generation
        call_args = mock_gen.call_args
        assert call_args[0][2] == "03/01/2026"
