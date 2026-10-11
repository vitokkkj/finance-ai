from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.accounts import router as accounts_router
from app.ai import router as ai_router
from app.auth import router as auth_router
from app.cards import router as cards_router
from app.categories import router as categories_router
from app.commitments import router as commitments_router
from app.config import settings
from app.database import get_db
from app.invoices import router as invoices_router
from app.recurrences import router as recurrences_router
from app.request_limits import RequestBodyLimitMiddleware
from app.transactions import router as transactions_router
from app.transfers import router as transfers_router

is_development = settings.app_env == "development"
app = FastAPI(
    title="SophIA API",
    description="API privada da SophIA.",
    version="0.1.0",
    docs_url="/api/docs" if is_development else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if is_development else None,
)
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=16 * 1024 * 1024)
app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(accounts_router)
app.include_router(categories_router)
app.include_router(transactions_router)
app.include_router(cards_router)
app.include_router(invoices_router)
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
