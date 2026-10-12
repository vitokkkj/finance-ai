from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth import password_hasher
from app.finance_engine import current_financial_date
from app.models import RecurrenceOccurrence, RecurrenceRule, User
from app.recurrences import extend_active_occurrences, scheduled_dates


def setup_user(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": "recorrencias@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201


def setup_references(client: TestClient, starts_on: date) -> tuple[str, str]:
    account = client.post(
        "/api/accounts",
        json={
            "name": "Sicredi",
            "type": "CHECKING",
            "opening_balance": "1000.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    category = client.post("/api/categories", json={"name": "Moradia", "type": "EXPENSE"})
    assert account.status_code == 201
    assert category.status_code == 201
    assert starts_on >= date.fromisoformat(account.json()["opening_balance_date"])
    return cast(str, account.json()["id"]), cast(str, category.json()["id"])


def create_recurrence(
    client: TestClient,
    *,
    account_id: str,
    category_id: str,
    starts_on: date,
    frequency: str = "MONTHLY",
    amount: str = "120.00",
) -> dict[str, object]:
    response = client.post(
        "/api/recurrences",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "type": "EXPENSE",
            "description": "Internet",
            "amount": amount,
            "frequency": frequency,
            "interval": 1,
            "starts_on": starts_on.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_schedule_dates_anchor_month_end_and_leap_day() -> None:
    assert scheduled_dates(
        frequency="MONTHLY",
        interval=1,
        starts_on=date(2026, 1, 31),
        through=date(2026, 4, 30),
    ) == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    assert scheduled_dates(
        frequency="YEARLY",
        interval=1,
        starts_on=date(2024, 2, 29),
        through=date(2026, 2, 28),
    ) == [date(2024, 2, 29), date(2025, 2, 28), date(2026, 2, 28)]
    assert scheduled_dates(
        frequency="WEEKLY",
        interval=2,
        starts_on=date(2026, 1, 5),
        through=date(2026, 1, 31),
    ) == [date(2026, 1, 5), date(2026, 1, 19)]


def test_create_generates_a_rolling_occurrence_horizon_idempotently(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
        frequency="DAILY",
    )

    rows = client.get(
        "/api/recurrences/occurrences",
        params={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=90)).isoformat(),
        },
    ).json()
    assert len(rows) == 91
    assert rows[0]["status"] == "PENDING"
    assert rows[1]["status"] == "PLANNED"
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/dashboard/summary").json()["monthly_expenses"] == "0.00"

    with test_session_factory() as db:
        assert extend_active_occurrences(db, today=today) == 0
        persisted_rule = db.get(RecurrenceRule, UUID(cast(str, rule["id"])))
        assert persisted_rule is not None
        assert persisted_rule.amount == Decimal("120.00")


def test_occurrence_status_tracks_sao_paulo_local_date(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.recurrences as recurrence_module

    today = date(2026, 10, 8)
    monkeypatch.setattr(recurrence_module, "current_financial_date", lambda: today)
    setup_user(client)
    account_id, category_id = setup_references(client, today)
    create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
    )

    tomorrow = today + timedelta(days=1)
    monkeypatch.setattr(recurrence_module, "current_financial_date", lambda: tomorrow)
    rows = client.get(
        "/api/recurrences/occurrences",
        params={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=31)).isoformat(),
        },
    ).json()
    assert rows[0]["status"] == "OVERDUE"
    assert all(row["status"] == "PLANNED" for row in rows[1:])


def test_occurrence_lookup_by_id_includes_old_overdue_items(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.recurrences as recurrence_module

    today = date(2026, 10, 11)
    monkeypatch.setattr(recurrence_module, "current_financial_date", lambda: today)
    setup_user(client)
    account_id, category_id = setup_references(client, today)
    create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
    )
    current_occurrence = client.get(
        "/api/recurrences/occurrences",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
    ).json()[0]
    old_due_date = today - timedelta(days=60)
    with test_session_factory() as db:
        occurrence = db.get(RecurrenceOccurrence, UUID(cast(str, current_occurrence["id"])))
        assert occurrence is not None
        occurrence.due_date = old_due_date
        db.commit()

    old_rows = client.get(
        "/api/recurrences/occurrences",
        params={"start_date": old_due_date.isoformat(), "end_date": old_due_date.isoformat()},
    ).json()
    old_occurrence = old_rows[0]
    assert old_occurrence["status"] == "OVERDUE"
    assert old_occurrence["id"] not in {
        item["id"] for item in client.get("/api/recurrences/occurrences").json()
    }

    focused_rows = client.get(
        "/api/recurrences/occurrences",
        params={"occurrence_id": old_occurrence["id"]},
    )
    assert focused_rows.status_code == 200
    assert [item["id"] for item in focused_rows.json()] == [old_occurrence["id"]]


