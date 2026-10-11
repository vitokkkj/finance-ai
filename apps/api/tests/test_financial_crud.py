from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient


def test_transactions_and_accounts_can_be_edited_and_history_deleted(client: TestClient) -> None:
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert setup.status_code == 201
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "1000.00",
            "opening_balance_date": "2026-01-01",
        },
    ).json()
    category = client.post("/api/categories", json={"name": "Mercado", "type": "EXPENSE"}).json()
    transaction = client.post(
        "/api/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "type": "EXPENSE",
            "description": "Compra pequena",
            "amount": "100.00",
            "occurred_at": "2026-10-08",
        },
    )
    assert transaction.status_code == 201
    transaction_id = transaction.json()["id"]

    updated = client.patch(
        f"/api/transactions/{transaction_id}",
        json={"description": "Compra corrigida", "amount": "125.00"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Compra corrigida"
    assert updated.json()["amount"] == "125.00"
    assert client.get("/api/accounts").json()[0]["balance"] == "875.00"

    account_update = client.patch(
        f"/api/accounts/{account['id']}", json={"opening_balance": "125.00"}
    )
    assert account_update.status_code == 200
    assert account_update.json()["balance"] == "0.00"

    archived = client.post(f"/api/accounts/{account['id']}/archive")
    assert archived.status_code == 200
    assert client.get("/api/accounts").json() == []
    assert client.get("/api/accounts?include_archived=true").json()[0]["balance"] == "0.00"

    deleted = client.delete(f"/api/transactions/{transaction_id}")
    assert deleted.status_code == 204
    assert client.get("/api/transactions").json() == []


def test_money_inputs_require_exact_decimal_strings(client: TestClient) -> None:
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert setup.status_code == 201
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta",
            "type": "CHECKING",
            "opening_balance": 1200.75,
            "opening_balance_date": "2026-01-01",
        },
    )
    assert account.status_code == 422

    valid_account = client.post(
        "/api/accounts",
        json={
            "name": "Conta",
            "type": "CHECKING",
            "opening_balance": "1200.75",
            "opening_balance_date": "2026-01-01",
        },
    )
    category = client.post("/api/categories", json={"name": "Alimentação", "type": "EXPENSE"})
    transaction = client.post(
        "/api/transactions",
        json={
            "account_id": valid_account.json()["id"],
            "category_id": category.json()["id"],
            "type": "EXPENSE",
            "description": "Almoço",
            "amount": 18.5,
            "occurred_at": datetime.now(UTC)
            .astimezone(ZoneInfo("America/Sao_Paulo"))
            .date()
            .isoformat(),
        },
    )
    assert transaction.status_code == 422
