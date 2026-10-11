from fastapi.testclient import TestClient


def sign_in(client: TestClient, email: str = "usuario@example.com") -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": email,
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201


def test_account_starts_with_exact_opening_balance(client: TestClient) -> None:
    sign_in(client)

    created = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "currency": "BRL",
            "opening_balance": "5000.00",
            "opening_balance_date": "2026-01-01",
        },
    )

    assert created.status_code == 201
    account = created.json()
    assert account["name"] == "Sicredi"
    assert account["opening_balance"] == "5000.00"
    assert account["balance"] == "5000.00"
    assert account["currency"] == "BRL"
    assert account["type"] == "CHECKING"

    listed = client.get("/api/accounts")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == account["id"]


def test_account_can_be_created_before_opening_balance_is_known(client: TestClient) -> None:
    sign_in(client)

    created = client.post(
        "/api/accounts",
        json={"name": "Sicredi", "type": "CHECKING"},
    )

    assert created.status_code == 201
    account = created.json()
    assert account["opening_balance"] is None
    assert account["opening_balance_date"] is None
    assert account["balance"] is None

    summary = client.get("/api/dashboard/summary").json()
    assert summary["checking_balance"] is None
    assert summary["incomplete_checking_account_count"] == 1


def test_manual_expense_is_allowed_without_known_balance_but_base_cannot_skip_it(
    client: TestClient,
) -> None:
    sign_in(client)
    account = client.post(
        "/api/accounts",
        json={"name": "Sicredi", "type": "CHECKING"},
    ).json()
    category = client.post(
        "/api/categories", json={"name": "Combustível", "type": "EXPENSE"}
    ).json()

    expense = client.post(
        "/api/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "type": "EXPENSE",
            "description": "Abastecimento",
            "amount": "87.50",
            "occurred_at": "2026-10-08",
        },
    )

    assert expense.status_code == 201
    account_after_expense = client.get("/api/accounts").json()[0]
    assert account_after_expense["balance"] is None

    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert summary["checking_balance"] is None
    assert summary["incomplete_checking_account_count"] == 1
    assert summary["monthly_expenses"] == "87.50"

    base_after_existing_movement = client.patch(
        f"/api/accounts/{account['id']}",
        json={"opening_balance": "500.00", "opening_balance_date": "2026-10-09"},
    )
    assert base_after_existing_movement.status_code == 422


def test_account_opening_balance_and_date_must_be_set_or_cleared_together(
    client: TestClient,
) -> None:
    sign_in(client)

    missing_date = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance": "0.00",
        },
    )
    missing_amount = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance_date": "2026-01-01",
        },
    )

    assert missing_date.status_code == 422
    assert missing_amount.status_code == 422


def test_clearing_opening_balance_makes_balance_unavailable_until_reentered(
    client: TestClient,
) -> None:
    sign_in(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance": "1250.00",
            "opening_balance_date": "2026-01-01",
        },
    ).json()

    cleared = client.patch(
        f"/api/accounts/{account['id']}",
        json={"opening_balance": None, "opening_balance_date": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["balance"] is None
    assert client.get("/api/dashboard/summary").json()["checking_balance"] is None

    incomplete_patch = client.patch(
        f"/api/accounts/{account['id']}",
        json={"opening_balance": "1250.00"},
    )
    assert incomplete_patch.status_code == 422

    completed = client.patch(
        f"/api/accounts/{account['id']}",
        json={
            "opening_balance": "1250.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["balance"] == "1250.00"
    assert client.get("/api/dashboard/summary").json()["checking_balance"] == "1250.00"


def test_account_with_nonzero_balance_cannot_be_archived(client: TestClient) -> None:
    sign_in(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance": "125.00",
            "opening_balance_date": "2026-01-01",
        },
    ).json()

    archived = client.post(f"/api/accounts/{account['id']}/archive")

    assert archived.status_code == 409
    assert "R$ 0,00" in archived.json()["detail"]
    assert client.get("/api/accounts").json()[0]["is_active"] is True


def test_account_with_unknown_balance_cannot_be_archived(client: TestClient) -> None:
    sign_in(client)
    account = client.post("/api/accounts", json={"name": "Poupança", "type": "SAVINGS"}).json()

    archived = client.post(f"/api/accounts/{account['id']}/archive")

    assert archived.status_code == 409
    assert "saldo inicial" in archived.json()["detail"]
    assert client.get("/api/accounts").json()[0]["is_active"] is True


def test_account_with_zero_balance_can_be_archived(client: TestClient) -> None:
    sign_in(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta encerrada",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    ).json()

    archived = client.post(f"/api/accounts/{account['id']}/archive")

    assert archived.status_code == 200
    assert archived.json()["balance"] == "0.00"
    assert client.get("/api/accounts").json() == []
