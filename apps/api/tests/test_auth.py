import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "gamercreeper74@gmail.com"
    assert response.json()["mfa_required"] is False
    assert response.json()["mfa_enrolled"] is False
    assert response.cookies.get("finance_ai_session")
    assert client.get("/api/auth/me").json()["display_name"] == "Pessoa"

    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
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
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    invalid = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "senha-incorreta-123"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "E-mail, senha ou código inválidos."

    valid = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_checks_password_before_mfa_step(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    invalid = client.post(
        "/api/auth/login/check",
        json={"email": "gamercreeper74@gmail.com", "password": "senha-incorreta-123"},
    )
    assert invalid.status_code == 401

    valid = client.post(
        "/api/auth/login/check",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 200
    assert valid.json() == {
        "mfa_required": False,
        "mfa_enrolled": False,
        "mfa_enrollment_available": False,
        "mfa_enrollment_token_required": True,
    }
    assert client.get("/api/auth/me").status_code == 401


def test_owner_can_pair_authenticator_with_one_time_enrollment_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import auth

    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()
    monkeypatch.setattr(settings, "owner_totp_secret", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    monkeypatch.setattr(settings, "mfa_enrollment_token", "m" * 64)
    monkeypatch.setattr(
        auth, "_owner_totp_counter", lambda code: 123456 if code == "123456" else None
    )

    checked = client.post(
        "/api/auth/login/check",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
    )
    assert checked.json() == {
        "mfa_required": True,
        "mfa_enrolled": False,
        "mfa_enrollment_available": True,
        "mfa_enrollment_token_required": True,
    }
    assert client.get("/api/auth/me").status_code == 401

    start = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": "gamercreeper74@gmail.com",
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
            "email": "gamercreeper74@gmail.com",
            "password": "uma-senha-local-segura",
            "enrollment_token": "m" * 64,
            "totp_code": "123456",
        },
    )
    assert confirm.status_code == 200
    assert confirm.cookies.get("finance_ai_session")
    assert client.get("/api/auth/me").json()["email"] == "gamercreeper74@gmail.com"

    repeated = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": "gamercreeper74@gmail.com",
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
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()
    monkeypatch.setattr(settings, "owner_totp_secret", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    monkeypatch.setattr(settings, "mfa_enrollment_token", "m" * 64)
    monkeypatch.setattr(auth, "_owner_totp_counter", lambda code: None)

    response = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": "gamercreeper74@gmail.com",
            "password": "uma-senha-local-segura",
            "enrollment_token": "wrong" * 8,
        },
    )
    assert response.status_code == 401
    assert "qr_code_data_url" not in response.json()


def test_totp_code_cannot_create_two_sessions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import auth

    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()
    monkeypatch.setattr(settings, "owner_totp_secret", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    monkeypatch.setattr(
        auth, "_owner_totp_counter", lambda code: 123456 if code == "123456" else None
    )
    login_payload = {
        "email": "gamercreeper74@gmail.com",
        "password": "uma-senha-local-segura",
        "totp_code": "123456",
    }

    first_login = client.post("/api/auth/login", json=login_payload)
    assert first_login.status_code == 200
    client.cookies.clear()

    replay = client.post("/api/auth/login", json=login_payload)
    assert replay.status_code == 401


def test_login_rate_limit_blocks_repeated_failures(client: TestClient) -> None:
    from app.main import app

    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": "gamercreeper74@gmail.com", "password": "senha-incorreta-123"},
        )
        assert response.status_code == 401

    limited = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "senha-incorreta-123"},
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers

    valid = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 429

    with TestClient(
        app,
        client=("203.0.113.7", 1234),
        headers={"X-SophIA-Request": "1"},
    ) as other_client:
        valid_from_another_ip = other_client.post(
            "/api/auth/login",
            json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
        )
    assert valid_from_another_ip.status_code == 429


def test_login_password_check_and_mfa_share_one_rate_limit(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    for _ in range(5):
        response = client.post(
            "/api/auth/login/check",
            json={"email": "gamercreeper74@gmail.com", "password": "senha-incorreta-123"},
        )
        assert response.status_code == 401

    blocked_second_stage = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
    )
    assert blocked_second_stage.status_code == 429


def test_login_rate_limit_blocks_attempts_across_multiple_ips(client: TestClient) -> None:
    from app.main import app

    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    client.cookies.clear()

    for index in range(5):
        with TestClient(
            app,
            client=(f"203.0.113.{10 + index}", 1234),
            headers={"X-SophIA-Request": "1"},
        ) as remote_client:
            response = remote_client.post(
                "/api/auth/login",
                json={"email": "gamercreeper74@gmail.com", "password": "senha-incorreta-123"},
            )
        assert response.status_code == 401

    with TestClient(
        app,
        client=("203.0.113.20", 1234),
        headers={"X-SophIA-Request": "1"},
    ) as remote_client:
        blocked = remote_client.post(
            "/api/auth/login",
            json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
        )
    assert blocked.status_code == 429


