"""Application-owned database resources. Creating a pool does not connect."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@dataclass(frozen=True)
class Database:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    async def close(self):
        await self.engine.dispose()


def create_database(url: str) -> Database:
    engine = create_async_engine(url)
    return Database(engine, async_sessionmaker(engine, expire_on_commit=False))
