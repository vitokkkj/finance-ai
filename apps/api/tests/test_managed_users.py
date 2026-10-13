import base64
import hashlib
import hmac
import struct
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import AuthSession, Category, User

OWNER_EMAIL = "gamercreeper74@gmail.com"
OWNER_PASSWORD = "senha-do-proprietario-segura"


def _create_first_user(client: TestClient, email: str = OWNER_EMAIL) -> str:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": email,
            "display_name": "Proprietário",
            "password": OWNER_PASSWORD,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_managed_user(client: TestClient, email: str = "richard@example.com") -> dict:
    response = client.post(
        "/api/admin/users",
        json={
            "email": email,
            "display_name": "Richard",
            "password": "senha-inicial-segura-123",
        },
    )
    assert response.status_code == 201
    return response.json()


def _totp_code(secret: str, counter: int) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def test_owner_can_create_list_and_delete_empty_managed_user(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    owner_id = _create_first_user(client)
    created = _create_managed_user(client, " Richard@Example.com ")

    assert created["email"] == "richard@example.com"
    assert created["mfa_enrolled"] is False
    assert "password" not in created
    assert "password_hash" not in created
    assert {row["email"] for row in client.get("/api/admin/users").json()} == {
        OWNER_EMAIL,
        "richard@example.com",
    }

    self_delete = client.delete(f"/api/admin/users/{owner_id}")
    assert self_delete.status_code == 409

    deleted = client.delete(f"/api/admin/users/{created['id']}")
    assert deleted.status_code == 204
    assert [row["email"] for row in client.get("/api/admin/users").json()] == [OWNER_EMAIL]

    with test_session_factory() as db:
        assert db.get(User, UUID(owner_id)) is not None
        assert db.get(User, UUID(created["id"])) is None
        assert db.scalar(
            select(func.count()).select_from(AuthSession).where(
                AuthSession.user_id == UUID(created["id"])
            )
        ) == 0


def test_managed_user_summary_reports_mfa_enrollment_state(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _create_first_user(client)
    managed = _create_managed_user(client)

    listed = client.get("/api/admin/users")
    assert listed.status_code == 200
    managed_row = next(row for row in listed.json() if row["id"] == managed["id"])
    assert managed_row["mfa_enrolled"] is False

    with test_session_factory() as db:
        user = db.get(User, UUID(managed["id"]))
        assert user is not None
        user.mfa_enrolled_at = datetime.now(UTC)
        db.commit()

    listed = client.get("/api/admin/users")
    managed_row = next(row for row in listed.json() if row["id"] == managed["id"])
    assert managed_row["mfa_enrolled"] is True


def test_managed_user_with_data_cannot_be_deleted_and_data_is_preserved(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _create_first_user(client)
    created = _create_managed_user(client)
    managed_user_id = UUID(created["id"])

    with test_session_factory() as db:
        db.add(Category(user_id=managed_user_id, name="Alimentação", type="EXPENSE"))
        db.commit()

    deleted = client.delete(f"/api/admin/users/{managed_user_id}")
    assert deleted.status_code == 409
    assert "dados associados" in deleted.json()["detail"]

    with test_session_factory() as db:
        assert db.get(User, managed_user_id) is not None
        assert db.scalar(
            select(func.count()).select_from(Category).where(Category.user_id == managed_user_id)
        ) == 1


def test_non_owner_cannot_list_create_or_delete_managed_users(client: TestClient) -> None:
    _create_first_user(client, "pessoa@example.com")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post(
        "/api/admin/users",
        json={
            "email": "outra@example.com",
            "display_name": "Outra pessoa",
            "password": "outra-senha-segura-123",
        },
    ).status_code == 403
    assert client.delete("/api/admin/users/00000000-0000-0000-0000-000000000001").status_code == 403


def test_managed_user_creation_rejects_duplicate_email(client: TestClient) -> None:
    _create_first_user(client)
    _create_managed_user(client)
    duplicate = client.post(
        "/api/admin/users",
        json={
            "email": "RICHARD@example.com",
            "display_name": "Richard duplicado",
            "password": "outra-senha-segura-123",
        },
    )
    assert duplicate.status_code == 409


def test_managed_user_routes_require_a_session(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/admin/users").status_code == 401
    assert client.post("/api/admin/users", json={}).status_code == 401
    assert client.delete("/api/admin/users/00000000-0000-0000-0000-000000000001").status_code == 401


def test_managed_users_enroll_individual_encrypted_mfa_and_login_with_replay_protection(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "mfa_encryption_key", encryption_key)
    _create_first_user(client)
    first = _create_managed_user(client, "first@example.com")
    second = _create_managed_user(client, "second@example.com")

    checked = client.post(
        "/api/auth/login/check",
        json={"email": first["email"], "password": "senha-inicial-segura-123"},
    )
    assert checked.json() == {
        "mfa_required": True,
        "mfa_enrolled": False,
        "mfa_enrollment_available": True,
        "mfa_enrollment_token_required": False,
    }
    assert client.post(
        "/api/auth/login",
        json={"email": first["email"], "password": "senha-inicial-segura-123"},
    ).status_code == 403

    first_start = client.post(
        "/api/auth/mfa/enrollment/start",
        json={
            "email": first["email"],
            "password": "senha-inicial-segura-123",
            "enrollment_token": "",
        },
    )
    second_start = client.post(
        "/api/auth/mfa/enrollment/start",
        json={"email": second["email"], "password": "senha-inicial-segura-123"},
    )
    assert first_start.status_code == second_start.status_code == 200
    first_secret = first_start.json()["manual_key"]
    second_secret = second_start.json()["manual_key"]
    assert first_secret != second_secret

    with test_session_factory() as db:
        stored = db.get(User, UUID(first["id"]))
        assert stored is not None
        assert stored.mfa_secret_encrypted != first_secret
        assert Fernet(encryption_key.encode()).decrypt(
            stored.mfa_secret_encrypted.encode()
        ).decode() == first_secret

    current_counter = int(time.time() // 30)
    confirm = client.post(
        "/api/auth/mfa/enrollment/confirm",
        json={
            "email": first["email"],
            "password": "senha-inicial-segura-123",
            "totp_code": _totp_code(first_secret, current_counter),
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["mfa_required"] is True
    assert confirm.json()["mfa_enrolled"] is True

    client.cookies.clear()
    next_code = _totp_code(first_secret, current_counter + 1)
    login_payload = {
        "email": first["email"],
        "password": "senha-inicial-segura-123",
        "totp_code": next_code,
    }
    assert client.post("/api/auth/login", json=login_payload).status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/login", json=login_payload).status_code == 401


def test_managed_mfa_enrollment_is_rate_limited_and_expires(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth import login_rate_limiter

    monkeypatch.setattr(settings, "mfa_encryption_key", Fernet.generate_key().decode("ascii"))
    _create_first_user(client)
    managed = _create_managed_user(client)
    payload = {
        "email": managed["email"],
        "password": "senha-inicial-segura-123",
    }
    for _ in range(5):
        limited = client.post(
            "/api/auth/mfa/enrollment/start",
            json={**payload, "password": "senha-errada-segura-123"},
        )
        assert limited.status_code == 401
    assert client.post("/api/auth/mfa/enrollment/start", json=payload).status_code == 429

    login_rate_limiter.reset()
    started = client.post("/api/auth/mfa/enrollment/start", json=payload)
    assert started.status_code == 200
    with test_session_factory() as db:
        user = db.get(User, UUID(managed["id"]))
        assert user is not None
        user.mfa_enrollment_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    expired = client.post(
        "/api/auth/mfa/enrollment/confirm",
        json={**payload, "totp_code": "000000"},
    )
    assert expired.status_code == 410


def test_managed_mfa_reset_requires_owner_reauthentication_and_preserves_financial_data(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import managed_users

    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "mfa_encryption_key", encryption_key)
    _create_first_user(client)
    monkeypatch.setattr(settings, "owner_totp_secret", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    monkeypatch.setattr(
        managed_users,
        "matching_totp_counter",
        lambda secret, code: 456 if code == "123456" else None,
    )
    target = _create_managed_user(client)
    target_id = UUID(target["id"])
    with test_session_factory() as db:
        owner = db.scalar(select(User).where(User.email == OWNER_EMAIL))
        managed = db.get(User, target_id)
        assert owner is not None and managed is not None
        owner.mfa_enrolled_at = datetime.now(UTC)
        managed.mfa_secret_encrypted = Fernet(encryption_key.encode()).encrypt(
            b"GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        ).decode()
        managed.mfa_enrolled_at = datetime.now(UTC)
        managed.mfa_enrollment_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        managed.last_totp_counter = 123
        db.add(Category(user_id=target_id, name="Preservada", type="EXPENSE"))
        db.add(
            AuthSession(
                token_digest="f" * 64,
                user_id=target_id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()

    endpoint = f"/api/admin/users/{target_id}/mfa/reset"
    bad = client.post(
        endpoint,
        json={"current_password": "senha-errada-12345", "totp_code": "123456"},
    )
    assert bad.status_code == 401

    reset = client.post(
        endpoint,
        json={"current_password": OWNER_PASSWORD, "totp_code": "123456"},
    )
    assert reset.status_code == 200
    assert reset.json() == {"status": "mfa_reset"}
    with test_session_factory() as db:
        managed = db.get(User, target_id)
        assert managed is not None
        assert managed.mfa_secret_encrypted is None
        assert managed.mfa_enrolled_at is None
        assert managed.mfa_enrollment_expires_at is None
        assert managed.last_totp_counter is None
        assert db.scalar(
            select(func.count()).select_from(AuthSession).where(AuthSession.user_id == target_id)
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(Category).where(Category.user_id == target_id)
        ) == 1
