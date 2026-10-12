from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.finance_engine import financial_date, financial_day_after, financial_day_start
from app.finance_views import transaction_response
from app.models import Account, Category, Transaction, User
from app.schemas import TransactionResponse
from app.transactions import _transaction_instant, _validate_references

router = APIRouter(prefix="/api/imports", tags=["importação"])

MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 500
PREVIEW_TTL = timedelta(minutes=15)
CSV_HEADERS = ("data", "descricao", "tipo", "valor", "conta", "categoria")
CSV_DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
CSV_MONEY_PATTERN = re.compile(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}\Z")
CSV_TYPES: dict[str, Literal["INCOME", "EXPENSE"]] = {
    "receita": "INCOME",
    "despesa": "EXPENSE",
}


class CSVTransactionImportPreviewRequest(BaseModel):
    csv_content: str = Field(min_length=1, max_length=MAX_CSV_BYTES)


class CSVTransactionImportDecision(BaseModel):
    row_number: int = Field(ge=2)
    action: Literal["IMPORT", "SKIP"]


class CSVTransactionImportCommitRequest(CSVTransactionImportPreviewRequest):
    preview_token: str = Field(min_length=20, max_length=4096)
    confirmed: bool
    decisions: list[CSVTransactionImportDecision] = Field(
        default_factory=list, max_length=MAX_CSV_ROWS
    )


class CSVImportMatch(BaseModel):
    kind: Literal["exact", "similar"]
    source: Literal["transaction", "csv_row"]
    transaction_id: UUID | None = None
    row_number: int | None = None
    description: str
    occurred_at: date
    amount: Decimal

    @field_serializer("amount")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class CSVTransactionImportRowPreview(BaseModel):
    row_number: int
    occurred_at: date
    description: str
    type: Literal["INCOME", "EXPENSE"]
    amount: Decimal
    account_name: str
    category_name: str
    matches: list[CSVImportMatch]
    matches_truncated: bool = False

    @field_serializer("amount")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class CSVTransactionImportPreviewResponse(BaseModel):
    preview_token: str
    expires_at: datetime
    row_count: int
    rows: list[CSVTransactionImportRowPreview]


class CSVTransactionImportCommitResponse(BaseModel):
    imported_count: int
    skipped_count: int
    imported: list[TransactionResponse]


class _CSVImportRow:
    def __init__(
        self,
        *,
        row_number: int,
        occurred_at: date,
        description: str,
        transaction_type: Literal["INCOME", "EXPENSE"],
        amount: Decimal,
        account: Account,
        category: Category,
    ) -> None:
        self.row_number = row_number
        self.occurred_at = occurred_at
        self.description = description
        self.transaction_type = transaction_type
        self.amount = amount
        self.account = account
        self.category = category


def _unprocessable(detail: str) -> NoReturn:
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _parse_date(value: str, row_number: int) -> date:
    normalized = value.strip()
    if not CSV_DATE_PATTERN.fullmatch(normalized):
        _unprocessable(f"Linha {row_number}: informe a data no formato DD/MM/AAAA.")
    try:
        parsed = datetime.strptime(normalized, "%d/%m/%Y").date()
    except ValueError:
        _unprocessable(f"Linha {row_number}: informe a data no formato DD/MM/AAAA.")
    return parsed


def _parse_amount(value: str, row_number: int) -> Decimal:
    normalized = value.strip()
    if not CSV_MONEY_PATTERN.fullmatch(normalized):
        _unprocessable(
            f"Linha {row_number}: informe o valor em reais com vírgula e duas casas decimais, "
            "por exemplo 1.234,56."
        )
    try:
        amount = Decimal(normalized.replace(".", "").replace(",", "."))
    except InvalidOperation:
        _unprocessable(f"Linha {row_number}: o valor não é válido.")
    if amount <= Decimal("0.00") or amount.adjusted() > 11:
        _unprocessable(
            f"Linha {row_number}: o valor precisa ser positivo e ter até 12 dígitos inteiros."
        )
    return amount