def test_paying_an_occurrence_creates_one_confirmed_transaction(
    client: TestClient,
) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
    )
    occurrence = client.get(
        "/api/recurrences/occurrences",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
    ).json()[0]
    path = f"/api/recurrences/{rule['id']}/occurrences/{occurrence['id']}/pay"

    first = client.post(path)
    second = client.post(path)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "PAID"
    assert first.json()["transaction_id"] == second.json()["transaction_id"]
    transactions = client.get("/api/transactions").json()
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "120.00"
    assert client.get("/api/dashboard/summary").json()["monthly_expenses"] == "120.00"
    deleted = client.delete(f"/api/transactions/{transactions[0]['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/transactions").json() == []
    occurrence_after_delete = client.get(
        "/api/recurrences/occurrences",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
    ).json()[0]
    assert occurrence_after_delete["transaction_id"] is None
    assert occurrence_after_delete["status"] == "PENDING"
    assert client.get("/api/dashboard/summary").json()["monthly_expenses"] == "0.00"


def test_deleting_recurrence_removes_generated_transactions_and_occurrences(
    client: TestClient,
) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client, account_id=account_id, category_id=category_id, starts_on=today
    )
    occurrence = client.get(
        "/api/recurrences/occurrences",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
    ).json()[0]
    paid = client.post(f"/api/recurrences/{rule['id']}/occurrences/{occurrence['id']}/pay")
    assert paid.status_code == 200

    deleted = client.delete(f"/api/recurrences/{rule['id']}")

    assert deleted.status_code == 204
    assert client.get("/api/recurrences").json() == []
    assert client.get("/api/recurrences/occurrences").json() == []
    assert client.get("/api/transactions").json() == []


def test_occurrence_scope_updates_only_the_requested_series_range(client: TestClient) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
    )
    rows = client.get(
        "/api/recurrences/occurrences",
        params={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=90)).isoformat(),
        },
    ).json()
    selected = rows[1]

    updated = client.patch(
        f"/api/recurrences/{rule['id']}/occurrences/{selected['id']}",
        json={"scope": "THIS_AND_FUTURE", "amount": "145.50"},
    )
    assert updated.status_code == 200
    current_rows = client.get(
        "/api/recurrences/occurrences",
        params={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=90)).isoformat(),
        },
    ).json()
    assert current_rows[0]["amount"] == "120.00"
    assert all(row["amount"] == "145.50" for row in current_rows[1:])
    assert client.get("/api/recurrences").json()[0]["amount"] == "145.50"


def test_skipping_an_occurrence_does_not_create_a_transaction(client: TestClient) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
    )
    occurrence = client.get(
        "/api/recurrences/occurrences",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
    ).json()[0]

    skipped = client.post(f"/api/recurrences/{rule['id']}/occurrences/{occurrence['id']}/skip")
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "SKIPPED"
    assert client.get("/api/transactions").json() == []


def test_shortening_rule_end_cancels_occurrences_after_new_end(client: TestClient) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
        frequency="DAILY",
    )

    updated = client.patch(
        f"/api/recurrences/{rule['id']}",
        json={"ends_on": (today + timedelta(days=2)).isoformat()},
    )
    assert updated.status_code == 200
    rows = client.get(
        "/api/recurrences/occurrences",
        params={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=4)).isoformat(),
        },
    ).json()
    assert [row["status"] for row in rows] == [
        "PENDING",
        "PLANNED",
        "PLANNED",
        "CANCELLED",
        "CANCELLED",
    ]


def test_recurrences_are_private_to_the_authenticated_user(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    setup_user(client)
    today = current_financial_date()
    account_id, category_id = setup_references(client, today)
    rule = create_recurrence(
        client,
        account_id=account_id,
        category_id=category_id,
        starts_on=today,
    )
    with test_session_factory() as db:
        second_user = User(
            email="outra-recorrencia@example.com",
            display_name="Outra pessoa",
            password_hash=password_hasher.hash("outra-senha-local-segura"),
        )
        db.add(second_user)
        db.commit()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"email": "outra-recorrencia@example.com", "password": "outra-senha-local-segura"},
    )
    assert login.status_code == 200
    assert client.get("/api/recurrences").json() == []
    inaccessible = client.patch(f"/api/recurrences/{rule['id']}", json={"amount": "1.00"})
    assert inaccessible.status_code == 404
