from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import ipaddress
import secrets
import threading
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote, urlencode
from uuid import uuid4

import qrcode
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from PIL import Image, ImageOps, UnidentifiedImageError
from qrcode.image.svg import SvgPathImage
from sqlalchemy import or_, select, text, update
from sqlalchemy.orm import Session

from app.auth_security import LoginRateLimiter, matching_totp_counter
from app.config import settings
from app.database import get_db
from app.models import AuthSession, User
from app.schemas import (
    AvatarUpdate,
    LoginCheckResponse,
    LoginRequest,
    MFAEnrollmentConfirmRequest,
    MFAEnrollmentRequest,
    MFAEnrollmentResponse,
    PasswordChangeRequest,
    ProfileUpdate,
    ReauthenticationRequest,
    SessionRevocationResponse,
    SessionSummary,
    SetupRequest,
    SetupStateResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["autenticação"])
password_hasher = PasswordHasher()
dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
setup_lock = threading.Lock()
SETUP_ADVISORY_LOCK_ID = 873421073914
OWNER_EMAIL = "gamercreeper74@gmail.com"


login_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)
rate_limit_key = secrets.token_bytes(32)


def _totp_is_required() -> bool:
    return bool(settings.owner_totp_secret)


def _email_requires_mfa(email: str) -> bool:
    if email.strip().casefold() == OWNER_EMAIL:
        return _totp_is_required()
    return True


def _is_managed_user(user: User) -> bool:
    return user.email.strip().casefold() != OWNER_EMAIL


def _managed_mfa_fernet() -> Fernet:
    key = (settings.mfa_encryption_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O pareamento MFA ainda não está disponível neste servidor.",
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A configuração de criptografia do MFA está inválida.",
        ) from error


def _encrypt_managed_totp_secret(secret: str) -> str:
    return _managed_mfa_fernet().encrypt(secret.encode("ascii")).decode("ascii")


def _decrypt_managed_totp_secret(user: User) -> str | None:
    if not user.mfa_secret_encrypted:
        return None
    try:
        return _managed_mfa_fernet().decrypt(user.mfa_secret_encrypted.encode("ascii")).decode(
            "ascii"
        )
    except (InvalidToken, UnicodeDecodeError, ValueError):
        return None


def _owner_totp_counter(code: str | None) -> int | None:
    if not _totp_is_required():
        return -1 if settings.app_env.casefold() != "production" else None
    return matching_totp_counter(settings.owner_totp_secret or "", code)


