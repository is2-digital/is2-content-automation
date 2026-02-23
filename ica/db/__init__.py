"""Database layer — models, session management, and CRUD operations.

Re-exports the most commonly used symbols so callers can do::

    from ica.db import Base, Article, get_session, SqlArticleRepository
"""

from ica.db.models import (
    Article,
    Base,
    HtmlGeneratorUserFeedback,
    MarkdownGeneratorUserFeedback,
    NewsletterEmailSubjectFeedback,
    NewsletterTheme,
    NewsletterThemesUserFeedback,
    SummarizationUserFeedback,
)
from ica.db.repository import SqlArticleRepository
from ica.db.session import get_engine, get_session, get_session_factory

__all__ = [
    # Base
    "Base",
    # Models
    "Article",
    "HtmlGeneratorUserFeedback",
    "MarkdownGeneratorUserFeedback",
    "NewsletterEmailSubjectFeedback",
    "NewsletterTheme",
    "NewsletterThemesUserFeedback",
    "SummarizationUserFeedback",
    # Session
    "get_engine",
    "get_session",
    "get_session_factory",
    # Repository
    "SqlArticleRepository",
]
