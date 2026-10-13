from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.finance_engine import financial_day_start
from app.models import Account, Category, Transaction, User

CSV_HEADER = "data;descricao;tipo;valor;conta;categoria\n"


def _setup_finances(
    client: TestClient,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    setup = client.post(
        "/api/auth/setup",
        json={
            "email": "importacao@example.com",
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
    )
    assert account.status_code == 201
    expense = client.post("/api/categories", json={"name": "Mercado", "type": "EXPENSE"})
    income = client.post("/api/categories", json={"name": "Salário", "type": "INCOME"})
    assert expense.status_code == income.status_code == 201
    return account.json(), {"expense": expense.json(), "income": income.json()}


def _csv_row(
    *,
    date_value: str = "10/10/2026",
    description: str = "Compra do mercado",
    kind: str = "despesa",
    amount: str = "12,34",
    account: str = "Conta principal",
    category: str = "Mercado",
) -> str:
    return f"{date_value};{description};{kind};{amount};{account};{category}\n"


def test_preview_is_read_only_and_parses_brazilian_decimal(client: TestClient) -> None:
    _setup_finances(client)
    csv_content = CSV_HEADER + _csv_row(amount="1.234,56")

    preview = client.post("/api/imports/transactions/preview", json={"csv_content": csv_content})

    assert preview.status_code == 200
    result = preview.json()
    assert result["row_count"] == 1
    assert result["rows"][0]["row_number"] == 2
    assert result["rows"][0]["amount"] == "1234.56"
    assert result["rows"][0]["type"] == "EXPENSE"
    assert result["rows"][0]["matches"] == []
    assert client.get("/api/transactions").json()["items"] == []


def test_confirmation_requires_review_of_matches_and_repeat_is_rejected(
    client: TestClient,
) -> None:
    account, categories = _setup_finances(client)
    existing = client.post(
        "/api/transactions",
        json={
            "account_id": account["id"],
            "category_id": categories["expense"]["id"],
            "type": "EXPENSE",
            "description": "Compra do mercado",
            "amount": "12.34",
            "occurred_at": "2026-10-10",
        },
    )
    assert existing.status_code == 201
    csv_content = (
        CSV_HEADER
        + _csv_row()
        + _csv_row(
            date_value="11/10/2026",
            description="Pagamento recebido",
            kind="receita",
            amount="50,00",
            category="Salário",
        )
    )
    preview = client.post("/api/imports/transactions/preview", json={"csv_content": csv_content})
    assert preview.status_code == 200
    preview_data = preview.json()
    match = preview_data["rows"][0]["matches"][0]
    assert match["kind"] == "exact"
    assert match["transaction_id"] == existing.json()["id"]

    base_confirmation = {
        "csv_content": csv_content,
        "preview_token": preview_data["preview_token"],
        "confirmed": True,
    }
    missing_decision = client.post("/api/imports/transactions/confirm", json=base_confirmation)
    assert missing_decision.status_code == 422
    assert len(client.get("/api/transactions").json()["items"]) == 1

    confirmation = client.post(
        "/api/imports/transactions/confirm",
        json={**base_confirmation, "decisions": [{"row_number": 2, "action": "SKIP"}]},
    )
    assert confirmation.status_code == 200
    assert confirmation.json()["imported_count"] == 1
    assert confirmation.json()["skipped_count"] == 1
    assert confirmation.json()["imported"][0]["amount"] == "50.00"
    assert len(client.get("/api/transactions").json()["items"]) == 2

    repeated = client.post(
        "/api/imports/transactions/confirm",
        json={**base_confirmation, "decisions": [{"row_number": 2, "action": "SKIP"}]},
    )
    assert repeated.status_code == 409
    assert len(client.get("/api/transactions").json()["items"]) == 2


def test_possible_match_can_be_imported_after_an_explicit_choice(client: TestClient) -> None:
    account, categories = _setup_finances(client)
    existing = client.post(
        "/api/transactions",
        json={
            "account_id": account["id"],
            "category_id": categories["expense"]["id"],
            "type": "EXPENSE",
            "description": "Compra em Mercado Central",
            "amount": "18.50",
            "occurred_at": "2026-10-10",
        },
    )
    assert existing.status_code == 201
    csv_content = CSV_HEADER + _csv_row(description="Compra mercado", amount="18,50")
    preview = client.post(
        "/api/imports/transactions/preview", json={"csv_content": csv_content}
    ).json()
    assert preview["rows"][0]["matches"][0]["kind"] == "similar"

    result = client.post(
        "/api/imports/transactions/confirm",
        json={
            "csv_content": csv_content,
            "preview_token": preview["preview_token"],
            "confirmed": True,
            "decisions": [{"row_number": 2, "action": "IMPORT"}],
        },
    )

    assert result.status_code == 200
    assert result.json()["imported_count"] == 1
    assert result.json()["skipped_count"] == 0
    assert len(client.get("/api/transactions").json()["items"]) == 2


def test_duplicate_rows_inside_csv_are_flagged_before_commit(client: TestClient) -> None:
    _setup_finances(client)
    one_row = _csv_row()
    csv_content = CSV_HEADER + one_row + one_row
    preview = client.post(
        "/api/imports/transactions/preview", json={"csv_content": csv_content}
    ).json()
    assert preview["rows"][1]["matches"][0]["source"] == "csv_row"
    assert preview["rows"][1]["matches"][0]["row_number"] == 2

    result = client.post(
        "/api/imports/transactions/confirm",
        json={
            "csv_content": csv_content,
            "preview_token": preview["preview_token"],
            "confirmed": True,
            "decisions": [{"row_number": 3, "action": "SKIP"}],
        },
    )

    assert result.status_code == 200
    assert result.json()["imported_count"] == 1
    assert result.json()["skipped_count"] == 1


def test_confirmation_requires_explicit_confirmation_and_unchanged_csv(
    client: TestClient,
) -> None:
    _setup_finances(client)
    csv_content = CSV_HEADER + _csv_row()
    preview = client.post(
        "/api/imports/transactions/preview", json={"csv_content": csv_content}
    ).json()

    not_confirmed = client.post(
        "/api/imports/transactions/confirm",
        json={
            "csv_content": csv_content,
            "preview_token": preview["preview_token"],
            "confirmed": False,
        },
    )
    assert not_confirmed.status_code == 409
    assert client.get("/api/transactions").json()["items"] == []

    changed_file = client.post(
        "/api/imports/transactions/confirm",
        json={
            "csv_content": csv_content + _csv_row(date_value="11/10/2026"),
            "preview_token": preview["preview_token"],
            "confirmed": True,
        },
    )
    assert changed_file.status_code == 409
    assert client.get("/api/transactions").json()["items"] == []


def test_csv_rejects_unsupported_movement_and_invalid_money_without_writes(
    client: TestClient,
) -> None:
    _setup_finances(client)
    unsupported = client.post(
        "/api/imports/transactions/preview",
        json={"csv_content": CSV_HEADER + _csv_row(kind="transferência")},
    )
    assert unsupported.status_code == 422

    invalid_money = client.post(
        "/api/imports/transactions/preview",
        json={"csv_content": CSV_HEADER + _csv_row(amount="12.34")},
    )
    assert invalid_money.status_code == 422
    assert client.get("/api/transactions").json()["items"] == []


def test_import_matching_is_limited_to_the_authenticated_user(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _setup_finances(client)
    with test_session_factory() as db:
        other_user = User(
            email="outra-pessoa@example.com",
            display_name="Outra pessoa",
            password_hash="hash-de-teste",
        )
        db.add(other_user)
        db.flush()
        other_account = Account(
            user_id=other_user.id,
            name="Conta principal",
            type="CHECKING",
            opening_balance=Decimal("1000.00"),
            opening_balance_date=date(2026, 1, 1),
        )
        other_category = Category(
            user_id=other_user.id,
            name="Mercado",
            type="EXPENSE",
        )
        db.add_all([other_account, other_category])
        db.flush()
        db.add(
            Transaction(
                user_id=other_user.id,
                account_id=other_account.id,
                category_id=other_category.id,
                type="EXPENSE",
                source="MANUAL",
                status="CONFIRMED",
                description="Compra do mercado",
                amount=Decimal("12.34"),
                occurred_at=financial_day_start(date(2026, 10, 10)),
            )
        )
        db.commit()

    preview = client.post(
        "/api/imports/transactions/preview",
        json={"csv_content": CSV_HEADER + _csv_row()},
    )

    assert preview.status_code == 200
    assert preview.json()["rows"][0]["matches"] == []
    assert client.get("/api/transactions").json()["items"] == []


def test_import_endpoints_require_authenticated_session(client: TestClient) -> None:
    anonymous = TestClient(client.app, headers={"X-SophIA-Request": "1"})

    response = anonymous.post(
        "/api/imports/transactions/preview",
        json={"csv_content": CSV_HEADER + _csv_row()},
    )

    assert response.status_code == 401
