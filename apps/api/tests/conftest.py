from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from app.auth import login_rate_limiter  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuthSession, User  # noqa: E402


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
    with TestClient(app, headers={"X-SophIA-Request": "1"}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def authenticate_as_user(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> Callable[[str], None]:
    """Create a valid session for ownership tests without exercising MFA itself."""

    def authenticate(email: str) -> None:
        raw_token = secrets.token_urlsafe(32)
        with test_session_factory() as session:
            user = session.scalar(select(User).where(User.email == email))
            assert user is not None
            session.add(
                AuthSession(
                    token_digest=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                    user_id=user.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            session.commit()
        client.cookies.set(settings.session_cookie_name, raw_token)

    return authenticate
