from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import transactions as transactions_module
from app.auth import password_hasher
from app.models import (
    Account,
    CardInvoice,
    Category,
    CreditCard,
    FinancialIdempotencyRecord,
    Transaction,
    User,
)
from app.schemas import TransactionCreate

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


def create_card(
    client: TestClient,
    limit: str = "10000.00",
    closing_day: int = 13,
) -> dict[str, object]:
    response = client.post(
        "/api/cards",
        json={
            "name": "Nubank",
            "institution": "Nu Pagamentos",
            "credit_limit": limit,
            "closing_day": closing_day,
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
    card = create_card(client, closing_day=28)
    category_id = create_expense_category(client)

    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Restaurante",
            "amount": "100.00",
            "occurred_at": TODAY,
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


def test_card_read_endpoints_batch_invoice_queries(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    setup_user(client)
    card = create_card(client)
    category_id = create_expense_category(client)
    card_id = cast(str, card["id"])
    today = datetime.now(UTC).astimezone(SAO_PAULO).date()

    def add_purchase(month_offset: int) -> None:
        purchase_date = (
            today.replace(day=min(today.day, 13))
            if month_offset == 0
            else today - timedelta(days=60 * month_offset)
        )
        response = client.post(
            "/api/card-purchases",
            json={
                "credit_card_id": card_id,
                "category_id": category_id,
                "description": f"Compra do ciclo {month_offset}",
                "amount": "10.00",
                "occurred_at": purchase_date.isoformat(),
            },
        )
        assert response.status_code == 201

    def get_with_select_count(path: str) -> tuple[int, object]:
        statements: list[str] = []

        def record_select(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = test_session_factory.kw["bind"]
        event.listen(engine, "before_cursor_execute", record_select)
        try:
            response = client.get(path)
        finally:
            event.remove(engine, "before_cursor_execute", record_select)
        assert response.status_code == 200
        return len(statements), response.json()

    add_purchase(0)
    paths = (
        "/api/cards",
        f"/api/cards/{card_id}/invoices",
        "/api/cards/invoices/upcoming",
        "/api/dashboard/summary",
    )
    counts_with_one_invoice = {path: get_with_select_count(path)[0] for path in paths}

    for month_offset in range(1, 5):
        add_purchase(month_offset)

    counts_with_five_invoices: dict[str, int] = {}
    responses: dict[str, object] = {}
    for path in paths:
        counts_with_five_invoices[path], responses[path] = get_with_select_count(path)

    assert counts_with_five_invoices == counts_with_one_invoice
    cards = cast(list[dict[str, object]], responses["/api/cards"])
    invoices = cast(list[dict[str, object]], responses[f"/api/cards/{card_id}/invoices"])
    upcoming = cast(list[dict[str, object]], responses["/api/cards/invoices/upcoming"])
    assert cards[0]["used_limit"] == "50.00"
    assert cards[0]["available_limit"] == "9950.00"
    assert len(invoices) == 5
    assert all(invoice["total"] == "10.00" for invoice in invoices)
    assert len(upcoming) == 5


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
    card = create_card(client, closing_day=5)
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
        json={"due_month": "2026-11", "amount": "654.63"},
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
        json={"due_month": "2026-11", "amount": "654.63"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["total"] == "654.63"


def test_existing_invoice_balance_can_be_moved_to_its_correct_due_month(
    client: TestClient,
) -> None:
    setup_user(client)
    cards = [
        {
            "name": "Gold",
            "closing_day": 26,
            "due_day": 10,
            "expected": ("2026-09-27", "2026-10-26", "2026-10-26", "2026-11-10"),
        },
        {
            "name": "Cresol",
            "closing_day": 23,
            "due_day": 3,
            "expected": ("2026-09-24", "2026-10-23", "2026-10-23", "2026-11-03"),
        },
    ]

    for card_data in cards:
        card = client.post(
            "/api/cards",
            json={
                "name": card_data["name"],
                "credit_limit": "5000.00",
                "closing_day": card_data["closing_day"],
                "due_day": card_data["due_day"],
            },
        ).json()
        preview = client.get(
            f"/api/cards/{card['id']}/billing-cycle?due_month=2026-11"
        )
        assert preview.status_code == 200, preview.text
        assert (
            preview.json()["period_start"],
            preview.json()["period_end"],
            preview.json()["closing_date"],
            preview.json()["due_date"],
        ) == card_data["expected"]

        imported = client.put(
            f"/api/cards/{card['id']}/invoices/opening-balance",
            json={"due_month": "2026-12", "amount": "654.63"},
        )
        assert imported.status_code == 200, imported.text

        corrected = client.put(
            f"/api/invoices/{imported.json()['id']}/opening-balance",
            json={"due_month": "2026-11", "amount": "654.63"},
        )

        assert corrected.status_code == 200, corrected.text
        invoice = corrected.json()
        assert (
            invoice["period_start"],
            invoice["period_end"],
            invoice["closing_date"],
            invoice["due_date"],
        ) == card_data["expected"]
        assert invoice["opening_balance"] == "654.63"
        assert invoice["total"] == "654.63"
        assert invoice["purchases"] == []
        assert invoice["payments"] == []


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
    assert client.delete(f"/api/transactions/{transaction_id}").status_code == 204
    assert client.get("/api/transactions").json()["items"] == []


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


def test_deleting_paid_card_purchase_cannot_make_payments_exceed_invoice_total(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Compra parcialmente paga",
            "amount": "100.00",
            "occurred_at": TODAY,
        },
    )
    invoice_id = purchase.json()["invoice_id"]
    payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": account["id"], "amount": "40.00", "occurred_at": TODAY},
    )
    assert purchase.status_code == payment.status_code == 201

    deleted = client.delete(f"/api/transactions/{purchase.json()['id']}")

    assert deleted.status_code == 409
    assert client.get(f"/api/invoices/{invoice_id}").json()["outstanding"] == "60.00"
    assert any(
        row["id"] == purchase.json()["id"]
        for row in client.get("/api/transactions").json()["items"]
    )


def test_deleting_fully_paid_purchase_is_blocked(client: TestClient) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Compra quitada",
            "amount": "100.00",
            "occurred_at": TODAY,
        },
    )
    invoice_id = purchase.json()["invoice_id"]
    payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": account["id"], "amount": "100.00", "occurred_at": TODAY},
    )

    deleted = client.delete(f"/api/transactions/{purchase.json()['id']}")

    invoice = client.get(f"/api/invoices/{invoice_id}").json()
    assert purchase.status_code == payment.status_code == 201
    assert deleted.status_code == 409
    assert invoice["total"] == invoice["paid_amount"] == "100.00"
    assert invoice["outstanding"] == "0.00"


