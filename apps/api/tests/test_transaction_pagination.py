from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Transaction, User

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _create_financial_owner(client: TestClient) -> tuple[str, str, str, str]:
    today = datetime.now(UTC).astimezone(SAO_PAULO).date().isoformat()
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "paginacao@example.com",
            "display_name": "Pessoa paginada",
            "password": "uma-senha-local-segura",
        },
    )
    assert setup.status_code == 201
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta paginada",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": today,
        },
    )
    category = client.post("/api/categories", json={"name": "Compras", "type": "EXPENSE"})
    other_category = client.post(
        "/api/categories", json={"name": "Transporte", "type": "EXPENSE"}
    )
    assert account.status_code == category.status_code == other_category.status_code == 201
    return (
        account.json()["id"],
        category.json()["id"],
        other_category.json()["id"],
        today,
    )


def _seed_transactions(
    factory: sessionmaker[Session],
    account_id: str,
    category_id: str,
    other_category_id: str,
    *,
    matching_count: int,
) -> list[UUID]:
    now = datetime.now(UTC).astimezone(SAO_PAULO)
    occurred_at = now.replace(hour=12, minute=0, second=0, microsecond=0)
    created_at = now.replace(hour=13, minute=0, second=0, microsecond=123456)
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "paginacao@example.com"))
        assert user is not None
        matching = [
            Transaction(
                id=UUID(int=index),
                user_id=user.id,
                account_id=UUID(account_id),
                category_id=UUID(category_id),
                type="EXPENSE",
                source="MANUAL",
                status="CONFIRMED",
                description=f"Compra alvo {index}",
                amount=Decimal("10.00"),
                occurred_at=occurred_at,
                created_at=created_at,
                updated_at=created_at,
            )
            for index in range(1, matching_count + 1)
        ]
        noise = [
            Transaction(
                id=UUID(int=1000 + index),
                user_id=user.id,
                account_id=UUID(account_id),
                category_id=UUID(other_category_id if index == 1 else category_id),
                type="EXPENSE",
                source="MANUAL",
                status="CONFIRMED",
                description="Ignorar este lançamento",
                amount=Decimal("20.00"),
                occurred_at=occurred_at,
                created_at=created_at,
                updated_at=created_at,
            )
            for index in range(2)
        ]
        db.add_all([*matching, *noise])
        db.commit()
    return [row.id for row in matching]


def test_transaction_cursor_pagination_is_stable_and_preserves_filters(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    account_id, category_id, other_category_id, today = _create_financial_owner(client)
    matching_ids = _seed_transactions(
        test_session_factory, account_id, category_id, other_category_id, matching_count=23
    )
    params: dict[str, str | int] = {
        "start_date": today,
        "end_date": today,
        "account_id": account_id,
        "category_id": category_id,
        "type": "EXPENSE",
        "q": "alvo",
        "limit": 7,
    }
    observed_ids: list[str] = []
    cursors: set[str] = set()
    while True:
        response = client.get("/api/transactions", params=params)
        assert response.status_code == 200
        page = response.json()
        assert page["has_more"] is (page["next_cursor"] is not None)
        observed_ids.extend(row["id"] for row in page["items"])
        assert all(row["category_id"] == category_id for row in page["items"])
        assert all(row["type"] == "EXPENSE" for row in page["items"])
        assert all("alvo" in row["description"].lower() for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert cursor not in cursors
        cursors.add(cursor)
        params["cursor"] = cursor

    expected_ids = [str(transaction_id) for transaction_id in sorted(matching_ids, reverse=True)]
    assert observed_ids == expected_ids
    assert len(observed_ids) == len(set(observed_ids)) == 23
    assert len(cursors) == 3


def test_transaction_pagination_rejects_invalid_cursor_and_limits(client: TestClient) -> None:
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "limites@example.com",
            "display_name": "Pessoa paginada",
            "password": "uma-senha-local-segura",
        },
    )
    assert setup.status_code == 201
    assert client.get("/api/transactions", params={"cursor": "inválido"}).status_code == 422
    assert client.get("/api/transactions", params={"limit": 0}).status_code == 422
    assert client.get("/api/transactions", params={"limit": 101}).status_code == 422
