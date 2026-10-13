from fastapi.testclient import TestClient


def setup_finances(client: TestClient) -> tuple[str, str, str]:
    user = client.post(
        "/api/auth/setup",
        json={
            "email": "usuario@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert user.status_code == 201
    account = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance": "5000.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    assert account.status_code == 201
    expense_category = client.post(
        "/api/categories", json={"name": "Alimentação", "type": "EXPENSE"}
    )
    income_category = client.post("/api/categories", json={"name": "Salário", "type": "INCOME"})
    assert expense_category.status_code == 201
    assert income_category.status_code == 201
    return account.json()["id"], expense_category.json()["id"], income_category.json()["id"]


def test_dashboard_calculates_exact_balance_and_monthly_result(client: TestClient) -> None:
    account_id, expense_category_id, income_category_id = setup_finances(client)

    expense = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": expense_category_id,
            "type": "EXPENSE",
            "description": "Restaurante",
            "amount": "75.00",
            "occurred_at": "2026-10-08",
        },
    )
    assert expense.status_code == 201
    assert expense.json()["amount"] == "75.00"

    first_summary = client.get("/api/dashboard/summary?year=2026&month=10")
    assert first_summary.status_code == 200
    assert first_summary.json()["checking_balance"] == "4925.00"
    assert first_summary.json()["incomplete_checking_account_count"] == 0
    assert first_summary.json()["monthly_income"] == "0.00"
    assert first_summary.json()["monthly_expenses"] == "75.00"
    assert first_summary.json()["monthly_result"] == "-75.00"
    assert first_summary.json()["expenses_by_category"] == [
        {"category_id": expense_category_id, "category_name": "Alimentação", "amount": "75.00"}
    ]

    income = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": income_category_id,
            "type": "INCOME",
            "description": "Salário",
            "amount": "1000.00",
            "occurred_at": "2026-10-08",
        },
    )
    assert income.status_code == 201

    final_summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert final_summary["checking_balance"] == "5925.00"
    assert final_summary["monthly_income"] == "1000.00"
    assert final_summary["monthly_expenses"] == "75.00"
    assert final_summary["monthly_result"] == "925.00"


def test_dashboard_hides_consolidated_balance_when_any_active_account_is_incomplete(
    client: TestClient,
) -> None:
    setup_finances(client)
    unknown_account = client.post(
        "/api/accounts",
        json={"name": "Inter", "type": "CHECKING"},
    )
    assert unknown_account.status_code == 201

    summary = client.get("/api/dashboard/summary?year=2026&month=10")

    assert summary.status_code == 200
    assert summary.json()["checking_balance"] is None
    assert summary.json()["incomplete_checking_account_count"] == 1
    assert summary.json()["monthly_income"] == "0.00"
    assert summary.json()["monthly_expenses"] == "0.00"


def test_checking_balance_excludes_savings_and_reports_it_separately(client: TestClient) -> None:
    setup_finances(client)
    savings = client.post(
        "/api/accounts",
        json={
            "name": "Nubank Caixinha",
            "type": "SAVINGS",
            "opening_balance": "3000.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    assert savings.status_code == 201

    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    balances = {row["account_type"]: row for row in summary["account_type_balances"]}

    assert summary["checking_balance"] == "5000.00"
    assert balances["CHECKING"]["balance"] == "5000.00"
    assert balances["SAVINGS"]["balance"] == "3000.00"
    assert balances["SAVINGS"]["projected_balance"] == "3000.00"


def test_unknown_savings_balance_does_not_hide_known_checking_balance(client: TestClient) -> None:
    setup_finances(client)
    savings = client.post("/api/accounts", json={"name": "Reserva", "type": "SAVINGS"})
    assert savings.status_code == 201

    summary = client.get("/api/dashboard/summary").json()

    assert summary["checking_balance"] == "5000.00"
    groups = {row["account_type"]: row for row in summary["account_type_balances"]}
    assert groups["SAVINGS"]["balance"] is None
    assert groups["CHECKING"]["incomplete_account_count"] == 0


def test_transaction_filters_and_month_boundary_use_local_calendar_dates(
    client: TestClient,
) -> None:
    account_id, expense_category_id, income_category_id = setup_finances(client)
    created_ids: dict[str, str] = {}
    movements = [
        ("2026-09-30", "EXPENSE", expense_category_id, "75.00", "Setembro"),
        ("2026-10-01", "EXPENSE", expense_category_id, "25.00", "Outubro"),
        ("2026-10-08", "INCOME", income_category_id, "250.00", "Salário fim do mês"),
    ]
    for occurred_at, kind, category_id, amount, description in movements:
        response = client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "type": kind,
                "description": description,
                "amount": amount,
                "occurred_at": occurred_at,
            },
        )
        assert response.status_code == 201
        created_ids[description] = response.json()["id"]

    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert summary["monthly_income"] == "250.00"
    assert summary["monthly_expenses"] == "25.00"
    assert summary["monthly_result"] == "225.00"

    october_expenses = client.get(
        "/api/transactions",
        params={
            "start_date": "2026-10-01",
            "end_date": "2026-10-08",
            "account_id": account_id,
            "category_id": expense_category_id,
            "type": "EXPENSE",
            "q": "Outubro",
        },
    )
    assert october_expenses.status_code == 200
    assert [row["id"] for row in october_expenses.json()["items"]] == [created_ids["Outubro"]]
