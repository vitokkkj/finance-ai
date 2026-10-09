from fastapi.testclient import TestClient


def test_first_account_setup_creates_a_session(client: TestClient) -> None:
    state = client.get("/api/auth/setup-state")
    assert state.status_code == 200
    assert state.json() == {"requires_setup": True}

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
    assert invalid.json()["detail"] == "E-mail ou senha inválidos."

    valid = client.post(
        "/api/auth/login",
        json={"email": "usuario@example.com", "password": "uma-senha-local-segura"},
    )
    assert valid.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit_blocks_repeated_failures(client: TestClient) -> None:
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
