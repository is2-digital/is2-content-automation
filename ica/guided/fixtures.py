"""Automated test data provisioning for guided pipeline runs.

Generates realistic, deterministic fixture data for each pipeline step so
operators can run individual steps or the full pipeline without manual data
setup.  Uses a seed value to make all generated data reproducible.

Usage::

    from ica.guided.fixtures import FixtureProvider

    provider = FixtureProvider(seed=42)

    # Provision for a single step (includes all prerequisite data)
    ctx = provider.for_step("theme_generation")

    # Provision for a full run (empty context — step 1 starts from scratch)
    ctx = provider.for_full_run()

    # Clean up persisted test-run state files
    FixtureProvider.cleanup(store_dir)
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ica.pipeline.orchestrator import PipelineContext, StepName
from ica.utils.marker_parser import (
    FeaturedArticle,
    FormattedTheme,
    IndustryDevelopment,
    MainArticle,
    QuickHit,
    RequirementsVerified,
)

# ---------------------------------------------------------------------------
# Seed-derived deterministic helpers
# ---------------------------------------------------------------------------

_ORIGINS = [
    "TechCrunch",
    "The Verge",
    "Ars Technica",
    "Wired",
    "MIT Technology Review",
    "VentureBeat",
    "ZDNet",
    "Forbes",
    "Bloomberg",
    "Reuters",
]

_ARTICLE_TITLES = [
    "How Small Businesses Are Using AI to Compete with Giants",
    "New AI Tools Make Customer Service Faster and Cheaper",
    "OpenAI Releases GPT-5 with Enhanced Reasoning Capabilities",
    "Google DeepMind Achieves Breakthrough in Protein Folding",
    "Microsoft Copilot Now Available for Small Business Plans",
    "AI-Powered Marketing Tools See 300% Adoption Growth",
    "Anthropic Introduces Claude for Enterprise Workflows",
    "Amazon Launches AI-Driven Supply Chain Optimization",
    "The Rise of No-Code AI Platforms for Non-Technical Users",
    "EU AI Act Implementation Timeline and Business Impact",
]

_CATEGORIES = [
    "AI Tools & Productivity",
    "AI Strategy",
    "Enterprise AI",
    "AI Research",
    "AI Policy & Regulation",
]

_SUMMARY_TEXTS = [
    (
        "Small businesses are increasingly adopting AI tools to level the playing "
        "field against larger competitors. New affordable platforms offer capabilities "
        "that were previously only available to enterprises with large budgets."
    ),
    (
        "Customer service departments are seeing dramatic improvements through AI "
        "chatbot integration. Response times have dropped by 60% while customer "
        "satisfaction scores have improved across the board."
    ),
    (
        "The latest generation of large language models brings significant improvements "
        "in reasoning and accuracy. Early benchmarks show reduced hallucination rates "
        "and better handling of complex multi-step tasks."
    ),
    (
        "A major breakthrough in computational biology demonstrates AI's potential "
        "to accelerate scientific discovery. The new model can predict protein "
        "structures with unprecedented accuracy."
    ),
    (
        "Productivity suites are integrating AI assistants directly into everyday "
        "workflows. Early adopters report significant time savings on routine "
        "document creation and data analysis tasks."
    ),
    (
        "Marketing automation platforms powered by AI are experiencing explosive "
        "growth. Businesses report improved targeting accuracy and higher ROI "
        "on advertising spend."
    ),
    (
        "Enterprise-grade AI assistants are becoming available for specialized "
        "business workflows. These tools offer enhanced security features and "
        "custom training capabilities."
    ),
    (
        "Major retailers are using AI to optimize their supply chains, reducing "
        "waste and improving delivery times. The technology analyzes demand "
        "patterns to predict inventory needs."
    ),
    (
        "No-code AI platforms are democratizing access to machine learning "
        "capabilities. Business users can now build and deploy AI models "
        "without programming expertise."
    ),
    (
        "New AI regulations are creating compliance challenges for businesses "
        "operating across borders. Companies need to understand varying "
        "requirements in different jurisdictions."
    ),
]

_RELEVANCE_TEXTS = [
    (
        "Directly relevant to solopreneurs seeking affordable AI tools. "
        "Provides actionable guidance on tool selection."
    ),
    (
        "Highly relevant for SMB professionals managing customer-facing teams. "
        "Demonstrates measurable ROI from AI adoption."
    ),
    (
        "Important context for understanding the evolving AI landscape. "
        "Helps business leaders anticipate future capabilities."
    ),
    (
        "Shows AI impact beyond traditional business applications. "
        "Demonstrates breadth of AI transformation."
    ),
    (
        "Directly applicable to daily business operations. "
        "Most readers already use these productivity tools."
    ),
    (
        "Core topic for marketing professionals and small business owners. "
        "Offers concrete adoption strategies."
    ),
    (
        "Relevant for businesses evaluating enterprise AI solutions. "
        "Highlights key vendor developments."
    ),
    (
        "Valuable for businesses with physical supply chains. "
        "Shows practical AI applications beyond knowledge work."
    ),
    ("Empowering for non-technical business owners. Removes traditional barriers to AI adoption."),
    ("Critical for compliance-aware businesses. Helps leaders prepare for regulatory changes."),
]


def _seeded_hash(seed: int, label: str) -> str:
    """Produce a deterministic hex string from seed + label."""
    return hashlib.sha256(f"{seed}:{label}".encode()).hexdigest()


def _pick(items: list[str], seed: int, idx: int) -> str:
    """Deterministically select an item from a list."""
    return items[(seed + idx) % len(items)]


# ---------------------------------------------------------------------------
# Fixture data builders
# ---------------------------------------------------------------------------


def build_articles(seed: int, count: int = 10) -> list[dict[str, Any]]:
    """Generate a list of article dicts matching the curation step output schema.

    Keys: ``url``, ``title``, ``publish_date``, ``origin``, ``approved``,
    ``newsletter_id``, ``industry_news``.
    """
    newsletter_id = f"test-{_seeded_hash(seed, 'newsletter')[:8]}"
    articles: list[dict[str, Any]] = []
    for i in range(count):
        h = _seeded_hash(seed, f"article-{i}")
        articles.append(
            {
                "url": f"https://example.com/article/{h[:12]}",
                "title": _pick(_ARTICLE_TITLES, seed, i),
                "publish_date": f"02/{(i % 28) + 1:02d}/2026",
                "origin": _pick(_ORIGINS, seed, i),
                "approved": True,
                "newsletter_id": newsletter_id,
                "industry_news": i >= count - 2,  # last 2 are industry news
            }
        )
    return articles


def build_summaries(articles: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Generate summary dicts matching the summarization step output schema.

    Keys (Title-case per pipeline convention): ``URL``, ``Title``, ``Summary``,
    ``BusinessRelevance``, ``order``, ``newsletter_id``, ``industry_news``.
    """
    summaries: list[dict[str, Any]] = []
    for i, article in enumerate(articles):
        summaries.append(
            {
                "URL": article["url"],
                "Title": article["title"],
                "Summary": _pick(_SUMMARY_TEXTS, seed, i),
                "BusinessRelevance": _pick(_RELEVANCE_TEXTS, seed, i),
                "order": i + 1,
                "newsletter_id": article["newsletter_id"],
                "industry_news": article.get("industry_news", False),
            }
        )
    return summaries