def _parse_csv_rows(
    csv_content: str,
    user: User,
    db: Session,
) -> list[_CSVImportRow]:
    encoded = csv_content.encode("utf-8")
    if len(encoded) > MAX_CSV_BYTES:
        _unprocessable("O CSV pode ter no máximo 1 MB.")
    if "\x00" in csv_content:
        _unprocessable("O arquivo contém caracteres inválidos.")

    source = csv_content.removeprefix("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(source, newline=""), delimiter=";", strict=True)
        headers = reader.fieldnames
        if headers is None:
            _unprocessable("O CSV está vazio ou não contém cabeçalho.")
        normalized_headers = [header.strip().casefold() for header in headers]
        if len(normalized_headers) != len(set(normalized_headers)):
            _unprocessable("O CSV contém nomes de coluna repetidos.")
        if tuple(normalized_headers) != CSV_HEADERS:
            _unprocessable(
                "Use o cabeçalho nesta ordem: data;descricao;tipo;valor;conta;categoria."
            )
        reader.fieldnames = normalized_headers
        raw_rows = [(reader.line_num, raw) for raw in reader]
    except csv.Error as error:
        _unprocessable(f"Não foi possível ler o CSV: {error}.")

    accounts_by_name: dict[str, list[Account]] = {}
    accounts = db.scalars(
        select(Account).where(Account.user_id == user.id, Account.is_active.is_(True))
    ).all()
    for account in accounts:
        accounts_by_name.setdefault(_normalized_text(account.name), []).append(account)

    categories_by_name_and_type: dict[tuple[str, str], list[Category]] = {}
    categories = db.scalars(
        select(Category).where(Category.user_id == user.id, Category.archived_at.is_(None))
    ).all()
    for category in categories:
        key = (_normalized_text(category.name), category.type)
        categories_by_name_and_type.setdefault(key, []).append(category)

    parsed_rows: list[_CSVImportRow] = []
    for row_number, raw in raw_rows:
        if raw.get(None):
            _unprocessable(f"Linha {row_number}: há mais campos do que colunas no cabeçalho.")
        values = {header: raw.get(header) for header in CSV_HEADERS}
        if all(not (value or "").strip() for value in values.values()):
            continue
        if any(value is None for value in values.values()):
            _unprocessable(f"Linha {row_number}: todos os seis campos precisam estar preenchidos.")
        data = {key: (value or "").strip() for key, value in values.items()}
        transaction_type = CSV_TYPES.get(data["tipo"].casefold())
        if transaction_type is None:
            _unprocessable(f"Linha {row_number}: o tipo deve ser receita ou despesa.")
        description = data["descricao"]
        if not description or len(description) > 200:
            _unprocessable(f"Linha {row_number}: a descrição precisa ter de 1 a 200 caracteres.")

        account_matches = accounts_by_name.get(_normalized_text(data["conta"]), [])
        if len(account_matches) != 1:
            detail = "não encontrada ou inativa" if not account_matches else "ambígua"
            _unprocessable(f"Linha {row_number}: conta {detail}: {data['conta']}.")
        account = account_matches[0]
        category_matches = categories_by_name_and_type.get(
            (_normalized_text(data["categoria"]), transaction_type), []
        )
        if len(category_matches) != 1:
            detail = (
                "não encontrada, arquivada ou incompatível" if not category_matches else "ambígua"
            )
            _unprocessable(f"Linha {row_number}: categoria {detail}: {data['categoria']}.")
        category = category_matches[0]
        occurred_at = _parse_date(data["data"], row_number)
        amount = _parse_amount(data["valor"], row_number)
        _validate_references(
            user.id,
            account.id,
            category.id,
            transaction_type,
            occurred_at,
            db,
        )
        parsed_rows.append(
            _CSVImportRow(
                row_number=row_number,
                occurred_at=occurred_at,
                description=description,
                transaction_type=transaction_type,
                amount=amount,
                account=account,
                category=category,
            )
        )
        if len(parsed_rows) > MAX_CSV_ROWS:
            _unprocessable(f"O CSV pode conter no máximo {MAX_CSV_ROWS} lançamentos.")

    if not parsed_rows:
        _unprocessable("O CSV não contém lançamentos para importar.")
    return parsed_rows


def _same_movement(left: _CSVImportRow, right: _CSVImportRow | Transaction) -> bool:
    right_type: str
    right_account_id: UUID | None
    if isinstance(right, _CSVImportRow):
        right_date = right.occurred_at
        right_type = right.transaction_type
        right_account_id = right.account.id
        right_amount = right.amount
    else:
        right_date = financial_date(right.occurred_at)
        right_type = right.type
        right_account_id = right.account_id
        right_amount = right.amount
    return (
        left.occurred_at == right_date
        and left.transaction_type == right_type
        and left.account.id == right_account_id
        and left.amount == right_amount
    )


def _find_import_matches(
    rows: list[_CSVImportRow], user_id: UUID, db: Session
) -> list[list[CSVImportMatch]]:
    first_date = min(row.occurred_at for row in rows)
    last_date = max(row.occurred_at for row in rows)
    existing = db.scalars(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.type.in_(("INCOME", "EXPENSE")),
            Transaction.occurred_at >= financial_day_start(first_date),
            Transaction.occurred_at < financial_day_after(last_date),
        )
        .order_by(Transaction.occurred_at, Transaction.created_at, Transaction.id)
    ).all()

    results: list[list[CSVImportMatch]] = []
    previous_rows: list[_CSVImportRow] = []
    for row in rows:
        matches: list[CSVImportMatch] = []
        for transaction in existing:
            if not _same_movement(row, transaction):
                continue
            matches.append(
                CSVImportMatch(
                    kind=(
                        "exact"
                        if _normalized_text(row.description)
                        == _normalized_text(transaction.description)
                        else "similar"
                    ),
                    source="transaction",
                    transaction_id=transaction.id,
                    description=transaction.description,
                    occurred_at=financial_date(transaction.occurred_at),
                    amount=transaction.amount,
                )
            )
        for previous in previous_rows:
            if not _same_movement(row, previous):
                continue
            matches.append(
                CSVImportMatch(
                    kind=(
                        "exact"
                        if _normalized_text(row.description)
                        == _normalized_text(previous.description)
                        else "similar"
                    ),
                    source="csv_row",
                    row_number=previous.row_number,
                    description=previous.description,
                    occurred_at=previous.occurred_at,
                    amount=previous.amount,
                )
            )
        matches.sort(key=lambda item: (item.kind != "exact", item.source != "transaction"))
        results.append(matches)
        previous_rows.append(row)
    return results


