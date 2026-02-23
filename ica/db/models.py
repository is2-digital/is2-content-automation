"""SQLAlchemy 2.0 ORM models for all 7 database tables.

Schema matches PRD Section 2.2. The database ``n8n_custom_data`` contains:

- ``curated_articles`` — discovered articles with editorial metadata
- ``newsletter_themes`` — generated themes with approval status
- 5 feedback tables sharing a common ``FeedbackMixin`` pattern
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Index, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Mixin for the 5 feedback tables
# ---------------------------------------------------------------------------


class FeedbackMixin:
    """Columns shared by all feedback tables.

    Each feedback table has an auto-incrementing primary key, a non-null
    ``feedback_text`` column, and a server-generated ``created_at`` timestamp.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# curated_articles
# ---------------------------------------------------------------------------


class CuratedArticle(Base):
    """An article discovered by the collection pipeline."""

    __tablename__ = "curated_articles"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(Text)
    publish_date: Mapped[date | None] = mapped_column(Date)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    industry_news: Mapped[bool | None] = mapped_column(Boolean)
    newsletter_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# newsletter_themes
# ---------------------------------------------------------------------------


class NewsletterTheme(Base):
    """A generated newsletter theme."""

    __tablename__ = "newsletter_themes"

    theme: Mapped[str] = mapped_column(Text, primary_key=True)
    theme_body: Mapped[str | None] = mapped_column(Text)
    theme_summary: Mapped[str | None] = mapped_column(Text)
    newsletter_id: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# Feedback tables (3 plain + 2 with newsletter_id)
# ---------------------------------------------------------------------------


class SummarizationUserFeedback(FeedbackMixin, Base):
    """Feedback on article summarization quality."""

    __tablename__ = "summarization_user_feedback"

    __table_args__ = (
        Index("ix_summarization_user_feedback_created_at", "created_at"),
    )


class MarkdownGeneratorUserFeedback(FeedbackMixin, Base):
    """Feedback on markdown generation quality."""

    __tablename__ = "markdowngenerator_user_feedback"

    __table_args__ = (
        Index("ix_markdowngenerator_user_feedback_created_at", "created_at"),
    )


class HtmlGeneratorUserFeedback(FeedbackMixin, Base):
    """Feedback on HTML generation quality."""

    __tablename__ = "htmlgenerator_user_feedback"

    __table_args__ = (
        Index("ix_htmlgenerator_user_feedback_created_at", "created_at"),
    )


class NewsletterThemesUserFeedback(FeedbackMixin, Base):
    """Feedback on theme generation — includes newsletter association."""

    __tablename__ = "newsletter_themes_user_feedback"

    newsletter_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_newsletter_themes_user_feedback_created_at", "created_at"),
    )


class NewsletterEmailSubjectFeedback(FeedbackMixin, Base):
    """Feedback on email subject line generation — includes newsletter association."""

    __tablename__ = "newsletter_email_subject_feedback"

    newsletter_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_newsletter_email_subject_feedback_created_at", "created_at"),
    )
