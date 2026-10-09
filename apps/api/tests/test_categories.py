from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient


def create_user(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201


def test_category_can_be_renamed_and_archived_without_deletion(client: TestClient) -> None:
    create_user(client)

    created = client.post("/api/categories", json={"name": "Alimentação", "type": "EXPENSE"})
    assert created.status_code == 201
    category_id = created.json()["id"]
    assert created.json()["is_archived"] is False

    renamed = client.patch(f"/api/categories/{category_id}", json={"name": "Mercado"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Mercado"

    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    transaction = client.post(
        "/api/transactions",
        json={
            "account_id": account.json()["id"],
            "category_id": category_id,
            "type": "EXPENSE",
            "description": "Lanche",
            "amount": "18.90",
            "occurred_at": datetime.now(UTC)
            .astimezone(ZoneInfo("America/Sao_Paulo"))
            .date()
            .isoformat(),
        },
    )
    assert transaction.status_code == 201

    archived = client.post(f"/api/categories/{category_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True

    assert client.get("/api/categories").json() == []
    history = client.get("/api/categories?include_archived=true")
    assert history.status_code == 200
    assert history.json()[0]["id"] == category_id
    assert history.json()[0]["name"] == "Mercado"
    transactions = client.get("/api/transactions")
    assert transactions.status_code == 200
    assert transactions.json()[0]["id"] == transaction.json()["id"]
    assert transactions.json()[0]["category_name"] == "Mercado"
