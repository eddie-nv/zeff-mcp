"""Test fixtures.

Strategy: connect to a Postgres instance the developer (or CI) has running,
create an isolated database per test session, run Alembic migrations against
it, and hand each test a clean async session. Drop the DB at teardown.

Default DSN points at the local docker compose stack
(`docker compose up -d`). CI overrides via `TEST_DATABASE_URL_ADMIN`.

Why not pytest-postgresql: it requires a local `postgres` binary on the host.
Using the same Postgres binary that production will use (via Docker) is more
faithful and avoids version skew.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db import connection as db_conn

REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN_DSN_ENV = "TEST_DATABASE_URL_ADMIN"
DEFAULT_ADMIN_DSN = "postgresql://zeff:zeff@localhost:5432/postgres"


def _alembic_config(sync_dsn: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_dsn)
    return cfg


def _swap_dbname(dsn: str, dbname: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{dbname}"))


def _to_async(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg_async://"):
        return dsn
    if dsn.startswith("postgresql+psycopg://"):
        return dsn.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    return dsn.replace("postgresql://", "postgresql+psycopg_async://", 1)


def _to_sync(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg://"):
        return dsn
    if dsn.startswith("postgresql+psycopg_async://"):
        return dsn.replace("postgresql+psycopg_async://", "postgresql+psycopg://", 1)
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="session")
def _ephemeral_db() -> Iterator[tuple[str, str]]:
    """Create a fresh DB on the configured Postgres, yield (sync, async) DSNs."""
    admin_dsn = os.environ.get(ADMIN_DSN_ENV, DEFAULT_ADMIN_DSN)
    dbname = f"zeff_test_{secrets.token_hex(4)}"

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"Cannot reach Postgres at {admin_dsn} ({exc}); "
            f"start it with `docker compose up -d` or set {ADMIN_DSN_ENV}."
        )

    target_dsn = _swap_dbname(admin_dsn, dbname)
    sync_dsn = _to_sync(target_dsn)
    async_dsn = _to_async(target_dsn)

    try:
        yield sync_dsn, async_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (dbname,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{dbname}"')


@pytest.fixture(scope="session")
def _migrated_dsn(_ephemeral_db: tuple[str, str]) -> tuple[str, str]:
    sync_dsn, async_dsn = _ephemeral_db
    os.environ["DATABASE_URL"] = sync_dsn
    command.upgrade(_alembic_config(sync_dsn), "head")
    return sync_dsn, async_dsn


@pytest_asyncio.fixture
async def db_session(_migrated_dsn: tuple[str, str]) -> AsyncIterator[AsyncSession]:
    """Yield a clean async session bound to the migrated ephemeral DB.

    Each test gets a freshly-truncated DB. We TRUNCATE rather than DROP so we
    keep the migrated schema across the test session (cheap), but isolate
    state per test.
    """
    _, async_dsn = _migrated_dsn
    db_conn.configure_engine(async_dsn)
    factory = db_conn._ensure_initialized()  # noqa: SLF001

    async with db_conn.get_engine().begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE node_facets, node_external_ids, nodes RESTART IDENTITY CASCADE")
        )

    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await db_conn.get_engine().dispose()
        db_conn.reset_engine()
