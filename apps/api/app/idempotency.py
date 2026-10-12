"""Persistent idempotency for user initiated financial movements."""

import hashlib
import json
import re
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialIdempotencyRecord, Transaction

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~:-]{16,255}$")


def idempotency_fingerprint(payload: BaseModel | dict[str, object]) -> str:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_idempotency_key(key: str | None) -> str | None:
    if key is not None and _KEY_PATTERN.fullmatch(key) is None:
        raise HTTPException(
            status_code=422,
            detail="O cabeçalho Idempotency-Key deve ter de 16 a 255 caracteres válidos.",
        )
    return key


def _transaction_for_record(
    db: Session, user_id: UUID, record: FinancialIdempotencyRecord
) -> Transaction:
    transaction = db.scalar(
        select(Transaction).where(
            Transaction.id == record.original_transaction_id,
            Transaction.user_id == user_id,
        )
    )
    if transaction is None:
        raise HTTPException(
            status_code=410,
            detail=(
                "Esta operação já foi registrada, mas o movimento original foi removido. "
                "A chave não pode ser reutilizada."
            ),
        )
    return transaction


def find_idempotent_transaction(
    db: Session,
    user_id: UUID,
    operation: str,
    key: str | None,
    payload: BaseModel | dict[str, object],
) -> tuple[Transaction | None, str | None]:
    """Find a previous result and validate that a key is not reused for other input."""
    if key is None:
        return None, None
    validate_idempotency_key(key)
    fingerprint = idempotency_fingerprint(payload)
    record = db.scalar(
        select(FinancialIdempotencyRecord).where(
            FinancialIdempotencyRecord.user_id == user_id,
            FinancialIdempotencyRecord.operation == operation,
            FinancialIdempotencyRecord.idempotency_key == key,
        )
    )
    if record is not None:
        if record.request_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Esta chave Idempotency-Key já foi usada com outros dados.",
            )
        transaction = _transaction_for_record(db, user_id, record)
        return transaction, fingerprint

    # Read keys written by the previous application version during a code rollback.
    legacy_transaction = db.scalar(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.idempotency_operation == operation,
            Transaction.idempotency_key == key,
        )
    )
    if (
        legacy_transaction is not None
        and legacy_transaction.idempotency_fingerprint != fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail="Esta chave Idempotency-Key já foi usada com outros dados.",
        )
    return legacy_transaction, fingerprint


def store_idempotency(
    db: Session,
    transaction: Transaction,
    operation: str,
    key: str | None,
    fingerprint: str | None,
) -> None:
    if key is not None:
        validate_idempotency_key(key)
        if fingerprint is None:
            raise ValueError("A chave de idempotência exige fingerprint do payload.")
        transaction.idempotency_operation = operation
        transaction.idempotency_key = key
        transaction.idempotency_fingerprint = fingerprint
        db.flush()
        db.add(
            FinancialIdempotencyRecord(
                user_id=transaction.user_id,
                operation=operation,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                original_transaction_id=transaction.id,
            )
        )


def recover_concurrent_idempotency(
    db: Session,
    user_id: UUID,
    operation: str,
    key: str | None,
    fingerprint: str | None,
) -> Transaction | None:
    """After a unique-key race, return the winning request or raise a conflict."""
    if key is None:
        return None
    db.rollback()
    record = db.scalar(
        select(FinancialIdempotencyRecord).where(
            FinancialIdempotencyRecord.user_id == user_id,
            FinancialIdempotencyRecord.operation == operation,
            FinancialIdempotencyRecord.idempotency_key == key,
        )
    )
    if record is None:
        # A version rolled back to 0017 writes the transaction columns only.
        transaction = db.scalar(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.idempotency_operation == operation,
                Transaction.idempotency_key == key,
            )
        )
        if transaction is None:
            return None
        if transaction.idempotency_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Esta chave Idempotency-Key já foi usada com outros dados.",
            )
        return transaction
    if record.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Esta chave Idempotency-Key já foi usada com outros dados.",
        )
    return _transaction_for_record(db, user_id, record)
