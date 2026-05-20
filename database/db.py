from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


_MIGRATIONS = [
    # Safety columns (pre-auth era)
    "ALTER TABLE sites ADD COLUMN restricted BOOLEAN NOT NULL DEFAULT 0",
    "ALTER TABLE sites ADD COLUMN restricted_reason VARCHAR(128)",
    # Multi-user columns
    "ALTER TABLE sites ADD COLUMN user_id VARCHAR",
    "ALTER TABLE clusters ADD COLUMN user_id VARCHAR",
    # url uniqueness constraint was global — now per-user via code (SQLite can't drop unique easily)
    # OAuth columns
    "ALTER TABLE users ADD COLUMN oauth_provider VARCHAR(32)",
    "ALTER TABLE users ADD COLUMN oauth_id VARCHAR(256)",
]


async def init_db():
    from database.models import User, Site, Cluster, UserProfile  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _MIGRATIONS:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # column already exists
