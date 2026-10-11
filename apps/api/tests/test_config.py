import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_worker_does_not_require_owner_totp() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        app_component="worker",
        database_url="sqlite+pysqlite:///:memory:",
        session_cookie_secure=True,
    )

    assert settings.app_component == "worker"
    assert settings.owner_totp_secret is None


def test_production_api_requires_owner_totp() -> None:
    with pytest.raises(ValidationError, match="OWNER_TOTP_SECRET"):
        Settings(
            _env_file=None,
            app_env="production",
            app_component="api",
            database_url="sqlite+pysqlite:///:memory:",
            session_cookie_secure=True,
        )
