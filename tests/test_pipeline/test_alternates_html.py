"""Tests for is2news.pipeline.alternates_html — unused article filtering."""

import pytest

from ica.pipeline.alternates_html import (
    FilterResult,
    extract_urls_from_theme,
    filter_unused_articles,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

THEME_FIXTURE: dict = {
    "THEME": "AI Agents Transform Small Business Operations",
    "FEATURED ARTICLE": {
        "Title": "How AI Agents Are Reshaping the Workplace",
        "Source": "TechCrunch",
        "URL": "https://techcrunch.com/ai-agents-workplace",
        "Category": "AI Implementation",
        "Why Featured": "Comprehensive overview of AI agent adoption trends",
    },
    "MAIN ARTICLE 1": {
        "Title": "Small Businesses Embrace AI Tools",
        "Source": "Forbes",
        "URL": "https://forbes.com/small-biz-ai",
        "Category": "SMB Technology",
    },
    "MAIN ARTICLE 2": {
        "Title": "The Rise of Autonomous AI Systems",
        "Source": "Wired",
        "URL": "https://wired.com/autonomous-ai",
        "Category": "AI Trends",
    },
    "QUICK HIT 1": {
        "Title": "OpenAI Launches New Agent Framework",
        "Source": "The Verge",
        "URL": "https://theverge.com/openai-agents",
        "Category": "Product Launch",
    },
    "QUICK HIT 2": {
        "Title": "Google Bard Gets Enterprise Features",
        "Source": "CNBC",
        "URL": "https://cnbc.com/google-bard-enterprise",
        "Category": "Product Update",
    },
    "QUICK HIT 3": {
        "Title": "AI Regulation Bill Advances",
        "Source": "Reuters",
        "URL": "https://reuters.com/ai-regulation",
        "Category": "Policy",
    },
    "INDUSTRY DEVELOPMENT 1": {
        "Title": "Microsoft Copilot Adoption Surges",
        "Source": "Bloomberg",
        "URL": "https://bloomberg.com/copilot-surge",
        "Major AI Player": "Microsoft",
    },
    "INDUSTRY DEVELOPMENT 2": {
        "Title": "Anthropic Raises $2B Series C",
        "Source": "WSJ",
        "URL": "https://wsj.com/anthropic-funding",
        "Major AI Player": "Anthropic",
    },
    "REQUIREMENTS VERIFIED": {
        "2-2-2 Distribution": "Yes",
        "Source mix": "8 unique sources",
        "Technical complexity": "Balanced",
        "Major AI player coverage": "2 players covered",
    },
}

SUMMARIES_FIXTURE: list[dict] = [
    # --- Articles IN the theme (should be filtered OUT of unused) ---
    {
        "URL": "https://techcrunch.com/ai-agents-workplace",
        "Title": "How AI Agents Are Reshaping the Workplace",
        "Summary": "AI agents are transforming how businesses operate.",
        "BusinessRelevance": "Critical for SMB planning.",
        "order": 1,
        "newsletter_id": "2026-02-22",
        "industry_news": False,
    },
    {
        "URL": "https://forbes.com/small-biz-ai",
        "Title": "Small Businesses Embrace AI Tools",
        "Summary": "SMBs are adopting AI at record rates.",
        "BusinessRelevance": "Direct impact on target audience.",
        "order": 2,
        "newsletter_id": "2026-02-22",
        "industry_news": False,
    },
    {
        "URL": "https://bloomberg.com/copilot-surge",
        "Title": "Microsoft Copilot Adoption Surges",
        "Summary": "Enterprise copilot usage grows 300%.",
        "BusinessRelevance": "Signals mainstream AI adoption.",
        "order": 3,
        "newsletter_id": "2026-02-22",
        "industry_news": True,
    },
    # --- Articles NOT in the theme (should appear in unused) ---
    {
        "URL": "https://arstechnica.com/ai-startups",
        "Title": "AI Startups See Record Funding",
        "Summary": "Venture capital flowing into AI space.",
        "BusinessRelevance": "Opportunity indicators for SMBs.",
        "order": 4,
        "newsletter_id": "2026-02-22",
        "industry_news": False,
    },
    {
        "URL": "https://nytimes.com/ai-education",
        "Title": "AI in Education Reaches Tipping Point",
        "Summary": "Schools adopt AI tools widely.",
        "BusinessRelevance": "Training implications for businesses.",
        "order": 5,
        "newsletter_id": "2026-02-22",
        "industry_news": False,
    },
]


# ---------------------------------------------------------------------------
# extract_urls_from_theme
# ---------------------------------------------------------------------------


class TestExtractUrlsFromTheme:
    def test_extracts_all_article_urls(self):
        urls = extract_urls_from_theme(THEME_FIXTURE)
        assert len(urls) == 8
        assert "https://techcrunch.com/ai-agents-workplace" in urls
        assert "https://forbes.com/small-biz-ai" in urls
        assert "https://wired.com/autonomous-ai" in urls
        assert "https://theverge.com/openai-agents" in urls
        assert "https://cnbc.com/google-bard-enterprise" in urls
        assert "https://reuters.com/ai-regulation" in urls
        assert "https://bloomberg.com/copilot-surge" in urls
        assert "https://wsj.com/anthropic-funding" in urls

    def test_ignores_non_url_keys(self):
        urls = extract_urls_from_theme(THEME_FIXTURE)
        # "THEME", "Title", "Source", etc. should not appear
        assert "AI Agents Transform Small Business Operations" not in urls
        assert "TechCrunch" not in urls

    def test_empty_theme(self):
        assert extract_urls_from_theme({}) == set()

    def test_case_insensitive_key_matching(self):
        theme = {
            "article": {"url": "https://a.com", "Url": "https://b.com", "URL": "https://c.com"}
        }
        urls = extract_urls_from_theme(theme)
        assert urls == {"https://a.com", "https://b.com", "https://c.com"}

    def test_strips_whitespace(self):
        theme = {"article": {"URL": "  https://example.com  "}}
        urls = extract_urls_from_theme(theme)
        assert urls == {"https://example.com"}

    def test_skips_empty_url_values(self):
        theme = {"article": {"URL": ""}, "other": {"URL": "   "}}
        urls = extract_urls_from_theme(theme)
        assert urls == set()

    def test_handles_nested_lists(self):
        theme = {
            "articles": [
                {"URL": "https://a.com"},
                {"URL": "https://b.com"},
            ]
        }
        urls = extract_urls_from_theme(theme)
        assert urls == {"https://a.com", "https://b.com"}

    def test_handles_deeply_nested_structures(self):
        theme = {"level1": {"level2": {"level3": {"URL": "https://deep.com"}}}}
        urls = extract_urls_from_theme(theme)
        assert urls == {"https://deep.com"}

    def test_ignores_non_string_url_values(self):
        theme = {"article": {"URL": 12345}, "other": {"URL": None}}
        urls = extract_urls_from_theme(theme)
        assert urls == set()


# ---------------------------------------------------------------------------
# filter_unused_articles
# ---------------------------------------------------------------------------


class TestFilterUnusedArticles:
    def test_returns_filter_result(self):
        result = filter_unused_articles(THEME_FIXTURE, SUMMARIES_FIXTURE)
        assert isinstance(result, FilterResult)

    def test_identifies_unused_articles(self):
        result = filter_unused_articles(THEME_FIXTURE, SUMMARIES_FIXTURE)
        unused_urls = [s["URL"] for s in result.unused_summaries]
        assert "https://arstechnica.com/ai-startups" in unused_urls
        assert "https://nytimes.com/ai-education" in unused_urls
        assert len(result.unused_summaries) == 2

    def test_excludes_used_articles(self):
        result = filter_unused_articles(THEME_FIXTURE, SUMMARIES_FIXTURE)
        unused_urls = {s["URL"] for s in result.unused_summaries}
        # These are in the theme and should NOT be in unused
        assert "https://techcrunch.com/ai-agents-workplace" not in unused_urls
        assert "https://forbes.com/small-biz-ai" not in unused_urls
        assert "https://bloomberg.com/copilot-surge" not in unused_urls

    def test_preserves_formatted_theme(self):
        result = filter_unused_articles(THEME_FIXTURE, SUMMARIES_FIXTURE)
        assert result.formatted_theme is THEME_FIXTURE

    def test_urls_in_theme_sorted(self):
        result = filter_unused_articles(THEME_FIXTURE, SUMMARIES_FIXTURE)
        assert result.urls_in_theme == sorted(result.urls_in_theme)
        assert len(result.urls_in_theme) == 8

    def test_all_summaries_used(self):
        """When every summary URL is in the theme, unused should be empty."""
        summaries = [
            {"URL": "https://techcrunch.com/ai-agents-workplace", "Title": "A"},
            {"URL": "https://forbes.com/small-biz-ai", "Title": "B"},
        ]
        result = filter_unused_articles(THEME_FIXTURE, summaries)
        assert result.unused_summaries == []

    def test_no_summaries_used(self):
        """When no summary URLs match the theme, all should be unused."""
        summaries = [
            {"URL": "https://unique1.com", "Title": "X"},
            {"URL": "https://unique2.com", "Title": "Y"},
        ]
        result = filter_unused_articles(THEME_FIXTURE, summaries)
        assert len(result.unused_summaries) == 2

    def test_empty_summaries(self):
        result = filter_unused_articles(THEME_FIXTURE, [])
        assert result.unused_summaries == []
        assert len(result.urls_in_theme) == 8

    def test_empty_theme(self):
        summaries = [{"URL": "https://example.com", "Title": "Test"}]
        result = filter_unused_articles({}, summaries)
        assert result.unused_summaries == summaries
        assert result.urls_in_theme == []

    def test_url_whitespace_normalization(self):
        """URLs with leading/trailing whitespace should still match."""
        theme = {"article": {"URL": "https://example.com"}}
        summaries = [{"URL": "  https://example.com  ", "Title": "Test"}]
        result = filter_unused_articles(theme, summaries)
        assert result.unused_summaries == []

    def test_skips_summaries_without_url(self):
        """Summaries missing a URL key are excluded from unused."""
        summaries = [
            {"Title": "No URL article"},
            {"URL": "https://valid.com", "Title": "Has URL"},
        ]
        result = filter_unused_articles({}, summaries)
        unused_urls = [s["URL"] for s in result.unused_summaries]
        assert unused_urls == ["https://valid.com"]

    def test_skips_summaries_with_non_string_url(self):
        summaries = [
            {"URL": None, "Title": "Null URL"},
            {"URL": 123, "Title": "Int URL"},
            {"URL": "https://valid.com", "Title": "Valid"},
        ]
        result = filter_unused_articles({}, summaries)
        assert len(result.unused_summaries) == 1
        assert result.unused_summaries[0]["URL"] == "https://valid.com"

    def test_preserves_full_summary_data(self):
        """Unused summaries retain all their original fields."""
        result = filter_unused_articles(THEME_FIXTURE, SUMMARIES_FIXTURE)
        for s in result.unused_summaries:
            assert "URL" in s
            assert "Title" in s
            assert "Summary" in s
            assert "BusinessRelevance" in s

    def test_type_error_for_non_dict_theme(self):
        with pytest.raises(TypeError, match="formatted_theme must be a dict"):
            filter_unused_articles("not a dict", [])

    def test_type_error_for_non_list_summaries(self):
        with pytest.raises(TypeError, match="summaries must be a list"):
            filter_unused_articles({}, "not a list")
