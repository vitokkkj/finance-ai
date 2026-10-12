from fastapi.testclient import TestClient


def test_owner_can_create_isolated_user_account(client: TestClient) -> None:
    owner_login = client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Vitor",
            "password": "senha-do-proprietario-segura",
        },
    )
    assert owner_login.status_code == 201

    created = client.post(
        "/api/admin/users",
        json={
            "email": "colega@example.com",
            "display_name": "Colega",
            "password": "senha-inicial-segura-123",
        },
    )
    assert created.status_code == 201
    assert created.json()["email"] == "colega@example.com"
    assert "password" not in created.json()
    assert "password_hash" not in created.json()
    assert [row["email"] for row in client.get("/api/admin/users").json()] == [
        "colega@example.com",
        "gamercreeper74@gmail.com",
    ]

    client.cookies.clear()
    signed_in = client.post(
        "/api/auth/login",
        json={"email": "colega@example.com", "password": "senha-inicial-segura-123"},
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["mfa_required"] is False
    assert client.get("/api/accounts").json() == []


def test_non_owner_cannot_list_or_create_users(client: TestClient) -> None:
    created_first_user = client.post(
        "/api/auth/setup",
        json={
            "email": "colega@example.com",
            "display_name": "Colega",
            "password": "senha-inicial-segura-123",
        },
    )
    assert created_first_user.status_code == 201

    assert client.get("/api/admin/users").status_code == 403
    response = client.post(
        "/api/admin/users",
        json={
            "email": "outra@example.com",
            "display_name": "Outra pessoa",
            "password": "outra-senha-segura-123",
        },
    )
    assert response.status_code == 403


def test_managed_user_creation_rejects_duplicate_email(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Vitor",
            "password": "senha-do-proprietario-segura",
        },
    )
    response = client.post(
        "/api/admin/users",
        json={
            "email": "GAMERCREEPER74@gmail.com",
            "display_name": "Duplicada",
            "password": "outra-senha-segura-123",
        },
    )
    assert response.status_code == 409