def build_formatted_theme(articles: list[dict[str, Any]], seed: int) -> FormattedTheme:
    """Build a ``FormattedTheme`` that references the provided articles.

    Assigns articles to slots: featured (1), main (2), quick hits (3),
    industry developments (2).  Requires at least 8 articles.
    """
    # Ensure deterministic assignment by using seed-based offset
    offset = seed % max(len(articles) - 8, 1) if len(articles) > 8 else 0

    def _art(idx: int) -> dict[str, Any]:
        return articles[min(offset + idx, len(articles) - 1)]

    theme_title = f"AI Revolution in Small Business (seed={seed})"

    return FormattedTheme(
        theme=theme_title,
        featured_article=FeaturedArticle(
            title=_art(0)["title"],
            source=_art(0)["title"],
            origin=_art(0)["origin"],
            url=_art(0)["url"],
            category=_pick(_CATEGORIES, seed, 0),
            why_featured=(
                "This article highlights a transformative trend in AI adoption "
                "that directly affects our core audience of solopreneurs."
            ),
        ),
        main_article_1=MainArticle(
            title=_art(1)["title"],
            source=_art(1)["title"],
            origin=_art(1)["origin"],
            url=_art(1)["url"],
            category=_pick(_CATEGORIES, seed, 1),
            rationale="Provides actionable insights for SMB AI adoption.",
        ),
        main_article_2=MainArticle(
            title=_art(2)["title"],
            source=_art(2)["title"],
            origin=_art(2)["origin"],
            url=_art(2)["url"],
            category=_pick(_CATEGORIES, seed, 2),
            rationale="Demonstrates measurable business impact from AI tools.",
        ),
        quick_hit_1=QuickHit(
            title=_art(3)["title"],
            source=_art(3)["title"],
            origin=_art(3)["origin"],
            url=_art(3)["url"],
            category=_pick(_CATEGORIES, seed, 3),
        ),
        quick_hit_2=QuickHit(
            title=_art(4)["title"],
            source=_art(4)["title"],
            origin=_art(4)["origin"],
            url=_art(4)["url"],
            category=_pick(_CATEGORIES, seed, 4),
        ),
        quick_hit_3=QuickHit(
            title=_art(5)["title"],
            source=_art(5)["title"],
            origin=_art(5)["origin"],
            url=_art(5)["url"],
            category=_pick(_CATEGORIES, seed, 5),
        ),
        industry_development_1=IndustryDevelopment(
            title=_art(6)["title"],
            source=_art(6)["title"],
            origin=_art(6)["origin"],
            url=_art(6)["url"],
            major_ai_player="OpenAI",
        ),
        industry_development_2=IndustryDevelopment(
            title=_art(7)["title"],
            source=_art(7)["title"],
            origin=_art(7)["origin"],
            url=_art(7)["url"],
            major_ai_player="Google",
        ),
        requirements_verified=RequirementsVerified(
            distribution_achieved="Yes — 2 featured/main, 3 quick hits, 2 industry",
            source_mix="Balanced — 5+ unique sources used",
            technical_complexity="Appropriate — accessible to non-technical audience",
            major_ai_player_coverage="Covered — OpenAI, Google represented",
        ),
    )


