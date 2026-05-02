"""Async SQLAlchemy engine, session factory, and a session context manager.

The engine is constructed lazily on first use. Tests can override the DSN by
calling `configure_engine(...)` before any session is opened, or by calling
`reset_engine()` to clear the cached engine after mutating env.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from zeff.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _to_async_url(url: str) -> str:
    """Force the async psycopg driver if the caller passed the sync DSN."""
    if "+psycopg_async" in url:
        return url
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg_async://", 1)
    return url


def configure_engine(database_url: str, *, echo: bool = False) -> None:
    """Build (or rebuild) the engine and session factory for a given DSN.

    Used by tests with `pytest-postgresql` to point at an ephemeral DB.
    """
    global _engine, _session_factory
    if _engine is not None:
        # Schedule disposal; safe to ignore if no loop is running yet.
        try:
            import asyncio

            asyncio.get_event_loop().run_until_complete(_engine.dispose())
        except RuntimeError:
            pass
    _engine = create_async_engine(_to_async_url(database_url), echo=echo, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def reset_engine() -> None:
    """Drop the cached engine. Next session call rebuilds from current settings."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def _ensure_initialized() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        configure_engine(get_settings().database_url)
    assert _session_factory is not None
    return _session_factory


def get_engine() -> AsyncEngine:
    _ensure_initialized()
    assert _engine is not None
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session.

    Commits on clean exit, rolls back on any exception, always closes.
    """
    factory = _ensure_initialized()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
