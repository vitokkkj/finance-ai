from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth import password_hasher
from app.models import Account, CardInvoice, Category, CreditCard, Transaction, User

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
TODAY = datetime.now(UTC).astimezone(SAO_PAULO).date().isoformat()


def setup_user(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": "fase2b@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201


def create_account(client: TestClient, name: str, balance: str) -> dict[str, str]:
    response = client.post(
        "/api/accounts",
        json={
            "name": name,
            "type": "CHECKING",
            "opening_balance": balance,
            "opening_balance_date": "2026-01-01",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, str], response.json())


def create_card(client: TestClient, limit: str = "10000.00") -> dict[str, object]:
    response = client.post(
        "/api/cards",
        json={
            "name": "Nubank",
            "institution": "Nu Pagamentos",
            "credit_limit": limit,
            "closing_day": 13,
            "due_day": 20,
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def create_expense_category(client: TestClient) -> str:
    response = client.post("/api/categories", json={"name": "Alimentação", "type": "EXPENSE"})
    assert response.status_code == 201
    return cast(str, response.json()["id"])


def test_transfer_changes_only_the_two_account_balances(client: TestClient) -> None:
    setup_user(client)
    sicredi = create_account(client, "Sicredi", "5000.00")
    inter = create_account(client, "Inter", "1000.00")

    transfer = client.post(
        "/api/transfers",
        json={
            "source_account_id": sicredi["id"],
            "destination_account_id": inter["id"],
            "amount": "500.00",
            "occurred_at": TODAY,
            "notes": "Reserva",
        },
    )

    assert transfer.status_code == 201
    assert transfer.json()["type"] == "TRANSFER"
    accounts = {
        account["name"]: account["balance"] for account in client.get("/api/accounts").json()
    }
    assert accounts == {"Sicredi": "4500.00", "Inter": "1500.00"}
    summary = client.get("/api/dashboard/summary").json()
    assert summary["checking_balance"] == "6000.00"
    assert summary["monthly_income"] == "0.00"
    assert summary["monthly_expenses"] == "0.00"
    assert summary["monthly_result"] == "0.00"


def test_card_purchase_creates_one_expense_and_does_not_change_bank_balance(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "5000.00")
    card = create_card(client)
    category_id = create_expense_category(client)

    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Restaurante",
            "amount": "100.00",
            "occurred_at": "2026-10-08",
        },
    )

    assert purchase.status_code == 201
    assert purchase.json()["type"] == "CARD_PURCHASE"
    assert client.get("/api/accounts").json()[0]["balance"] == "5000.00"
    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert summary["checking_balance"] == "5000.00"
    assert summary["monthly_expenses"] == "100.00"
    assert summary["monthly_income"] == "0.00"
    assert summary["monthly_result"] == "-100.00"
    invoices = client.get(f"/api/cards/{card['id']}/invoices").json()
    assert len(invoices) == 1
    assert invoices[0]["total"] == "100.00"
    assert invoices[0]["outstanding"] == "100.00"
    assert invoices[0]["status"] == "OPEN"
    cards = client.get("/api/cards").json()
    assert cards[0]["used_limit"] == "100.00"
    assert cards[0]["available_limit"] == "9900.00"
    assert account["id"] in {item["id"] for item in client.get("/api/accounts").json()}


def test_acceptance_transfer_card_purchase_and_invoice_payment_are_not_double_counted(
    client: TestClient,
) -> None:
    setup_user(client)
    sicredi = create_account(client, "Sicredi", "5000.00")
    inter = create_account(client, "Inter", "1000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    assert (
        client.post(
            "/api/transfers",
            json={
                "source_account_id": sicredi["id"],
                "destination_account_id": inter["id"],
                "amount": "500.00",
                "occurred_at": "2026-10-08",
            },
        ).status_code
        == 201
    )
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Restaurante",
            "amount": "100.00",
            "occurred_at": "2026-10-08",
        },
    )
    assert purchase.status_code == 201
    invoice_id = purchase.json()["invoice_id"]

    payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": sicredi["id"], "amount": "100.00", "occurred_at": TODAY},
    )

    assert payment.status_code == 201
    assert payment.json()["type"] == "CARD_PAYMENT"
    accounts = {
        account["name"]: account["balance"] for account in client.get("/api/accounts").json()
    }
    assert accounts == {"Sicredi": "4400.00", "Inter": "1500.00"}
    invoice = client.get(f"/api/invoices/{invoice_id}").json()
    assert invoice["total"] == "100.00"
    assert invoice["paid_amount"] == "100.00"
    assert invoice["outstanding"] == "0.00"
    assert invoice["status"] == "PAID"
    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert summary["checking_balance"] == "5900.00"
    assert summary["monthly_expenses"] == "100.00"
    assert summary["monthly_result"] == "-100.00"


