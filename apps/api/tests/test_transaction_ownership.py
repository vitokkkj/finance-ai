from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth import password_hasher
from app.models import Account, Category, Transaction, User

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def test_a_user_cannot_read_update_or_reference_another_users_financial_records(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    first_user = client.post(
        "/api/auth/setup",
        json={
            "email": "primeiro@example.com",
            "display_name": "Primeiro usuário",
            "password": "uma-senha-local-segura",
        },
    )
    assert first_user.status_code == 201
    first_account = client.post(
        "/api/accounts",
        json={
            "name": "Conta própria",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    first_category = client.post("/api/categories", json={"name": "Própria", "type": "EXPENSE"})
    today = datetime.now(UTC).astimezone(SAO_PAULO).date()

    with test_session_factory() as db:
        second = User(
            email="segundo@example.com",
            display_name="Segundo usuário",
            password_hash=password_hasher.hash("outra-senha-local-segura"),
        )
        db.add(second)
        db.flush()
        second_account = Account(
            user_id=second.id,
            name="Conta de outra pessoa",
            type="CHECKING",
            currency="BRL",
            opening_balance=Decimal("500.00"),
            opening_balance_date=today,
        )
        second_category = Category(user_id=second.id, name="Outra", type="EXPENSE")
        db.add_all([second_account, second_category])
        db.flush()
        foreign_transaction = Transaction(
            user_id=second.id,
            account_id=second_account.id,
            category_id=second_category.id,
            type="EXPENSE",
            source="MANUAL",
            status="CONFIRMED",
            description="Registro de outra pessoa",
            amount=Decimal("12.34"),
            occurred_at=datetime.now(UTC).astimezone(SAO_PAULO),
        )
        db.add(foreign_transaction)
        db.commit()
        foreign_account_id = str(second_account.id)
        foreign_category_id = str(second_category.id)
        foreign_transaction_id = str(foreign_transaction.id)

    client.post("/api/auth/logout")
    other_login = client.post(
        "/api/auth/login",
        json={"email": "segundo@example.com", "password": "outra-senha-local-segura"},
    )
    assert other_login.status_code == 200
    assert len(client.get("/api/transactions").json()) == 1
    client.post("/api/auth/logout")

    own_login = client.post(
        "/api/auth/login",
        json={"email": "primeiro@example.com", "password": "uma-senha-local-segura"},
    )
    assert own_login.status_code == 200
    assert client.get("/api/transactions").json() == []
    assert (
        client.patch(
            f"/api/transactions/{foreign_transaction_id}",
            json={"description": "Tentativa de alteração"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/transactions/{foreign_transaction_id}").status_code == 404

    foreign_account = client.post(
        "/api/transactions",
        json={
            "account_id": foreign_account_id,
            "category_id": first_category.json()["id"],
            "type": "EXPENSE",
            "description": "Referência cruzada",
            "amount": "10.00",
            "occurred_at": today.isoformat(),
        },
    )
    assert foreign_account.status_code == 404
    foreign_category = client.post(
        "/api/transactions",
        json={
            "account_id": first_account.json()["id"],
            "category_id": foreign_category_id,
            "type": "EXPENSE",
            "description": "Referência cruzada",
            "amount": "10.00",
            "occurred_at": today.isoformat(),
        },
    )
    assert foreign_category.status_code == 404