def _snapshot_digest(rows: list[_CSVImportRow], matches: list[list[CSVImportMatch]]) -> str:
    snapshot = [
        {
            "row": row.row_number,
            "date": row.occurred_at.isoformat(),
            "description": row.description,
            "type": row.transaction_type,
            "amount": format(row.amount, ".2f"),
            "account_id": str(row.account.id),
            "account_name": row.account.name,
            "category_id": str(row.category.id),
            "category_name": row.category.name,
            "matches": [
                {
                    "kind": match.kind,
                    "source": match.source,
                    "transaction_id": str(match.transaction_id) if match.transaction_id else None,
                    "row_number": match.row_number,
                }
                for match in row_matches
            ],
        }
        for row, row_matches in zip(rows, matches, strict=True)
    ]
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _session_signing_key(request: Request) -> bytes:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária."
        )
    return token.encode("utf-8")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _issue_preview_token(
    request: Request,
    user_id: UUID,
    csv_content: str,
    snapshot: str,
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + PREVIEW_TTL
    claims = {
        "user_id": str(user_id),
        "csv_sha256": hashlib.sha256(csv_content.encode("utf-8")).hexdigest(),
        "snapshot_sha256": snapshot,
        "expires_at": int(expires_at.timestamp()),
    }
    encoded_claims = _base64url(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        _session_signing_key(request), encoded_claims.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded_claims}.{_base64url(signature)}", expires_at


def _verify_preview_token(
    request: Request,
    user_id: UUID,
    csv_content: str,
    token: str,
) -> str:
    try:
        encoded_claims, encoded_signature = token.split(".", maxsplit=1)
        encoded_claims_bytes = encoded_claims.encode("ascii")
        padding = "=" * (-len(encoded_claims) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded_claims + padding))
        signature_padding = "=" * (-len(encoded_signature) % 4)
        signature = base64.urlsafe_b64decode(encoded_signature + signature_padding)
    except (ValueError, binascii.Error, json.JSONDecodeError, UnicodeEncodeError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A prévia expirou ou é inválida."
        ) from None

    if not isinstance(claims, dict) or not isinstance(claims.get("expires_at"), int):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A prévia expirou ou é inválida."
        )

    expected_signature = hmac.new(
        _session_signing_key(request), encoded_claims_bytes, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A prévia expirou ou é inválida."
        )
    if claims.get("user_id") != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A prévia pertence a outra sessão."
        )
    if claims["expires_at"] <= int(datetime.now(UTC).timestamp()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A prévia expirou; envie o CSV novamente."
        )
    content_digest = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()
    if claims.get("csv_sha256") != content_digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="O CSV mudou após a prévia."
        )
    return str(claims.get("snapshot_sha256", ""))


