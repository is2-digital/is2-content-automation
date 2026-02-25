"""Alternates HTML Generator — Step 6a of the newsletter pipeline.

Creates an A/B variant document using articles that were curated and
summarized but not selected for the main newsletter theme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FilterResult:
    """Result of filtering unused articles from the formatted theme."""

    formatted_theme: dict[str, Any]
    unused_summaries: list[dict[str, Any]]
    urls_in_theme: list[str]


def extract_urls_from_theme(theme: dict[str, Any]) -> set[str]:
    """Recursively extract all URL values from the formatted_theme object.

    Walks the nested dict/list structure and collects every value whose
    key (case-insensitive) is ``"url"``.

    Args:
        theme: The formatted_theme dict produced by theme generation (Step 3).

    Returns:
        A set of URL strings found in the theme.
    """
    urls: set[str] = set()
    _collect_urls(theme, urls)
    return urls


def _collect_urls(obj: Any, urls: set[str]) -> None:
    """Recursive helper that accumulates URL strings into *urls*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() == "url" and isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    urls.add(stripped)
            else:
                _collect_urls(value, urls)
    elif isinstance(obj, list):
        for item in obj:
            _collect_urls(item, urls)


def filter_unused_articles(
    formatted_theme: dict[str, Any],
    summaries: list[dict[str, Any]],
) -> FilterResult:
    """Identify curated articles that were **not** used in the main newsletter.

    Compares the URLs embedded in ``formatted_theme`` (selected articles)
    against the full ``summaries`` list (all curated articles) and returns
    the subset of summaries whose URLs do not appear in the theme.

    This is the first step of the Alternates HTML Generator (Step 6a).
    The unused summaries are then rendered into an alternative HTML document
    for A/B testing.

    Args:
        formatted_theme: Nested dict from theme generation containing keys
            like ``"FEATURED ARTICLE"``, ``"MAIN ARTICLE 1"``, etc., each
            with a ``"URL"`` field.
        summaries: List of article summary dicts, each containing at minimum
            a ``"URL"`` key plus ``"Title"``, ``"Summary"``, and
            ``"BusinessRelevance"``.

    Returns:
        A :class:`FilterResult` with the original theme, the unused
        summaries, and the list of URLs found in the theme.

    Raises:
        TypeError: If *formatted_theme* is not a dict or *summaries* is
            not a list.
    """
    if not isinstance(formatted_theme, dict):
        raise TypeError(f"formatted_theme must be a dict, got {type(formatted_theme).__name__}")
    if not isinstance(summaries, list):
        raise TypeError(f"summaries must be a list, got {type(summaries).__name__}")

    used_urls = extract_urls_from_theme(formatted_theme)

    unused = [
        s
        for s in summaries
        if isinstance(s, dict)
        and isinstance(s.get("URL"), str)
        and s["URL"].strip()
        and s["URL"].strip() not in used_urls
    ]

    return FilterResult(
        formatted_theme=formatted_theme,
        unused_summaries=unused,
        urls_in_theme=sorted(used_urls),
    )
