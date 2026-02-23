"""Concrete repository implementations satisfying pipeline Protocols."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ica.db import crud
from ica.pipeline.article_collection import ArticleRecord


class SqlArticleRepository:
    """Database-backed :class:`~ica.pipeline.article_collection.ArticleRepository`.

    Wraps an ``AsyncSession`` and delegates to :mod:`ica.db.crud` functions.
    The caller is responsible for session lifecycle (commit / rollback).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_articles(self, articles: list[ArticleRecord]) -> int:
        """Insert or update articles via PostgreSQL ON CONFLICT."""
        return await crud.upsert_articles(self._session, articles)
