from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuthSession, Category, User

OWNER_EMAIL = "gamercreeper74@gmail.com"
OWNER_PASSWORD = "senha-do-proprietario-segura"


def _create_first_user(client: TestClient, email: str = OWNER_EMAIL) -> str:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": email,
            "display_name": "Proprietário",
            "password": OWNER_PASSWORD,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_managed_user(client: TestClient, email: str = "richard@example.com") -> dict:
    response = client.post(
        "/api/admin/users",
        json={
            "email": email,
            "display_name": "Richard",
            "password": "senha-inicial-segura-123",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_owner_can_create_list_and_delete_empty_managed_user(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    owner_id = _create_first_user(client)
    created = _create_managed_user(client, " Richard@Example.com ")

    assert created["email"] == "richard@example.com"
    assert "password" not in created
    assert "password_hash" not in created
    assert {row["email"] for row in client.get("/api/admin/users").json()} == {
        OWNER_EMAIL,
        "richard@example.com",
    }

    self_delete = client.delete(f"/api/admin/users/{owner_id}")
    assert self_delete.status_code == 409

    deleted = client.delete(f"/api/admin/users/{created['id']}")
    assert deleted.status_code == 204
    assert [row["email"] for row in client.get("/api/admin/users").json()] == [OWNER_EMAIL]

    with test_session_factory() as db:
        assert db.get(User, UUID(owner_id)) is not None
        assert db.get(User, UUID(created["id"])) is None
        assert db.scalar(
            select(func.count()).select_from(AuthSession).where(
                AuthSession.user_id == UUID(created["id"])
            )
        ) == 0


def test_managed_user_with_data_cannot_be_deleted_and_data_is_preserved(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _create_first_user(client)
    created = _create_managed_user(client)
    managed_user_id = UUID(created["id"])

    with test_session_factory() as db:
        db.add(Category(user_id=managed_user_id, name="Alimentação", type="EXPENSE"))
        db.commit()

    deleted = client.delete(f"/api/admin/users/{managed_user_id}")
    assert deleted.status_code == 409
    assert "dados associados" in deleted.json()["detail"]

    with test_session_factory() as db:
        assert db.get(User, managed_user_id) is not None
        assert db.scalar(
            select(func.count()).select_from(Category).where(Category.user_id == managed_user_id)
        ) == 1


def test_non_owner_cannot_list_create_or_delete_managed_users(client: TestClient) -> None:
    _create_first_user(client, "pessoa@example.com")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post(
        "/api/admin/users",
        json={
            "email": "outra@example.com",
            "display_name": "Outra pessoa",
            "password": "outra-senha-segura-123",
        },
    ).status_code == 403
    assert client.delete("/api/admin/users/00000000-0000-0000-0000-000000000001").status_code == 403


def test_managed_user_creation_rejects_duplicate_email(client: TestClient) -> None:
    _create_first_user(client)
    _create_managed_user(client)
    duplicate = client.post(
        "/api/admin/users",
        json={
            "email": "RICHARD@example.com",
            "display_name": "Richard duplicado",
            "password": "outra-senha-segura-123",
        },
    )
    assert duplicate.status_code == 409


def test_managed_user_routes_require_a_session(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/admin/users").status_code == 401
    assert client.post("/api/admin/users", json={}).status_code == 401
    assert client.delete("/api/admin/users/00000000-0000-0000-0000-000000000001").status_code == 401
