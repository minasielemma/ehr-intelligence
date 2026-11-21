"""Database engine, session management, and base declarative class for SQLAlchemy 2.0.

Provides asynchronous SQLite database connectivity via aiosqlite.
"""

from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.api.dependencies import get_current_settings
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


_engines: Dict[str, AsyncEngine] = {}
_session_factories: Dict[str, async_sessionmaker[AsyncSession]] = {}


from sqlalchemy import event


def get_engine(db_url: Optional[str] = None) -> AsyncEngine:
    """Return asynchronous database engine for specified URL or default settings."""
    settings = get_settings()
    url = db_url or settings.sqlite_url
    if not url.startswith("sqlite"):
        url = f"sqlite+aiosqlite:///{url}"

    if url not in _engines:
        engine = create_async_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            try:
                cursor.execute("PRAGMA journal_mode = WAL;")
            except Exception:
                pass
            cursor.execute("PRAGMA busy_timeout = 5000;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.close()

        _engines[url] = engine
    return _engines[url]


def get_session_factory(db_url: Optional[str] = None) -> async_sessionmaker[AsyncSession]:
    """Return async sessionmaker for specified URL or default settings."""
    settings = get_settings()
    url = db_url or settings.sqlite_url
    if not url.startswith("sqlite"):
        url = f"sqlite+aiosqlite:///{url}"

    if url not in _session_factories:
        engine = get_engine(url)
        _session_factories[url] = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factories[url]


async def get_db_session(
    settings: Settings = Depends(get_current_settings),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session configured for active settings."""
    session_factory = get_session_factory(settings.sqlite_url)
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db(db_url: Optional[str] = None, database_path: Optional[str] = None) -> None:
    """Initialize database tables ensuring directories and schemas exist."""
    settings = get_settings()
    path_str = database_path or settings.DATABASE_PATH
    try:
        db_path = Path(path_str)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not pre-create database parent directory: %s", exc)

    url = db_url or (f"sqlite+aiosqlite:///{path_str}" if database_path else settings.sqlite_url)
    engine = get_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Initialized structured database schema at %s", path_str)
