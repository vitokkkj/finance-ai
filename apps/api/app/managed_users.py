from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import OWNER_EMAIL, get_current_user, password_hasher
from app.database import Base, get_db
from app.models import User

router = APIRouter(prefix="/api/admin/users", tags=["administração"])


class ManagedUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
            raise ValueError("Informe um e-mail válido.")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome da pessoa.")
        return normalized


class ManagedUserSummary(BaseModel):
    id: UUID
    email: str
    display_name: str
    created_at: datetime


def _require_owner(user: User) -> None:
    if user.email.strip().casefold() != OWNER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o proprietário pode administrar as contas.",
        )


@router.get("", response_model=list[ManagedUserSummary])
def list_managed_users(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    _require_owner(user)
    return list(db.scalars(select(User).order_by(User.created_at.desc(), User.email.asc())))


@router.post("", response_model=ManagedUserSummary, status_code=status.HTTP_201_CREATED)
def create_managed_user(
    payload: ManagedUserCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    _require_owner(user)
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        )

    managed_user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=password_hasher.hash(payload.password),
    )
    db.add(managed_user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        ) from error
    db.refresh(managed_user)
    return managed_user


@router.delete("/{managed_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_managed_user(
    managed_user_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _require_owner(user)
    if managed_user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O acesso do proprietário não pode ser excluído por esta área.",
        )

    managed_user = db.scalar(
        select(User).where(User.id == managed_user_id).with_for_update()
    )
    if managed_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conta de acesso não encontrada.",
        )

    # Keep every financial or personal record. Only sessions are allowed to cascade.
    for table in Base.metadata.tables.values():
        if table.name == "auth_sessions" or "user_id" not in table.c:
            continue
        record_exists = db.scalar(
            select(func.count()).select_from(table).where(table.c.user_id == managed_user_id)
        )
        if record_exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta conta tem dados associados e não pode ser excluída. "
                    "Preserve ou trate esses dados antes de remover o acesso."
                ),
            )

    db.delete(managed_user)
    db.commit()
