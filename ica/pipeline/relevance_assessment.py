"""LLM-based relevance screening for search results.

Evaluates each article from Brave Search against the IS2 newsletter
audience criteria before storing it in the database. Articles that
don't meet the criteria are marked as rejected with a reason.

Model: ``google/gemini-2.5-flash`` (fast and cheap — runs per-article
on every collection cycle).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ica.config.llm_config import LLMPurpose
from ica.prompts.relevance_assessment import build_relevance_prompt
from ica.services.llm import LLMResponse, completion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelevanceResult:
    """Result of a single article relevance assessment."""

    url: str
    decision: str  # "accept" or "reject"
    reason: str


async def assess_article(
    title: str,
    excerpt: str,
    url: str,
    *,
    model: str | None = None,
) -> RelevanceResult:
    """Assess a single article's relevance to the newsletter audience.

    Calls the LLM to evaluate the article and parses the structured
    JSON response. If the LLM response cannot be parsed, the article
    is accepted by default (fail-open).

    Args:
        title: Article title from the search result.
        excerpt: Article excerpt/description snippet.
        url: Article URL (passed through to the result).
        model: Optional model override.

    Returns:
        A :class:`RelevanceResult` with the decision and reason.
    """
    system_prompt, user_prompt = build_relevance_prompt(title=title, excerpt=excerpt)

    result: LLMResponse = await completion(
        purpose=LLMPurpose.RELEVANCE_ASSESSMENT,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        step="relevance_assessment",
    )

    return _parse_response(result.text, url=url)


def _parse_response(text: str, *, url: str) -> RelevanceResult:
    """Parse the LLM JSON response into a RelevanceResult.

    Handles common variations: markdown code fences, extra whitespace,
    and malformed JSON. Defaults to accept if parsing fails.
    """
    cleaned = text.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first line (```json or ```) and last line (```)
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse relevance response for %s, defaulting to accept", url)
        return RelevanceResult(
            url=url, decision="accept", reason="Parse error — accepted by default"
        )

    decision = str(data.get("decision", "accept")).lower().strip()
    if decision not in ("accept", "reject"):
        logger.warning("Unknown decision '%s' for %s, defaulting to accept", decision, url)
        decision = "accept"

    reason = str(data.get("reason", "")).strip()
    if not reason:
        reason = "No reason provided"

    return RelevanceResult(url=url, decision=decision, reason=reason)


async def assess_articles(
    search_results: list[tuple[str, str, str]],
    *,
    model: str | None = None,
) -> list[RelevanceResult]:
    """Assess multiple articles sequentially.

    Runs assessments one at a time since Gemini Flash is fast and cheap.

    Args:
        search_results: List of ``(url, title, excerpt)`` tuples.
        model: Optional model override applied to all assessments.

    Returns:
        List of :class:`RelevanceResult` objects, one per input article.
    """
    results: list[RelevanceResult] = []
    for url, title, excerpt in search_results:
        result = await assess_article(title=title, excerpt=excerpt, url=url, model=model)
        logger.info(
            "Relevance: %s — %s (%s)",
            result.decision,
            url,
            result.reason,
        )
        results.append(result)
    return results