def _lock_user_imports(user_id: UUID, db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    lock_key = int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def _preview_rows(
    rows: list[_CSVImportRow], matches: list[list[CSVImportMatch]]
) -> list[CSVTransactionImportRowPreview]:
    return [
        CSVTransactionImportRowPreview(
            row_number=row.row_number,
            occurred_at=row.occurred_at,
            description=row.description,
            type=row.transaction_type,
            amount=row.amount,
            account_name=row.account.name,
            category_name=row.category.name,
            matches=row_matches[:5],
            matches_truncated=len(row_matches) > 5,
        )
        for row, row_matches in zip(rows, matches, strict=True)
    ]


@router.post("/transactions/preview", response_model=CSVTransactionImportPreviewResponse)
def preview_csv_transactions(
    payload: CSVTransactionImportPreviewRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CSVTransactionImportPreviewResponse:
    rows = _parse_csv_rows(payload.csv_content, user, db)
    matches = _find_import_matches(rows, user.id, db)
    snapshot = _snapshot_digest(rows, matches)
    token, expires_at = _issue_preview_token(request, user.id, payload.csv_content, snapshot)
    return CSVTransactionImportPreviewResponse(
        preview_token=token,
        expires_at=expires_at,
        row_count=len(rows),
        rows=_preview_rows(rows, matches),
    )


@router.post("/transactions/confirm", response_model=CSVTransactionImportCommitResponse)
def confirm_csv_transactions(
    payload: CSVTransactionImportCommitRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CSVTransactionImportCommitResponse:
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirme explicitamente a gravação dos lançamentos revisados.",
        )
    expected_snapshot = _verify_preview_token(
        request, user.id, payload.csv_content, payload.preview_token
    )
    _lock_user_imports(user.id, db)

    rows = _parse_csv_rows(payload.csv_content, user, db)
    matches = _find_import_matches(rows, user.id, db)
    current_snapshot = _snapshot_digest(rows, matches)
    if not hmac.compare_digest(current_snapshot, expected_snapshot):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Os lançamentos ou possíveis duplicidades mudaram. Gere uma nova prévia.",
        )

    decisions: dict[int, Literal["IMPORT", "SKIP"]] = {}
    for decision in payload.decisions:
        if decision.row_number in decisions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Há decisões repetidas para a mesma linha.",
            )
        decisions[decision.row_number] = decision.action
    rows_with_matches = {
        row.row_number for row, row_matches in zip(rows, matches, strict=True) if row_matches
    }
    if not rows_with_matches.issubset(decisions):
        missing = ", ".join(str(value) for value in sorted(rows_with_matches - decisions.keys()))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Escolha importar ou ignorar as linhas com correspondências: {missing}.",
        )
    if decisions.keys() - rows_with_matches:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Só é necessário informar decisões para linhas com possíveis correspondências.",
        )

    transactions: list[tuple[Transaction, Category]] = []
    skipped_count = 0
    for row, row_matches in zip(rows, matches, strict=True):
        if row_matches and decisions[row.row_number] == "SKIP":
            skipped_count += 1
            continue
        transaction = Transaction(
            user_id=user.id,
            account_id=row.account.id,
            category_id=row.category.id,
            type=row.transaction_type,
            source="MANUAL",
            status="CONFIRMED",
            description=row.description,
            amount=row.amount,
            occurred_at=_transaction_instant(row.occurred_at),
        )
        db.add(transaction)
        transactions.append((transaction, row.category))

    if transactions:
        db.commit()
        for transaction, _category in transactions:
            db.refresh(transaction)
    return CSVTransactionImportCommitResponse(
        imported_count=len(transactions),
        skipped_count=skipped_count,
        imported=[
            transaction_response(transaction, category.name)
            for transaction, category in transactions
        ],
    )
