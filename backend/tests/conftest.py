import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_URL = os.getenv(
    "TEST_ADMIN_URL", "postgresql://app:app@localhost:5432/callassist"
)
TEST_DB = "callassist_test"
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", f"postgresql+psycopg://app:app@localhost:5432/{TEST_DB}"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Recreate the test database and run every migration against it."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(
        ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}", autocommit=True
    ) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def session():
    """A session whose changes are rolled back after each test."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as s:
            yield s
        await trans.rollback()
    await engine.dispose()
