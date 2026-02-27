"""Parser for ``%XX_`` markers in LLM-generated theme output.

Extracts structured article data from the theme generation LLM response,
which uses ``%PREFIX_FIELD: value`` markers to tag each piece of content.

This is a direct port of two n8n Code nodes in
``SUB/theme_generation_subworkflow.json``:

* **"Prepare AI generated themes"** — splits the raw LLM output on ``-----``
  delimiters into individual theme blocks and a recommendation section.
* **"Selected Theme output"** — extracts all ``%XX_`` markers from a single
  theme body into a structured ``formatted_theme`` dict.

See PRD Section 3.3 and the theme generation prompt for the full marker spec.

Marker prefixes
---------------
- **FA** — Featured Article (TITLE, SOURCE, ORIGIN, URL, CATEGORY, WHY FEATURED)
- **M1, M2** — Main Articles (TITLE, SOURCE, ORIGIN, URL, CATEGORY, RATIONALE)
- **Q1, Q2, Q3** — Quick Hits (TITLE, SOURCE, ORIGIN, URL, CATEGORY)
- **I1, I2** — Industry Developments (TITLE, SOURCE, ORIGIN, URL, Major AI Player)
- **RV** — Requirements Verified (4 verification fields)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeaturedArticle:
    """Extracted data for the Featured Article slot."""

    title: str | None = None
    source: str | None = None
    origin: str | None = None
    url: str | None = None
    category: str | None = None
    why_featured: str | None = None


@dataclass(frozen=True)
class MainArticle:
    """Extracted data for a Main Article slot (M1 or M2)."""

    title: str | None = None
    source: str | None = None
    origin: str | None = None
    url: str | None = None
    category: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class QuickHit:
    """Extracted data for a Quick Hit slot (Q1, Q2, or Q3)."""

    title: str | None = None
    source: str | None = None
    origin: str | None = None
    url: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class IndustryDevelopment:
    """Extracted data for an Industry Development slot (I1 or I2)."""

    title: str | None = None
    source: str | None = None
    origin: str | None = None
    url: str | None = None
    major_ai_player: str | None = None


@dataclass(frozen=True)
class RequirementsVerified:
    """Extracted requirements-verification fields."""

    distribution_achieved: str | None = None
    source_mix: str | None = None
    technical_complexity: str | None = None
    major_ai_player_coverage: str | None = None


@dataclass(frozen=True)
class FormattedTheme:
    """Fully parsed theme with all article slots populated.

    Mirrors the ``formatted_theme`` object built by the n8n
    "Selected Theme output" Code node.
    """

    theme: str | None = None
    featured_article: FeaturedArticle = field(default_factory=FeaturedArticle)
    main_article_1: MainArticle = field(default_factory=MainArticle)
    main_article_2: MainArticle = field(default_factory=MainArticle)
    quick_hit_1: QuickHit = field(default_factory=QuickHit)
    quick_hit_2: QuickHit = field(default_factory=QuickHit)
    quick_hit_3: QuickHit = field(default_factory=QuickHit)
    industry_development_1: IndustryDevelopment = field(
        default_factory=IndustryDevelopment,
    )
    industry_development_2: IndustryDevelopment = field(
        default_factory=IndustryDevelopment,
    )
    requirements_verified: RequirementsVerified = field(
        default_factory=RequirementsVerified,
    )


@dataclass(frozen=True)
class ParsedThemeBlock:
    """One theme block extracted from the raw LLM output.

    Contains the theme name, description, and the full body text that can
    be fed to :func:`parse_markers`.
    """

    theme_name: str | None = None
    theme_description: str | None = None
    theme_body: str = ""


@dataclass(frozen=True)
class ThemeParseResult:
    """Complete result of parsing the full LLM theme-generation response."""

    themes: list[ParsedThemeBlock] = field(default_factory=list)
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract(pattern: str, text: str) -> str | None:
    """Extract the first capture group from *text* using *pattern*.

    Returns ``None`` when the pattern does not match (mirrors the n8n
    ``(text.match(regex) || [])[1] || null`` idiom).
    """
    m = re.search(pattern, text)
    if m:
        value = m.group(1).strip()
        return value if value else None
    return None


# ---------------------------------------------------------------------------
# Public API — theme splitting
# ---------------------------------------------------------------------------


def split_themes(raw_output: str) -> ThemeParseResult:
    """Split raw LLM output into theme blocks and a recommendation.

    Mirrors the n8n "Prepare AI generated themes" Code node:
    1. Split on ``-----`` delimiter.
    2. Blocks containing ``RECOMMENDATION:`` go to the recommendation field.
    3. All other blocks become :class:`ParsedThemeBlock` entries.

    Args:
        raw_output: The complete text returned by the theme-generation LLM.

    Returns:
        A :class:`ThemeParseResult` with the extracted themes and
        recommendation text.
    """
    parts = [p.strip() for p in raw_output.split("-----") if p.strip()]

    recommendation_parts = [p for p in parts if "RECOMMENDATION:" in p]
    theme_parts = [p for p in parts if "RECOMMENDATION:" not in p]

    themes: list[ParsedThemeBlock] = []
    for block in theme_parts:
        name = _extract(r"THEME[ \t]*:[ \t]*(.+)", block)
        description = _extract(r"Theme Description[ \t]*:[ \t]*(.+)", block)
        themes.append(
            ParsedThemeBlock(
                theme_name=name,
                theme_description=description,
                theme_body=block,
            )
        )

    recommendation = "\n-----\n".join(recommendation_parts)

    return ThemeParseResult(themes=themes, recommendation=recommendation)


# ---------------------------------------------------------------------------
# Public API — marker extraction
# ---------------------------------------------------------------------------


def parse_markers(theme_body: str, theme_title: str | None = None) -> FormattedTheme:
    """Extract all ``%XX_`` markers from a single theme body.

    Mirrors the n8n "Selected Theme output" Code node.  Each marker is
    extracted with a regex of the form ``%PREFIX_FIELD:\\s*(.+)`` and the
    first capture group (trimmed) is stored.

    Args:
        theme_body: The raw text of a single theme block (the ``theme_body``
            field from :class:`ParsedThemeBlock`).
        theme_title: Optional override for the theme name.  When ``None``,
            the ``THEME:`` line inside *theme_body* is used.

    Returns:
        A :class:`FormattedTheme` with all article slots populated (fields
        that were not found in the text will be ``None``).
    """
    t = theme_body

    # Resolve theme title.
    resolved_title = theme_title or _extract(r"THEME[ \t]*:[ \t]*(.+)", t)

    featured = FeaturedArticle(
        title=_extract(r"%FA_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%FA_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%FA_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%FA_URL:[ \t]*(.+)", t),
        category=_extract(r"%FA_CATEGORY:[ \t]*(.+)", t),
        why_featured=_extract(r"%FA_WHY FEATURED:[ \t]*(.+)", t),
    )

    main1 = MainArticle(
        title=_extract(r"%M1_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%M1_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%M1_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%M1_URL:[ \t]*(.+)", t),
        category=_extract(r"%M1_CATEGORY:[ \t]*(.+)", t),
        rationale=_extract(r"%M1_RATIONALE:[ \t]*(.+)", t),
    )

    main2 = MainArticle(
        title=_extract(r"%M2_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%M2_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%M2_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%M2_URL:[ \t]*(.+)", t),
        category=_extract(r"%M2_CATEGORY:[ \t]*(.+)", t),
        rationale=_extract(r"%M2_RATIONALE:[ \t]*(.+)", t),
    )

    q1 = QuickHit(
        title=_extract(r"%Q1_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%Q1_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%Q1_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%Q1_URL:[ \t]*(.+)", t),
        category=_extract(r"%Q1_CATEGORY:[ \t]*(.+)", t),
    )

    q2 = QuickHit(
        title=_extract(r"%Q2_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%Q2_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%Q2_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%Q2_URL:[ \t]*(.+)", t),
        category=_extract(r"%Q2_CATEGORY:[ \t]*(.+)", t),
    )

    q3 = QuickHit(
        title=_extract(r"%Q3_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%Q3_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%Q3_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%Q3_URL:[ \t]*(.+)", t),
        category=_extract(r"%Q3_CATEGORY:[ \t]*(.+)", t),
    )

    i1 = IndustryDevelopment(
        title=_extract(r"%I1_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%I1_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%I1_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%I1_URL:[ \t]*(.+)", t),
        major_ai_player=_extract(r"%I1_Major AI Player:[ \t]*(.+)", t),
    )

    i2 = IndustryDevelopment(
        title=_extract(r"%I2_TITLE:[ \t]*(.+)", t),
        source=_extract(r"%I2_SOURCE:[ \t]*(.+)", t),
        origin=_extract(r"%I2_ORIGIN:[ \t]*(.+)", t),
        url=_extract(r"%I2_URL:[ \t]*(.+)", t),
        major_ai_player=_extract(r"%I2_Major AI Player:[ \t]*(.+)", t),
    )

    rv = RequirementsVerified(
        distribution_achieved=_extract(
            r"%RV_2-2-2 Distribution Achieved:%[ \t]*(.+)",
            t,
        ),
        source_mix=_extract(r"%RV_Source mix:%[ \t]*(.+)", t),
        technical_complexity=_extract(r"%RV_Technical complexity:%[ \t]*(.+)", t),
        major_ai_player_coverage=_extract(
            r"%RV_Major AI player coverage:%[ \t]*(.+)",
            t,
        ),
    )

    return FormattedTheme(
        theme=resolved_title,
        featured_article=featured,
        main_article_1=main1,
        main_article_2=main2,
        quick_hit_1=q1,
        quick_hit_2=q2,
        quick_hit_3=q3,
        industry_development_1=i1,
        industry_development_2=i2,
        requirements_verified=rv,
    )