def build_theme_body(theme: FormattedTheme) -> str:
    """Render a ``FormattedTheme`` back into ``%XX_`` marker text."""
    lines = [f"THEME: {theme.theme or 'Untitled'}"]
    lines.append("")

    fa = theme.featured_article
    lines.extend(
        [
            f"%FA_TITLE: {fa.title}",
            f"%FA_SOURCE: {fa.source}",
            f"%FA_ORIGIN: {fa.origin}",
            f"%FA_URL: {fa.url}",
            f"%FA_CATEGORY: {fa.category}",
            f"%FA_WHY FEATURED: {fa.why_featured}",
            "",
        ]
    )

    for idx, ma in [(1, theme.main_article_1), (2, theme.main_article_2)]:
        prefix = f"M{idx}"
        lines.extend(
            [
                f"%{prefix}_TITLE: {ma.title}",
                f"%{prefix}_SOURCE: {ma.source}",
                f"%{prefix}_ORIGIN: {ma.origin}",
                f"%{prefix}_URL: {ma.url}",
                f"%{prefix}_CATEGORY: {ma.category}",
                f"%{prefix}_RATIONALE: {ma.rationale}",
                "",
            ]
        )

    for idx, qh in [
        (1, theme.quick_hit_1),
        (2, theme.quick_hit_2),
        (3, theme.quick_hit_3),
    ]:
        prefix = f"Q{idx}"
        lines.extend(
            [
                f"%{prefix}_TITLE: {qh.title}",
                f"%{prefix}_SOURCE: {qh.source}",
                f"%{prefix}_ORIGIN: {qh.origin}",
                f"%{prefix}_URL: {qh.url}",
                f"%{prefix}_CATEGORY: {qh.category}",
                "",
            ]
        )

    for idx, ind in [
        (1, theme.industry_development_1),
        (2, theme.industry_development_2),
    ]:
        prefix = f"I{idx}"
        lines.extend(
            [
                f"%{prefix}_TITLE: {ind.title}",
                f"%{prefix}_SOURCE: {ind.source}",
                f"%{prefix}_ORIGIN: {ind.origin}",
                f"%{prefix}_URL: {ind.url}",
                f"%{prefix}_Major AI Player: {ind.major_ai_player}",
                "",
            ]
        )

    rv = theme.requirements_verified
    lines.extend(
        [
            f"%RV_2-2-2 Distribution Achieved:% {rv.distribution_achieved}",
            f"%RV_Source mix:% {rv.source_mix}",
            f"%RV_Technical complexity:% {rv.technical_complexity}",
            f"%RV_Major AI player coverage:% {rv.major_ai_player_coverage}",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step prerequisite map
# ---------------------------------------------------------------------------

# For each step, which prior context fields must be populated.
# Ordered so provisioning walks backwards to find all prerequisites.
_STEP_PREREQUISITES: dict[str, list[str]] = {
    StepName.CURATION: [],
    StepName.SUMMARIZATION: ["articles", "newsletter_id"],
    StepName.THEME_GENERATION: ["summaries_json", "summaries", "newsletter_id"],
    StepName.MARKDOWN_GENERATION: [
        "formatted_theme",
        "theme_name",
        "theme_body",
        "newsletter_id",
    ],
    StepName.HTML_GENERATION: ["markdown_doc_id", "newsletter_id"],
    StepName.ALTERNATES_HTML: ["formatted_theme", "summaries"],
    StepName.EMAIL_SUBJECT: ["html_doc_id", "newsletter_id"],
    StepName.SOCIAL_MEDIA: ["html_doc_id", "formatted_theme"],
    StepName.LINKEDIN_CAROUSEL: ["html_doc_id", "formatted_theme"],
}

# Ordered step sequence for walking prerequisites
_STEP_ORDER = [
    StepName.CURATION,
    StepName.SUMMARIZATION,
    StepName.THEME_GENERATION,
    StepName.MARKDOWN_GENERATION,
    StepName.HTML_GENERATION,
]


def _steps_before(step_name: str) -> list[str]:
    """Return the ordered list of steps that must complete before *step_name*."""
    try:
        idx = _STEP_ORDER.index(step_name)
        return list(_STEP_ORDER[:idx])
    except ValueError:
        # Parallel step — needs all sequential steps
        return list(_STEP_ORDER)


# ---------------------------------------------------------------------------
# FixtureProvider
# ---------------------------------------------------------------------------


class FixtureProvider:
    """Generates deterministic test data for guided pipeline runs.

    Args:
        seed: Integer seed for deterministic data generation.  Using the same
            seed always produces identical fixture data.
        article_count: Number of test articles to generate (default 10).
    """

    def __init__(self, seed: int = 42, *, article_count: int = 10) -> None:
        self._seed = seed
        self._article_count = article_count

    @property
    def seed(self) -> int:
        return self._seed

    def for_step(self, step_name: str) -> PipelineContext:
        """Provision a ``PipelineContext`` with all data required to run *step_name*.

        Walks backwards through the pipeline to populate all prerequisite
        fields so the step can execute without prior steps having run.

        Args:
            step_name: A :class:`StepName` value (e.g. ``"theme_generation"``).

        Returns:
            A fully provisioned ``PipelineContext``.
        """
        ctx = PipelineContext()
        ctx.run_id = f"fixture-{_seeded_hash(self._seed, 'run')[:8]}"

        # Determine which fields need populating
        needed_fields: set[str] = set()
        needed_fields.update(_STEP_PREREQUISITES.get(step_name, []))
        for prior_step in _steps_before(step_name):
            needed_fields.update(_STEP_PREREQUISITES.get(prior_step, []))

        # Populate fields
        if "articles" in needed_fields or "newsletter_id" in needed_fields:
            articles = build_articles(self._seed, self._article_count)
            ctx.articles = articles
            ctx.newsletter_id = articles[0]["newsletter_id"]

        if "summaries" in needed_fields or "summaries_json" in needed_fields:
            if not ctx.articles:
                ctx.articles = build_articles(self._seed, self._article_count)
                ctx.newsletter_id = ctx.articles[0]["newsletter_id"]
            summaries = build_summaries(ctx.articles, self._seed)
            ctx.summaries = summaries
            ctx.summaries_json = json.dumps(summaries, default=str)

        if "formatted_theme" in needed_fields or "theme_name" in needed_fields:
            if not ctx.articles:
                ctx.articles = build_articles(self._seed, self._article_count)
                ctx.newsletter_id = ctx.articles[0]["newsletter_id"]
            if not ctx.summaries:
                ctx.summaries = build_summaries(ctx.articles, self._seed)
                ctx.summaries_json = json.dumps(ctx.summaries, default=str)
            theme = build_formatted_theme(ctx.articles, self._seed)
            ctx.formatted_theme = asdict(theme)
            ctx.theme_name = theme.theme or ""
            ctx.theme_body = build_theme_body(theme)
            ctx.theme_summary = (
                "This edition explores how AI is reshaping small business "
                "operations across multiple industries."
            )

        if "markdown_doc_id" in needed_fields:
            ctx.markdown_doc_id = f"test-doc-md-{_seeded_hash(self._seed, 'md')[:16]}"

        if "html_doc_id" in needed_fields:
            ctx.html_doc_id = f"test-doc-html-{_seeded_hash(self._seed, 'html')[:16]}"

        return ctx

    def for_full_run(self) -> PipelineContext:
        """Provision a minimal ``PipelineContext`` for a full pipeline run.

        Returns a context with only the run_id set — step 1 (curation) starts
        from scratch using live services.
        """
        ctx = PipelineContext()
        ctx.run_id = f"fixture-{_seeded_hash(self._seed, 'run')[:8]}"
        return ctx

    def snapshot(self, step_name: str) -> dict[str, Any]:
        """Return the provisioned context as a JSON-safe dict.

        Useful for injecting into a persisted test-run state's
        ``context_snapshot`` field.
        """
        from ica.guided.runner import snapshot_context

        ctx = self.for_step(step_name)
        return snapshot_context(ctx)

    @staticmethod
    def cleanup(store_dir: Path | str = ".guided-runs") -> int:
        """Remove all fixture-generated test-run state files.

        Only deletes files whose run_id starts with ``fixture-`` to avoid
        removing real guided-run state.

        Args:
            store_dir: Directory containing ``.json`` state files.

        Returns:
            The number of files removed.
        """
        path = Path(store_dir)
        if not path.exists():
            return 0
        count = 0
        for f in path.glob("fixture-*.json"):
            f.unlink()
            count += 1
        return count

    @staticmethod
    def cleanup_all(store_dir: Path | str = ".guided-runs") -> bool:
        """Remove the entire guided-runs store directory.

        Args:
            store_dir: Directory to remove.

        Returns:
            ``True`` if the directory was removed, ``False`` if it didn't exist.
        """
        path = Path(store_dir)
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True