def _consume_totp_counter(db: Session, user: User, counter: int) -> bool:
    if counter < 0:
        return True
    consumed_user_id = db.scalar(
        update(User)
        .where(
            User.id == user.id,
            or_(User.last_totp_counter.is_(None), User.last_totp_counter < counter),
        )
        .values(last_totp_counter=counter)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    if consumed_user_id is None:
        return False
    user.last_totp_counter = counter
    return True


def _client_rate_keys(request: Request, action: str, email: str) -> tuple[str, ...]:
    client_host = request.client.host if request.client else "unknown"
    forwarded_client_ip = request.headers.get("x-sophia-client-ip", "").strip()
    if forwarded_client_ip:
        try:
            client_host = ipaddress.ip_address(forwarded_client_ip).compressed
        except ValueError:
            pass
    normalized_email = email.strip().casefold()
    account_digest = hmac.new(
        rate_limit_key, normalized_email.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (f"{action}:ip:{client_host}", f"{action}:account:{account_digest}")


def _password_authenticated_user(
    db: Session, email: str, password: str, *, lock_user: bool = False
) -> User | None:
    statement = select(User).where(User.email == email)
    if lock_user:
        statement = statement.with_for_update()
    user = db.scalar(statement)
    encoded_hash = user.password_hash if user is not None else dummy_password_hash
    try:
        password_hasher.verify(encoded_hash, password)
        password_matches = user is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_matches = False
    return user if password_matches else None


def _mfa_enrollment_token_matches(candidate: str) -> bool:
    configured = settings.mfa_enrollment_token
    return bool(
        configured and hmac.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8"))
    )


def _make_totp_qr(secret: str, label_text: str) -> str:
    label = quote(f"SophIA: {label_text}", safe="")
    parameters = urlencode(
        {
            "secret": secret,
            "issuer": "SophIA",
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    provisioning_uri = f"otpauth://totp/{label}?{parameters}"
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    output = io.BytesIO()
    qr.make_image(image_factory=SvgPathImage).save(output)
    encoded_svg = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded_svg}"


def _make_owner_totp_qr() -> str:
    return _make_totp_qr((settings.owner_totp_secret or "").strip().upper(), "proprietário")


def _managed_mfa_enrollment_available(user: User) -> bool:
    if not _is_managed_user(user):
        return bool(settings.mfa_enrollment_token and _totp_is_required())
    return user.mfa_enrolled_at is None and bool(settings.mfa_encryption_key)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
    return UserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        mfa_required=_email_requires_mfa(user.email),
        mfa_enrolled=user.mfa_enrolled_at is not None,
        avatar_url=(
            f"/api/auth/me/avatar/{user.avatar_revision}" if user.avatar_revision else None
        ),
    )


def _normalized_avatar(data_url: str) -> bytes:
    media_type, _, encoded = data_url.partition(",")
    expected_format = {
        "data:image/png;base64": "PNG",
        "data:image/jpeg;base64": "JPEG",
        "data:image/webp;base64": "WEBP",
    }.get(media_type)
    if expected_format is None:
        raise ValueError("Formato de imagem não permitido.")

    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > 1_500_000:
        raise ValueError("A imagem excede o tamanho permitido.")

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != expected_format:
                raise ValueError("O conteúdo não corresponde ao formato da imagem.")
            if source.width * source.height > 48_000_000:
                raise ValueError("A imagem excede a resolução permitida.")
            source.verify()

        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            normalized = ImageOps.exif_transpose(source)
            normalized.thumbnail((512, 512), Image.Resampling.LANCZOS)
            mode = "RGBA" if "A" in normalized.getbands() else "RGB"
            normalized = normalized.convert(mode)
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=82, method=4)
            return output.getvalue()


def _reauthentication_matches(db: Session, user: User, payload: ReauthenticationRequest) -> bool:
    authenticated_user = _password_authenticated_user(db, user.email, payload.current_password)
    password_matches = authenticated_user is not None and authenticated_user.id == user.id
    if not password_matches:
        return False
    if not _email_requires_mfa(user.email):
        return True
    counter = _owner_totp_counter(payload.totp_code)
    mfa_matches = (
        user.mfa_enrolled_at is not None
        and counter is not None
        and _consume_totp_counter(db, user, counter)
    )
    return mfa_matches


def _session_is_active(session: AuthSession, now: datetime) -> bool:
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > now


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
    setup_keys = _client_rate_keys(request, "setup", payload.email)
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

    # The bootstrap account is the server owner. Managed accounts use their
    # own encrypted authenticator after they are provisioned.
    mfa_required = payload.email.strip().casefold() == OWNER_EMAIL and _totp_is_required()
    totp_counter = _owner_totp_counter(payload.totp_code) if mfa_required else -1
    if not token_matches or totp_counter is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível validar os dados do primeiro acesso.",
        )
    if settings.app_env.casefold() == "production" and payload.email != OWNER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A configuração inicial deve usar o e-mail do proprietário.",
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
            mfa_enrolled_at=datetime.now(UTC) if mfa_required else None,
            last_totp_counter=totp_counter
            if totp_counter is not None and totp_counter >= 0
            else None,
        )
        db.add(user)
        db.flush()
        if settings.app_env.casefold() != "production" and not mfa_required:
            _create_session(db, user, response)
        db.commit()
        db.refresh(user)
    return _user_response(user)


