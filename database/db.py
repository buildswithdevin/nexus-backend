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


async def init_db():
    from database.models import Site, Cluster  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add safety columns to existing databases (SQLite ignores errors if column exists)
        for col_def in [
            "ALTER TABLE sites ADD COLUMN restricted BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE sites ADD COLUMN restricted_reason VARCHAR(128)",
        ]:
            try:
                await conn.execute(text(col_def))
            except Exception:
                pass  # Column already exists
