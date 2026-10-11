import pytest
from fastapi.testclient import TestClient

from app.config import settings


def test_first_account_setup_creates_a_development_session(client: TestClient) -> None:
    state = client.get("/api/auth/setup-state")
    assert state.status_code == 200
    assert state.json() == {
        "requires_setup": True,
        "setup_available": True,
        "bootstrap_token_required": False,
        "mfa_required": False,
    }

    response = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "usuario@example.com"
    assert response.cookies.get("finance_ai_session")
    assert client.get("/api/auth/me").json()["display_name"] == "Pessoa"

    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").json()["display_name"] == "Pessoa"

    second_setup = client.post(
        "/api/auth/setup",
        json={
            "email": "outra@example.com",
            "display_name": "Outra pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert second_setup.status_code == 409


def test_login_uses_generic_failure_and_logout_revokes_session(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    invalid = client.post(
        "/api/auth/login",
        json={"email": "usuario@example.com", "password": "senha-incorreta-123"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "E-mail, senha ou código inválidos."

    valid = client.post(
        "/api/auth/login",
        json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_checks_password_before_mfa_step(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    invalid = client.post(
        "/api/auth/login/check",
        json={"email": "usuario@example.com", "password": "senha-incorreta-123"},
    )
    assert invalid.status_code == 401

    valid = client.post(
        "/api/auth/login/check",
        json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 200
    assert valid.json() == {
        "mfa_required": False,
        "mfa_enrolled": False,
        "mfa_enrollment_available": False,
    }
    assert client.get("/api/auth/me").status_code == 401


def test_owner_can_pair_authenticator_with_one_time_enrollment_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import auth

    client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()
    monkeypatch.setattr(settings, "owner_totp_secret", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    monkeypatch.setattr(settings, "mfa_enrollment_token", "m" * 64)
    monkeypatch.setattr(auth, "_verify_owner_totp", lambda code: code == "123456")

    checked = client.post(
        "/api/auth/login/check",
        json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
    )
    assert checked.json() == {
        "mfa_required": True,
        "mfa_enrolled": False,
        "mfa_enrollment_available": True,
    }
    assert client.get("/api/auth/me").status_code == 401

    start = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": "usuario@example.com",
            "password": "uma-senha-local-segura",
            "enrollment_token": "m" * 64,
        },
    )
    assert start.status_code == 200
    assert start.headers["cache-control"] == "no-store"
    assert start.json()["qr_code_data_url"].startswith("data:image/svg+xml;base64,")
    assert start.json()["manual_key"] == "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    client.cookies.clear()
    confirm = client.post(
        "/api/auth/mfa/enrollment/confirm",
        json={
            "email": "usuario@example.com",
            "password": "uma-senha-local-segura",
            "enrollment_token": "m" * 64,
            "totp_code": "123456",
        },
    )
    assert confirm.status_code == 200
    assert confirm.cookies.get("finance_ai_session")
    assert client.get("/api/auth/me").json()["email"] == "usuario@example.com"

    repeated = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": "usuario@example.com",
            "password": "uma-senha-local-segura",
            "enrollment_token": "m" * 64,
        },
    )
    assert repeated.status_code == 409


def test_mfa_enrollment_requires_the_server_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import auth

    client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()
    monkeypatch.setattr(settings, "owner_totp_secret", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    monkeypatch.setattr(settings, "mfa_enrollment_token", "m" * 64)
    monkeypatch.setattr(auth, "_verify_owner_totp", lambda code: False)

    response = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": "usuario@example.com",
            "password": "uma-senha-local-segura",
            "enrollment_token": "wrong" * 8,
        },
    )
    assert response.status_code == 401
    assert "qr_code_data_url" not in response.json()


def test_login_rate_limit_blocks_repeated_failures(client: TestClient) -> None:
    from app.main import app

    client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": "usuario@example.com", "password": "senha-incorreta-123"},
        )
        assert response.status_code == 401

    limited = client.post(
        "/api/auth/login",
        json={"email": "usuario@example.com", "password": "senha-incorreta-123"},
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers

    valid = client.post(
        "/api/auth/login",
        json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 429

    with TestClient(
        app,
        client=("203.0.113.7", 1234),
        headers={"X-SophIA-Request": "1"},
    ) as other_client:
        valid_from_another_ip = other_client.post(
            "/api/auth/login",
            json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
        )
    assert valid_from_another_ip.status_code == 200


def test_state_changing_requests_require_the_same_origin_header(client: TestClient) -> None:
    from fastapi.testclient import TestClient as BareTestClient

    from app.main import app

    with BareTestClient(app) as bare_client:
        response = bare_client.post("/api/auth/logout")

    assert response.status_code == 403


def test_login_rate_limiter_keeps_memory_bounded() -> None:
    from app.auth_security import LoginRateLimiter

    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, max_keys=2)
    assert limiter.allow_attempt(("ip:1",), 1)
    assert limiter.allow_attempt(("ip:2",), 2)
    assert limiter.allow_attempt(("ip:3",), 3)

    assert len(limiter._failures) == 2
    assert limiter.allow_attempt(("ip:1",), 4)
    assert limiter.allow_attempt(("ip:1",), 5)
    assert not limiter.allow_attempt(("ip:1",), 6)


def test_totp_accepts_current_and_neighboring_time_steps() -> None:
    from app.auth_security import verify_totp

    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert verify_totp(secret, "287082", now=59)
    assert verify_totp(secret, "287082", now=30)
    assert not verify_totp(secret, "287082", now=120)
    assert not verify_totp(secret, "abc123", now=59)


def test_production_bootstrap_needs_owner_token_and_totp(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import auth

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "initial_setup_token", "a" * 64)
    monkeypatch.setattr(settings, "owner_totp_secret", "A" * 32)
    monkeypatch.setattr(auth, "_verify_owner_totp", lambda code: code == "123456")

    invalid = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
            "bootstrap_token": "b" * 64,
            "totp_code": "123456",
        },
    )
    assert invalid.status_code == 401

    created = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
            "bootstrap_token": "a" * 64,
            "totp_code": "123456",
        },
    )
    assert created.status_code == 201
    assert created.cookies.get("finance_ai_session") is None
    assert client.get("/api/auth/me").status_code == 401
