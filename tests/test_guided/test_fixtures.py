"""Tests for ica.guided.fixtures — automated test data provisioning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ica.guided.fixtures import (
    FixtureProvider,
    build_articles,
    build_formatted_theme,
    build_summaries,
    build_theme_body,
)
from ica.pipeline.orchestrator import StepName
from ica.utils.marker_parser import FormattedTheme, parse_markers

# ---------------------------------------------------------------------------
# Article fixtures
# ---------------------------------------------------------------------------


class TestBuildArticles:
    """Tests for build_articles()."""

    def test_returns_correct_count(self) -> None:
        articles = build_articles(seed=42, count=10)
        assert len(articles) == 10

    def test_custom_count(self) -> None:
        articles = build_articles(seed=42, count=5)
        assert len(articles) == 5

    def test_deterministic_with_same_seed(self) -> None:
        a = build_articles(seed=42, count=8)
        b = build_articles(seed=42, count=8)
        assert a == b

    def test_different_seed_produces_different_data(self) -> None:
        a = build_articles(seed=1)
        b = build_articles(seed=99)
        # URLs are based on seed hash, so they differ
        assert a[0]["url"] != b[0]["url"]

    def test_article_schema(self) -> None:
        articles = build_articles(seed=42, count=3)
        required_keys = {
            "url",
            "title",
            "publish_date",
            "origin",
            "approved",
            "newsletter_id",
            "industry_news",
        }
        for article in articles:
            assert set(article.keys()) == required_keys

    def test_urls_are_unique(self) -> None:
        articles = build_articles(seed=42, count=10)
        urls = [a["url"] for a in articles]
        assert len(urls) == len(set(urls))

    def test_all_approved(self) -> None:
        articles = build_articles(seed=42, count=5)
        assert all(a["approved"] is True for a in articles)

    def test_shared_newsletter_id(self) -> None:
        articles = build_articles(seed=42, count=5)
        ids = {a["newsletter_id"] for a in articles}
        assert len(ids) == 1

    def test_newsletter_id_is_deterministic(self) -> None:
        a = build_articles(seed=42)
        b = build_articles(seed=42)
        assert a[0]["newsletter_id"] == b[0]["newsletter_id"]

    def test_industry_news_on_last_two(self) -> None:
        articles = build_articles(seed=42, count=10)
        assert articles[-1]["industry_news"] is True
        assert articles[-2]["industry_news"] is True
        assert articles[0]["industry_news"] is False

    def test_publish_date_format(self) -> None:
        articles = build_articles(seed=42, count=5)
        for a in articles:
            # MM/DD/YYYY format
            parts = a["publish_date"].split("/")
            assert len(parts) == 3
            assert len(parts[0]) == 2  # MM
            assert len(parts[1]) == 2  # DD
            assert len(parts[2]) == 4  # YYYY


# ---------------------------------------------------------------------------
# Summary fixtures
# ---------------------------------------------------------------------------


class TestBuildSummaries:
    """Tests for build_summaries()."""

    def test_matches_article_count(self) -> None:
        articles = build_articles(seed=42, count=8)
        summaries = build_summaries(articles, seed=42)
        assert len(summaries) == len(articles)

    def test_deterministic(self) -> None:
        articles = build_articles(seed=42, count=5)
        a = build_summaries(articles, seed=42)
        b = build_summaries(articles, seed=42)
        assert a == b

    def test_summary_schema_keys(self) -> None:
        articles = build_articles(seed=42, count=3)
        summaries = build_summaries(articles, seed=42)
        required_keys = {
            "URL",
            "Title",
            "Summary",
            "BusinessRelevance",
            "order",
            "newsletter_id",
            "industry_news",
        }
        for s in summaries:
            assert set(s.keys()) == required_keys

    def test_urls_match_articles(self) -> None:
        articles = build_articles(seed=42, count=5)
        summaries = build_summaries(articles, seed=42)
        for article, summary in zip(articles, summaries, strict=True):
            assert summary["URL"] == article["url"]
            assert summary["Title"] == article["title"]

    def test_order_is_1_based(self) -> None:
        articles = build_articles(seed=42, count=5)
        summaries = build_summaries(articles, seed=42)
        orders = [s["order"] for s in summaries]
        assert orders == [1, 2, 3, 4, 5]

    def test_serializable_to_json(self) -> None:
        articles = build_articles(seed=42, count=5)
        summaries = build_summaries(articles, seed=42)
        result = json.dumps(summaries, default=str)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert len(parsed) == 5


# ---------------------------------------------------------------------------
# Formatted theme fixtures
# ---------------------------------------------------------------------------


class TestBuildFormattedTheme:
    """Tests for build_formatted_theme()."""

    def test_returns_formatted_theme(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        assert isinstance(theme, FormattedTheme)

    def test_deterministic(self) -> None:
        articles = build_articles(seed=42, count=10)
        a = build_formatted_theme(articles, seed=42)
        b = build_formatted_theme(articles, seed=42)
        assert a == b

    def test_theme_title_set(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        assert theme.theme is not None
        assert "seed=42" in theme.theme

    def test_featured_article_populated(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        fa = theme.featured_article
        assert fa.title is not None
        assert fa.url is not None
        assert fa.origin is not None
        assert fa.why_featured is not None

    def test_main_articles_populated(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        for ma in [theme.main_article_1, theme.main_article_2]:
            assert ma.title is not None
            assert ma.url is not None
            assert ma.rationale is not None

    def test_quick_hits_populated(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        for qh in [theme.quick_hit_1, theme.quick_hit_2, theme.quick_hit_3]:
            assert qh.title is not None
            assert qh.url is not None

    def test_industry_developments_populated(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        for ind in [theme.industry_development_1, theme.industry_development_2]:
            assert ind.title is not None
            assert ind.url is not None
            assert ind.major_ai_player is not None

    def test_requirements_verified_populated(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        rv = theme.requirements_verified
        assert rv.distribution_achieved is not None
        assert rv.source_mix is not None

    def test_urls_reference_provided_articles(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        article_urls = {a["url"] for a in articles}
        # All theme URLs should come from the article pool
        for url in [
            theme.featured_article.url,
            theme.main_article_1.url,
            theme.main_article_2.url,
            theme.quick_hit_1.url,
            theme.quick_hit_2.url,
            theme.quick_hit_3.url,
            theme.industry_development_1.url,
            theme.industry_development_2.url,
        ]:
            assert url in article_urls


# ---------------------------------------------------------------------------
# Theme body rendering + round-trip
# ---------------------------------------------------------------------------


class TestBuildThemeBody:
    """Tests for build_theme_body() and round-trip parsing."""

    def test_contains_markers(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        body = build_theme_body(theme)
        assert "%FA_TITLE:" in body
        assert "%M1_TITLE:" in body
        assert "%Q1_TITLE:" in body
        assert "%I1_TITLE:" in body

    def test_contains_theme_line(self) -> None:
        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        body = build_theme_body(theme)
        assert body.startswith("THEME:")

    def test_round_trip_parse(self) -> None:
        """Rendering and re-parsing should produce equivalent data."""
        articles = build_articles(seed=42, count=10)
        original = build_formatted_theme(articles, seed=42)
        body = build_theme_body(original)
        reparsed = parse_markers(body)

        # Theme title
        assert reparsed.theme == original.theme

        # Featured article
        assert reparsed.featured_article.title == original.featured_article.title
        assert reparsed.featured_article.url == original.featured_article.url

        # Main articles
        assert reparsed.main_article_1.title == original.main_article_1.title
        assert reparsed.main_article_2.title == original.main_article_2.title

        # Quick hits
        assert reparsed.quick_hit_1.title == original.quick_hit_1.title
        assert reparsed.quick_hit_2.url == original.quick_hit_2.url

        # Industry developments
        assert (
            reparsed.industry_development_1.major_ai_player
            == original.industry_development_1.major_ai_player
        )


# ---------------------------------------------------------------------------
# FixtureProvider — single step provisioning
# ---------------------------------------------------------------------------


class TestFixtureProviderForStep:
    """Tests for FixtureProvider.for_step()."""

    def test_curation_step_has_no_prereqs(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.CURATION)
        # Curation needs nothing — context should be mostly empty
        assert ctx.run_id.startswith("fixture-")
        assert ctx.articles == []

    def test_summarization_step_has_articles(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.SUMMARIZATION)
        assert len(ctx.articles) == 10
        assert ctx.newsletter_id is not None

    def test_theme_generation_has_summaries(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.THEME_GENERATION)
        assert len(ctx.summaries) == 10
        assert ctx.summaries_json != ""
        assert ctx.newsletter_id is not None

    def test_markdown_generation_has_theme(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.MARKDOWN_GENERATION)
        assert ctx.formatted_theme != {}
        assert ctx.theme_name != ""
        assert ctx.theme_body != ""
        assert ctx.newsletter_id is not None

    def test_html_generation_has_markdown_doc_id(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.HTML_GENERATION)
        assert ctx.markdown_doc_id is not None
        assert ctx.markdown_doc_id.startswith("test-doc-md-")

    def test_alternates_html_has_theme_and_summaries(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.ALTERNATES_HTML)
        assert ctx.formatted_theme != {}
        assert len(ctx.summaries) > 0

    def test_email_subject_has_html_doc_id(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.EMAIL_SUBJECT)
        assert ctx.html_doc_id is not None
        assert ctx.html_doc_id.startswith("test-doc-html-")

    def test_social_media_has_theme_and_html(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.SOCIAL_MEDIA)
        assert ctx.html_doc_id is not None
        assert ctx.formatted_theme != {}

    def test_linkedin_carousel_has_theme_and_html(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.LINKEDIN_CAROUSEL)
        assert ctx.html_doc_id is not None
        assert ctx.formatted_theme != {}


class TestFixtureProviderDeterminism:
    """Tests that FixtureProvider produces deterministic output."""

    def test_same_seed_same_context(self) -> None:
        a = FixtureProvider(seed=42).for_step(StepName.MARKDOWN_GENERATION)
        b = FixtureProvider(seed=42).for_step(StepName.MARKDOWN_GENERATION)
        assert a.articles == b.articles
        assert a.summaries == b.summaries
        assert a.formatted_theme == b.formatted_theme
        assert a.theme_name == b.theme_name
        assert a.theme_body == b.theme_body
        assert a.newsletter_id == b.newsletter_id
        assert a.run_id == b.run_id

    def test_different_seed_different_context(self) -> None:
        a = FixtureProvider(seed=1).for_step(StepName.SUMMARIZATION)
        b = FixtureProvider(seed=99).for_step(StepName.SUMMARIZATION)
        assert a.articles[0]["url"] != b.articles[0]["url"]
        assert a.newsletter_id != b.newsletter_id

    def test_custom_article_count(self) -> None:
        provider = FixtureProvider(seed=42, article_count=5)
        ctx = provider.for_step(StepName.THEME_GENERATION)
        assert len(ctx.articles) == 5
        assert len(ctx.summaries) == 5

    def test_seed_property(self) -> None:
        provider = FixtureProvider(seed=123)
        assert provider.seed == 123


# ---------------------------------------------------------------------------
# FixtureProvider — full run provisioning
# ---------------------------------------------------------------------------


class TestFixtureProviderForFullRun:
    """Tests for FixtureProvider.for_full_run()."""

    def test_returns_minimal_context(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_full_run()
        assert ctx.run_id.startswith("fixture-")
        assert ctx.articles == []
        assert ctx.summaries == []
        assert ctx.formatted_theme == {}

    def test_deterministic_run_id(self) -> None:
        a = FixtureProvider(seed=42).for_full_run()
        b = FixtureProvider(seed=42).for_full_run()
        assert a.run_id == b.run_id


# ---------------------------------------------------------------------------
# FixtureProvider — snapshot
# ---------------------------------------------------------------------------


class TestFixtureProviderSnapshot:
    """Tests for FixtureProvider.snapshot()."""

    def test_returns_dict(self) -> None:
        provider = FixtureProvider(seed=42)
        snap = provider.snapshot(StepName.THEME_GENERATION)
        assert isinstance(snap, dict)

    def test_json_serializable(self) -> None:
        provider = FixtureProvider(seed=42)
        snap = provider.snapshot(StepName.MARKDOWN_GENERATION)
        result = json.dumps(snap, default=str)
        assert isinstance(result, str)

    def test_round_trips_through_restore(self) -> None:
        from ica.guided.runner import restore_context

        provider = FixtureProvider(seed=42)
        snap = provider.snapshot(StepName.MARKDOWN_GENERATION)
        ctx = restore_context(snap)
        assert len(ctx.summaries) == 10
        assert ctx.theme_name != ""


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestFixtureCleanup:
    """Tests for cleanup and cleanup_all."""

    def test_cleanup_removes_fixture_files(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "runs"
        store_dir.mkdir()
        # Create fixture files
        (store_dir / "fixture-abc123.json").write_text("{}")
        (store_dir / "fixture-def456.json").write_text("{}")
        # Create a non-fixture file that should be preserved
        (store_dir / "real-run-789.json").write_text("{}")

        removed = FixtureProvider.cleanup(store_dir)
        assert removed == 2
        assert not (store_dir / "fixture-abc123.json").exists()
        assert not (store_dir / "fixture-def456.json").exists()
        assert (store_dir / "real-run-789.json").exists()

    def test_cleanup_nonexistent_dir(self, tmp_path: Path) -> None:
        removed = FixtureProvider.cleanup(tmp_path / "nonexistent")
        assert removed == 0

    def test_cleanup_all_removes_directory(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "runs"
        store_dir.mkdir()
        (store_dir / "anything.json").write_text("{}")

        result = FixtureProvider.cleanup_all(store_dir)
        assert result is True
        assert not store_dir.exists()

    def test_cleanup_all_nonexistent(self, tmp_path: Path) -> None:
        result = FixtureProvider.cleanup_all(tmp_path / "nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# Schema validation — ensure generated data matches pipeline expectations
# ---------------------------------------------------------------------------


class TestSchemaValidity:
    """Verify that generated fixture data matches the schemas expected by
    pipeline steps."""

    def _check_article_schema(self, article: dict[str, Any]) -> None:
        assert isinstance(article["url"], str)
        assert article["url"].startswith("https://")
        assert isinstance(article["title"], str)
        assert len(article["title"]) > 0
        assert isinstance(article["publish_date"], str)
        assert isinstance(article["origin"], str)
        assert article["approved"] is True
        assert isinstance(article["newsletter_id"], str)
        assert isinstance(article["industry_news"], bool)

    def _check_summary_schema(self, summary: dict[str, Any]) -> None:
        assert isinstance(summary["URL"], str)
        assert summary["URL"].startswith("https://")
        assert isinstance(summary["Title"], str)
        assert isinstance(summary["Summary"], str)
        assert len(summary["Summary"]) > 20  # meaningful text
        assert isinstance(summary["BusinessRelevance"], str)
        assert len(summary["BusinessRelevance"]) > 10
        assert isinstance(summary["order"], int)
        assert summary["order"] >= 1
        assert isinstance(summary["newsletter_id"], str)
        assert isinstance(summary["industry_news"], bool)

    def test_article_schema_validity(self) -> None:
        articles = build_articles(seed=42, count=10)
        for article in articles:
            self._check_article_schema(article)

    def test_summary_schema_validity(self) -> None:
        articles = build_articles(seed=42, count=10)
        summaries = build_summaries(articles, seed=42)
        for summary in summaries:
            self._check_summary_schema(summary)

    def test_formatted_theme_asdict_schema(self) -> None:
        """formatted_theme as dict should have the expected top-level keys."""
        from dataclasses import asdict

        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        d = asdict(theme)
        expected_keys = {
            "theme",
            "featured_article",
            "main_article_1",
            "main_article_2",
            "quick_hit_1",
            "quick_hit_2",
            "quick_hit_3",
            "industry_development_1",
            "industry_development_2",
            "requirements_verified",
        }
        assert set(d.keys()) == expected_keys

    def test_formatted_theme_article_slots_have_urls(self) -> None:
        from dataclasses import asdict

        articles = build_articles(seed=42, count=10)
        theme = build_formatted_theme(articles, seed=42)
        d = asdict(theme)

        # Every article slot should have a non-null URL
        article_slots = [
            "featured_article",
            "main_article_1",
            "main_article_2",
            "quick_hit_1",
            "quick_hit_2",
            "quick_hit_3",
            "industry_development_1",
            "industry_development_2",
        ]
        for slot_name in article_slots:
            slot = d[slot_name]
            assert slot["url"] is not None, f"{slot_name} missing url"
            assert slot["title"] is not None, f"{slot_name} missing title"

    def test_summaries_json_is_valid_json(self) -> None:
        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.THEME_GENERATION)
        parsed = json.loads(ctx.summaries_json)
        assert isinstance(parsed, list)
        assert len(parsed) == 10

    def test_full_pipeline_context_is_snapshot_safe(self) -> None:
        """A fully provisioned context should survive snapshot + restore."""
        from ica.guided.runner import restore_context, snapshot_context

        provider = FixtureProvider(seed=42)
        ctx = provider.for_step(StepName.LINKEDIN_CAROUSEL)
        snap = snapshot_context(ctx)
        restored = restore_context(snap)

        assert restored.run_id == ctx.run_id
        assert restored.newsletter_id == ctx.newsletter_id
        assert len(restored.articles) == len(ctx.articles)
        assert len(restored.summaries) == len(ctx.summaries)
        assert restored.formatted_theme == ctx.formatted_theme
        assert restored.theme_name == ctx.theme_name
        assert restored.html_doc_id == ctx.html_doc_id

    def test_all_steps_can_be_provisioned(self) -> None:
        """Every step name should be provisionable without error."""
        provider = FixtureProvider(seed=42)
        for step in StepName:
            ctx = provider.for_step(step)
            assert ctx.run_id.startswith("fixture-")
