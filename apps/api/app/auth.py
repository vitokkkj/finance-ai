from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth_security import LoginRateLimiter, verify_totp
from app.config import settings
from app.database import get_db
from app.models import AuthSession, User
from app.schemas import LoginRequest, SetupRequest, SetupStateResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["autenticação"])
password_hasher = PasswordHasher()
dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
setup_lock = threading.Lock()
SETUP_ADVISORY_LOCK_ID = 873421073914


login_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)


def _totp_is_required() -> bool:
    return bool(settings.owner_totp_secret)


def _verify_owner_totp(code: str | None) -> bool:
    if not _totp_is_required():
        return settings.app_env.casefold() != "production"
    return verify_totp(settings.owner_totp_secret or "", code)


def _client_rate_keys(request: Request, action: str) -> tuple[str, ...]:
    client_host = request.client.host if request.client else "unknown"
    return (f"{action}:ip:{client_host}",)


def _raise_rate_limit() -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Muitas tentativas. Aguarde antes de tentar novamente.",
        headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
    )


@contextmanager
def _exclusive_first_user_creation(db: Session) -> Iterator[None]:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": SETUP_ADVISORY_LOCK_ID},
        )
        yield
        return
    with setup_lock:
        yield


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=str(user.id), email=user.email, display_name=user.display_name)


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def _create_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    max_age = settings.session_ttl_hours * 60 * 60
    db.add(
        AuthSession(
            token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=max_age),
        )
    )
    _set_session_cookie(response, token, max_age)


@router.get("/setup-state", response_model=SetupStateResponse)
def setup_state(db: Annotated[Session, Depends(get_db)]) -> SetupStateResponse:
    existing_user = db.scalar(select(User.id).limit(1))
    requires_setup = existing_user is None
    setup_available = settings.app_env.casefold() != "production" or bool(
        settings.initial_setup_token
    )
    return SetupStateResponse(
        requires_setup=requires_setup,
        setup_available=not requires_setup or setup_available,
        bootstrap_token_required=requires_setup and bool(settings.initial_setup_token),
        mfa_required=_totp_is_required(),
    )


@router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_first_user(
    payload: SetupRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    setup_keys = _client_rate_keys(request, "setup")
    now = time.monotonic()
    if not login_rate_limiter.allow_attempt(setup_keys, now):
        _raise_rate_limit()
    if settings.app_env.casefold() == "production":
        configured_token = settings.initial_setup_token
        if not configured_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="O primeiro acesso ainda não foi habilitado pelo proprietário.",
            )
        token_matches = hmac.compare_digest(
            (payload.bootstrap_token or "").encode("utf-8"), configured_token.encode("utf-8")
        )
    else:
        token_matches = not settings.initial_setup_token or hmac.compare_digest(
            (payload.bootstrap_token or "").encode("utf-8"),
            settings.initial_setup_token.encode("utf-8"),
        )

    credentials_match = token_matches and _verify_owner_totp(payload.totp_code)
    if not credentials_match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível validar os dados do primeiro acesso.",
        )

    login_rate_limiter.clear(setup_keys)
    with _exclusive_first_user_creation(db):
        if db.scalar(select(User.id).limit(1)) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Configuração já concluída.",
            )
        user = User(
            email=payload.email,
            display_name=payload.display_name,
            password_hash=password_hasher.hash(payload.password),
        )
        db.add(user)
        db.flush()
        if settings.app_env.casefold() != "production" and not _totp_is_required():
            _create_session(db, user, response)
        db.commit()
        db.refresh(user)
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    keys = _client_rate_keys(request, "login")
    now = time.monotonic()
    if not login_rate_limiter.allow_attempt(keys, now):
        _raise_rate_limit()

    user = db.scalar(select(User).where(User.email == payload.email))
    encoded_hash = user.password_hash if user is not None else dummy_password_hash
    try:
        password_hasher.verify(encoded_hash, payload.password)
        password_matches = user is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_matches = False

    totp_matches = _verify_owner_totp(payload.totp_code)
    if not password_matches or user is None or not totp_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail, senha ou código inválidos.",
        )

    login_rate_limiter.clear(keys)
    _create_session(db, user, response)
    db.commit()
    return _user_response(user)


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária.",
        )

    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.scalar(select(AuthSession).where(AuthSession.token_digest == token_digest))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida.")

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada.")
    return session.user


@router.get("/me", response_model=UserResponse)
def current_user(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return _user_response(user)


@router.post("/logout", response_model=dict[str, str])
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        session = db.scalar(select(AuthSession).where(AuthSession.token_digest == token_digest))
        if session is not None:
            db.delete(session)
            db.commit()
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"status": "ok"}
