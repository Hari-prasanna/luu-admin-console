"""
Database configuration and connection management.

Provides SQLAlchemy async engine and session factory for PostgreSQL.
"""

import os
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# Database URL from environment or default
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://luu_user:luu_password_dev@localhost:5432/luu_console"
)

# Convert standard PostgreSQL URL to async variant
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Base class for all models
Base = declarative_base()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    # Ensure ORM models are imported so metadata contains all tables.
    import backend.db_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Backward-compatible schema updates for existing deployments.
        await conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS panels_json TEXT DEFAULT '[]'"))
        await conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true"))
        await conn.execute(text("UPDATE users SET panels_json = CASE WHEN role = 'admin' THEN '[\"transit_theater\",\"monitor\",\"pipelines\",\"automation\",\"admin_panel\"]' ELSE '[\"transit_theater\"]' END WHERE panels_json IS NULL OR panels_json = ''"))
        await conn.execute(text("UPDATE users SET is_active = true WHERE is_active IS NULL"))


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