@router.post("/login/check", response_model=LoginCheckResponse)
def check_login_password(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> LoginCheckResponse:
    """Valida a primeira etapa para que a interface só peça MFA depois da senha."""
    keys = _client_rate_keys(request, "login", payload.email)
    now = time.monotonic()
    if not login_rate_limiter.allow_attempt(keys, now):
        _raise_rate_limit()
    user = _password_authenticated_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível validar o e-mail e a senha.",
        )
    return LoginCheckResponse(
        mfa_required=_email_requires_mfa(user.email),
        mfa_enrolled=user.mfa_enrolled_at is not None,
        mfa_enrollment_available=(
            _email_requires_mfa(user.email)
            and user.mfa_enrolled_at is None
            and _managed_mfa_enrollment_available(user)
        ),
        mfa_enrollment_token_required=not _is_managed_user(user),
    )


@router.post("/mfa/enrollment/start", response_model=MFAEnrollmentResponse)
def start_mfa_enrollment(
    payload: MFAEnrollmentRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> MFAEnrollmentResponse:
    keys = _client_rate_keys(request, "mfa-enrollment-start", payload.email)
    now_monotonic = time.monotonic()
    if not login_rate_limiter.allow_attempt(keys, now_monotonic):
        _raise_rate_limit()
    user = _password_authenticated_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível autorizar o pareamento do autenticador.",
        )
    managed_user = _is_managed_user(user)
    if not managed_user and not _mfa_enrollment_token_matches(payload.enrollment_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível autorizar o pareamento do autenticador.",
        )
    if user.mfa_enrolled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O autenticador desta conta já foi configurado.",
        )
    if not managed_user and not _totp_is_required():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O MFA ainda não foi configurado pelo proprietário do servidor.",
        )

    secret = (
        base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        if managed_user
        else (settings.owner_totp_secret or "").strip().upper().rstrip("=")
    )
    if managed_user:
        user.mfa_secret_encrypted = _encrypt_managed_totp_secret(secret)
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    user.mfa_enrollment_expires_at = expires_at
    db.commit()
    login_rate_limiter.clear(keys)
    return MFAEnrollmentResponse(
        qr_code_data_url=_make_totp_qr(secret, user.email if managed_user else "proprietário"),
        manual_key=secret,
        expires_at=expires_at,
    )


