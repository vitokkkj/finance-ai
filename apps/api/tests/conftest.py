from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from app.auth import login_rate_limiter  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def test_session_factory() -> Generator[sessionmaker[Session], None, None]:
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if test_database_url is None:
        test_engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        test_engine = create_engine(test_database_url, pool_pre_ping=True)
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    yield test_session

    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def client(test_session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:

    def override_get_db() -> Generator[Session, None, None]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    login_rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