def test_partial_payment_leaves_invoice_partially_paid_and_limit_used(client: TestClient) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "3000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Compra maior",
            "amount": "1000.00",
            "occurred_at": "2026-10-08",
        },
    )
    invoice_id = purchase.json()["invoice_id"]

    payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": account["id"], "amount": "400.00", "occurred_at": TODAY},
    )

    assert payment.status_code == 201
    invoice = client.get(f"/api/invoices/{invoice_id}").json()
    assert invoice["total"] == "1000.00"
    assert invoice["paid_amount"] == "400.00"
    assert invoice["outstanding"] == "600.00"
    assert invoice["status"] == "PARTIALLY_PAID"
    assert client.get("/api/cards").json()[0]["used_limit"] == "600.00"
    assert client.get("/api/accounts").json()[0]["balance"] == "2600.00"

    final_payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": account["id"], "amount": "600.00", "occurred_at": TODAY},
    )
    assert final_payment.status_code == 201
    invoice = client.get(f"/api/invoices/{invoice_id}").json()
    assert invoice["status"] == "PAID"
    assert invoice["outstanding"] == "0.00"
    assert len(invoice["payments"]) == 2
    assert client.get("/api/cards").json()[0]["used_limit"] == "0.00"


def test_existing_invoice_balance_can_be_imported_and_paid_without_creating_expense(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "2000.00")
    card = create_card(client)

    imported = client.put(
        f"/api/cards/{card['id']}/invoices/opening-balance",
        json={"closing_month": "2026-11", "amount": "654.63"},
    )

    assert imported.status_code == 200
    invoice = imported.json()
    assert invoice["opening_balance"] == "654.63"
    assert invoice["total"] == "654.63"
    assert invoice["outstanding"] == "654.63"
    assert invoice["purchases"] == []
    assert invoice["closing_date"] == "2026-11-13"
    assert invoice["due_date"] == "2026-11-20"
    assert client.get("/api/cards").json()[0]["used_limit"] == "654.63"
    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert summary["monthly_expenses"] == "0.00"

    payment = client.post(
        f"/api/invoices/{invoice['id']}/payments",
        json={"account_id": account["id"], "amount": "654.63", "occurred_at": TODAY},
    )

    assert payment.status_code == 201
    paid_invoice = client.get(f"/api/invoices/{invoice['id']}").json()
    assert paid_invoice["paid_amount"] == "654.63"
    assert paid_invoice["outstanding"] == "0.00"
    assert paid_invoice["status"] == "PAID"
    assert client.get("/api/accounts").json()[0]["balance"] == "1345.37"
    summary = client.get("/api/dashboard/summary?year=2026&month=10").json()
    assert summary["monthly_expenses"] == "0.00"

    repeated = client.put(
        f"/api/cards/{card['id']}/invoices/opening-balance",
        json={"closing_month": "2026-11", "amount": "654.63"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["total"] == "654.63"


def test_card_closing_is_inclusive_and_next_day_moves_to_next_invoice(client: TestClient) -> None:
    setup_user(client)
    card = create_card(client)
    category_id = create_expense_category(client)
    invoice_ids = []
    for date_value in ("2026-09-13", "2026-09-14"):
        response = client.post(
            "/api/card-purchases",
            json={
                "credit_card_id": card["id"],
                "category_id": category_id,
                "description": f"Compra {date_value}",
                "amount": "1.00",
                "occurred_at": date_value,
            },
        )
        assert response.status_code == 201
        invoice_ids.append(response.json()["invoice_id"])

    first = client.get(f"/api/invoices/{invoice_ids[0]}").json()
    second = client.get(f"/api/invoices/{invoice_ids[1]}").json()
    assert first["closing_date"] == "2026-09-13"
    assert first["period_start"] == "2026-08-14"
    assert first["period_end"] == "2026-09-13"
    assert second["closing_date"] == "2026-10-13"
    assert second["period_start"] == "2026-09-14"
    assert second["period_end"] == "2026-10-13"


def test_card_cycle_clamps_short_month_and_moves_due_after_closing(client: TestClient) -> None:
    setup_user(client)
    card = client.post(
        "/api/cards",
        json={
            "name": "Cartão fechamento 31",
            "credit_limit": "5000.00",
            "closing_day": 31,
            "due_day": 20,
        },
    ).json()
    category_id = create_expense_category(client)
    invoice_ids = []
    for date_value in ("2026-02-28", "2026-03-01"):
        response = client.post(
            "/api/card-purchases",
            json={
                "credit_card_id": card["id"],
                "category_id": category_id,
                "description": f"Compra {date_value}",
                "amount": "1.00",
                "occurred_at": date_value,
            },
        )
        assert response.status_code == 201
        invoice_ids.append(response.json()["invoice_id"])

    february = client.get(f"/api/invoices/{invoice_ids[0]}").json()
    march = client.get(f"/api/invoices/{invoice_ids[1]}").json()
    assert february["closing_date"] == "2026-02-28"
    assert february["period_start"] == "2026-02-01"
    assert february["due_date"] == "2026-03-20"
    assert march["closing_date"] == "2026-03-31"
    assert march["period_start"] == "2026-03-01"
    assert march["due_date"] == "2026-04-20"


def test_transfer_and_card_endpoints_enforce_ownership(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    setup_user(client)
    own_account = create_account(client, "Minha conta", "1000.00")
    own_card = create_card(client)
    category_id = create_expense_category(client)
    own_purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": own_card["id"],
            "category_id": category_id,
            "description": "Compra minha",
            "amount": "50.00",
            "occurred_at": "2026-10-08",
        },
    )
    own_invoice_id = own_purchase.json()["invoice_id"]

    with test_session_factory() as db:
        other = User(
            email="outro-fase2b@example.com",
            display_name="Outra pessoa",
            password_hash=password_hasher.hash("outra-senha-local-segura"),
        )
        db.add(other)
        db.flush()
        foreign_account = Account(
            user_id=other.id,
            name="Conta estrangeira",
            type="CHECKING",
            currency="BRL",
            opening_balance=Decimal("500.00"),
            opening_balance_date=datetime.fromisoformat(TODAY).date(),
        )
        foreign_card = CreditCard(
            user_id=other.id,
            name="Cartão estrangeiro",
            institution=None,
            credit_limit=Decimal("2000.00"),
            currency="BRL",
            closing_day=13,
            due_day=20,
        )
        foreign_category = Category(user_id=other.id, name="Outra categoria", type="EXPENSE")
        db.add_all([foreign_account, foreign_card, foreign_category])
        db.flush()
        foreign_invoice_record = CardInvoice(
            user_id=other.id,
            credit_card_id=foreign_card.id,
            period_start=datetime(2026, 8, 14).date(),
            period_end=datetime(2026, 9, 13).date(),
            closing_date=datetime(2026, 9, 13).date(),
            due_date=datetime(2026, 9, 20).date(),
        )
        db.add(foreign_invoice_record)
        db.flush()
        db.add(
            Transaction(
                user_id=other.id,
                type="CARD_PURCHASE",
                source="MANUAL",
                status="CONFIRMED",
                category_id=foreign_category.id,
                card_invoice_id=foreign_invoice_record.id,
                description="Compra de outra pessoa",
                amount=Decimal("25.00"),
                occurred_at=datetime(2026, 9, 13, tzinfo=SAO_PAULO).astimezone(UTC),
            )
        )
        db.commit()
        foreign_account_id = str(foreign_account.id)
        foreign_card_id = str(foreign_card.id)
        foreign_invoice_id = str(foreign_invoice_record.id)

    transfer = client.post(
        "/api/transfers",
        json={
            "source_account_id": own_account["id"],
            "destination_account_id": foreign_account_id,
            "amount": "25.00",
            "occurred_at": TODAY,
        },
    )
    foreign_purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": foreign_card_id,
            "category_id": category_id,
            "description": "Tentativa cruzada",
            "amount": "25.00",
            "occurred_at": TODAY,
        },
    )
    foreign_invoice = client.get(f"/api/cards/{foreign_card_id}/invoices")
    foreign_invoice_detail = client.get(f"/api/invoices/{foreign_invoice_id}")
    foreign_invoice_payments = client.get(f"/api/invoices/{foreign_invoice_id}/payments")
    foreign_payment = client.post(
        f"/api/invoices/{foreign_invoice_id}/payments",
        json={"account_id": own_account["id"], "amount": "25.00", "occurred_at": TODAY},
    )

    assert transfer.status_code == 404
    assert foreign_purchase.status_code == 404
    assert foreign_invoice.status_code == 404
    assert foreign_invoice_detail.status_code == 404
    assert foreign_invoice_payments.status_code == 404
    assert foreign_payment.status_code == 404
    assert all(card["id"] != foreign_card_id for card in client.get("/api/cards").json())
    upcoming_invoice_ids = {
        invoice["id"] for invoice in client.get("/api/cards/invoices/upcoming").json()
    }
    assert own_invoice_id in upcoming_invoice_ids
    assert foreign_invoice_id not in upcoming_invoice_ids
    assert client.get(f"/api/invoices/{own_invoice_id}/payments").json() == []