def test_purchase_deletion_preserves_reconciliation_when_other_purchase_covers_payment(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    first_purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Compra maior",
            "amount": "100.00",
            "occurred_at": TODAY,
        },
    )
    second_purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Outra compra",
            "amount": "50.00",
            "occurred_at": TODAY,
        },
    )
    invoice_id = first_purchase.json()["invoice_id"]
    payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": account["id"], "amount": "50.00", "occurred_at": TODAY},
    )

    deleted_larger = client.delete(f"/api/transactions/{first_purchase.json()['id']}")
    deleted_last_coverage = client.delete(f"/api/transactions/{second_purchase.json()['id']}")
    invoice = client.get(f"/api/invoices/{invoice_id}").json()

    assert first_purchase.status_code == second_purchase.status_code == payment.status_code == 201
    assert deleted_larger.status_code == 204
    assert deleted_last_coverage.status_code == 409
    assert invoice["total"] == invoice["paid_amount"] == "50.00"
    assert invoice["outstanding"] == "0.00"


def test_financial_idempotency_replays_transactions_transfers_and_invoice_payments(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    destination = create_account(client, "Inter", "500.00")
    category_id = create_expense_category(client)
    card = create_card(client)
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Fatura para pagar",
            "amount": "200.00",
            "occurred_at": TODAY,
        },
    )
    invoice_id = purchase.json()["invoice_id"]
    card_purchase_payload = {
        "credit_card_id": card["id"],
        "category_id": category_id,
        "description": "Compra com retry",
        "amount": "10.00",
        "occurred_at": TODAY,
    }
    card_purchase_headers = {"Idempotency-Key": "card-purchase-retry-0001"}
    first_card_purchase = client.post(
        "/api/card-purchases", json=card_purchase_payload, headers=card_purchase_headers
    )
    retry_card_purchase = client.post(
        "/api/card-purchases", json=card_purchase_payload, headers=card_purchase_headers
    )
    assert first_card_purchase.status_code == retry_card_purchase.status_code == 201
    assert first_card_purchase.json()["id"] == retry_card_purchase.json()["id"]

    transaction_payload = {
        "account_id": account["id"],
        "category_id": category_id,
        "type": "EXPENSE",
        "description": "Mercado",
        "amount": "25.00",
        "occurred_at": TODAY,
    }
    key = "tx-retry-000000001"
    first = client.post(
        "/api/transactions", json=transaction_payload, headers={"Idempotency-Key": key}
    )
    retry = client.post(
        "/api/transactions", json=transaction_payload, headers={"Idempotency-Key": key}
    )
    changed_payload = {**transaction_payload, "amount": "26.00"}
    conflict = client.post(
        "/api/transactions", json=changed_payload, headers={"Idempotency-Key": key}
    )
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert conflict.status_code == 409

    transfer_payload = {
        "source_account_id": account["id"],
        "destination_account_id": destination["id"],
        "amount": "50.00",
        "occurred_at": TODAY,
    }
    transfer_headers = {"Idempotency-Key": "transfer-retry-00001"}
    first_transfer = client.post("/api/transfers", json=transfer_payload, headers=transfer_headers)
    retry_transfer = client.post("/api/transfers", json=transfer_payload, headers=transfer_headers)
    assert first_transfer.status_code == retry_transfer.status_code == 201
    assert first_transfer.json()["id"] == retry_transfer.json()["id"]

    payment_payload = {"account_id": account["id"], "amount": "60.00", "occurred_at": TODAY}
    payment_headers = {"Idempotency-Key": "payment-retry-000001"}
    first_payment = client.post(
        f"/api/invoices/{invoice_id}/payments", json=payment_payload, headers=payment_headers
    )
    retry_payment = client.post(
        f"/api/invoices/{invoice_id}/payments", json=payment_payload, headers=payment_headers
    )
    assert first_payment.status_code == retry_payment.status_code == 201
    assert first_payment.json()["id"] == retry_payment.json()["id"]
    assert client.get(f"/api/invoices/{invoice_id}").json()["paid_amount"] == "60.00"


