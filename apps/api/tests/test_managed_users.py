from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import User


def test_account_provisioning_routes_are_disabled_and_existing_user_is_preserved(
    client,
    test_session_factory: sessionmaker[Session],
) -> None:
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "gamercreeper74@gmail.com",
            "display_name": "Proprietário",
            "password": "senha-do-proprietario-segura",
        },
    )
    assert setup.status_code == 201
    owner_id = setup.json()["id"]

    assert client.get("/api/admin/users").status_code == 404
    assert client.post(
        "/api/admin/users",
        json={
            "email": "outra@example.com",
            "display_name": "Outra pessoa",
            "password": "outra-senha-segura-123",
        },
    ).status_code == 404

    with test_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        existing_email = db.scalar(select(User.email).where(User.id == UUID(owner_id)))
        assert existing_email == "gamercreeper74@gmail.com"


def test_account_provisioning_routes_are_absent_without_a_session(client) -> None:
    assert client.get("/api/admin/users").status_code == 404
    assert client.post("/api/admin/users", json={}).status_code == 404
