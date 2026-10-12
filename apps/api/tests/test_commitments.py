from calendar import monthrange
from datetime import timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.finance_engine import current_financial_date


def setup_commitment_finances(client: TestClient) -> tuple[str, str, str, str]:
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "compromissos@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert setup.status_code == 201
    account = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance": "1000.00",
            "opening_balance_date": "2026-01-01",
        },
    ).json()
    expense = client.post("/api/categories", json={"name": "Moradia", "type": "EXPENSE"}).json()
    income = client.post("/api/categories", json={"name": "Salário", "type": "INCOME"}).json()
    return account["id"], expense["id"], income["id"], account["balance"]


def test_planned_commitments_are_forecast_then_recorded_once_when_paid(client: TestClient) -> None:
    account_id, expense_category, income_category, _ = setup_commitment_finances(client)
    today = current_financial_date()
    due_soon = today + timedelta(days=2)
    overdue_date = today - timedelta(days=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    due_soon = min(due_soon, month_end)

    late_bill = client.post(
        "/api/commitments",
        json={
            "account_id": account_id,
            "category_id": expense_category,
            "type": "EXPENSE",
            "description": "Conta atrasada",
            "amount": "50.00",
            "due_date": overdue_date.isoformat(),
        },
    )
    bill = client.post(
        "/api/commitments",
        json={
            "account_id": account_id,
            "category_id": expense_category,
            "type": "EXPENSE",
            "description": "Conta de luz",
            "amount": "70.00",
            "due_date": due_soon.isoformat(),
        },
    )
    salary = client.post(
        "/api/commitments",
        json={
            "account_id": account_id,
            "category_id": income_category,
            "type": "INCOME",
            "description": "Salário previsto",
            "amount": "200.00",
            "due_date": due_soon.isoformat(),
        },
    )
    assert late_bill.status_code == bill.status_code == salary.status_code == 201

    summary = client.get("/api/dashboard/summary").json()
    assert summary["checking_balance"] == "1000.00"
    assert summary["forecast_overdue_total"] == "50.00"
    assert summary["forecast_next_7_days_total"] == "70.00"
    assert summary["forecast_rest_of_month_total"] == "0.00"
    assert summary["forecast_payables_total"] == "120.00"
    assert summary["forecast_income_total"] == "200.00"
    assert (
        next(row for row in summary["account_type_balances"] if row["account_type"] == "CHECKING")[
            "projected_balance"
        ]
        == "1080.00"
    )
    assert client.get("/api/transactions").json()["items"] == []

    paid = client.post(f"/api/commitments/{bill.json()['id']}/pay")
    repeated = client.post(f"/api/commitments/{bill.json()['id']}/pay")
    assert paid.status_code == repeated.status_code == 200
    assert paid.json()["transaction_id"] == repeated.json()["transaction_id"]
    assert client.get("/api/accounts").json()[0]["balance"] == "930.00"
    assert client.get("/api/transactions").json()["items"][0]["amount"] == "70.00"
    deleted_payment = client.delete(f"/api/transactions/{paid.json()['transaction_id']}")
    assert deleted_payment.status_code == 204
    assert client.get("/api/accounts").json()[0]["balance"] == "1000.00"
    reset_commitment = next(
        item for item in client.get("/api/commitments").json() if item["id"] == bill.json()["id"]
    )
    assert reset_commitment["transaction_id"] is None
    assert reset_commitment["status"] == "PLANNED"
    assert client.get("/api/dashboard/summary").json()["monthly_expenses"] == "0.00"

    deleted_commitment = client.delete(f"/api/commitments/{bill.json()['id']}")
    assert deleted_commitment.status_code == 204
    assert bill.json()["id"] not in {item["id"] for item in client.get("/api/commitments").json()}


def test_dashboard_keeps_seven_day_due_alerts_across_month_end(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.commitments as commitments_module
    import app.transactions as transactions_module

    current_day = current_financial_date()
    today = current_day.replace(day=monthrange(current_day.year, current_day.month)[1] - 2)
    monkeypatch.setattr(commitments_module, "current_financial_date", lambda: today)
    monkeypatch.setattr(transactions_module, "current_financial_date", lambda: today)
    account_id, expense_category, _, _ = setup_commitment_finances(client)
    due_soon = today.replace(day=monthrange(today.year, today.month)[1]) + timedelta(days=1)
    due_later = due_soon + timedelta(days=6)

    commitments = (
        ("Conta no início do mês", due_soon),
        ("Conta além dos sete dias", due_later),
    )
    for description, due_date in commitments:
        response = client.post(
            "/api/commitments",
            json={
                "account_id": account_id,
                "category_id": expense_category,
                "type": "EXPENSE",
                "description": description,
                "amount": "70.00",
                "due_date": due_date.isoformat(),
            },
        )
        assert response.status_code == 201, response.text

    summary = client.get("/api/dashboard/summary").json()
    assert summary["forecast_end"] == (today + timedelta(days=6)).isoformat()
    assert summary["forecast_next_7_days_total"] == "70.00"
    assert [item["description"] for item in summary["forecast_items"]] == ["Conta no início do mês"]


def test_planned_commitment_requires_owned_active_account_and_matching_category(
    client: TestClient,
) -> None:
    account_id, expense_category, income_category, _ = setup_commitment_finances(client)
    response = client.post(
        "/api/commitments",
        json={
            "account_id": account_id,
            "category_id": income_category,
            "type": "EXPENSE",
            "description": "Conta incompatível",
            "amount": "10.00",
            "due_date": current_financial_date().isoformat(),
        },
    )
    assert response.status_code == 422
    assert client.get("/api/commitments").json() == []
    assert expense_category


def test_open_card_invoice_is_forecast_and_reduces_only_its_selected_account_type(
    client: TestClient,
) -> None:
    account_id, _, _, _ = setup_commitment_finances(client)
    today = current_financial_date()
    due_month = f"{today.year:04d}-{today.month:02d}"
    card = client.post(
        "/api/cards",
        json={
            "name": "Nubank",
            "credit_limit": "5000.00",
            "closing_day": 13,
            "due_day": 20,
            "payment_account_id": account_id,
        },
    )
    assert card.status_code == 201
    invoice = client.put(
        f"/api/cards/{card.json()['id']}/invoices/opening-balance",
        json={"due_month": due_month, "amount": "250.00"},
    )
    assert invoice.status_code == 200

    summary = client.get("/api/dashboard/summary").json()

    assert summary["monthly_expenses"] == "0.00"
    assert summary["checking_balance"] == "1000.00"
    assert summary["forecast_payables_total"] == "250.00"
    assert summary["forecast_unassigned_invoice_total"] == "0.00"
    checking = next(
        row for row in summary["account_type_balances"] if row["account_type"] == "CHECKING"
    )
    assert checking["projected_balance"] == "750.00"
    assert any(
        item["source"] == "CARD_INVOICE"
        and item["amount"] == "250.00"
        and item["credit_card_id"] == card.json()["id"]
        and item["id"] == f"invoice:{invoice.json()['id']}"
        for item in summary["forecast_items"]
    )


def test_upcoming_card_invoices_are_sorted_by_due_date_and_exclude_paid_invoices(
    client: TestClient,
) -> None:
    account_id, _, _, _ = setup_commitment_finances(client)
    today = current_financial_date()
    due_month = f"{today.year:04d}-{today.month:02d}"

    def create_card(name: str, due_day: int) -> dict[str, str]:
        response = client.post(
            "/api/cards",
            json={
                "name": name,
                "credit_limit": "5000.00",
                "closing_day": 1,
                "due_day": due_day,
                "payment_account_id": account_id,
            },
        )
        assert response.status_code == 201, response.text
        return cast(dict[str, str], response.json())

    earlier_card = create_card("Cartão com vencimento próximo", 15)
    later_card = create_card("Cartão com vencimento posterior", 28)
    paid_card = create_card("Cartão já pago", 20)

    earlier_invoice = client.put(
        f"/api/cards/{earlier_card['id']}/invoices/opening-balance",
        json={"due_month": due_month, "amount": "120.00"},
    ).json()
    later_invoice = client.put(
        f"/api/cards/{later_card['id']}/invoices/opening-balance",
        json={"due_month": due_month, "amount": "80.00"},
    ).json()
    paid_invoice = client.put(
        f"/api/cards/{paid_card['id']}/invoices/opening-balance",
        json={"due_month": due_month, "amount": "40.00"},
    ).json()
    payment = client.post(
        f"/api/invoices/{paid_invoice['id']}/payments",
        json={"account_id": account_id, "amount": "40.00", "occurred_at": today.isoformat()},
    )
    assert payment.status_code == 201, payment.text

    upcoming = client.get("/api/cards/invoices/upcoming")

    assert upcoming.status_code == 200, upcoming.text
    rows = upcoming.json()
    assert [row["id"] for row in rows] == [earlier_invoice["id"], later_invoice["id"]]
    assert [row["due_date"] for row in rows] == sorted(row["due_date"] for row in rows)
    assert all(row["outstanding"] != "0.00" for row in rows)