def test_specialized_movements_cannot_be_changed_through_manual_transaction_endpoints(
    client: TestClient,
) -> None:
    setup_user(client)
    source = create_account(client, "Origem", "100.00")
    destination = create_account(client, "Destino", "0.00")
    response = client.post(
        "/api/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": "10.00",
            "occurred_at": TODAY,
        },
    )
    transaction_id = response.json()["id"]

    assert (
        client.patch(
            f"/api/transactions/{transaction_id}", json={"description": "Quebrar vínculo"}
        ).status_code
        == 409
    )
    assert client.delete(f"/api/transactions/{transaction_id}").status_code == 409


def test_transfer_rejects_same_account_and_card_payment_rejects_overpayment(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    same_account = client.post(
        "/api/transfers",
        json={
            "source_account_id": account["id"],
            "destination_account_id": account["id"],
            "amount": "10.00",
            "occurred_at": TODAY,
        },
    )
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Compra",
            "amount": "100.00",
            "occurred_at": "2026-10-08",
        },
    )
    overpayment = client.post(
        f"/api/invoices/{purchase.json()['invoice_id']}/payments",
        json={"account_id": account["id"], "amount": "100.01", "occurred_at": TODAY},
    )

    assert same_account.status_code == 422
    assert overpayment.status_code == 422


def test_phase_2b_money_inputs_reject_json_numbers(client: TestClient) -> None:
    setup_user(client)
    card = client.post(
        "/api/cards",
        json={
            "name": "Nubank",
            "credit_limit": 10000.0,
            "closing_day": 13,
            "due_day": 20,
        },
    )
    account = create_account(client, "Sicredi", "1000.00")
    transfer = client.post(
        "/api/transfers",
        json={
            "source_account_id": account["id"],
            "destination_account_id": account["id"],
            "amount": 1.0,
            "occurred_at": TODAY,
        },
    )

    assert card.status_code == 422
    assert transfer.status_code == 422
