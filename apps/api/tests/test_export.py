from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth import password_hasher
from app.finance_engine import current_financial_date
from app.models import (
    Account,
    CardInvoice,
    Category,
    CreditCard,
    PlannedCommitment,
    RecurrenceOccurrence,
    RecurrenceRule,
    Transaction,
    User,
)


def _setup_user(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": "export-owner@example.com",
            "display_name": "Proprietário",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201


def _seed_other_user(
    session_factory: sessionmaker[Session], today: date
) -> dict[str, list[str]]:
    with session_factory() as db:
        user = User(
            email="export-other@example.com",
            display_name="Outra pessoa",
            password_hash=password_hasher.hash("outra-senha-local-segura"),
        )
        db.add(user)
        db.flush()

        account = Account(
            user_id=user.id,
            name="Conta de outra pessoa",
            type="CHECKING",
            currency="BRL",
            opening_balance=Decimal("321.09"),
            opening_balance_date=today,
        )
        destination = Account(
            user_id=user.id,
            name="Reserva de outra pessoa",
            type="SAVINGS",
            currency="BRL",
            opening_balance=Decimal("500.00"),
            opening_balance_date=today,
        )
        category = Category(user_id=user.id, name="Categoria de outra pessoa", type="EXPENSE")
        db.add_all([account, destination, category])
        db.flush()

        card = CreditCard(
            user_id=user.id,
            name="Cartão de outra pessoa",
            institution="Instituição de teste",
            credit_limit=Decimal("1000.00"),
            currency="BRL",
            closing_day=20,
            due_day=10,
            payment_account_id=account.id,
        )
        db.add(card)
        db.flush()
        invoice = CardInvoice(
            user_id=user.id,
            credit_card_id=card.id,
            period_start=today,
            period_end=today + timedelta(days=5),
            closing_date=today + timedelta(days=5),
            due_date=today + timedelta(days=15),
            opening_balance=Decimal("12.34"),
        )
        rule = RecurrenceRule(
            user_id=user.id,
            account_id=account.id,
            category_id=category.id,
            type="EXPENSE",
            description="Recorrência de outra pessoa",
            amount=Decimal("20.00"),
            currency="BRL",
            frequency="MONTHLY",
            interval=1,
            starts_on=today,
            ends_on=None,
            is_active=True,
        )
        db.add_all([invoice, rule])
        db.flush()

        transaction = Transaction(
            user_id=user.id,
            account_id=account.id,
            category_id=category.id,
            type="EXPENSE",
            source="MANUAL",
            status="CONFIRMED",
            description="Lançamento de outra pessoa",
            amount=Decimal("12.34"),
            occurred_at=datetime.combine(today, datetime.min.time(), UTC),
        )
        commitment = PlannedCommitment(
            user_id=user.id,
            transaction_id=None,
            account_id=account.id,
            category_id=category.id,
            type="EXPENSE",
            description="Compromisso de outra pessoa",
            amount=Decimal("34.56"),
            due_date=today + timedelta(days=2),
            status="PLANNED",
        )
        occurrence = RecurrenceOccurrence(
            user_id=user.id,
            rule_id=rule.id,
            transaction_id=None,
            account_id=account.id,
            category_id=category.id,
            type="EXPENSE",
            description="Ocorrência de outra pessoa",
            amount=Decimal("20.00"),
            due_date=today + timedelta(days=30),
            status="PLANNED",
        )
        db.add_all([transaction, commitment, occurrence])
        db.flush()
        expected_ids = {
            "accounts": [str(account.id), str(destination.id)],
            "categories": [str(category.id)],
            "transactions": [str(transaction.id)],
            "credit_cards": [str(card.id)],
            "card_invoices": [str(invoice.id)],
            "planned_commitments": [str(commitment.id)],
            "recurrence_rules": [str(rule.id)],
            "recurrence_occurrences": [str(occurrence.id)],
        }
        db.commit()
        return expected_ids


def test_export_requires_an_authenticated_session(client: TestClient) -> None:
    response = client.get("/api/export")

    assert response.status_code == 401


def test_export_is_versioned_private_and_serializes_financial_values(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _setup_user(client)
    today = current_financial_date()
    opening_date = today - timedelta(days=30)

    checking = client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "1234.56",
            "opening_balance_date": opening_date.isoformat(),
        },
    ).json()
    savings = client.post(
        "/api/accounts",
        json={
            "name": "Poupança",
            "type": "SAVINGS",
            "opening_balance": "900.00",
            "opening_balance_date": opening_date.isoformat(),
        },
    ).json()
    expense_category = client.post(
        "/api/categories", json={"name": "Mercado", "type": "EXPENSE"}
    ).json()
    income_category = client.post(
        "/api/categories", json={"name": "Salário", "type": "INCOME"}
    ).json()

    expense = client.post(
        "/api/transactions",
        json={
            "account_id": checking["id"],
            "category_id": expense_category["id"],
            "type": "EXPENSE",
            "description": "Compra de teste",
            "amount": "18.75",
            "occurred_at": today.isoformat(),
            "notes": "Observação financeira",
        },
    )
    income = client.post(
        "/api/transactions",
        json={
            "account_id": checking["id"],
            "category_id": income_category["id"],
            "type": "INCOME",
            "description": "Receita de teste",
            "amount": "2000.00",
            "occurred_at": today.isoformat(),
        },
    )
    transfer = client.post(
        "/api/transfers",
        json={
            "source_account_id": checking["id"],
            "destination_account_id": savings["id"],
            "amount": "100.25",
            "occurred_at": today.isoformat(),
        },
    )
    card = client.post(
        "/api/cards",
        json={
            "name": "Cartão principal",
            "institution": "Banco de teste",
            "credit_limit": "5000.00",
            "closing_day": 20,
            "due_day": 10,
            "payment_account_id": checking["id"],
        },
    ).json()
    purchase = client.post(
        "/api/card-purchases",
        json={
            "credit_card_id": card["id"],
            "category_id": expense_category["id"],
            "description": "Compra no cartão",
            "amount": "80.40",
            "occurred_at": today.isoformat(),
        },
    )
    assert purchase.status_code == 201
    payment = client.post(
        f"/api/invoices/{purchase.json()['invoice_id']}/payments",
        json={
            "account_id": checking["id"],
            "amount": "20.00",
            "occurred_at": today.isoformat(),
            "notes": "Pagamento parcial",
        },
    )
    assert payment.status_code == 201

    commitment = client.post(
        "/api/commitments",
        json={
            "account_id": checking["id"],
            "category_id": expense_category["id"],
            "type": "EXPENSE",
            "description": "Conta futura",
            "amount": "45.67",
            "due_date": (today + timedelta(days=2)).isoformat(),
        },
    )
    recurrence = client.post(
        "/api/recurrences",
        json={
            "account_id": checking["id"],
            "category_id": expense_category["id"],
            "type": "EXPENSE",
            "description": "Assinatura mensal",
            "amount": "29.90",
            "frequency": "MONTHLY",
            "interval": 1,
            "starts_on": today.isoformat(),
        },
    )
    assert expense.status_code == income.status_code == transfer.status_code == 201
    assert commitment.status_code == recurrence.status_code == 201

    other_user_ids = _seed_other_user(test_session_factory, today)
    response = client.get("/api/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="sophia-financas-'
    )
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"format", "schema_version", "exported_at", "data"}
    assert payload["format"] == "sophia-finance-export"
    assert payload["schema_version"] == 1
    assert payload["exported_at"].endswith("Z")

    data = payload["data"]
    assert set(data) == {
        "accounts",
        "categories",
        "transactions",
        "credit_cards",
        "card_invoices",
        "planned_commitments",
        "recurrence_rules",
        "recurrence_occurrences",
    }
    own_account = next(row for row in data["accounts"] if row["id"] == checking["id"])
    assert own_account["opening_balance"] == "1234.56"
    assert own_account["opening_balance_date"] == opening_date.isoformat()
    assert own_account["type"] == "CHECKING"

    own_transactions = data["transactions"]
    assert {row["type"] for row in own_transactions} == {
        "INCOME",
        "EXPENSE",
        "TRANSFER",
        "CARD_PURCHASE",
        "CARD_PAYMENT",
    }
    purchase_row = next(row for row in own_transactions if row["id"] == purchase.json()["id"])
    assert purchase_row["amount"] == "80.40"
    assert purchase_row["card_invoice_id"] == purchase.json()["invoice_id"]
    timestamp = purchase_row["occurred_at"]
    assert timestamp.endswith("Z")
    assert datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is not None
    assert next(row for row in own_transactions if row["id"] == payment.json()["id"])["amount"] == (
        "20.00"
    )

    own_invoice = next(
        row for row in data["card_invoices"] if row["id"] == purchase.json()["invoice_id"]
    )
    assert date.fromisoformat(own_invoice["due_date"]) > date.fromisoformat(
        own_invoice["closing_date"]
    )
    assert own_invoice["opening_balance"] == "0.00"
    assert "total" not in own_invoice
    assert data["planned_commitments"][0]["amount"] == "45.67"
    assert data["planned_commitments"][0]["due_date"] == (
        today + timedelta(days=2)
    ).isoformat()
    assert data["recurrence_rules"][0]["amount"] == "29.90"
    assert data["recurrence_occurrences"]
    assert all("user_id" not in row for rows in data.values() for row in rows)

    client.post("/api/auth/logout")
    other_login = client.post(
        "/api/auth/login",
        json={"email": "export-other@example.com", "password": "outra-senha-local-segura"},
    )
    assert other_login.status_code == 200
    other_data = client.get("/api/export").json()["data"]
    for collection, expected_ids in other_user_ids.items():
        assert {row["id"] for row in other_data[collection]} == set(expected_ids)
    assert other_data["transactions"][0]["description"] == "Lançamento de outra pessoa"

    forbidden_fields = {
        "password_hash",
        "password",
        "token",
        "sessions",
        "token_digest",
        "avatar_data",
        "avatar_revision",
        "image",
        "images",
        "image_data",
        "owner_totp_secret",
        "totp_secret",
        "mfa_enrolled_at",
        "provider_api_key",
        "provider_settings",
    }
    assert not forbidden_fields.intersection(payload)
    assert not forbidden_fields.intersection(
        key for rows in data.values() for row in rows for key in row
    )
