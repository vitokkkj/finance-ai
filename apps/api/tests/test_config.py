import pytest
from cryptography.fernet import Fernet
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


def test_production_api_requires_valid_managed_mfa_encryption_key() -> None:
    with pytest.raises(ValidationError, match="MFA_ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            app_component="api",
            database_url="sqlite+pysqlite:///:memory:",
            session_cookie_secure=True,
            owner_totp_secret="A" * 32,
            mfa_encryption_key="",
        )

    configured = Settings(
        _env_file=None,
        app_env="production",
        app_component="api",
        database_url="sqlite+pysqlite:///:memory:",
        session_cookie_secure=True,
        owner_totp_secret="A" * 32,
        mfa_encryption_key=Fernet.generate_key().decode("ascii"),
    )
    assert configured.mfa_encryption_key is not None


def test_production_api_rejects_short_mfa_enrollment_token() -> None:
    with pytest.raises(ValidationError, match="MFA_ENROLLMENT_TOKEN"):
        Settings(
            _env_file=None,
            app_env="production",
            app_component="api",
            database_url="sqlite+pysqlite:///:memory:",
            session_cookie_secure=True,
            owner_totp_secret="A" * 32,
            mfa_enrollment_token="too-short",
        )


def test_production_api_rejects_short_initial_setup_token() -> None:
    with pytest.raises(ValidationError, match="INITIAL_SETUP_TOKEN"):
        Settings(
            _env_file=None,
            app_env="production",
            app_component="api",
            database_url="sqlite+pysqlite:///:memory:",
            session_cookie_secure=True,
            owner_totp_secret="A" * 32,
            initial_setup_token="too-short",
        )