def test_login_rate_limit_uses_valid_client_ip_from_trusted_proxy_header(
    client: TestClient,
) -> None:
    for index in range(5):
        response = client.post(
            "/api/auth/login",
            headers={"X-SophIA-Client-IP": "198.51.100.24"},
            json={
                "email": f"inexistente-{index}@example.com",
                "password": "senha-incorreta-123",
            },
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        headers={"X-SophIA-Client-IP": "198.51.100.24"},
        json={"email": "inexistente-final@example.com", "password": "senha-incorreta-123"},
    )
    assert blocked.status_code == 429

    another_ip = client.post(
        "/api/auth/login",
        headers={"X-SophIA-Client-IP": "198.51.100.25"},
        json={"email": "inexistente-final@example.com", "password": "senha-incorreta-123"},
    )
    assert another_ip.status_code == 401


def test_account_profile_and_active_sessions_can_be_managed(client: TestClient) -> None:
    from app.main import app

    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    with TestClient(
        app,
        client=("203.0.113.8", 1234),
        headers={"X-SophIA-Request": "1"},
    ) as other_client:
        signed_in = other_client.post(
            "/api/auth/login",
            json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
        )
        assert signed_in.status_code == 200

        sessions = client.get("/api/auth/sessions")
        assert sessions.status_code == 200
        assert len(sessions.json()) == 2
        assert sum(session["is_current"] for session in sessions.json()) == 1
        assert "token" not in sessions.json()[0]

        revoked = client.post(
            "/api/auth/sessions/revoke-others",
            json={"current_password": "uma-senha-local-segura"},
        )
        assert revoked.status_code == 200
        assert revoked.json() == {"revoked_count": 1}
        assert other_client.get("/api/auth/me").status_code == 401

    updated = client.patch("/api/auth/me", json={"display_name": "  Vitor  "})
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Vitor"
    assert client.get("/api/auth/me").json()["display_name"] == "Vitor"


def test_profile_avatar_is_private_normalized_and_removable(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )

    image_buffer = BytesIO()
    Image.new("RGB", (3000, 3000), color=(49, 94, 73)).save(image_buffer, format="PNG")
    image_data_url = f"data:image/png;base64,{base64.b64encode(image_buffer.getvalue()).decode()}"

    updated = client.put("/api/auth/me/avatar", json={"image_data_url": image_data_url})
    assert updated.status_code == 200
    avatar_url = updated.json()["avatar_url"]
    assert avatar_url.startswith("/api/auth/me/avatar/")

    avatar = client.get(avatar_url)
    assert avatar.status_code == 200
    assert avatar.headers["content-type"] == "image/webp"
    assert avatar.headers["cache-control"] == "no-store"
    assert avatar.headers["x-content-type-options"] == "nosniff"
    with Image.open(BytesIO(avatar.content)) as normalized:
        assert normalized.format == "WEBP"
        assert normalized.size == (512, 512)

    invalid = client.put(
        "/api/auth/me/avatar",
        json={"image_data_url": "data:image/png;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="},
    )
    assert invalid.status_code == 422

    removed = client.delete("/api/auth/me/avatar")
    assert removed.status_code == 200
    assert removed.json()["avatar_url"] is None
    assert client.get(avatar_url).status_code == 404

    client.cookies.clear()
    assert client.get(avatar_url).status_code == 401


def test_password_change_requires_reauthentication_and_revokes_all_sessions(
    client: TestClient,
) -> None:
    from app.main import app

    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    with TestClient(
        app,
        client=("203.0.113.9", 1234),
        headers={"X-SophIA-Request": "1"},
    ) as other_client:
        other_client.post(
            "/api/auth/login",
            json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
        )

        rejected = client.post(
            "/api/auth/password/change",
            json={
                "current_password": "senha-incorreta-123",
                "new_password": "outra-senha-local-segura",
            },
        )
        assert rejected.status_code == 401
        assert len(client.get("/api/auth/sessions").json()) == 2

        changed = client.post(
            "/api/auth/password/change",
            json={
                "current_password": "uma-senha-local-segura",
                "new_password": "outra-senha-local-segura",
            },
        )
        assert changed.status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        assert other_client.get("/api/auth/me").status_code == 401

    old_password = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "uma-senha-local-segura"},
    )
    assert old_password.status_code == 401
    new_password = client.post(
        "/api/auth/login",
        json={"email": "gamercreeper74@gmail.com", "password": "outra-senha-local-segura"},
    )
    assert new_password.status_code == 200


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
    assert limiter.allow_attempt(("ip:1",), 2)
    assert not limiter.allow_attempt(("ip:1",), 3)
    assert limiter.allow_attempt(("ip:2",), 2)
    assert not limiter.allow_attempt(("ip:3",), 3)

    assert len(limiter._failures) == 2
    assert not limiter.allow_attempt(("ip:1",), 4)
    assert limiter.allow_attempt(("ip:3",), 63)
    assert limiter.allow_attempt(("ip:2",), 63)
    assert len(limiter._failures) == 2


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
    monkeypatch.setattr(
        auth, "_owner_totp_counter", lambda code: 123456 if code == "123456" else None
    )

    invalid = client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
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
            "email": "gamercreeper74@gmail.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
            "bootstrap_token": "a" * 64,
            "totp_code": "123456",
        },
    )
    assert created.status_code == 201
    assert created.cookies.get("finance_ai_session") is None
    assert client.get("/api/auth/me").status_code == 401

    wrong_owner = client.post(
        "/api/auth/setup",
        json={
            "email": "nao-proprietario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
            "bootstrap_token": "a" * 64,
            "totp_code": "123456",
        },
    )
    assert wrong_owner.status_code == 403
