"""Persistent idempotency for user initiated financial movements."""

import hashlib
import json
import re
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~:-]{16,255}$")


def idempotency_fingerprint(payload: BaseModel | dict[str, object]) -> str:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    if _KEY_PATTERN.fullmatch(key) is None:
        raise HTTPException(
            status_code=422,
            detail="O cabeçalho Idempotency-Key deve ter de 16 a 255 caracteres válidos.",
        )
    fingerprint = idempotency_fingerprint(payload)
    transaction = db.scalar(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.idempotency_operation == operation,
            Transaction.idempotency_key == key,
        )
    )
    if transaction is not None and transaction.idempotency_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Esta chave Idempotency-Key já foi usada com outros dados.",
        )
    return transaction, fingerprint


def store_idempotency(
    transaction: Transaction,
    operation: str,
    key: str | None,
    fingerprint: str | None,
) -> None:
    if key is not None:
        transaction.idempotency_operation = operation
        transaction.idempotency_key = key
        transaction.idempotency_fingerprint = fingerprint


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
