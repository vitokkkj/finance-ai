from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.accounts import router as accounts_router
from app.ai import create_ai_provider
from app.ai import router as ai_router
from app.auth import router as auth_router
from app.cards import router as cards_router
from app.categories import router as categories_router
from app.commitments import router as commitments_router
from app.config import settings
from app.database import get_db
from app.exports import router as exports_router
from app.imports import router as imports_router
from app.invoices import router as invoices_router
from app.managed_users import router as managed_users_router
from app.recurrences import router as recurrences_router
from app.request_limits import RequestBodyLimitMiddleware
from app.transactions import router as transactions_router
from app.transfers import router as transfers_router

is_development = settings.app_env == "development"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    provider = create_ai_provider()
    app.state.ai_provider = provider
    try:
        yield
    finally:
        await provider.close()


app = FastAPI(
    title="SophIA API",
    description="API privada da SophIA.",
    version="0.1.0",
    docs_url="/api/docs" if is_development else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if is_development else None,
    lifespan=lifespan,
)
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=16 * 1024 * 1024)
app.include_router(auth_router)
app.include_router(exports_router)
app.include_router(imports_router)
app.include_router(ai_router)
app.include_router(accounts_router)
app.include_router(categories_router)
app.include_router(transactions_router)
app.include_router(cards_router)
app.include_router(invoices_router)
app.include_router(managed_users_router)
app.include_router(transfers_router)
app.include_router(recurrences_router)
app.include_router(commitments_router)


@app.get("/api/health/live", tags=["saúde"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready", tags=["saúde"])
def ready(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
