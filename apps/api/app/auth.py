from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuthSession, User
from app.schemas import Credentials, SetupRequest, SetupStateResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["autenticação"])
password_hasher = PasswordHasher()
dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
setup_lock = threading.Lock()


class LoginRateLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_limited(self, key: str, now: float) -> bool:
        with self._lock:
            recent = [
                attempt
                for attempt in self._failures.get(key, [])
                if now - attempt < settings.login_rate_limit_window_seconds
            ]
            if recent:
                self._failures[key] = recent
            else:
                self._failures.pop(key, None)
            return len(recent) >= settings.login_rate_limit_attempts

    def record_failure(self, key: str, now: float) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_rate_limiter = LoginRateLimiter()


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
    return SetupStateResponse(requires_setup=existing_user is None)


@router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_first_user(
    payload: SetupRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    with setup_lock:
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
        _create_session(db, user, response)
        db.commit()
        db.refresh(user)
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(
    payload: Credentials,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    key = payload.email
    now = time.monotonic()
    if login_rate_limiter.is_limited(key, now):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas. Aguarde antes de tentar novamente.",
            headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )

    user = db.scalar(select(User).where(User.email == payload.email))
    encoded_hash = user.password_hash if user is not None else dummy_password_hash
    try:
        password_hasher.verify(encoded_hash, payload.password)
        password_matches = user is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_matches = False

    if not password_matches or user is None:
        login_rate_limiter.record_failure(key, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha inválidos.",
        )

    login_rate_limiter.clear(key)
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