def test_idempotency_key_remains_reserved_after_transaction_deletion(client: TestClient) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    category_id = create_expense_category(client)
    payload = {
        "account_id": account["id"],
        "category_id": category_id,
        "type": "EXPENSE",
        "description": "Lançamento removido",
        "amount": "25.00",
        "occurred_at": TODAY,
    }
    headers = {"Idempotency-Key": "deleted-movement-retry-0001"}

    created = client.post("/api/transactions", json=payload, headers=headers)
    assert created.status_code == 201
    deleted = client.delete(f"/api/transactions/{created.json()['id']}")
    replay = client.post("/api/transactions", json=payload, headers=headers)
    changed_payload = {**payload, "amount": "26.00"}
    changed_replay = client.post("/api/transactions", json=changed_payload, headers=headers)

    assert deleted.status_code == 204
    assert replay.status_code == 410
    assert changed_replay.status_code == 409
    assert client.get("/api/transactions").json()["items"] == []


def test_idempotency_falls_back_to_legacy_transaction_columns_during_rollback(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    category_id = create_expense_category(client)
    payload = {
        "account_id": account["id"],
        "category_id": category_id,
        "type": "EXPENSE",
        "description": "Retry durante rollback",
        "amount": "25.00",
        "occurred_at": TODAY,
    }
    key = "legacy-rollback-retry-0001"
    created = client.post(
        "/api/transactions", json=payload, headers={"Idempotency-Key": key}
    )
    assert created.status_code == 201
    transaction_id = UUID(created.json()["id"])

    with test_session_factory() as db:
        transaction = db.get(Transaction, transaction_id)
        assert transaction is not None
        assert transaction.idempotency_operation == "transaction"
        assert transaction.idempotency_key == key
        assert transaction.idempotency_fingerprint is not None
        db.execute(
            delete(FinancialIdempotencyRecord).where(
                FinancialIdempotencyRecord.user_id == transaction.user_id,
                FinancialIdempotencyRecord.operation == "transaction",
                FinancialIdempotencyRecord.idempotency_key == key,
            )
        )
        db.commit()

    replay = client.post("/api/transactions", json=payload, headers={"Idempotency-Key": key})
    changed = client.post(
        "/api/transactions",
        json={**payload, "amount": "26.00"},
        headers={"Idempotency-Key": key},
    )

    assert replay.status_code == 201
    assert replay.json()["id"] == created.json()["id"]
    assert changed.status_code == 409
    assert len(client.get("/api/transactions").json()["items"]) == 1


def test_concurrent_idempotency_retries_create_one_transaction(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = test_session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("A corrida entre sessões independentes é verificada na CI PostgreSQL.")

    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    category_id = create_expense_category(client)
    with test_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "fase2b@example.com"))
        assert user is not None
        user_id = user.id

    payload = TransactionCreate(
        account_id=UUID(account["id"]),
        category_id=UUID(category_id),
        type="EXPENSE",
        description="Retry concorrente",
        amount=Decimal("25.00"),
        occurred_at=TODAY,
    )
    key = "concurrent-retry-key-0001"
    barrier = Barrier(2)
    original_find = transactions_module.find_idempotent_transaction

    def synchronized_find(*args: object, **kwargs: object) -> tuple[Transaction | None, str | None]:
        result = original_find(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(transactions_module, "find_idempotent_transaction", synchronized_find)

    def create_movement() -> str:
        with test_session_factory() as db:
            user = db.get(User, user_id)
            assert user is not None
            result = transactions_module.create_transaction(payload, user, db, key)
            return str(result.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        transaction_ids = list(executor.map(lambda _index: create_movement(), range(2)))

    assert transaction_ids[0] == transaction_ids[1]
    with test_session_factory() as db:
        count = db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                Transaction.description == "Retry concorrente",
            )
        )
    assert count == 1