@router.post("/mfa/enrollment/confirm", response_model=UserResponse)
def confirm_mfa_enrollment(
    payload: MFAEnrollmentConfirmRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    keys = _client_rate_keys(request, "mfa-enrollment-confirm", payload.email)
    now_monotonic = time.monotonic()
    if not login_rate_limiter.allow_attempt(keys, now_monotonic):
        _raise_rate_limit()
    user = _password_authenticated_user(db, payload.email, payload.password, lock_user=True)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível confirmar o pareamento do autenticador.",
        )
    managed_user = _is_managed_user(user)
    if not managed_user and not _mfa_enrollment_token_matches(payload.enrollment_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível confirmar o pareamento do autenticador.",
        )
    if user.mfa_enrolled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O autenticador desta conta já foi configurado.",
        )
    expires_at = user.mfa_enrollment_expires_at
    if expires_at is None or _as_utc(expires_at) <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="O QR expirou. Gere um novo para continuar.",
        )
    secret = _decrypt_managed_totp_secret(user) if managed_user else settings.owner_totp_secret
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="O pareamento expirou ou não está disponível. Gere um novo QR.",
        )
    totp_counter = (
        matching_totp_counter(secret, payload.totp_code)
        if managed_user
        else _owner_totp_counter(payload.totp_code)
    )
    if totp_counter is None or not _consume_totp_counter(db, user, totp_counter):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código inválido. Confira o Authy e tente novamente.",
        )

    user.mfa_enrolled_at = datetime.now(UTC)
    user.mfa_enrollment_expires_at = None
    login_rate_limiter.clear(keys)
    _create_session(db, user, response)
    db.commit()
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    keys = _client_rate_keys(request, "login", payload.email)
    now = time.monotonic()
    if not login_rate_limiter.allow_attempt(keys, now):
        _raise_rate_limit()

    user = _password_authenticated_user(db, payload.email, payload.password, lock_user=True)
    mfa_required = user is not None and _email_requires_mfa(user.email)
    managed_user = user is not None and _is_managed_user(user)
    if user is not None and managed_user and user.mfa_enrolled_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Configure o autenticador antes de entrar.",
        )
    secret = (
        _decrypt_managed_totp_secret(user)
        if managed_user and user is not None
        else settings.owner_totp_secret
    )
    totp_counter = (
        (
            matching_totp_counter(secret or "", payload.totp_code)
            if managed_user
            else _owner_totp_counter(payload.totp_code)
        )
        if mfa_required
        else None
    )
    if user is None or (
        mfa_required
        and (
            secret is None
            or totp_counter is None
            or not _consume_totp_counter(db, user, totp_counter)
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail, senha ou código inválidos.",
        )

    login_rate_limiter.clear(keys)
    if mfa_required and user.mfa_enrolled_at is None:
        user.mfa_enrolled_at = datetime.now(UTC)
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


@router.patch("/me", response_model=UserResponse)
def update_current_user(
    payload: ProfileUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    user.display_name = payload.display_name
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.put("/me/avatar", response_model=UserResponse)
def update_current_user_avatar(
    payload: AvatarUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    try:
        user.avatar_data = _normalized_avatar(payload.image_data_url)
    except (
        binascii.Error,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Escolha uma imagem PNG, JPEG ou WebP válida, de até 48 megapixels.",
        ) from error
    user.avatar_revision = uuid4()
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.get("/me/avatar/{revision}")
def get_current_user_avatar(
    revision: str,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if str(user.avatar_revision) != revision or user.avatar_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foto não encontrada.")
    return Response(
        content=user.avatar_data,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="perfil.webp"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/me/avatar", response_model=UserResponse)
def delete_current_user_avatar(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    user.avatar_data = None
    user.avatar_revision = None
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.get("/sessions", response_model=list[SessionSummary])
def list_current_user_sessions(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[SessionSummary]:
    token = request.cookies.get(settings.session_cookie_name)
    current_digest = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
    now = datetime.now(UTC)
    sessions = db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.expires_at > now)
        .order_by(AuthSession.created_at.desc())
    ).all()
    return [
        SessionSummary(
            created_at=session.created_at,
            expires_at=session.expires_at,
            is_current=hmac.compare_digest(session.token_digest, current_digest),
        )
        for session in sessions
    ]


@router.post("/sessions/revoke-others", response_model=SessionRevocationResponse)
def revoke_other_sessions(
    payload: ReauthenticationRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SessionRevocationResponse:
    keys = _client_rate_keys(request, "session-revocation", user.email)
    if not login_rate_limiter.allow_attempt(keys, time.monotonic()):
        _raise_rate_limit()
    if not _reauthentication_matches(db, user, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível confirmar sua identidade. Confira a senha e o código MFA.",
        )

    token = request.cookies.get(settings.session_cookie_name)
    current_digest = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    revoked_count = 0
    for session in sessions:
        if hmac.compare_digest(session.token_digest, current_digest):
            continue
        db.delete(session)
        if _session_is_active(session, datetime.now(UTC)):
            revoked_count += 1
    db.commit()
    login_rate_limiter.clear(keys)
    return SessionRevocationResponse(revoked_count=revoked_count)


@router.post("/password/change", response_model=dict[str, str])
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    keys = _client_rate_keys(request, "password-change", user.email)
    if not login_rate_limiter.allow_attempt(keys, time.monotonic()):
        _raise_rate_limit()
    if not _reauthentication_matches(db, user, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não foi possível confirmar sua identidade. Confira a senha e o código MFA.",
        )
    if hmac.compare_digest(payload.current_password, payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escolha uma senha diferente da atual.",
        )

    user.password_hash = password_hasher.hash(payload.new_password)
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    for session in sessions:
        db.delete(session)
    db.commit()
    login_rate_limiter.clear(keys)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"status": "password_changed"}


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
