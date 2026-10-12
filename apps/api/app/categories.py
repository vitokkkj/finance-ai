from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Category,
    PlannedCommitment,
    RecurrenceOccurrence,
    RecurrenceRule,
    Transaction,
    User,
)
from app.schemas import CategoryCreate, CategoryResponse, CategoryUpdate

router = APIRouter(prefix="/api/categories", tags=["categorias"])


def _category_response(category: Category) -> CategoryResponse:
    return CategoryResponse(
        id=category.id,
        name=category.name,
        type=category.type,
        is_archived=category.archived_at is not None,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


@router.get("", response_model=list[CategoryResponse])
def list_categories(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_archived: bool = False,
) -> list[CategoryResponse]:
    statement = select(Category).where(Category.user_id == user.id)
    if not include_archived:
        statement = statement.where(Category.archived_at.is_(None))
    categories = db.scalars(statement.order_by(Category.name, Category.id)).all()
    return [_category_response(category) for category in categories]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CategoryResponse:
    category = Category(user_id=user.id, name=payload.name, type=payload.type)
    db.add(category)
    db.commit()
    db.refresh(category)
    return _category_response(category)


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CategoryResponse:
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Categoria não encontrada."
        )
    if category.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reative a categoria antes de alterá-la.",
        )
    if payload.type is not None and payload.type != category.type:
        has_transactions = db.scalar(
            select(Transaction.id)
            .where(Transaction.category_id == category.id, Transaction.user_id == user.id)
            .limit(1)
        )
        if has_transactions is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O tipo de uma categoria usada não pode mudar; crie outra categoria.",
            )
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return _category_response(category)


@router.post("/{category_id}/archive", response_model=CategoryResponse)
def archive_category(
    category_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CategoryResponse:
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Categoria não encontrada."
        )
    if category.archived_at is None:
        category.archived_at = datetime.now(UTC)
        db.commit()
        db.refresh(category)
    return _category_response(category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    category = db.scalar(
        select(Category)
        .where(Category.id == category_id, Category.user_id == user.id)
        .with_for_update()
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    references = (
        select(Transaction.id)
        .where(Transaction.user_id == user.id, Transaction.category_id == category.id)
        .limit(1),
        select(RecurrenceRule.id)
        .where(RecurrenceRule.user_id == user.id, RecurrenceRule.category_id == category.id)
        .limit(1),
        select(RecurrenceOccurrence.id)
        .where(
            RecurrenceOccurrence.user_id == user.id,
            RecurrenceOccurrence.category_id == category.id,
        )
        .limit(1),
        select(PlannedCommitment.id)
        .where(
            PlannedCommitment.user_id == user.id,
            PlannedCommitment.category_id == category.id,
        )
        .limit(1),
    )
    if any(db.scalar(statement) is not None for statement in references):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A categoria ainda está vinculada a lançamentos, pagamentos previstos ou "
                "recorrências. Remova esses vínculos antes de excluí-la."
            ),
        )
    db.delete(category)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
