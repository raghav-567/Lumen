"""Database engine and session management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine

from app.core.config import settings

# ── Async engine (for FastAPI) ────────────────────────
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # was settings.DEBUG — SQL echo floods logs and kills performance
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Sync engine (for Celery workers) ─────────────────
_sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2").replace("postgresql+psycopg2", "postgresql+psycopg2")
if "+asyncpg" in settings.DATABASE_URL:
    _sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
else:
    _sync_url = settings.DATABASE_URL

sync_engine = create_engine(_sync_url, echo=False, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)

# ── Base model ────────────────────────────────────────
Base = declarative_base()


async def get_db():
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    """Create all tables on startup."""
    async with async_engine.begin() as conn:
        from app.models.models import Base as ModelBase  # noqa
        await conn.run_sync(ModelBase.metadata.create_all)
