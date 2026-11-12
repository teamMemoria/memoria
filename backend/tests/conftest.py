import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import make_url, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.core.config import get_settings
from backend.models.evaluation import EvaluationForm, EvaluationFormVersion

BACKEND_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = BACKEND_DIR / "src"

# The disposable database the suite drops, recreates and migrates on every run.
# Point TEST_DATABASE_URL at any scratch database to isolate a run.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/callassist_test"
)
_test_url = make_url(TEST_DATABASE_URL)
TEST_DB = _test_url.database
# Same server and credentials, but connected to the maintenance database so the
# test database can be dropped and recreated.
ADMIN_URL = _test_url.set(
    drivername="postgresql", database="postgres"
).render_as_string(hide_password=False)
TEST_DB_DIRECT_URL = _test_url.set(drivername="postgresql").render_as_string(
    hide_password=False
)


def _same_database(a: str, b: str) -> bool:
    a_url, b_url = make_url(a), make_url(b)
    return (a_url.host, a_url.port or 5432, a_url.database) == (
        b_url.host,
        b_url.port or 5432,
        b_url.database,
    )


def _recreate_test_database() -> None:
    """Drop the test database, create it again and run every migration."""
    if not TEST_DB:
        pytest.exit("TEST_DATABASE_URL must name a database", returncode=2)
    if _same_database(TEST_DATABASE_URL, get_settings().database_url):
        pytest.exit(
            f"TEST_DATABASE_URL points at the app database ({TEST_DB}); "
            "refusing to drop it",
            returncode=2,
        )
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        name = sql.Identifier(TEST_DB)
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(name))
    with psycopg.connect(TEST_DB_DIRECT_URL, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={
            **os.environ,
            "DATABASE_URL": TEST_DATABASE_URL,
            "PYTHONPATH": str(SOURCE_DIR),
        },
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Recreate the test database and run every migration against it."""
    _recreate_test_database()


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


@pytest.fixture
async def committed_sessions():
    """A session factory whose sessions really commit, for concurrency tests.

    Each session gets its own connection, as in the running app. The database
    is rebuilt afterwards, so later tests start from the migrated state again,
    including the rows the migrations seed (the default organization and the
    default evaluation form).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
    _recreate_test_database()


@pytest.fixture
async def default_evaluation_version(session):
    return await session.scalar(
        select(EvaluationFormVersion)
        .join(EvaluationForm)
        .where(EvaluationForm.name == "Default quality form")
    )