def test_deleting_invoice_removes_purchases_and_payments_and_reconciles_account(
    client: TestClient,
) -> None:
    setup_user(client)
    account = create_account(client, "Sicredi", "1000.00")
    card = create_card(client)
    category_id = create_expense_category(client)
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": category_id,
            "description": "Compra lançada errada",
            "amount": "110.00",
            "occurred_at": TODAY,
        },
    )
    invoice_id = purchase.json()["invoice_id"]
    payment = client.post(
        f"/api/invoices/{invoice_id}/payments",
        json={"account_id": account["id"], "amount": "40.00", "occurred_at": TODAY},
    )
    assert purchase.status_code == payment.status_code == 201
    assert client.get("/api/accounts").json()[0]["balance"] == "960.00"
    assert client.delete(f"/api/accounts/{account['id']}").status_code == 409
    assert client.delete(f"/api/cards/{card['id']}").status_code == 409
    assert client.delete(f"/api/categories/{category_id}").status_code == 409

    deleted = client.delete(f"/api/invoices/{invoice_id}")

    assert deleted.status_code == 204
    assert client.get(f"/api/invoices/{invoice_id}").status_code == 404
    assert client.get("/api/transactions").json()["items"] == []
    assert client.get("/api/accounts").json()[0]["balance"] == "1000.00"
    assert client.get("/api/accounts").json()[0]["balance"] == "1000.00"
    assert client.get("/api/cards").json()[0]["used_limit"] == "0.00"
    assert client.delete(f"/api/cards/{card['id']}").status_code == 204
    assert client.delete(f"/api/accounts/{account['id']}").status_code == 204
    assert client.delete(f"/api/categories/{category_id}").status_code == 204


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
