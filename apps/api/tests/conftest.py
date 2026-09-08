import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

from apps.api.app.core.db import get_session
from apps.api.app.main import create_app
from apps.api.app.models import Base


@pytest.fixture
async def empty_engine() -> AsyncIterator[AsyncEngine]:
    # PostgreSQL tests use a schema owned by THIS test, never public or a shared table set.
    test_url = os.getenv("TEST_DATABASE_URL")
    if test_url:
        if not test_url.startswith("postgresql+asyncpg://"):
            raise ValueError("TEST_DATABASE_URL must use postgresql+asyncpg")
        schema = f"test_investigation_{uuid.uuid4().hex}"
        admin_engine = create_async_engine(test_url, poolclass=NullPool)
        async with admin_engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        engine = create_async_engine(
            test_url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}}
        )
        try:
            yield engine
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
            await admin_engine.dispose()
        return

    # StaticPool keeps every session on the one connection that owns the in-memory database.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection: Any, _: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def engine(empty_engine: AsyncEngine) -> AsyncEngine:
    engine = empty_engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    application = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_get_session
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
