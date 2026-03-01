"""Article Collection Pipeline — scheduled utility for article discovery.

Runs on two schedules:
- **Daily**: Brave Web Search with freshness filter, 3 keywords (10 results each)
- **Every 2 days**: Brave Web Search relevance ranking, 5 keywords (10 results each)

Flow: Brave Search queries → deduplication → date parsing →
LLM relevance assessment → DB upsert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Protocol

from ica.services.brave_search import BraveSearchClient
from ica.services.google_search import SearchResult
from ica.utils.date_parser import parse_relative_date

logger = logging.getLogger(__name__)

# Default keyword sets per PRD Section 1.3
DAILY_KEYWORDS: list[str] = [
    "Artificial General Intelligence",
    "Automation",
    "Artificial Intelligence",
]

EVERY_2_DAYS_KEYWORDS: list[str] = [
    "AI breakthrough",
    "AI latest",
    "AI tutorial",
    "AI case study",
    "AI research",
]


@dataclass(frozen=True)
class ArticleRecord:
    """A processed article ready for database insertion.

    Attributes:
        url: Article URL (primary key in DB).
        title: Article title.
        origin: Schedule label (``"daily"`` or ``"every_2_days"``).
        publish_date: Parsed publish date from search result metadata.
        excerpt: Search result snippet (from Brave Search description).
        relevance_status: LLM assessment result — ``'accepted'`` or ``'rejected'``.
        relevance_reason: Short LLM explanation of the accept/reject decision.
    """

    url: str
    title: str
    origin: str
    publish_date: date
    excerpt: str | None = None
    relevance_status: str | None = None
    relevance_reason: str | None = None


class ArticleRepository(Protocol):
    """Database interface for article persistence."""

    async def upsert_articles(self, articles: list[ArticleRecord]) -> int:
        """Insert or update articles in the articles table.

        Args:
            articles: List of article records to upsert.

        Returns:
            Number of rows affected.
        """
        ...


@dataclass
class CollectionResult:
    """Result of an article collection run.

    Attributes:
        raw_results: All search results before deduplication.
        deduplicated: Articles after URL deduplication.
        articles: Processed article records ready for/after DB insertion.
        rows_affected: Number of DB rows upserted.
        accepted_count: Articles accepted by relevance filter.
        rejected_count: Articles rejected by relevance filter.
    """

    raw_results: list[SearchResult] = field(default_factory=list)
    deduplicated: list[SearchResult] = field(default_factory=list)
    articles: list[ArticleRecord] = field(default_factory=list)
    rows_affected: int = 0
    accepted_count: int = 0
    rejected_count: int = 0


def deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    """Remove duplicate search results by URL, preserving insertion order.

    The first occurrence of each URL wins; subsequent duplicates are discarded.

    Args:
        results: Raw search results that may contain duplicate URLs.

    Returns:
        Deduplicated list with order preserved.
    """
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for r in results:
        url = r.url.strip()
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    return unique


def parse_articles(
    results: list[SearchResult],
    *,
    reference_date: date | None = None,
) -> list[ArticleRecord]:
    """Convert search results to article records with parsed dates.

    Args:
        results: Deduplicated search results.
        reference_date: Base date for relative date calculation (default: today).

    Returns:
        List of :class:`ArticleRecord` objects with parsed publish dates.
    """
    ref = reference_date or date.today()
    articles: list[ArticleRecord] = []
    for r in results:
        publish_date = parse_relative_date(r.date, reference=ref)
        articles.append(
            ArticleRecord(
                url=r.url.strip(),
                title=r.title.strip(),
                origin=r.origin,
                publish_date=publish_date,
                excerpt=r.excerpt or None,
            )
        )
    return articles


async def collect_articles(
    client: BraveSearchClient,
    repository: ArticleRepository,
    *,
    schedule: str = "daily",
    reference_date: date | None = None,
) -> CollectionResult:
    """Execute the full article collection pipeline.

    1. Query Brave Web Search for each keyword in the schedule's keyword set.
    2. Deduplicate results by URL.
    3. Parse dates into calendar dates.
    4. Run LLM relevance assessment on each article.
    5. Upsert all article records (accepted and rejected) into the database.

    Args:
        client: Configured :class:`BraveSearchClient`.
        repository: Database repository implementing :class:`ArticleRepository`.
        schedule: Either ``"daily"`` (sort by date, 3 keywords, 10 results)
            or ``"every_2_days"`` (relevance ranking, 5 keywords, 10 results).
        reference_date: Override for date calculations (testing).

    Returns:
        A :class:`CollectionResult` with the full pipeline state.

    Raises:
        ValueError: If *schedule* is not ``"daily"`` or ``"every_2_days"``.
    """
    from ica.pipeline.relevance_assessment import assess_articles

    if schedule == "daily":
        keywords = DAILY_KEYWORDS
        sort_by_date = True
        num = 10
    elif schedule == "every_2_days":
        keywords = EVERY_2_DAYS_KEYWORDS
        sort_by_date = False
        num = 10
    else:
        raise ValueError(f"schedule must be 'daily' or 'every_2_days', got {schedule!r}")

    # Step 1: Search
    raw_results = await client.search_keywords(
        keywords, num=num, sort_by_date=sort_by_date
    )

    # Step 2: Deduplicate
    deduplicated = deduplicate_results(raw_results)

    # Step 3: Parse dates
    articles = parse_articles(deduplicated, reference_date=reference_date)

    # Step 4: Relevance assessment
    assessment_input = [
        (a.url, a.title, a.excerpt or "") for a in articles
    ]
    relevance_results = await assess_articles(assessment_input)
    relevance_map = {r.url: r for r in relevance_results}

    articles = [
        replace(
            article,
            relevance_status=relevance_map[article.url].decision,
            relevance_reason=relevance_map[article.url].reason,
        )
        if article.url in relevance_map
        else article
        for article in articles
    ]

    accepted = sum(1 for a in articles if a.relevance_status == "accept")
    rejected = sum(1 for a in articles if a.relevance_status == "reject")

    # Step 5: Persist (both accepted and rejected)
    rows_affected = await repository.upsert_articles(articles)

    logger.info(
        "Collected %d articles, %d accepted, %d rejected by relevance filter",
        len(articles),
        accepted,
        rejected,
    )

    return CollectionResult(
        raw_results=raw_results,
        deduplicated=deduplicated,
        articles=articles,
        rows_affected=rows_affected,
        accepted_count=accepted,
        rejected_count=rejected,
    )
