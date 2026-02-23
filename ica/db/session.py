"""Async SQLAlchemy engine and session factory.

Usage as a FastAPI dependency or standalone::

    async with get_session() as session:
        result = await session.execute(...)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ica.config.settings import get_settings


def get_engine(*, url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        url: Override the database URL (useful for testing).
             Defaults to ``Settings.database_url``.
    """
    return create_async_engine(url or get_settings().database_url, echo=False)


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*.

    Args:
        engine: An existing engine.  A new one is created when ``None``.
    """
    engine = engine or get_engine()
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a session that auto-commits on success.

    On exception the transaction is rolled back and the session closed.

    Args:
        factory: Session factory to use.  A default one is created when ``None``.
    """
    factory = factory or get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
